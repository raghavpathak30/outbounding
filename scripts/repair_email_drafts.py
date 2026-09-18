#!/usr/bin/env python3
"""
One-time Repair Script for Outbound Email Drafts.
Finds existing database rows (and optionally staged files) whose email draft
starts with '[{' and is parseable as a LangChain content-block Python repr,
extracts the clean plain text (discarding thinking blocks, signatures, and extras),
and rewrites the field.

Safety:
- By default, performs a 100% read-only DRY RUN and prints a unified diff.
- Requires explicit --apply flag to commit changes to the database.
"""
import os
import sys
import ast
import re
import json
import sqlite3
import difflib
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any

# Ensure project root is in sys.path so pipeline modules can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.adapters._llm_text import extract_llm_text

DEFAULT_DB_PATH = Path("data/outbound.db")
DEFAULT_STAGED_DIR = Path("staged_deliveries")


def repair_content_block_repr(raw_value: str) -> Optional[str]:
    """
    Attempts to repair a raw Python repr of content blocks (starting with '[{').
    Handles:
    - Standalone content block list: "[{'type': 'text', 'text': '...', 'extras': {...}}]"
    - List with appended opt-out footer: "[{'type': ...}]\n\n---\nIf you prefer not to..."
    - Preserves internal newlines, formatting, and any legitimate footer text.
    - Discards thinking blocks, signatures, and extras.

    Returns:
        Cleaned plain text string, or None if raw_value is not a parseable content-block repr.
    """
    if not isinstance(raw_value, str):
        return None

    raw_stripped = raw_value.strip()
    if not raw_stripped.startswith("[{"):
        return None

    repr_chunk = raw_stripped
    footer_chunk = ""

    # Check for standard opt-out footer delimiter appended to draft
    if "\n\n---\n" in raw_stripped:
        parts = raw_stripped.split("\n\n---\n", 1)
        repr_chunk = parts[0].strip()
        footer_chunk = parts[1].strip()

    parsed = None
    try:
        parsed = ast.literal_eval(repr_chunk)
    except Exception:
        # If literal_eval failed directly, attempt balanced bracket extraction
        match = re.match(r"^(\[.*?\])(.*)$", raw_stripped, re.DOTALL)
        if match:
            try:
                parsed = ast.literal_eval(match.group(1))
                remainder = match.group(2).strip()
                if remainder.startswith("---\n") or remainder.startswith("---\r\n"):
                    footer_chunk = remainder.split("\n", 1)[1].strip()
                elif remainder:
                    footer_chunk = remainder
            except Exception:
                return None
        else:
            return None

    if not isinstance(parsed, list):
        return None

    cleaned_text = extract_llm_text(parsed)
    if not cleaned_text:
        return None

    if footer_chunk:
        return f"{cleaned_text}\n\n---\n{footer_chunk}"
    return cleaned_text


def scan_and_repair_db(
    db_path: Path,
    apply_changes: bool = False
) -> Tuple[int, int, List[str]]:
    """
    Scans all tables in the SQLite database for corrupted content-block reprs in
    text columns (including 'email_draft', 'body', 'edited_body', 'subject', 'edited_subject').

    Returns:
        (total_corrupted_found, total_repaired, diff_outputs)
    """
    if not db_path.exists():
        print(f"[DB Scan] Database file not found: {db_path}")
        return 0, 0, []

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall() if not row[0].startswith("sqlite_")]

    corrupted_found = 0
    repaired_count = 0
    diff_outputs: List[str] = []
    updates_to_execute: List[Tuple[str, str, str, str, Any]] = []  # (table, pk_col, col_name, new_val, pk_val)

    for table in tables:
        cursor.execute(f"PRAGMA table_info(\"{table}\");")
        columns_info = cursor.fetchall()
        col_names = [c[1] for c in columns_info]
        pk_cols = [c[1] for c in columns_info if c[5] > 0]
        pk_col = pk_cols[0] if pk_cols else (col_names[0] if col_names else "rowid")

        # Target candidate columns: any column named email_draft, or text fields
        candidate_cols = [
            c for c in col_names
            if any(k in c.lower() for k in ["draft", "body", "subject", "content", "email"])
        ]
        if not candidate_cols:
            continue

        for col in candidate_cols:
            try:
                cursor.execute(
                    f"SELECT \"{pk_col}\", \"{col}\" FROM \"{table}\" WHERE \"{col}\" LIKE '[{{%';"
                )
                rows = cursor.fetchall()
            except sqlite3.OperationalError:
                continue

            for row in rows:
                pk_val = row[0]
                raw_val = row[1]
                if not raw_val:
                    continue

                repaired_val = repair_content_block_repr(raw_val)
                if repaired_val is not None and repaired_val != raw_val:
                    corrupted_found += 1
                    diff = difflib.unified_diff(
                        raw_val.splitlines(keepends=True),
                        repaired_val.splitlines(keepends=True),
                        fromfile=f"{table}.{col} (pk={pk_val}) [CORRUPTED]",
                        tofile=f"{table}.{col} (pk={pk_val}) [REPAIRED]",
                    )
                    diff_text = "".join(diff)
                    diff_outputs.append(diff_text)
                    updates_to_execute.append((table, pk_col, col, repaired_val, pk_val))

    if apply_changes and updates_to_execute:
        try:
            with conn:
                for tbl, pk_c, target_c, new_val, pk_v in updates_to_execute:
                    cursor.execute(
                        f"UPDATE \"{tbl}\" SET \"{target_c}\" = ? WHERE \"{pk_c}\" = ?;",
                        (new_val, pk_v)
                    )
                    repaired_count += 1
            print(f" ✓ Applied updates to {repaired_count} row(s) in {db_path}.")
        except Exception as e:
            print(f" ✗ Error writing updates to {db_path}: {e}", file=sys.stderr)
            conn.rollback()
            raise
    else:
        repaired_count = len(updates_to_execute)

    conn.close()
    return corrupted_found, repaired_count, diff_outputs


def scan_and_repair_staged_files(
    staged_dir: Path,
    apply_changes: bool = False
) -> Tuple[int, int, List[str]]:
    """
    Scans staged JSON delivery files for corrupted content-block reprs in email_body.

    Returns:
        (total_corrupted_found, total_repaired, diff_outputs)
    """
    if not staged_dir.exists():
        return 0, 0, []

    corrupted_found = 0
    repaired_count = 0
    diff_outputs: List[str] = []

    for file_path in sorted(staged_dir.glob("*.json")):
        try:
            content_text = file_path.read_text(encoding="utf-8")
            data = json.loads(content_text)
        except Exception:
            continue

        payload = data.get("payload") if isinstance(data, dict) else None
        if not payload or not isinstance(payload, dict):
            continue

        raw_body = payload.get("email_body")
        if not raw_body or not isinstance(raw_body, str):
            continue

        repaired_body = repair_content_block_repr(raw_body)
        if repaired_body is not None and repaired_body != raw_body:
            corrupted_found += 1
            diff = difflib.unified_diff(
                raw_body.splitlines(keepends=True),
                repaired_body.splitlines(keepends=True),
                fromfile=f"{file_path.name}::email_body [CORRUPTED]",
                tofile=f"{file_path.name}::email_body [REPAIRED]",
            )
            diff_outputs.append("".join(diff))

            if apply_changes:
                payload["email_body"] = repaired_body
                file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
                repaired_count += 1
            else:
                repaired_count += 1

    return corrupted_found, repaired_count, diff_outputs


def main():
    parser = argparse.ArgumentParser(
        description="One-time repair utility for content-block repr email drafts."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})"
    )
    parser.add_argument(
        "--staged-dir",
        type=Path,
        default=DEFAULT_STAGED_DIR,
        help=f"Path to staged delivery JSON directory (default: {DEFAULT_STAGED_DIR})"
    )
    parser.add_argument(
        "--include-staged",
        action="store_true",
        default=False,
        help="Also scan and repair staged deliveries JSON files in --staged-dir"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write repairs to database/files (default: dry run only)"
    )

    args = parser.parse_args()

    mode_str = "APPLY (WRITING TO DISK)" if args.apply else "DRY RUN (READ ONLY)"

    print("=" * 72)
    print(f" 🛠️  EMAIL DRAFT CONTENT-BLOCK REPAIR UTILITY - [{mode_str}]")
    print("=" * 72)
    print(f" • Target Database : {args.db}")
    print(f" • Mode            : {mode_str}")
    if args.include_staged:
        print(f" • Staged Directory: {args.staged_dir}")
    print("=" * 72)

    # 1. Database scan
    db_corrupted, db_repaired, db_diffs = scan_and_repair_db(args.db, apply_changes=args.apply)

    if db_diffs:
        print(f"\n[Database Scan] Found {db_corrupted} corrupted field(s) across tables:")
        print("-" * 72)
        for d in db_diffs:
            print(d)
            print("-" * 72)
    else:
        print(f"\n[Database Scan] No corrupted content-block rows found in {args.db}.")

    # 2. Staged deliveries scan (optional)
    staged_corrupted = 0
    staged_repaired = 0
    if args.include_staged:
        staged_corrupted, staged_repaired, staged_diffs = scan_and_repair_staged_files(
            args.staged_dir, apply_changes=args.apply
        )
        if staged_diffs:
            print(f"\n[Staged Deliveries Scan] Found {staged_corrupted} corrupted file(s):")
            print("-" * 72)
            for d in staged_diffs:
                print(d)
                print("-" * 72)
        else:
            print(f"\n[Staged Deliveries Scan] No corrupted files found in {args.staged_dir}.")

    # Summary
    total_corrupted = db_corrupted + staged_corrupted
    total_repaired = db_repaired + staged_repaired

    print("\n" + "=" * 72)
    print(" 📊 REPAIR SUMMARY")
    print("=" * 72)
    print(f" • Database Rows Corrupted : {db_corrupted}")
    if args.include_staged:
        print(f" • Staged Files Corrupted  : {staged_corrupted}")
    print(f" • Total Corrupted Targets : {total_corrupted}")

    if args.apply:
        print(f" • Total Successfully Fixed: {total_repaired}")
        print(" ✓ Repair operation complete.")
    else:
        print(f" • Proposed Repairs        : {total_repaired}")
        print(" ℹ️  DRY RUN ONLY. No changes were committed.")
        print("    Pass --apply to commit these repairs.")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()

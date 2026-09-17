#!/usr/bin/env python3
"""
Restore Utility for Outbound Lead Generation Pipeline.
Extracts a verified backup archive, validates SQLite database integrity,
and restores data/outbound.db, contacted_companies.jsonl, and staged_deliveries/.
Supports --dry-run to inspect and validate without modifying runtime data.
"""
import os
import sys
import shutil
import sqlite3
import tarfile
import argparse
import tempfile
from pathlib import Path

DEFAULT_DB_PATH = Path("data/outbound.db")
DEFAULT_CONTACTED_LOG = Path("contacted_companies.jsonl")
DEFAULT_STAGED_DIR = Path("staged_deliveries")


def safe_extractall(tar: tarfile.TarFile, path: Path) -> None:
    """Safely extracts tar contents using data filter on Python 3.12+ to prevent traversal."""
    try:
        tar.extractall(path=path, filter="data")
    except TypeError:
        tar.extractall(path=path)


def inspect_and_validate_backup(archive_path: Path) -> dict:
    """Inspects the tarball and validates the embedded SQLite database."""
    if not archive_path.exists():
        raise FileNotFoundError(f"Backup archive not found: {archive_path}")

    summary = {
        "has_database": False,
        "has_contacted_log": False,
        "has_staged_deliveries": False,
        "staged_file_count": 0,
        "db_integrity_ok": False,
        "db_tables": []
    }

    with tempfile.TemporaryDirectory(prefix="outbound_validate_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        with tarfile.open(archive_path, "r:gz") as tar:
            safe_extractall(tar, tmp_path)

        db_file = tmp_path / "outbound.db"
        if db_file.exists():
            summary["has_database"] = True
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check;")
                res = cursor.fetchone()
                if res and res[0] == "ok":
                    summary["db_integrity_ok"] = True
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                summary["db_tables"] = [row[0] for row in cursor.fetchall()]
            finally:
                conn.close()

        contacted = tmp_path / "contacted_companies.jsonl"
        if contacted.exists():
            summary["has_contacted_log"] = True

        staged = tmp_path / "staged_deliveries"
        if staged.exists() and staged.is_dir():
            summary["has_staged_deliveries"] = True
            summary["staged_file_count"] = len(list(staged.glob("*.json")))

    return summary


def restore_backup(
    archive_path: Path,
    target_db_path: Path = DEFAULT_DB_PATH,
    target_contacted_log: Path = DEFAULT_CONTACTED_LOG,
    target_staged_dir: Path = DEFAULT_STAGED_DIR,
    dry_run: bool = False
) -> None:
    """Performs extraction and restoration of the backup archive."""
    print(f"[Restore] Validating archive: {archive_path}")
    validation = inspect_and_validate_backup(archive_path)

    print(f"  • Database Present: {validation['has_database']} (Integrity: {'OK' if validation['db_integrity_ok'] else 'FAILED'})")
    print(f"  • Database Tables : {', '.join(validation['db_tables'])}")
    print(f"  • Contacted History: {validation['has_contacted_log']}")
    print(f"  • Staged Deliveries: {validation['has_staged_deliveries']} ({validation['staged_file_count']} files)")

    if validation["has_database"] and not validation["db_integrity_ok"]:
        raise RuntimeError("Database in backup archive failed PRAGMA integrity_check. Aborting restore.")

    if dry_run:
        print("[Restore] DRY RUN completed. No files were modified.")
        return

    with tempfile.TemporaryDirectory(prefix="outbound_restore_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        with tarfile.open(archive_path, "r:gz") as tar:
            safe_extractall(tar, tmp_path)

        # 1. Restore SQLite database
        src_db = tmp_path / "outbound.db"
        if src_db.exists():
            target_db_path.parent.mkdir(parents=True, exist_ok=True)
            # Remove any active WAL and SHM files to ensure clean restored state
            for ext in ["-shm", "-wal"]:
                wal_file = target_db_path.with_name(target_db_path.name + ext)
                if wal_file.exists():
                    wal_file.unlink()
            shutil.copy2(src_db, target_db_path)
            print(f"[Restore] Restored database to {target_db_path}")

        # 2. Restore Contacted History log
        src_contacted = tmp_path / "contacted_companies.jsonl"
        if src_contacted.exists():
            shutil.copy2(src_contacted, target_contacted_log)
            print(f"[Restore] Restored contacted log to {target_contacted_log}")

        # 3. Restore Staged Deliveries
        src_staged = tmp_path / "staged_deliveries"
        if src_staged.exists() and src_staged.is_dir():
            target_staged_dir.mkdir(parents=True, exist_ok=True)
            for file in src_staged.glob("*.json"):
                shutil.copy2(file, target_staged_dir / file.name)
            print(f"[Restore] Restored {len(list(src_staged.glob('*.json')))} staged deliveries to {target_staged_dir}")

    print(f"[Restore] SUCCESS: Restore completed from {archive_path}")


def main():
    parser = argparse.ArgumentParser(description="Autonomous Outbound Lead Pipeline Restore Utility")
    parser.add_argument("archive", type=Path, help="Path to the .tar.gz backup archive")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and validate archive without overwriting files")
    parser.add_argument("--target-db", type=Path, default=DEFAULT_DB_PATH, help="Path for restored database")
    args = parser.parse_args()

    try:
        restore_backup(
            archive_path=args.archive,
            target_db_path=args.target_db,
            dry_run=args.dry_run
        )
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"[Restore] ERROR: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

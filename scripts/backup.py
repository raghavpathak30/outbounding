#!/usr/bin/env python3
"""
Online, Atomic Backup Utility for Outbound Lead Generation Pipeline.
Creates a transactionally safe SQLite backup using the SQLite backup API (safe during WAL writes),
archives contacted history (contacted_companies.jsonl), and stages deliveries.
Excludes .env, credentials, temporary files, and caches.
"""
import os
import sys
import shutil
import sqlite3
import tarfile
import argparse
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Paths
DEFAULT_DB_PATH = Path("data/outbound.db")
DEFAULT_CONTACTED_LOG = Path("contacted_companies.jsonl")
DEFAULT_STAGED_DIR = Path("staged_deliveries")
DEFAULT_BACKUP_DIR = Path("backups")


def backup_sqlite_database(source_path: Path, target_path: Path) -> bool:
    """
    Performs an online, atomic SQLite backup using python sqlite3 backup API.
    Works safely without locking or corrupting live SQLite WAL databases.
    """
    if not source_path.exists():
        print(f"[Backup] Warning: SQLite database {source_path} does not exist. Skipping DB backup.")
        return False

    target_path.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(source_path))
    dst_conn = sqlite3.connect(str(target_path))

    try:
        with dst_conn:
            src_conn.backup(dst_conn, pages=100)
    finally:
        dst_conn.close()
        src_conn.close()

    # Verify integrity of the backup file
    verify_conn = sqlite3.connect(str(target_path))
    try:
        cursor = verify_conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        result = cursor.fetchone()
        if result and result[0] == "ok":
            print(f"[Backup] SQLite integrity check passed for {target_path}")
            return True
        else:
            raise RuntimeError(f"Database integrity check failed: {result}")
    finally:
        verify_conn.close()


def create_backup(
    db_path: Path = DEFAULT_DB_PATH,
    contacted_log: Path = DEFAULT_CONTACTED_LOG,
    staged_dir: Path = DEFAULT_STAGED_DIR,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    retention_count: int = 14
) -> Path:
    """Creates a timestamped, compressed backup archive."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_name = f"outbound_backup_{timestamp}.tar.gz"
    final_archive_path = backup_dir / archive_name

    with tempfile.TemporaryDirectory(prefix="outbound_backup_") as tmp_dir:
        tmp_path = Path(tmp_dir)

        # 1. Backup SQLite database atomically
        if db_path.exists():
            db_tmp = tmp_path / "outbound.db"
            backup_sqlite_database(db_path, db_tmp)

        # 2. Copy Contacted History log
        if contacted_log.exists():
            shutil.copy2(contacted_log, tmp_path / "contacted_companies.jsonl")
            print(f"[Backup] Included {contacted_log} ({contacted_log.stat().st_size} bytes)")

        # 3. Copy Staged Deliveries
        if staged_dir.exists() and staged_dir.is_dir():
            staged_tmp = tmp_path / "staged_deliveries"
            shutil.copytree(staged_dir, staged_tmp)
            file_count = len(list(staged_tmp.glob("*.json")))
            print(f"[Backup] Included {staged_dir} ({file_count} files)")

        # 4. Create compressed tarball
        with tarfile.open(final_archive_path, "w:gz") as tar:
            for item in tmp_path.iterdir():
                tar.add(item, arcname=item.name)

    print(f"[Backup] Successfully created backup: {final_archive_path} ({final_archive_path.stat().st_size} bytes)")

    # 5. Apply retention policy
    prune_old_backups(backup_dir, retention_count=retention_count)
    return final_archive_path


def prune_old_backups(backup_dir: Path, retention_count: int) -> None:
    """Retains the newest retention_count backups, deleting older ones."""
    if retention_count <= 0:
        return
    existing = sorted(backup_dir.glob("outbound_backup_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    if len(existing) > retention_count:
        for old_backup in existing[retention_count:]:
            try:
                old_backup.unlink()
                print(f"[Backup] Pruned old backup archive: {old_backup.name}")
            except Exception as e:
                print(f"[Backup] Warning: Could not remove {old_backup}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Autonomous Outbound Lead Pipeline Backup Utility")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR, help="Destination directory for backups")
    parser.add_argument("--retention", type=int, default=14, help="Number of backups to keep (default: 14)")
    args = parser.parse_args()

    try:
        archive_path = create_backup(
            db_path=args.db_path,
            backup_dir=args.backup_dir,
            retention_count=args.retention
        )
        print(f"[Backup] COMPLETED: {archive_path}")
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"[Backup] ERROR: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

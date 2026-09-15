"""
Persistent Contacted Companies Log and Volume Cap Enforcement.
Tracks all companies and contacts that reach delivery_node (staged or sent).
Prevents re-contacting and enforces hard daily and weekly outreach limits.
"""
import os
import json
import logging
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger("pipeline.contacted_log")

DEFAULT_LOG_FILE = "contacted_companies.jsonl"

def get_log_path(log_file: Optional[str] = None) -> Path:
    target = log_file or os.getenv("CONTACTED_LOG_FILE", DEFAULT_LOG_FILE)
    return Path(target)

def hash_email(email: Optional[str]) -> Optional[str]:
    """Returns SHA256 hex digest of normalized contact email."""
    if not email:
        return None
    return hashlib.sha256(email.lower().strip().encode("utf-8")).hexdigest()

def record_contacted(
    domain: str,
    contact_email: Optional[str],
    delivery_status: str,
    contact_name: Optional[str] = None,
    log_file: Optional[str] = None
) -> Dict[str, Any]:
    """
    Appends a new contacted company record to the persistent log.
    Both 'staged' and 'sent' deliveries are recorded.
    """
    p = get_log_path(log_file)
    p.parent.mkdir(parents=True, exist_ok=True)

    normalized_email = (contact_email or "").lower().strip() if contact_email else None

    record = {
        "domain": (domain or "").lower().strip(),
        "contact_email": normalized_email,
        "contact_email_hash": hash_email(normalized_email),
        "contact_name": contact_name,
        "delivery_status": delivery_status,
        "date": datetime.now().isoformat()
    }

    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    logger.info(f"Recorded contacted company: {record['domain']} ({record['contact_email']}) -> {delivery_status}")
    return record

def load_contacted_log(log_file: Optional[str] = None) -> List[Dict[str, Any]]:
    """Loads all records from the contacted companies log file."""
    p = get_log_path(log_file)
    if not p.exists():
        return []

    records = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records

def is_already_contacted(
    domain: str,
    contact_email: Optional[str] = None,
    log_file: Optional[str] = None,
    email: Optional[str] = None
) -> bool:
    """
    Checks if a domain or contact email has already reached delivery_node in previous runs.
    """
    effective_email = contact_email or email
    d_norm = (domain or "").lower().strip()
    e_norm = (effective_email or "").lower().strip() if effective_email else None
    e_hash = hash_email(effective_email)

    records = load_contacted_log(log_file)
    for r in records:
        r_domain = (r.get("domain") or "").lower().strip()
        r_email = (r.get("contact_email") or "").lower().strip() if r.get("contact_email") else None
        r_hash = r.get("contact_email_hash")

        if d_norm and r_domain == d_norm:
            return True
        if e_norm and r_email and r_email == e_norm:
            return True
        if e_hash and r_hash and r_hash == e_hash:
            return True
    return False

def get_contacted_in_window(hours: int, log_file: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns log records created within the last N hours."""
    records = load_contacted_log(log_file)
    cutoff = datetime.now() - timedelta(hours=hours)

    in_window = []
    for r in records:
        date_str = r.get("date")
        if not date_str:
            continue
        try:
            entry_time = datetime.fromisoformat(date_str)
            if entry_time >= cutoff:
                in_window.append(r)
        except (ValueError, TypeError):
            continue
    return in_window

def check_volume_caps(log_file: Optional[str] = None) -> Dict[str, Any]:
    """
    Checks daily and weekly volume caps against log timestamps.
    Returns remaining allowances and whether further processing is permitted.
    """
    max_day = int(os.getenv("MAX_SENDS_PER_DAY", "10"))
    max_week = int(os.getenv("MAX_SENDS_PER_WEEK", "50"))

    sends_today = len(get_contacted_in_window(hours=24, log_file=log_file))
    sends_week = len(get_contacted_in_window(hours=168, log_file=log_file))

    remaining_day = max(0, max_day - sends_today)
    remaining_week = max(0, max_week - sends_week)
    effective_allowance = min(remaining_day, remaining_week)

    return {
        "allowed": effective_allowance > 0,
        "remaining_day": remaining_day,
        "remaining_week": remaining_week,
        "effective_allowance": effective_allowance,
        "sends_today": sends_today,
        "sends_week": sends_week,
        "sends_this_week": sends_week,
        "max_day": max_day,
        "max_week": max_week
    }

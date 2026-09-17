"""
Central configuration for pipeline adapters, model versions, and free-tier rate limits.
Single point of configuration for model names to ensure seamless updates upon deprecation.
Runs 100% on Gemini free tier by default with zero Pro models.
"""
import os
import time
import logging
import threading
from typing import Optional, Callable, Any

logger = logging.getLogger("pipeline.config")

# Default Gemini model constants (Free Tier)
# gemini-3.6-flash: current default for fast, search-grounded discovery & drafting on free tier
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
DEFAULT_DISCOVERY_MODEL = "gemini-3.6-flash"
DEFAULT_DRAFTING_MODEL = "gemini-3.6-flash"
DEFAULT_PERSON_RESEARCH_MODEL = "gemini-3.6-flash"

# Deliverability & Confidence Thresholds
DEFAULT_MIN_EMAIL_CONFIDENCE = 80
DEFAULT_MIN_PERSON_CONFIDENCE = 0.70
DEFAULT_ALLOW_ACCEPT_ALL = False

# Proactive Call Pacing (RPM Protection)
DEFAULT_GEMINI_CALL_DELAY_MS = 2000

def get_discovery_model() -> str:
    """Precedence: GEMINI_DISCOVERY_MODEL -> GEMINI_MODEL -> DEFAULT_DISCOVERY_MODEL"""
    return os.getenv("GEMINI_DISCOVERY_MODEL", os.getenv("GEMINI_MODEL", DEFAULT_DISCOVERY_MODEL))

def get_drafting_model() -> str:
    """Precedence: GEMINI_DRAFTING_MODEL -> GEMINI_MODEL -> DEFAULT_DRAFTING_MODEL"""
    return os.getenv("GEMINI_DRAFTING_MODEL", os.getenv("GEMINI_MODEL", DEFAULT_DRAFTING_MODEL))

def get_person_research_model() -> str:
    """Precedence: GEMINI_PERSON_RESEARCH_MODEL -> GEMINI_MODEL -> DEFAULT_PERSON_RESEARCH_MODEL"""
    return os.getenv("GEMINI_PERSON_RESEARCH_MODEL", os.getenv("GEMINI_MODEL", DEFAULT_PERSON_RESEARCH_MODEL))

def get_min_email_confidence() -> int:
    try:
        return int(os.getenv("MIN_EMAIL_CONFIDENCE", str(DEFAULT_MIN_EMAIL_CONFIDENCE)))
    except ValueError:
        return DEFAULT_MIN_EMAIL_CONFIDENCE

def get_min_person_confidence() -> float:
    try:
        return float(os.getenv("MIN_PERSON_CONFIDENCE", str(DEFAULT_MIN_PERSON_CONFIDENCE)))
    except ValueError:
        return DEFAULT_MIN_PERSON_CONFIDENCE

def get_allow_accept_all() -> bool:
    return os.getenv("ALLOW_ACCEPT_ALL", "false").lower() in ["true", "1", "yes"]

def get_gemini_call_delay_ms() -> int:
    try:
        return int(os.getenv("GEMINI_CALL_DELAY_MS", str(DEFAULT_GEMINI_CALL_DELAY_MS)))
    except ValueError:
        return DEFAULT_GEMINI_CALL_DELAY_MS

GEMINI_DISCOVERY_MODEL = get_discovery_model()
GEMINI_DRAFTING_MODEL = get_drafting_model()
GEMINI_PERSON_RESEARCH_MODEL = get_person_research_model()
GEMINI_CALL_DELAY_MS = get_gemini_call_delay_ms()
MIN_EMAIL_CONFIDENCE = get_min_email_confidence()
MIN_PERSON_CONFIDENCE = get_min_person_confidence()
ALLOW_ACCEPT_ALL = get_allow_accept_all()

# Blacklist and Anti-Fabrication definitions
SYNTHETIC_EMAIL_PATTERNS = [
    "alex.morgan@",
    "placeholder@",
    "synthetic@"
]

DEFAULT_BLACKLISTED_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "test.com",
    "localhost",
    "invalid",
    "sample.com"
}


def is_blacklisted(email: Optional[str], domain: Optional[str] = None) -> bool:
    """
    Evaluates whether an email address or company domain is blacklisted or synthetic.
    Normalizes inputs (case-insensitive, whitespace stripped) and handles malformed strings safely.
    Checks:
      1. Synthetic / anti-fabrication email patterns (e.g., alex.morgan@, placeholder@).
      2. Configured BLACKLISTED_EMAILS environment variable.
      3. Default and configured BLACKLISTED_DOMAINS environment variable.
    """
    email_clean = (email or "").strip().lower() if email else ""
    domain_clean = (domain or "").strip().lower() if domain else ""

    # If domain wasn't passed explicitly, extract from email if valid
    if not domain_clean and "@" in email_clean:
        parts = email_clean.split("@", 1)
        if len(parts) == 2 and parts[1]:
            domain_clean = parts[1]

    # Strip protocol / www prefix from domain if present
    if domain_clean.startswith("https://"):
        domain_clean = domain_clean[8:]
    elif domain_clean.startswith("http://"):
        domain_clean = domain_clean[7:]
    if domain_clean.startswith("www."):
        domain_clean = domain_clean[4:]
    domain_clean = domain_clean.split("/")[0].strip()

    # 1. Anti-fabrication / synthetic email checks
    if email_clean:
        for pattern in SYNTHETIC_EMAIL_PATTERNS:
            if pattern in email_clean:
                return True
        local_part = email_clean.split("@")[0]
        if any(fake in local_part for fake in ["alex.morgan", "placeholder", "synthetic"]):
            return True

    # 2. Configured blacklisted emails
    env_emails = os.getenv("BLACKLISTED_EMAILS", "")
    if env_emails and email_clean:
        blacklisted_emails = {e.strip().lower() for e in env_emails.split(",") if e.strip()}
        if email_clean in blacklisted_emails:
            return True

    # 3. Domain checks (defaults + configured)
    env_domains = os.getenv("BLACKLISTED_DOMAINS", "")
    configured_domains = {d.strip().lower() for d in env_domains.split(",") if d.strip()}
    all_blacklisted_domains = DEFAULT_BLACKLISTED_DOMAINS | configured_domains

    if domain_clean:
        if domain_clean in all_blacklisted_domains:
            return True
        # Also check parent domain (e.g. sub.example.com -> example.com)
        for bd in all_blacklisted_domains:
            if domain_clean.endswith("." + bd):
                return True

    return False

# Global state tracking last Gemini invocation time for proactive pacing (thread-safe)
_gemini_pacing_lock = threading.Lock()
_last_gemini_call_time: float = 0.0


def reset_pacing_state():
    """Resets call timestamp state (primarily used in test fixtures)."""
    global _last_gemini_call_time
    with _gemini_pacing_lock:
        _last_gemini_call_time = 0.0


def pace_gemini_call(delay_ms: Optional[int] = None):
    """
    Proactively pauses execution to ensure at least delay_ms has elapsed since
    the previous Gemini call, preventing bursts from tripping free-tier RPM limits.
    Guaranteed thread-safe across concurrent background pipeline workers.
    """
    global _last_gemini_call_time
    with _gemini_pacing_lock:
        target_delay_ms = delay_ms if delay_ms is not None else get_gemini_call_delay_ms()
        if target_delay_ms > 0 and _last_gemini_call_time > 0:
            elapsed_ms = (time.time() - _last_gemini_call_time) * 1000.0
            if elapsed_ms < target_delay_ms:
                sleep_sec = (target_delay_ms - elapsed_ms) / 1000.0
                logger.info(f"Pacing Gemini call: sleeping {sleep_sec:.3f}s to respect RPM limits.")
                time.sleep(sleep_sec)
        _last_gemini_call_time = time.time()


# Quota Exhaustion Reporting & Exceptions
DAILY_QUOTA_RESET_MESSAGE = (
    "\n"
    + "=" * 72 + "\n"
    + " ⚠️  CRITICAL: GEMINI FREE TIER DAILY QUOTA EXHAUSTED (429 RESOURCE_EXHAUSTED)\n"
    + "=" * 72 + "\n"
    + " The free tier daily request limit (RPD) has been reached for this API key.\n"
    + " Free tier quotas reset daily at midnight Pacific Time (00:00 PST / 08:00 UTC).\n"
    + "\n"
    + " Next steps:\n"
    + "   1. Wait until midnight Pacific Time for your free tier quota to refresh.\n"
    + "   2. Or switch to STUB mode (DISCOVERY_MODE=stub, DRAFTING_MODE=stub).\n"
    + "   3. Or set GEMINI_DRAFTING_MODEL in .env if pay-as-you-go billing is enabled.\n"
    + "=" * 72 + "\n"
)


class DailyQuotaExhaustedError(RuntimeError):
    """Raised when Gemini free tier daily quota (RPD) is confirmed exhausted."""
    pass


_daily_quota_banner_printed: bool = False


def reset_quota_state():
    """Resets daily quota banner state (primarily used in test fixtures)."""
    global _daily_quota_banner_printed
    _daily_quota_banner_printed = False


def print_daily_quota_message():
    """Prints the daily quota exhaustion banner exactly once per process execution."""
    global _daily_quota_banner_printed
    if not _daily_quota_banner_printed:
        print(DAILY_QUOTA_RESET_MESSAGE)
        _daily_quota_banner_printed = True


def is_429_error(exc: BaseException) -> bool:
    """Determines whether an exception represents a 429 / RESOURCE_EXHAUSTED error."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in [429, "429"]:
        return True

    status = getattr(exc, "status", None)
    if status in ["RESOURCE_EXHAUSTED", 429]:
        return True

    err_str = str(exc).upper()
    return "429" in err_str or "RESOURCE_EXHAUSTED" in err_str


def is_daily_quota_error(exc: BaseException) -> bool:
    """
    Checks if error message explicitly indicates daily quota exhaustion (RPD)
    rather than transient per-minute rate limiting (RPM).
    """
    err_str = str(exc).lower()
    rpd_indicators = [
        "per day",
        "requests per day",
        "daily request",
        "daily quota",
        "quota exceeded for quota metric 'requests' and limit 'requests per day'",
        "quota exceeded for quota metric 'generatecontent requests per day'",
        "rpd",
        "free tier limit reached for today",
        "daily limit"
    ]
    return any(ind in err_str for ind in rpd_indicators)


def execute_with_quota_retry(
    call_fn: Callable[[], Any],
    adapter_name: str = "Gemini",
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0
) -> Any:
    """
    Executes call_fn with proactive call pacing and quota-aware 429 retry/backoff.
    Distinguishes RPM throttling from RPD daily exhaustion:
    - Proactively paces call using GEMINI_CALL_DELAY_MS.
    - On 429 RESOURCE_EXHAUSTED:
      * If error explicitly mentions daily quota, immediately prints DAILY_QUOTA_RESET_MESSAGE (once) and raises DailyQuotaExhaustedError.
      * Otherwise, attempts up to max_retries with exponential backoff (RPM throttling).
      * If retries are exhausted on 429, treats as persistent daily exhaustion, prints message (once), and raises DailyQuotaExhaustedError.
    """
    attempt = 0
    delay = initial_delay
    while True:
        pace_gemini_call()
        try:
            return call_fn()
        except Exception as e:
            if is_429_error(e):
                if is_daily_quota_error(e):
                    print_daily_quota_message()
                    logger.error(f"[{adapter_name}] Gemini free tier daily quota exhausted: {e}")
                    raise DailyQuotaExhaustedError(DAILY_QUOTA_RESET_MESSAGE) from e

                attempt += 1
                if attempt > max_retries:
                    print_daily_quota_message()
                    logger.error(
                        f"[{adapter_name}] Gemini 429 persists after {max_retries} retries. "
                        f"Treating as daily quota exhaustion (resets midnight Pacific): {e}"
                    )
                    raise DailyQuotaExhaustedError(DAILY_QUOTA_RESET_MESSAGE) from e

                logger.warning(
                    f"[{adapter_name}] Gemini 429 RPM throttling detected (attempt {attempt}/{max_retries}). "
                    f"Backing off for {delay:.1f}s before retry..."
                )
                time.sleep(delay)
                delay *= backoff_factor
            else:
                raise

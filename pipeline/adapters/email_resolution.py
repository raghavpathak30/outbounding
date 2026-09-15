"""
Email Resolution Adapter for resolving and verifying authentic work emails.
Integrates with Hunter.io Email Finder and Email Verifier APIs with strict deliverability gates.
"""
import os
import re
import logging
from typing import Optional, Dict, Any
import requests

from pipeline.adapters.base import EmailResolutionAdapter
from pipeline.config import (
    MIN_EMAIL_CONFIDENCE,
    ALLOW_ACCEPT_ALL,
)

logger = logging.getLogger("pipeline.adapters.email_resolution")

EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.\w+$")


class HunterEmailResolver(EmailResolutionAdapter):
    """
    Production Email Resolver using Hunter.io Email Finder API.
    Resolves domain + first_name + last_name into a verified business email.
    Enforces deliverability confidence threshold and catch-all rejection gates.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("HUNTER_API_KEY", "")

    def _verify_status_via_verifier(self, email: str) -> Dict[str, Any]:
        """Calls Hunter Email Verifier endpoint if finder verification status was unknown."""
        if not self.api_key or not email:
            return {"status": "unknown", "score": 0}
        try:
            url = f"https://api.hunter.io/v2/email-verifier?email={email}&api_key={self.api_key}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return {
                    "status": data.get("status", "unknown"),
                    "score": data.get("score", 0),
                    "result": data.get("result", "unknown")
                }
        except requests.RequestException as e:
            logger.warning(f"Hunter verification check error for {email}: {e}")
        return {"status": "unknown", "score": 0}

    def resolve_email(
        self,
        domain: str,
        first_name: str,
        last_name: str,
        role: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Resolves domain + first_name + last_name to verified email via Hunter.io.
        Returns resolution dict if deliverability gates pass, or None.
        """
        if not self.api_key:
            logger.warning("HUNTER_API_KEY not configured; cannot resolve emails via Hunter.")
            return {
                "email": None,
                "score": 0,
                "status": "provider_error",
                "reason": "missing_api_key",
                "provider": "hunter",
                "sources_count": 0
            }

        clean_d = (domain or "").strip().lower()
        fn = (first_name or "").strip()
        ln = (last_name or "").strip()

        if not clean_d or not fn or not ln:
            logger.warning(f"Insufficient parameters for email resolution: domain='{clean_d}', fn='{fn}', ln='{ln}'")
            return {
                "email": None,
                "score": 0,
                "status": "not_found",
                "reason": "insufficient_parameters",
                "provider": "hunter",
                "sources_count": 0
            }

        try:
            url = f"https://api.hunter.io/v2/email-finder?domain={clean_d}&first_name={fn}&last_name={ln}&api_key={self.api_key}"
            resp = requests.get(url, timeout=8)

            if resp.status_code == 429:
                logger.warning(f"Hunter API rate limit (429) encountered for {fn} {ln} at {clean_d}.")
                return {
                    "email": None,
                    "score": 0,
                    "status": "provider_error",
                    "reason": "rate_limit_exceeded",
                    "provider": "hunter",
                    "sources_count": 0
                }
            elif resp.status_code in [401, 403]:
                logger.warning(f"Hunter API authentication failure ({resp.status_code}). Check HUNTER_API_KEY.")
                return {
                    "email": None,
                    "score": 0,
                    "status": "provider_error",
                    "reason": f"auth_failure_{resp.status_code}",
                    "provider": "hunter",
                    "sources_count": 0
                }
            elif resp.status_code != 200:
                logger.warning(f"Hunter email-finder returned HTTP {resp.status_code} for {clean_d}.")
                return {
                    "email": None,
                    "score": 0,
                    "status": "provider_error",
                    "reason": f"http_status_{resp.status_code}",
                    "provider": "hunter",
                    "sources_count": 0
                }

            res_json = resp.json()
            data = res_json.get("data") or {}
            candidate_email = data.get("email")

            if not candidate_email:
                logger.info(f"Hunter found no email for {fn} {ln} at {clean_d}.")
                return {
                    "email": None,
                    "score": 0,
                    "status": "not_found",
                    "reason": "no_email_returned_by_provider",
                    "provider": "hunter",
                    "sources_count": 0
                }

            candidate_email = str(candidate_email).strip().lower()
            if not EMAIL_REGEX.match(candidate_email):
                logger.warning(f"Hunter candidate email {candidate_email} failed syntax regex.")
                return {
                    "email": None,
                    "score": 0,
                    "status": "invalid",
                    "reason": "invalid_syntax",
                    "provider": "hunter",
                    "sources_count": 0
                }

            score = int(data.get("score") or 0)
            verification = data.get("verification") or {}
            status = verification.get("status", "unknown")
            sources = data.get("sources") or []

            # If status is unknown, attempt dedicated email-verifier check
            if status == "unknown":
                ver_check = self._verify_status_via_verifier(candidate_email)
                status = ver_check.get("status", "unknown")
                if ver_check.get("score"):
                    score = max(score, ver_check.get("score", 0))

            # Deliverability Gate 1: Confidence Score Threshold
            if score < MIN_EMAIL_CONFIDENCE:
                logger.warning(
                    f"Hunter email {candidate_email} rejected: score {score} is below threshold {MIN_EMAIL_CONFIDENCE}."
                )
                return {
                    "email": None,
                    "score": score,
                    "status": "invalid" if status == "invalid" else "low_confidence",
                    "reason": f"score_{score}_below_threshold_{MIN_EMAIL_CONFIDENCE}",
                    "provider": "hunter",
                    "sources_count": len(sources)
                }

            # Deliverability Gate 2: Status Check
            if status == "invalid":
                logger.warning(f"Hunter email {candidate_email} rejected: verification status is 'invalid'.")
                return {
                    "email": None,
                    "score": score,
                    "status": "invalid",
                    "reason": "mailbox_invalid_or_nonexistent",
                    "provider": "hunter",
                    "sources_count": len(sources)
                }

            if status == "accept_all":
                # Catch-all domain handling
                if not ALLOW_ACCEPT_ALL:
                    logger.warning(
                        f"Hunter email {candidate_email} rejected: domain is catch-all (accept_all) and ALLOW_ACCEPT_ALL=false."
                    )
                    return {
                        "email": None,
                        "score": score,
                        "status": "accept_all",
                        "reason": "catch_all_rejected_by_policy",
                        "provider": "hunter",
                        "sources_count": len(sources)
                    }
                # If ALLOW_ACCEPT_ALL is true, enforce stricter threshold & source requirement
                if score < 85 or len(sources) < 1:
                    logger.warning(
                        f"Hunter catch-all email {candidate_email} rejected: score {score} < 85 or no supporting web sources."
                    )
                    return {
                        "email": None,
                        "score": score,
                        "status": "accept_all",
                        "reason": "catch_all_score_insufficient_or_no_sources",
                        "provider": "hunter",
                        "sources_count": len(sources)
                    }

            if status not in ["valid", "accept_all"]:
                logger.warning(f"Hunter email {candidate_email} rejected: status '{status}' is unverified.")
                return {
                    "email": None,
                    "score": score,
                    "status": "unverified",
                    "reason": f"status_{status}_unverified",
                    "provider": "hunter",
                    "sources_count": len(sources)
                }

            logger.info(f"Hunter resolved valid email for {fn} {ln} at {clean_d}: {candidate_email} (score: {score}, status: {status})")
            return {
                "email": candidate_email,
                "score": score,
                "status": status,
                "reason": "deliverable_verified",
                "provider": "hunter",
                "sources_count": len(sources)
            }

        except requests.RequestException as e:
            logger.warning(f"Hunter API request error resolving email for {clean_d}: {e}")
            return {
                "email": None,
                "score": 0,
                "status": "provider_error",
                "reason": f"request_exception: {e}",
                "provider": "hunter",
                "sources_count": 0
            }


class StubEmailResolver(EmailResolutionAdapter):
    """
    Deterministic stub email resolver for zero-network testing.
    Only returns emails for explicitly recognized test fixtures.
    Returns None for arbitrary or unverified domains.
    """

    MOCK_RESOLUTIONS = {
        ("apex-vault-fintech.io", "devon", "sterling"): {
            "email": "devon.sterling@apex-vault-fintech.io",
            "score": 95,
            "status": "valid",
            "provider": "hunter_stub",
            "sources_count": 3
        },
        ("hyperion-inference-labs.io", "maya", "lin"): {
            "email": "maya.lin@hyperion-inference-labs.io",
            "score": 95,
            "status": "valid",
            "provider": "hunter_stub",
            "sources_count": 2
        },
        ("nexus-talent-partners.co", "julian", "rivera"): {
            "email": "julian.rivera@nexus-talent-partners.co",
            "score": 95,
            "status": "valid",
            "provider": "hunter_stub",
            "sources_count": 2
        },
        ("cyber-corp.com", "marcus", "vance"): {
            "email": "marcus.vance@cyber-corp.com",
            "score": 95,
            "status": "valid",
            "provider": "hunter_stub",
            "sources_count": 4
        },
        ("mock-crypto.test", "alice", "walker"): {
            "email": "alice.walker@mock-crypto.test",
            "score": 95,
            "status": "valid",
            "provider": "hunter_stub",
            "sources_count": 3
        }
    }

    def resolve_email(
        self,
        domain: str,
        first_name: str,
        last_name: str,
        role: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        d_lower = (domain or "").strip().lower()
        fn = (first_name or "").strip().lower()
        ln = (last_name or "").strip().lower()

        # Check explicit test fixtures
        key = (d_lower, fn, ln)
        if key in self.MOCK_RESOLUTIONS:
            res = dict(self.MOCK_RESOLUTIONS[key])
            res["reason"] = "deliverable_verified"
            return res

        # Test case: invalid domain/name
        if any(k in d_lower for k in ["invalid", "no-email", "missing"]):
            return {
                "email": None,
                "score": 0,
                "status": "invalid",
                "reason": "invalid_domain_test_fixture",
                "provider": "hunter_stub",
                "sources_count": 0
            }

        # Test case: catch-all
        if "accept-all" in d_lower or "accept_all" in d_lower:
            candidate = f"{fn}.{ln}@{d_lower}"
            if not ALLOW_ACCEPT_ALL:
                return {
                    "email": None,
                    "score": 88,
                    "status": "accept_all",
                    "reason": "catch_all_rejected_by_policy",
                    "provider": "hunter_stub",
                    "sources_count": 1
                }
            return {
                "email": candidate,
                "score": 88,
                "status": "accept_all",
                "reason": "deliverable_verified",
                "provider": "hunter_stub",
                "sources_count": 1
            }

        # Test case: low-confidence
        if "low-confidence" in d_lower or "weak" in d_lower:
            return {
                "email": None,
                "score": 50,
                "status": "low_confidence",
                "reason": "score_50_below_threshold",
                "provider": "hunter_stub",
                "sources_count": 0
            }

        # Default for unknown in stub mode: return structured not_found, NEVER fabricate
        return {
            "email": None,
            "score": 0,
            "status": "not_found",
            "reason": "unmatched_stub_fixture",
            "provider": "hunter_stub",
            "sources_count": 0
        }

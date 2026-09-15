"""
Discovery Node implementation for automated target company surfacing.
Surfaces candidates matching candidate profile (cryptography, cybersecurity, fraud detection, AI infra/security)
with optional company size filtering, skipping already contacted companies.
"""
import logging
from typing import Dict, Any
from pipeline.state import PipelineState
from pipeline.adapters.base import AdapterFactory
from pipeline.contacted_log import is_already_contacted

logger = logging.getLogger("pipeline.discovery")

def discovery_node(state: PipelineState) -> Dict[str, Any]:
    """
    Discovery Node:
    - If domain is already provided, passes it through.
    - Otherwise, discovers uncontacted companies via DiscoveryAdapter matching technical profile.
    """
    existing_domain = state.get("domain")
    if existing_domain:
        logger.info(f"Target domain already provided ({existing_domain}), bypassing discovery.")
        return {
            "domain": existing_domain,
            "company_name": state.get("company_name"),
            "company_context": state.get("company_context"),
            "discover": state.get("discover", False),
        }

    company_size = state.get("company_size") or "any"
    adapter = AdapterFactory.get_discovery_adapter()
    candidates = adapter.discover(limit=10, company_size=company_size)

    for cand in candidates:
        domain = cand.get("domain")
        if domain and not is_already_contacted(domain=domain):
            logger.info(f"Discovered new uncontacted company: {cand.get('company_name')} ({domain})")
            return {
                "domain": domain,
                "company_name": cand.get("company_name"),
                "company_context": cand.get("company_context"),
                "discover": True,
            }

    if candidates:
        # If all candidates in current batch were contacted, fallback to first candidate
        cand = candidates[0]
        logger.warning(f"All discovered candidates were previously contacted. Using: {cand.get('domain')}")
        return {
            "domain": cand.get("domain"),
            "company_name": cand.get("company_name"),
            "company_context": cand.get("company_context"),
            "discover": True,
        }

    logger.warning("No candidate companies discovered.")
    return {
        "domain": "",
        "company_name": None,
        "company_context": None,
        "discover": True,
    }

"""
Delivery Node implementation with safety staging and webhook payload formatting.
"""
from typing import Dict, Any
import os
from pipeline.state import PipelineState
from pipeline.adapters.base import AdapterFactory
from pipeline.contacted_log import record_contacted
from pipeline.config import ALLOW_ACCEPT_ALL

def delivery_node(state: PipelineState) -> Dict[str, Any]:
    """
    Delivery Node: Formats Instantly.ai / Lemlist webhook payload with
    sender identification and opt-out footer, staging to staged_deliveries/.
    """
    domain = state.get("domain", "")
    email = state.get("contact_email")
    name = state.get("contact_name") or "Colleague"
    role = state.get("contact_role") or "Lead"
    draft = state.get("email_draft") or ""
    subject = state.get("email_subject")
    body_text = draft

    if draft.startswith("Subject:"):
        parts = draft.split("\n\n", 1)
        subject = parts[0].replace("Subject:", "").strip()
        body_text = parts[1] if len(parts) > 1 else draft

    if not subject:
        subject = f"Technical Collaboration & Opportunities at {domain}"

    sender_identity = "Raghav Pathak <raghav.candidate.outreach@example.com>"
    opt_out_footer = "\n\n---\nIf you prefer not to receive technical outreach, simply reply with 'unsubscribe' to be permanently removed."

    # Anti-Fabrication Safety Gate
    email_lower = (email or "").lower().strip()
    if not email_lower or "@" not in email_lower:
        return {
            "delivery_status": "skipped_no_email",
            "delivery_error": "refused_missing_email"
        }

    if any(fake in email_lower for fake in ["alex.morgan@", "placeholder@", "synthetic@"]):
        return {
            "delivery_status": "skipped_fabricated_contact",
            "delivery_error": "refused_fabrication_attempt"
        }

    ver_status = state.get("email_verification_status")
    if ver_status in ["invalid", "low_confidence", "not_found", "provider_error", "unverified"]:
        return {
            "delivery_status": "skipped_unverified_email",
            "delivery_error": f"refused_verification_status_{ver_status}"
        }

    if ver_status == "accept_all" and not ALLOW_ACCEPT_ALL:
        return {
            "delivery_status": "skipped_unverified_email",
            "delivery_error": "refused_catch_all_policy"
        }

    payload = {
        "campaign_id": "outbound_tech_lead_sequence_v1",
        "domain": domain,
        "recipient": {
            "name": name,
            "email": email,
            "role": role
        },
        "sender": sender_identity,
        "email_subject": subject,
        "email_body": body_text + opt_out_footer,
        "custom_variables": {
            "company_domain": domain,
            "role_title": role,
            "candidate_portfolio": "https://raghavpathak.dev"
        }
    }
    if state.get("company_context"):
        ctx = state["company_context"]
        payload["custom_variables"]["company_signal"] = ctx.get("signal") if isinstance(ctx, dict) else str(ctx)
    if state.get("person_confidence") is not None:
        payload["custom_variables"]["person_confidence"] = str(state.get("person_confidence"))
    if state.get("email_confidence") is not None:
        payload["custom_variables"]["email_confidence"] = str(state.get("email_confidence"))
    if state.get("email_verification_status"):
        payload["custom_variables"]["email_verification_status"] = state.get("email_verification_status")

    dry_run_env = os.getenv("DRY_RUN", "true").lower() in ["true", "1", "yes"]
    confirm_live_env = os.getenv("CONFIRM_LIVE", "false").lower() in ["true", "1", "yes"]
    review_status = state.get("review_status")

    adapter = AdapterFactory.get_delivery_adapter()
    result = adapter.deliver(
        payload,
        dry_run=dry_run_env,
        confirm_live=confirm_live_env,
        review_status=review_status
    )

    out = {
        "delivery_status": result.get("status", "staged")
    }
    if result.get("error"):
        out["delivery_error"] = result["error"]

    if domain:
        record_contacted(
            domain=domain,
            contact_email=email,
            delivery_status=out["delivery_status"],
            contact_name=name
        )

    return out


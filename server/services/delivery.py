"""
Authoritative Delivery Service for Phase 8.
Connects human review approval to outbound delivery with authoritative safety gates.
Enforces:
  1. Strict tenant isolation (Campaign.user_id)
  2. PipelineRun status == 'waiting_for_delivery'
  3. Review approval gate (Review.status == 'approved')
  4. Immutable draft integrity (approved subject & body)
  5. RFC email syntax validation
  6. Canonical blacklist & anti-fabrication filtering
  7. Database email verification status
  8. Person confidence threshold (>= 0.70)
  9. Race-safe deduplication union (JSONL + DB Delivery + Company contacted)
  10. Unified volume caps (10/day, 50/week across CLI and Web)
  11. Server-side live send gate (DELIVERY_MODE=live, DRY_RUN=False, CONFIRM_LIVE=True)

ZERO external provider side effects on any safety rejection or dry-run staging.
"""
import os
import re
import json
import logging
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session

from server.models.entities import (
    PipelineRun,
    Company,
    Campaign,
    Person,
    Contact,
    Draft,
    Review,
    Delivery,
    PipelineEvent,
    utc_now,
)
from server.config import get_settings
from pipeline.adapters.base import AdapterFactory
from pipeline.contacted_log import (
    record_contacted,
    is_already_contacted as jsonl_is_already_contacted,
    get_contacted_in_window as jsonl_get_contacted_in_window,
)
from pipeline.config import (
    is_blacklisted,
    MIN_PERSON_CONFIDENCE,
    ALLOW_ACCEPT_ALL,
    get_allow_accept_all,
)

logger = logging.getLogger("server.services.delivery")

# Mutex protecting delivery claims against concurrent requests/worker threads
_delivery_lock = threading.Lock()

# Email validation regex (RFC 5322 compliant basic structure)
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


# =====================================================================
# Pydantic Schemas
# =====================================================================

class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_run_id: str
    company_id: str
    contact_id: Optional[str] = None
    delivery_mode: str  # stub, staged, live
    delivery_status: str  # staged, sent, failed, blocked_safety
    provider: str
    staged_file_path: Optional[str] = None
    delivered_at: datetime
    error: Optional[str] = None
    safety_audit: Optional[Dict[str, Any]] = None


# =====================================================================
# Delivery Service
# =====================================================================

class DeliveryService:
    """
    Authoritative server-side delivery boundary.
    The single conceptual and practical execution point for outbound email delivery.
    """

    @staticmethod
    def sanitize_error(raw_err: Any) -> str:
        """Sanitizes error messages to protect secrets, tokens, API keys, and stack traces."""
        if not raw_err:
            return "Unknown delivery error."
        msg = str(raw_err).strip()

        # Redact secrets, keys, and authorization headers
        msg = re.sub(r"(?i)(api[_-]?key|token|secret|password|bearer|authorization)[=:\s]+['\"]?[a-zA-Z0-9_\-\.]{8,}['\"]?", r"\1=[REDACTED]", msg)
        msg = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_API_KEY]", msg)
        msg = re.sub(r"/(?:[a-zA-Z0-9_\.\-]+/)+[a-zA-Z0-9_\.\-]+", "[internal_path]", msg)

        # Strip multi-line stack trace
        lines = [line.strip() for line in msg.splitlines() if line.strip()]
        clean_lines = [l for l in lines if not l.startswith("Traceback") and not l.startswith("File \"") and not l.startswith("During handling")]
        cleaned = " ".join(clean_lines) if clean_lines else "Delivery error occurred."

        if len(cleaned) > 255:
            cleaned = cleaned[:252] + "..."
        return cleaned

    @classmethod
    def validate_email_syntax(cls, email: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Validates recipient email syntax against RFC standard structure."""
        if not email or not isinstance(email, str):
            return False, "Recipient email is missing or not a string."
        clean = email.strip()
        if not clean or "@" not in clean:
            return False, "Recipient email is missing '@' delimiter."
        if not EMAIL_REGEX.match(clean):
            return False, "Recipient email failed RFC syntax validation."
        return True, None

    @classmethod
    def check_dedupe_union(
        cls,
        db: Session,
        domain: str,
        email: Optional[str],
        company_id: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Authoritative Deduplication Check:
        Union of 3 sources:
          1. Historical CLI contacted_companies.jsonl
          2. Database Delivery records with status in ('staged', 'sent')
          3. Company.selection_status == 'contacted'
        """
        # 1. Check CLI JSONL log
        if jsonl_is_already_contacted(domain=domain, contact_email=email):
            return True, f"Recipient or domain '{domain}' was previously contacted in CLI history (contacted_companies.jsonl)."

        # 2. Check DB Delivery records for company or email
        existing_deliv = db.execute(
            select(Delivery)
            .where(
                Delivery.company_id == company_id,
                Delivery.delivery_status.in_(["staged", "sent"])
            )
        ).scalars().first()
        if existing_deliv:
            return True, f"Company {company_id} has an existing {existing_deliv.delivery_status} delivery (Delivery ID: {existing_deliv.id})."

        # Check DB Delivery for email match across contacts
        if email:
            email_lower = email.strip().lower()
            existing_email_deliv = db.execute(
                select(Delivery)
                .join(Contact, Delivery.contact_id == Contact.id)
                .where(
                    func.lower(Contact.email) == email_lower,
                    Delivery.delivery_status.in_(["staged", "sent"])
                )
            ).scalars().first()
            if existing_email_deliv:
                return True, f"Recipient email '{email}' has an existing {existing_email_deliv.delivery_status} delivery (Delivery ID: {existing_email_deliv.id})."

        # 3. Check Company.selection_status
        company = db.execute(select(Company).where(Company.id == company_id)).scalar_one_or_none()
        if company and company.selection_status == "contacted":
            return True, f"Company '{company.company_name}' ({domain}) already marked as contacted."

        return False, None

    @classmethod
    def check_volume_caps_unified(
        cls,
        db: Session
    ) -> Tuple[bool, Optional[str], Dict[str, Any]]:
        """
        Enforces 10/day and 50/week volume caps unifying:
          - CLI contacted_companies.jsonl records
          - DB Delivery records with status in ('staged', 'sent')
        Deduplicates entries that appear in both sources within 60s windows to avoid double-counting.
        """
        max_day = int(os.getenv("MAX_SENDS_PER_DAY", "10"))
        max_week = int(os.getenv("MAX_SENDS_PER_WEEK", "50"))

        now = utc_now()
        day_cutoff = now - timedelta(hours=24)
        week_cutoff = now - timedelta(hours=168)

        # 1. Query DB deliveries in window
        db_deliveries_week = list(
            db.execute(
                select(Delivery, Company, Contact)
                .outerjoin(Company, Delivery.company_id == Company.id)
                .outerjoin(Contact, Delivery.contact_id == Contact.id)
                .where(
                    Delivery.delivery_status.in_(["staged", "sent"]),
                    Delivery.delivered_at >= week_cutoff
                )
            ).all()
        )

        # 2. Query JSONL records in window
        jsonl_records_week = jsonl_get_contacted_in_window(hours=168)

        # Deduplicate union of events by (domain, email, hour_bucket)
        seen_events_day = set()
        seen_events_week = set()

        for deliv, comp, cont in db_deliveries_week:
            deliv_time = deliv.delivered_at
            if deliv_time.tzinfo is None:
                deliv_time = deliv_time.replace(tzinfo=timezone.utc)

            dom = (comp.domain.lower() if comp else "unknown").strip()
            em = (cont.email.lower() if cont and cont.email else "").strip()
            time_bucket = deliv_time.strftime("%Y%m%d%H%M")
            event_key = f"{dom}:{em}:{time_bucket}"

            seen_events_week.add(event_key)
            if deliv_time >= day_cutoff:
                seen_events_day.add(event_key)

        for rec in jsonl_records_week:
            dom = (rec.get("domain") or "unknown").strip().lower()
            em = (rec.get("contact_email") or "").strip().lower()
            date_str = rec.get("date", "")
            try:
                rec_time = datetime.fromisoformat(date_str)
                if rec_time.tzinfo is None:
                    rec_time = rec_time.replace(tzinfo=timezone.utc)
                time_bucket = rec_time.strftime("%Y%m%d%H%M")
                event_key = f"{dom}:{em}:{time_bucket}"

                seen_events_week.add(event_key)
                if rec_time >= day_cutoff:
                    seen_events_day.add(event_key)
            except Exception:
                # Fallback if unparseable date
                seen_events_week.add(f"{dom}:{em}:{date_str}")

        count_day = len(seen_events_day)
        count_week = len(seen_events_week)

        stats = {
            "sends_today": count_day,
            "sends_week": count_week,
            "max_day": max_day,
            "max_week": max_week,
            "remaining_day": max(0, max_day - count_day),
            "remaining_week": max(0, max_week - count_week),
        }

        if count_day >= max_day:
            return False, f"Daily volume cap exceeded: {count_day}/{max_day} sends in last 24h.", stats
        if count_week >= max_week:
            return False, f"Weekly volume cap exceeded: {count_week}/{max_week} sends in last 7 days.", stats

        return True, None, stats

    @classmethod
    def deliver_pipeline_run(
        cls,
        db: Session,
        run_id: str,
        user_id: Optional[str] = None
    ) -> DeliveryResponse:
        """
        Authoritative delivery entrypoint.
        Loads all run context, validates tenant ownership, revalidates every safety gate,
        atomically claims the delivery, and executes staged or live delivery.
        """
        with _delivery_lock:
            # 1. Load PipelineRun with related entities
            stmt = (
                select(PipelineRun, Campaign, Company, Draft, Review)
                .join(Campaign, PipelineRun.campaign_id == Campaign.id)
                .join(Company, PipelineRun.company_id == Company.id)
                .outerjoin(Draft, PipelineRun.id == Draft.pipeline_run_id)
                .outerjoin(Review, PipelineRun.id == Review.pipeline_run_id)
                .where(PipelineRun.id == run_id)
            )
            result = db.execute(stmt).first()

            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"PipelineRun '{run_id}' not found."
                )

            run, campaign, company, draft, review = result

            # 2. Enforce Tenant Ownership
            if user_id and campaign.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="PipelineRun not found or unauthorized access."
                )

            # Check for existing Delivery record (Idempotency check)
            existing_delivery = db.execute(
                select(Delivery).where(Delivery.pipeline_run_id == run.id)
            ).scalar_one_or_none()
            if existing_delivery and existing_delivery.delivery_status in ["sent", "staged"]:
                logger.info(f"[DeliveryService] Run {run_id} already has completed delivery ({existing_delivery.delivery_status}).")
                safety_audit = None
                if existing_delivery.safety_audit_json:
                    try:
                        safety_audit = json.loads(existing_delivery.safety_audit_json)
                    except Exception:
                        pass
                return DeliveryResponse(
                    id=existing_delivery.id,
                    pipeline_run_id=run.id,
                    company_id=company.id,
                    contact_id=existing_delivery.contact_id,
                    delivery_mode=existing_delivery.delivery_mode,
                    delivery_status=existing_delivery.delivery_status,
                    provider=existing_delivery.provider,
                    staged_file_path=existing_delivery.staged_file_path,
                    delivered_at=existing_delivery.delivered_at,
                    safety_audit=safety_audit
                )

            # Load Person and Contact
            person = db.execute(
                select(Person).where(Person.company_id == company.id)
            ).scalars().first()

            contact = db.execute(
                select(Contact).where(Contact.company_id == company.id)
            ).scalars().first()

            # Initialize Safety Audit Record
            safety_audit = {
                "run_id": run.id,
                "domain": company.domain,
                "evaluated_at": utc_now().isoformat(),
                "gates": {}
            }

            # Helper for recording blocked delivery
            def block_delivery(gate_name: str, reason: str) -> DeliveryResponse:
                safety_audit["gates"][gate_name] = {"passed": False, "reason": reason}
                logger.warning(f"[DeliveryService] Run {run_id} delivery BLOCKED at gate '{gate_name}': {reason}")

                # Transition run status to skipped or failed
                run.status = "skipped" if "dedupe" in gate_name or "review" in gate_name else "failed"
                run.last_completed_stage = "delivery_blocked"
                run.error_message = cls.sanitize_error(reason)
                run.completed_at = utc_now()

                delivery_rec = existing_delivery or Delivery(
                    pipeline_run_id=run.id,
                    company_id=company.id,
                    contact_id=contact.id if contact else None,
                    delivery_mode=os.getenv("DELIVERY_MODE", "staged").lower(),
                    delivery_status="blocked_safety",
                    provider="instantly",
                    safety_audit_json=json.dumps(safety_audit),
                    delivered_at=utc_now()
                )
                if not existing_delivery:
                    db.add(delivery_rec)
                else:
                    delivery_rec.delivery_status = "blocked_safety"
                    delivery_rec.safety_audit_json = json.dumps(safety_audit)

                event = PipelineEvent(
                    pipeline_run_id=run.id,
                    campaign_id=campaign.id,
                    event_type="delivery_blocked",
                    message=f"Delivery blocked by safety gate '{gate_name}': {reason}",
                    data_json=json.dumps({"gate": gate_name, "reason": reason}),
                    created_at=utc_now()
                )
                db.add(event)
                db.commit()

                return DeliveryResponse(
                    id=delivery_rec.id,
                    pipeline_run_id=run.id,
                    company_id=company.id,
                    contact_id=contact.id if contact else None,
                    delivery_mode=delivery_rec.delivery_mode,
                    delivery_status="blocked_safety",
                    provider=delivery_rec.provider,
                    delivered_at=delivery_rec.delivered_at,
                    error=reason,
                    safety_audit=safety_audit
                )

            # =================================================================
            # REVALIDATION GATE 1: PipelineRun Status Gate
            # =================================================================
            if run.status != "waiting_for_delivery":
                return block_delivery(
                    "run_status",
                    f"PipelineRun is in '{run.status}' state (expected 'waiting_for_delivery')."
                )
            safety_audit["gates"]["run_status"] = {"passed": True}

            # =================================================================
            # REVALIDATION GATE 2: Review Approval Gate
            # =================================================================
            if not review or review.pipeline_run_id != run.id:
                return block_delivery(
                    "review_association",
                    "No associated Review found for this PipelineRun."
                )
            if review.status != "approved":
                return block_delivery(
                    "review_approval",
                    f"Review is in '{review.status}' state (expected 'approved')."
                )
            safety_audit["gates"]["review_approval"] = {"passed": True}

            # =================================================================
            # REVALIDATION GATE 3: Draft Integrity Gate
            # =================================================================
            if not draft or draft.pipeline_run_id != run.id:
                return block_delivery(
                    "draft_existence",
                    "No associated Draft found for this PipelineRun."
                )

            final_subject = (review.edited_subject or draft.subject or "").strip()
            final_body = (review.edited_body or draft.body or "").strip()

            if not final_subject:
                return block_delivery("draft_subject", "Approved draft email subject is empty.")
            if not final_body:
                return block_delivery("draft_body", "Approved draft email body is empty.")
            safety_audit["gates"]["draft_integrity"] = {"passed": True}

            # =================================================================
            # REVALIDATION GATE 4: Recipient Email Syntax & Consistency
            # =================================================================
            recipient_email = contact.email if contact else None
            is_valid_email, email_err = cls.validate_email_syntax(recipient_email)
            if not is_valid_email:
                return block_delivery("email_syntax", email_err or "Invalid recipient email syntax.")
            safety_audit["gates"]["email_syntax"] = {"passed": True, "email": recipient_email}

            # =================================================================
            # REVALIDATION GATE 5: Blacklist & Anti-Fabrication Gate
            # =================================================================
            if is_blacklisted(recipient_email, company.domain):
                return block_delivery(
                    "blacklist",
                    f"Recipient '{recipient_email}' or domain '{company.domain}' is blacklisted or synthetic."
                )
            safety_audit["gates"]["blacklist"] = {"passed": True}

            # =================================================================
            # REVALIDATION GATE 6: Email Verification Status Gate
            # =================================================================
            ver_status = contact.verification_status if contact else "unverified"
            allow_accept_all = get_allow_accept_all()

            if ver_status in ["invalid", "low_confidence", "not_found", "provider_error", "unverified"]:
                return block_delivery(
                    "email_verification",
                    f"Email verification status is unacceptable: '{ver_status}'."
                )
            if ver_status == "accept_all" and not allow_accept_all:
                return block_delivery(
                    "email_verification",
                    "Email verification status is 'accept_all' and ALLOW_ACCEPT_ALL is false."
                )
            safety_audit["gates"]["email_verification"] = {"passed": True, "status": ver_status}

            # =================================================================
            # REVALIDATION GATE 7: Person Confidence Threshold Gate (>= 0.70)
            # =================================================================
            person_conf = person.person_confidence if person else None
            min_person_conf = MIN_PERSON_CONFIDENCE

            if person_conf is None:
                return block_delivery("person_confidence", "Person confidence is missing / unverified.")
            try:
                person_conf_float = float(person_conf)
            except (ValueError, TypeError):
                return block_delivery("person_confidence", f"Person confidence '{person_conf}' is invalid.")

            if person_conf_float < min_person_conf:
                return block_delivery(
                    "person_confidence",
                    f"Person confidence {person_conf_float:.2f} is below minimum threshold ({min_person_conf:.2f})."
                )
            safety_audit["gates"]["person_confidence"] = {"passed": True, "score": person_conf_float}

            # =================================================================
            # REVALIDATION GATE 8: Deduplication Union Gate
            # =================================================================
            is_dupe, dupe_reason = cls.check_dedupe_union(
                db=db,
                domain=company.domain,
                email=recipient_email,
                company_id=company.id
            )
            if is_dupe:
                return block_delivery("deduplication", dupe_reason or "Recipient/domain already contacted.")
            safety_audit["gates"]["deduplication"] = {"passed": True}

            # =================================================================
            # REVALIDATION GATE 9: Volume Caps Gate (10/day, 50/week)
            # =================================================================
            caps_ok, cap_err, cap_stats = cls.check_volume_caps_unified(db)
            if not caps_ok:
                return block_delivery("volume_caps", cap_err or "Outreach volume cap exceeded.")
            safety_audit["gates"]["volume_caps"] = {"passed": True, "stats": cap_stats}

            # =================================================================
            # REVALIDATION GATE 10: Server-side Live Dispatch Evaluation
            # =================================================================
            try:
                settings = get_settings()
                default_mode = settings.delivery_mode
                default_dry_run = str(settings.dry_run)
                default_confirm_live = str(settings.confirm_live)
            except Exception:
                default_mode = "staged"
                default_dry_run = "true"
                default_confirm_live = "false"

            env_delivery_mode = os.getenv("DELIVERY_MODE", default_mode).lower()
            env_dry_run = os.getenv("DRY_RUN", default_dry_run).lower() in ["true", "1", "yes"]
            env_confirm_live = os.getenv("CONFIRM_LIVE", default_confirm_live).lower() in ["true", "1", "yes"]

            is_live_authorized = (
                env_delivery_mode == "live" and
                not env_dry_run and
                env_confirm_live and
                review.status == "approved"
            )

            # Assemble payload for dispatch / staging
            recipient_name = person.full_name if person and person.full_name else (person.first_name if person else "Colleague")
            recipient_role = person.role if person and person.role else "Lead"
            opt_out_footer = "\n\n---\nIf you prefer not to receive technical outreach, simply reply with 'unsubscribe' to be permanently removed."

            payload = {
                "campaign_id": campaign.id,
                "domain": company.domain,
                "recipient": {
                    "name": recipient_name,
                    "email": recipient_email,
                    "role": recipient_role
                },
                "sender": "Raghav Pathak <raghav.candidate.outreach@example.com>",
                "email_subject": final_subject,
                "email_body": final_body + opt_out_footer,
                "custom_variables": {
                    "company_domain": company.domain,
                    "role_title": recipient_role,
                    "candidate_portfolio": "https://raghavpathak.dev",
                    "person_confidence": str(person_conf_float),
                    "email_verification_status": ver_status
                }
            }

            # Create or claim Delivery record in DB
            delivery_rec = existing_delivery or Delivery(
                pipeline_run_id=run.id,
                company_id=company.id,
                contact_id=contact.id if contact else None,
                delivery_mode=env_delivery_mode,
                delivery_status="claimed",
                provider="instantly",
                safety_audit_json=json.dumps(safety_audit),
                delivered_at=utc_now()
            )
            if not existing_delivery:
                db.add(delivery_rec)
            else:
                delivery_rec.delivery_status = "claimed"
                delivery_rec.safety_audit_json = json.dumps(safety_audit)
            db.commit()

            # =================================================================
            # DISPATCH BRANCH A: Non-Live / Dry-Run Staging
            # =================================================================
            if not is_live_authorized:
                unmet_live_reasons = []
                if env_delivery_mode != "live":
                    unmet_live_reasons.append(f"DELIVERY_MODE is '{env_delivery_mode}' (expected 'live')")
                if env_dry_run:
                    unmet_live_reasons.append("DRY_RUN is active (expected false)")
                if not env_confirm_live:
                    unmet_live_reasons.append("CONFIRM_LIVE flag is not set (expected true)")

                unmet_desc = "; ".join(unmet_live_reasons)
                logger.info(f"[DeliveryService] Live send not authorized ({unmet_desc}). Safely staging to disk.")

                staged_dir = Path("staged_deliveries")
                staged_dir.mkdir(parents=True, exist_ok=True)
                domain_slug = company.domain.replace(".", "_")
                timestamp_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
                staged_file = staged_dir / f"staged_{domain_slug}_{timestamp_slug}.json"

                staged_record = {
                    "mode": "staged_dry_run_safe",
                    "dry_run": env_dry_run,
                    "confirm_live": env_confirm_live,
                    "delivery_mode": env_delivery_mode,
                    "unmet_conditions": unmet_live_reasons,
                    "staged_at": utc_now().isoformat(),
                    "payload": payload,
                    "notice": f"Safely staged to disk; zero external network calls ({unmet_desc})."
                }
                staged_file.write_text(json.dumps(staged_record, indent=2), encoding="utf-8")

                # Persist Staged status
                delivery_rec.delivery_status = "staged"
                delivery_rec.staged_file_path = str(staged_file)
                delivery_rec.delivered_at = utc_now()

                run.status = "completed"
                run.last_completed_stage = "delivery_staged"
                run.completed_at = utc_now()
                company.selection_status = "contacted"

                # Record in historical contacted log
                record_contacted(
                    domain=company.domain,
                    contact_email=recipient_email,
                    delivery_status="staged",
                    contact_name=recipient_name
                )

                event = PipelineEvent(
                    pipeline_run_id=run.id,
                    campaign_id=campaign.id,
                    event_type="delivery_staged",
                    message=f"Outreach safely staged to disk at {staged_file}. Zero external provider calls.",
                    data_json=json.dumps({"staged_file": str(staged_file), "notice": unmet_desc}),
                    created_at=utc_now()
                )
                db.add(event)
                db.commit()

                return DeliveryResponse(
                    id=delivery_rec.id,
                    pipeline_run_id=run.id,
                    company_id=company.id,
                    contact_id=contact.id if contact else None,
                    delivery_mode=delivery_rec.delivery_mode,
                    delivery_status="staged",
                    provider=delivery_rec.provider,
                    staged_file_path=str(staged_file),
                    delivered_at=delivery_rec.delivered_at,
                    safety_audit=safety_audit
                )

            # =================================================================
            # DISPATCH BRANCH B: Live External Send (Triple-Key Authoritative)
            # =================================================================
            logger.info(f"[DeliveryService] ALL GATES PASSED. Initiating live provider dispatch for {company.domain} -> {recipient_email}")
            event_attempt = PipelineEvent(
                pipeline_run_id=run.id,
                campaign_id=campaign.id,
                event_type="delivery_attempted",
                message=f"Attempting live external dispatch via Instantly for {recipient_email}.",
                data_json=json.dumps({"domain": company.domain}),
                created_at=utc_now()
            )
            db.add(event_attempt)
            db.commit()

            adapter = AdapterFactory.get_delivery_adapter()
            try:
                result = adapter.deliver(
                    payload,
                    dry_run=False,
                    confirm_live=True,
                    review_status="approved"
                )
            except Exception as exc:
                err_msg = cls.sanitize_error(f"Provider invocation exception: {exc}")
                logger.exception(f"[DeliveryService] Live dispatch exception for {company.domain}: {err_msg}")
                delivery_rec.delivery_status = "failed"
                delivery_rec.webhook_response_json = json.dumps({"error": err_msg})
                run.status = "failed"
                run.error_message = err_msg
                run.completed_at = utc_now()

                event_fail = PipelineEvent(
                    pipeline_run_id=run.id,
                    campaign_id=campaign.id,
                    event_type="delivery_failed",
                    message=f"Live delivery provider dispatch failed: {err_msg}",
                    data_json=json.dumps({"error": err_msg}),
                    created_at=utc_now()
                )
                db.add(event_fail)
                db.commit()

                return DeliveryResponse(
                    id=delivery_rec.id,
                    pipeline_run_id=run.id,
                    company_id=company.id,
                    contact_id=contact.id if contact else None,
                    delivery_mode=delivery_rec.delivery_mode,
                    delivery_status="failed",
                    provider=delivery_rec.provider,
                    delivered_at=delivery_rec.delivered_at,
                    error=err_msg,
                    safety_audit=safety_audit
                )

            # Evaluate Provider Result
            res_status = result.get("status", "failed")
            if res_status == "sent":
                # Success confirmed by external provider
                delivery_rec.delivery_status = "sent"
                delivery_rec.delivered_at = utc_now()
                delivery_rec.webhook_response_json = json.dumps({
                    "http_status": result.get("http_status", 200),
                    "response": cls.sanitize_error(result.get("response", "ok"))
                })
                run.status = "completed"
                run.last_completed_stage = "delivery_sent"
                run.completed_at = utc_now()
                company.selection_status = "contacted"

                record_contacted(
                    domain=company.domain,
                    contact_email=recipient_email,
                    delivery_status="sent",
                    contact_name=recipient_name
                )

                event_sent = PipelineEvent(
                    pipeline_run_id=run.id,
                    campaign_id=campaign.id,
                    event_type="delivery_sent",
                    message=f"Live outreach successfully delivered to {recipient_email} via {delivery_rec.provider}.",
                    data_json=json.dumps({"domain": company.domain, "http_status": result.get("http_status", 200)}),
                    created_at=utc_now()
                )
                db.add(event_sent)
                db.commit()

                logger.info(f"[DeliveryService] Live dispatch SUCCEEDED for {company.domain} ({recipient_email}).")
                return DeliveryResponse(
                    id=delivery_rec.id,
                    pipeline_run_id=run.id,
                    company_id=company.id,
                    contact_id=contact.id if contact else None,
                    delivery_mode=delivery_rec.delivery_mode,
                    delivery_status="sent",
                    provider=delivery_rec.provider,
                    delivered_at=delivery_rec.delivered_at,
                    safety_audit=safety_audit
                )
            else:
                # Provider indicated failure
                prov_err = cls.sanitize_error(result.get("error", "Provider dispatch rejected."))
                logger.error(f"[DeliveryService] Live dispatch REJECTED for {company.domain}: {prov_err}")
                delivery_rec.delivery_status = "failed"
                delivery_rec.webhook_response_json = json.dumps({"error": prov_err})
                run.status = "failed"
                run.error_message = prov_err
                run.completed_at = utc_now()

                event_fail = PipelineEvent(
                    pipeline_run_id=run.id,
                    campaign_id=campaign.id,
                    event_type="delivery_failed",
                    message=f"Live delivery provider reported failure: {prov_err}",
                    data_json=json.dumps({"error": prov_err}),
                    created_at=utc_now()
                )
                db.add(event_fail)
                db.commit()

                return DeliveryResponse(
                    id=delivery_rec.id,
                    pipeline_run_id=run.id,
                    company_id=company.id,
                    contact_id=contact.id if contact else None,
                    delivery_mode=delivery_rec.delivery_mode,
                    delivery_status="failed",
                    provider=delivery_rec.provider,
                    delivered_at=delivery_rec.delivered_at,
                    error=prov_err,
                    safety_audit=safety_audit
                )

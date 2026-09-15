"""
Decoupled Two-Stage Enrichment Adapter.
Coordinates Stage 1 (Person Identification) and Stage 2 (Contact Resolution & Verification).
Enforces credit conservation: Stage 2 is NEVER called if Stage 1 fails to identify a verified leader.
"""
import logging
from typing import Optional, Dict, Any

from pipeline.adapters.base import EnrichmentAdapter, PersonResearchAdapter, EmailResolutionAdapter, AdapterFactory
from pipeline.config import MIN_PERSON_CONFIDENCE

logger = logging.getLogger("pipeline.adapters.two_stage")


class TwoStageEnrichmentAdapter(EnrichmentAdapter):
    """
    Decoupled Enrichment Adapter coordinating:
      1. PersonResearchAdapter: Discovers authentic founder/CTO via search grounding.
      2. EmailResolutionAdapter: Resolves & verifies deliverable business email.
    """

    def __init__(
        self,
        person_adapter: Optional[PersonResearchAdapter] = None,
        email_adapter: Optional[EmailResolutionAdapter] = None
    ):
        self.person_adapter = person_adapter or AdapterFactory.get_person_research_adapter()
        self.email_adapter = email_adapter or AdapterFactory.get_email_resolution_adapter()

    def enrich(
        self,
        domain: str,
        company_name: Optional[str] = None,
        company_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Executes two-stage enrichment for domain.
        Preserves state contract while returning rich confidence and verification metadata.
        """
        clean_d = (domain or "").strip().lower()
        logger.info(f"Starting Two-Stage Enrichment for domain: {clean_d}")

        # STAGE 1: Person Identification
        leader = self.person_adapter.find_leader(
            domain=clean_d,
            company_name=company_name,
            company_context=company_context
        )

        person_conf = float(leader.get("person_confidence") or 0.0) if leader else 0.0

        if not leader or person_conf < MIN_PERSON_CONFIDENCE:
            logger.info(
                f"[STAGE 1 FAILED] No verified technical leader found for {clean_d} (confidence: {person_conf:.2f} < {MIN_PERSON_CONFIDENCE}). "
                f"Credit conservation active: Stage 2 (Email Resolution) bypassed."
            )
            return {
                "contact_name": None,
                "contact_email": None,
                "contact_role": None,
                "company_context": company_context,
                "person_name": leader.get("full_name") if leader else None,
                "person_role": leader.get("role") if leader else None,
                "person_confidence": person_conf,
                "person_linkedin": leader.get("linkedin_url") if leader else None,
                "person_source": leader.get("source_url") if leader else None,
                "email_confidence": 0.0,
                "email_verification_status": "not_evaluated",
                "enrichment_provider": None,
                "enrichment_stage_reached": "person_research_failed",
                "enrichment_metadata": {
                    "stage_reached": "person_research_failed",
                    "reason": "confidence_below_threshold" if leader else "no_verified_technical_leader_found",
                    "person_confidence": person_conf
                }
            }

        first_name = leader.get("first_name", "")
        last_name = leader.get("last_name", "")
        full_name = leader.get("full_name") or f"{first_name} {last_name}".strip()
        role = leader.get("role", "Technical Leader")

        logger.info(
            f"[STAGE 1 SUCCESS] Verified leader for {clean_d}: {full_name} ({role}, confidence: {person_conf:.2f}). "
            f"Proceeding to Stage 2 (Email Resolution)..."
        )

        # STAGE 2: Contact Resolution & Verification
        resolution = self.email_adapter.resolve_email(
            domain=clean_d,
            first_name=first_name,
            last_name=last_name,
            role=role
        )

        if not resolution or not resolution.get("email"):
            res_status = resolution.get("status", "not_found") if resolution else "not_found"
            res_reason = resolution.get("reason", "unresolved") if resolution else "resolver_returned_none"
            res_provider = resolution.get("provider") if resolution else getattr(self.email_adapter, "__class__", type(self.email_adapter)).__name__

            logger.info(
                f"[STAGE 2 FAILED] No deliverable email verified for {full_name} at {clean_d} "
                f"(status: {res_status}, reason: {res_reason})."
            )
            return {
                "contact_name": full_name,
                "contact_email": None,
                "contact_role": role,
                "company_context": company_context,
                "person_name": full_name,
                "person_role": role,
                "person_confidence": person_conf,
                "person_linkedin": leader.get("linkedin_url"),
                "person_source": leader.get("source_url"),
                "email_confidence": 0.0,
                "email_verification_status": res_status,
                "enrichment_provider": res_provider,
                "enrichment_stage_reached": "email_resolution_failed",
                "enrichment_metadata": {
                    "stage_reached": "email_resolution_failed",
                    "reason": res_reason,
                    "status": res_status,
                    "evidence_snippet": leader.get("evidence_snippet"),
                    "linkedin_url": leader.get("linkedin_url"),
                    "source_url": leader.get("source_url"),
                    "grounding_sources": leader.get("grounding_sources", [])
                }
            }

        resolved_email = resolution.get("email")
        email_score = resolution.get("score", 0)
        email_conf = float(email_score) / 100.0
        status = resolution.get("status", "valid")
        provider = resolution.get("provider", "hunter")
        reason = resolution.get("reason", "deliverable_verified")

        logger.info(
            f"[STAGE 2 SUCCESS] Resolved deliverable email for {full_name} at {clean_d}: {resolved_email} "
            f"(score: {email_score}, status: {status}, provider: {provider})."
        )

        return {
            "contact_name": full_name,
            "contact_email": resolved_email,
            "contact_role": role,
            "company_context": company_context,
            "person_name": full_name,
            "person_role": role,
            "person_confidence": person_conf,
            "person_linkedin": leader.get("linkedin_url"),
            "person_source": leader.get("source_url"),
            "email_confidence": email_conf,
            "email_verification_status": status,
            "enrichment_provider": provider,
            "enrichment_stage_reached": "completed",
            "enrichment_metadata": {
                "stage_reached": "completed",
                "reason": reason,
                "status": status,
                "score": email_score,
                "sources_count": resolution.get("sources_count", 0),
                "evidence_snippet": leader.get("evidence_snippet"),
                "linkedin_url": leader.get("linkedin_url"),
                "source_url": leader.get("source_url"),
                "grounding_sources": leader.get("grounding_sources", [])
            }
        }

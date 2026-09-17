"""
Review service, validation schemas, and state-machine transitions for Phase 7 Web Human Review.
Enforces tenant isolation, idempotency, transactional concurrency safety, and audit logging.
Strictly stops at review persistence without triggering delivery or staging.
"""
import json
import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.entities import (
    Review,
    Draft,
    PipelineRun,
    Company,
    Contact,
    Person,
    Campaign,
    PipelineEvent,
    Delivery,
    utc_now,
)

logger = logging.getLogger("server.services.review")

# Mutex protecting review state transitions against concurrent requests/browser tabs
_review_lock = threading.Lock()


# =====================================================================
# Pydantic Schemas
# =====================================================================

class DraftUpdatePayload(BaseModel):
    subject: str = Field(..., min_length=1, max_length=255, description="Updated draft email subject line")
    body: str = Field(..., min_length=1, description="Updated draft email body text")


class ReviewActionPayload(BaseModel):
    notes: Optional[str] = Field(None, max_length=2000, description="Optional reviewer notes or comments")
    reason: Optional[str] = Field(None, max_length=2000, description="Optional rejection reason")
    edited_subject: Optional[str] = Field(None, max_length=255, description="Optional inline edited subject")
    edited_body: Optional[str] = Field(None, description="Optional inline edited email body")


class ReviewListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_run_id: str
    draft_id: str
    campaign_id: str
    campaign_name: str
    company_id: str
    company_name: str
    domain: str
    person_name: Optional[str] = None
    person_role: Optional[str] = None
    contact_email: Optional[str] = None
    match_score: Optional[int] = None
    persona: Optional[str] = None
    status: str
    created_at: datetime
    reviewed_at: Optional[datetime] = None


class ReviewDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    pipeline_run_id: str
    draft_id: str
    campaign: Dict[str, Any]
    company: Dict[str, Any]
    person: Optional[Dict[str, Any]] = None
    contact: Optional[Dict[str, Any]] = None
    draft: Dict[str, Any]
    run: Dict[str, Any]
    delivery: Optional[Dict[str, Any]] = None
    events: List[Dict[str, Any]] = Field(default_factory=list)
    edited_subject: Optional[str] = None
    edited_body: Optional[str] = None
    reviewer_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None


# =====================================================================
# Review Service
# =====================================================================

class ReviewService:
    """
    Manages human review lifecycle for email drafts:
    - Lists and filters review queue with strict tenant isolation.
    - Provides full decision context for specific drafts.
    - Edits draft subject/body prior to approval.
    - Approves or rejects reviews with transactional concurrency protection.
    """

    @staticmethod
    def _parse_json_list(raw_val: Optional[str]) -> List[str]:
        if not raw_val:
            return []
        try:
            parsed = json.loads(raw_val)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            pass
        return [raw_val]

    @classmethod
    def list_reviews(
        cls,
        db: Session,
        user_id: str,
        campaign_id: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[ReviewListItem]:
        """
        Lists reviews accessible to the authenticated user.
        Supports filtering by status ('pending', 'approved', 'rejected') and campaign.
        """
        stmt = (
            select(Review, Draft, PipelineRun, Company, Campaign)
            .join(Draft, Review.draft_id == Draft.id)
            .join(PipelineRun, Review.pipeline_run_id == PipelineRun.id)
            .join(Company, PipelineRun.company_id == Company.id)
            .join(Campaign, PipelineRun.campaign_id == Campaign.id)
            .where(Campaign.user_id == user_id)
        )

        if campaign_id:
            stmt = stmt.where(Campaign.id == campaign_id)

        if status_filter and status_filter.strip().lower() != "all":
            stmt = stmt.where(Review.status == status_filter.strip().lower())

        # Sort pending reviews newest first, then others
        stmt = stmt.order_by(
            (Review.status == "pending").desc(),
            Draft.created_at.desc()
        ).offset(offset).limit(limit)

        results = db.execute(stmt).all()
        items: List[ReviewListItem] = []

        for rev, draft, run, comp, camp in results:
            # Look up verified person and contact if available
            person = db.execute(select(Person).where(Person.company_id == comp.id)).scalars().first()
            contact = db.execute(select(Contact).where(Contact.company_id == comp.id)).scalars().first()

            items.append(
                ReviewListItem(
                    id=rev.id,
                    pipeline_run_id=run.id,
                    draft_id=draft.id,
                    campaign_id=camp.id,
                    campaign_name=camp.name,
                    company_id=comp.id,
                    company_name=comp.company_name,
                    domain=comp.domain,
                    person_name=person.full_name if person else None,
                    person_role=person.role if person else None,
                    contact_email=contact.email if contact else None,
                    match_score=comp.match_score,
                    persona=draft.persona,
                    status=rev.status,
                    created_at=draft.created_at,
                    reviewed_at=rev.reviewed_at
                )
            )

        return items

    @classmethod
    def get_review_detail(
        cls,
        db: Session,
        user_id: str,
        review_id: str
    ) -> ReviewDetailResponse:
        """
        Retrieves complete decision context for an operator inspecting a draft.
        Enforces tenant isolation by verifying the campaign belongs to user_id.
        Suppresses checkpoint_state_json, provider secrets, and raw internal tracebacks.
        """
        stmt = (
            select(Review, Draft, PipelineRun, Company, Campaign)
            .join(Draft, Review.draft_id == Draft.id)
            .join(PipelineRun, Review.pipeline_run_id == PipelineRun.id)
            .join(Company, PipelineRun.company_id == Company.id)
            .join(Campaign, PipelineRun.campaign_id == Campaign.id)
            .where(Review.id == review_id, Campaign.user_id == user_id)
        )
        result = db.execute(stmt).first()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found or unauthorized access."
            )

        rev, draft, run, comp, camp = result

        # Fetch Person, Contact, and Pipeline Events
        person = db.execute(select(Person).where(Person.company_id == comp.id)).scalars().first()
        contact = db.execute(select(Contact).where(Contact.company_id == comp.id)).scalars().first()
        events = list(
            db.execute(
                select(PipelineEvent)
                .where(PipelineEvent.pipeline_run_id == run.id)
                .order_by(PipelineEvent.created_at.asc())
            ).scalars().all()
        )

        company_dict = {
            "id": comp.id,
            "company_name": comp.company_name,
            "domain": comp.domain,
            "industry": comp.industry,
            "location": comp.location,
            "stage": comp.stage,
            "size": comp.size,
            "match_score": comp.match_score,
            "why_match": cls._parse_json_list(comp.why_match_json),
            "technical_signals": cls._parse_json_list(comp.technical_signals_json),
        }

        person_dict = None
        if person:
            person_dict = {
                "full_name": person.full_name,
                "first_name": person.first_name,
                "last_name": person.last_name,
                "role": person.role,
                "linkedin_url": person.linkedin_url,
                "source_url": person.source_url,
                "evidence_snippet": person.evidence_snippet,
                "person_confidence": person.person_confidence,
            }

        contact_dict = None
        if contact:
            contact_dict = {
                "email": contact.email,
                "email_confidence": contact.email_confidence,
                "verification_status": contact.verification_status,
                "provider": contact.provider,
                "sources_count": contact.sources_count,
            }

        draft_dict = {
            "id": draft.id,
            "subject": draft.subject,
            "body": draft.body,
            "persona": draft.persona,
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
        }

        run_dict = {
            "id": run.id,
            "status": run.status,
            "last_completed_stage": run.last_completed_stage,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        }

        event_list = [
            {
                "event_type": e.event_type,
                "message": e.message,
                "created_at": e.created_at,
            }
            for e in events
        ]

        delivery = db.execute(select(Delivery).where(Delivery.pipeline_run_id == run.id)).scalars().first()
        delivery_dict = None
        if delivery:
            delivery_dict = {
                "id": delivery.id,
                "delivery_mode": delivery.delivery_mode,
                "delivery_status": delivery.delivery_status,
                "provider": delivery.provider,
                "staged_file_path": delivery.staged_file_path,
                "delivered_at": delivery.delivered_at,
            }

        return ReviewDetailResponse(
            id=rev.id,
            status=rev.status,
            pipeline_run_id=run.id,
            draft_id=draft.id,
            campaign={"id": camp.id, "name": camp.name},
            company=company_dict,
            person=person_dict,
            contact=contact_dict,
            draft=draft_dict,
            run=run_dict,
            delivery=delivery_dict,
            events=event_list,
            edited_subject=rev.edited_subject,
            edited_body=rev.edited_body,
            reviewer_notes=rev.reviewer_notes,
            reviewed_at=rev.reviewed_at,
        )

    @classmethod
    def edit_draft(
        cls,
        db: Session,
        user_id: str,
        review_id: str,
        payload: DraftUpdatePayload
    ) -> ReviewDetailResponse:
        """
        Updates the generated draft before review decision.
        Updates Draft.subject, Draft.body, updates Draft.updated_at,
        and logs a 'draft_edited' audit PipelineEvent.
        """
        stmt = (
            select(Review, Draft, PipelineRun, Campaign)
            .join(Draft, Review.draft_id == Draft.id)
            .join(PipelineRun, Review.pipeline_run_id == PipelineRun.id)
            .join(Campaign, PipelineRun.campaign_id == Campaign.id)
            .where(Review.id == review_id, Campaign.user_id == user_id)
        )
        result = db.execute(stmt).first()

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found or unauthorized access."
            )

        rev, draft, run, camp = result

        if rev.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit draft for review in '{rev.status}' status. Only 'pending' reviews can be edited."
            )

        new_subject = payload.subject.strip()
        new_body = payload.body.strip()

        if not new_subject or not new_body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Subject and body cannot be blank."
            )

        draft.subject = new_subject
        draft.body = new_body
        draft.updated_at = utc_now()

        rev.edited_subject = new_subject
        rev.edited_body = new_body

        event = PipelineEvent(
            pipeline_run_id=run.id,
            campaign_id=camp.id,
            event_type="draft_edited",
            message="Draft subject/body modified by human operator.",
            data_json=json.dumps({"user_id": user_id}),
            created_at=utc_now()
        )
        db.add(event)
        db.commit()

        logger.info(f"[ReviewService] Draft {draft.id} edited for review {review_id}")
        return cls.get_review_detail(db, user_id, review_id)

    @classmethod
    def approve_review(
        cls,
        db: Session,
        user_id: str,
        review_id: str,
        payload: Optional[ReviewActionPayload] = None
    ) -> ReviewDetailResponse:
        """
        Explicitly approves a pending review.
        - Verifies ownership and 'pending' status.
        - Concurrency-safe & idempotent: repeated calls return current approved review.
        - Disallows approving a rejected review.
        - Updates Review.status='approved' and PipelineRun.status='waiting_for_delivery'.
        - Emits 'review_approved' PipelineEvent with user_id.
        - ZERO delivery or staging triggered.
        """
        with _review_lock:
            stmt = (
                select(Review, Draft, PipelineRun, Campaign)
                .join(Draft, Review.draft_id == Draft.id)
                .join(PipelineRun, Review.pipeline_run_id == PipelineRun.id)
                .join(Campaign, PipelineRun.campaign_id == Campaign.id)
                .where(Review.id == review_id, Campaign.user_id == user_id)
            )
            result = db.execute(stmt).first()

            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Review not found or unauthorized access."
                )

            rev, draft, run, camp = result

            # Idempotency: if already approved, return current detail without re-processing
            if rev.status == "approved":
                logger.info(f"[ReviewService] Review {review_id} already approved (idempotent request).")
                return cls.get_review_detail(db, user_id, review_id)

            # Strict state machine: cannot approve a rejected review
            if rev.status == "rejected":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot approve a review that has already been rejected."
                )

            # Optional inline draft editing during approval
            if payload:
                if payload.edited_subject and payload.edited_subject.strip():
                    draft.subject = payload.edited_subject.strip()
                    rev.edited_subject = draft.subject
                if payload.edited_body and payload.edited_body.strip():
                    draft.body = payload.edited_body.strip()
                    rev.edited_body = draft.body
                if payload.notes:
                    rev.reviewer_notes = payload.notes.strip()

            # State transitions
            rev.status = "approved"
            rev.reviewed_at = utc_now()

            # Transition run to waiting_for_delivery state (unambiguous handoff for Phase 8)
            run.status = "waiting_for_delivery"
            run.last_completed_stage = "review_approved"

            event_data = {"user_id": user_id, "decision": "approved"}
            if rev.reviewer_notes:
                event_data["notes"] = rev.reviewer_notes

            event = PipelineEvent(
                pipeline_run_id=run.id,
                campaign_id=camp.id,
                event_type="review_approved",
                message="Draft approved by human reviewer. Transitioned to waiting for delivery.",
                data_json=json.dumps(event_data),
                created_at=utc_now()
            )
            db.add(event)
            db.commit()

            logger.info(f"[ReviewService] Review {review_id} successfully approved. Run set to waiting_for_delivery. Zero delivery triggered.")
            return cls.get_review_detail(db, user_id, review_id)

    @classmethod
    def reject_review(
        cls,
        db: Session,
        user_id: str,
        review_id: str,
        payload: Optional[ReviewActionPayload] = None
    ) -> ReviewDetailResponse:
        """
        Explicitly rejects a pending review.
        - Verifies ownership and 'pending' status.
        - Concurrency-safe & idempotent: repeated calls return current rejected review.
        - Disallows rejecting an already approved review.
        - Updates Review.status='rejected' and PipelineRun.status='skipped'.
        - Emits 'review_rejected' PipelineEvent with user_id.
        - ZERO delivery or staging triggered.
        """
        with _review_lock:
            stmt = (
                select(Review, Draft, PipelineRun, Campaign)
                .join(Draft, Review.draft_id == Draft.id)
                .join(PipelineRun, Review.pipeline_run_id == PipelineRun.id)
                .join(Campaign, PipelineRun.campaign_id == Campaign.id)
                .where(Review.id == review_id, Campaign.user_id == user_id)
            )
            result = db.execute(stmt).first()

            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Review not found or unauthorized access."
                )

            rev, draft, run, camp = result

            # Idempotency: if already rejected, return current detail without re-processing
            if rev.status == "rejected":
                logger.info(f"[ReviewService] Review {review_id} already rejected (idempotent request).")
                return cls.get_review_detail(db, user_id, review_id)

            # Strict state machine: cannot reject an approved review
            if rev.status == "approved":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot reject a review that has already been approved."
                )

            reason = None
            if payload:
                reason = payload.reason or payload.notes
                if reason:
                    reason = reason.strip()
                    rev.reviewer_notes = reason

            # State transitions
            rev.status = "rejected"
            rev.reviewed_at = utc_now()

            # Transition run to terminal skipped state
            run.status = "skipped"
            run.last_completed_stage = "review_rejected"
            run.completed_at = utc_now()

            event_data = {"user_id": user_id, "decision": "rejected"}
            if reason:
                event_data["reason"] = reason

            event = PipelineEvent(
                pipeline_run_id=run.id,
                campaign_id=camp.id,
                event_type="review_rejected",
                message=f"Draft rejected by human reviewer. Reason: {reason or 'No reason provided'}.",
                data_json=json.dumps(event_data),
                created_at=utc_now()
            )
            db.add(event)
            db.commit()

            logger.info(f"[ReviewService] Review {review_id} rejected. Run marked skipped.")
            return cls.get_review_detail(db, user_id, review_id)

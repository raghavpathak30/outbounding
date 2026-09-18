"""
Background Job Manager for Phase 6 Pipeline Execution.
Executes enrichment, person research, email resolution, and drafting asynchronously
using a bounded ThreadPoolExecutor(max_workers=2).
Stops strictly at 'waiting_for_review' without invoking review or delivery.
Maintains persistent stage checkpoints in SQLite and supports crash recovery.
"""
import os
import re
import json
import logging
import threading
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, Future

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker, Session

from server.models.entities import (
    PipelineRun,
    Company,
    Campaign,
    Person,
    Contact,
    Draft,
    Review,
    PipelineEvent,
    Resume,
    utc_now,
)
from server.database import SessionLocal
from pipeline.adapters.base import AdapterFactory
from pipeline.config import MIN_PERSON_CONFIDENCE
from pipeline.drafting import detect_persona, load_resume_context

logger = logging.getLogger("server.job_manager")


class JobManager:
    """
    Singleton background pipeline runner.
    Bridges web application selections to the core pipeline stages with stage-level checkpointing.
    """
    _instance: Optional["JobManager"] = None
    _lock = threading.RLock()

    @staticmethod
    def _sanitize_error_message(exc: Exception) -> str:
        """
        Sanitizes exception messages to ensure user-facing error_message contains
        only a safe, informative description without Python tracebacks, filesystem paths,
        API keys, tokens, or sensitive provider payload dumps.
        """
        raw_msg = str(exc).strip()
        exc_type = type(exc).__name__

        # Handle quota exhaustion specifically
        if "DailyQuotaExhaustedError" in exc_type or "RESOURCE_EXHAUSTED" in raw_msg or "429" in raw_msg:
            return "Daily API quota exhausted for external provider (resets midnight PT)."

        # Strip multi-line traceback if present in message
        lines = [line.strip() for line in raw_msg.splitlines() if line.strip()]
        clean_lines = []
        for line in lines:
            if line.startswith("Traceback (") or line.startswith("File \"") or line.startswith("During handling of"):
                continue
            clean_lines.append(line)

        sanitized = " ".join(clean_lines) if clean_lines else f"{exc_type} occurred during pipeline execution."

        # Redact common secret patterns (API keys, tokens, auth headers)
        sanitized = re.sub(r"(?i)(api[_-]?key|token|secret|password|bearer)[=:\s]+['\"]?[a-zA-Z0-9_\-\.]{8,}['\"]?", r"\1=[REDACTED]", sanitized)
        sanitized = re.sub(r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_API_KEY]", sanitized)

        # Redact absolute filesystem paths
        sanitized = re.sub(r"/(?:[a-zA-Z0-9_\.\-]+/)+[a-zA-Z0-9_\.\-]+", "[internal_path]", sanitized)

        # Truncate to reasonable length (255 characters)
        if len(sanitized) > 255:
            sanitized = sanitized[:252] + "..."

        return sanitized

    def __init__(
        self,
        max_workers: int = 2,
        session_factory: Optional[sessionmaker] = None
    ):
        self.max_workers = max_workers
        self.session_factory = session_factory or SessionLocal
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="pipeline_worker"
        )
        self._futures: Dict[str, Future] = {}
        self._futures_lock = threading.Lock()
        logger.info(f"Initialized JobManager with max_workers={self.max_workers}")

    @classmethod
    def get_instance(
        cls,
        max_workers: int = 2,
        session_factory: Optional[sessionmaker] = None,
        reset: bool = False
    ) -> "JobManager":
        """Thread-safe singleton accessor."""
        with cls._lock:
            if reset and cls._instance:
                cls._instance.shutdown(wait=False)
                cls._instance = None
            if cls._instance is not None and getattr(cls._instance.executor, "_shutdown", False):
                cls._instance = None
            if cls._instance is None:
                cls._instance = cls(max_workers=max_workers, session_factory=session_factory)
            elif session_factory is not None:
                cls._instance.session_factory = session_factory
            return cls._instance

    def submit_run(self, run_id: str) -> Future:
        """Submits a queued or recovered PipelineRun for execution."""
        with self._futures_lock:
            future = self.executor.submit(self._execute_run, run_id)
            self._futures[run_id] = future
            return future

    def submit_delivery(self, run_id: str, user_id: Optional[str] = None) -> Future:
        """Submits an approved PipelineRun in 'waiting_for_delivery' for background delivery execution."""
        with self._futures_lock:
            future = self.executor.submit(self._execute_delivery, run_id, user_id)
            self._futures[f"delivery_{run_id}"] = future
            return future

    def get_future(self, run_id: str) -> Optional[Future]:
        """Returns future for active/completed run if tracked in memory."""
        with self._futures_lock:
            return self._futures.get(run_id) or self._futures.get(f"delivery_{run_id}")

    def _execute_delivery(self, run_id: str, user_id: Optional[str] = None) -> None:
        """Executes explicit delivery through the authoritative DeliveryService."""
        from server.services.delivery import DeliveryService
        session: Session = self.session_factory()
        try:
            logger.info(f"[JobManager] Executing explicit delivery for run {run_id}")
            DeliveryService.deliver_pipeline_run(session, run_id=run_id, user_id=user_id)
        except Exception as e:
            logger.exception(f"[JobManager] Delivery failed for run {run_id}: {e}")
        finally:
            session.close()

    def _execute_run(self, run_id: str) -> None:
        """
        Executes a PipelineRun through the decoupled pipeline stages:
          1. Stage 1: Person Research
          2. Stage 2: Email Resolution & Verification
          3. Stage 3: Drafting
          4. Boundary: Sets status to 'waiting_for_review'
        Persists stage checkpoints in DB to ensure safe crash recovery.
        """
        session: Session = self.session_factory()
        try:
            run = session.execute(
                select(PipelineRun).where(PipelineRun.id == run_id)
            ).scalar_one_or_none()

            if not run:
                logger.error(f"[JobManager] PipelineRun {run_id} not found.")
                return

            if run.status in ["waiting_for_review", "waiting_for_delivery", "completed", "failed", "cancelled", "skipped"]:
                logger.info(f"[JobManager] PipelineRun {run_id} already in terminal/review/delivery state ({run.status}).")
                return

            company = session.execute(
                select(Company).where(Company.id == run.company_id)
            ).scalar_one_or_none()

            campaign = session.execute(
                select(Campaign).where(Campaign.id == run.campaign_id)
            ).scalar_one_or_none()

            if not company or not campaign:
                run.status = "failed"
                run.error_message = "Associated Company or Campaign not found."
                session.commit()
                return

            # Concurrency guard: check if another run for (campaign_id, company_id) is currently running
            active_other_run = session.execute(
                select(PipelineRun).where(
                    PipelineRun.campaign_id == run.campaign_id,
                    PipelineRun.company_id == run.company_id,
                    PipelineRun.id != run.id,
                    PipelineRun.status == "running"
                )
            ).scalars().first()
            if active_other_run:
                logger.warning(
                    f"[JobManager] Run {run_id} cancelled: another active run {active_other_run.id} is currently running."
                )
                run.status = "cancelled"
                run.error_message = "Duplicate active run prevented: company is currently being processed."
                run.completed_at = utc_now()
                session.commit()
                return

            # Mark run as running
            run.status = "running"
            if not run.started_at:
                run.started_at = utc_now()
            self._record_event(
                session, run, campaign, "run_started",
                f"Starting pipeline execution for {company.company_name} ({company.domain})."
            )
            session.commit()

            # Prepare company context dictionary
            signals = []
            if company.technical_signals_json:
                try:
                    signals = json.loads(company.technical_signals_json)
                except Exception:
                    signals = []
            why_match = []
            if company.why_match_json:
                try:
                    why_match = json.loads(company.why_match_json)
                except Exception:
                    why_match = []

            company_context = {
                "headline": company.company_name,
                "industry": company.industry,
                "stage": company.stage,
                "size": company.size,
                "location": company.location,
                "technical_signals": signals,
                "signal": " ".join(why_match) if isinstance(why_match, list) else str(why_match),
            }

            # Prepare resume context
            resume_context = self._resolve_resume_context(session, campaign)

            # Checkpoint recovery: check existing progress
            checkpoint_state = {}
            if run.checkpoint_state_json:
                try:
                    checkpoint_state = json.loads(run.checkpoint_state_json)
                except Exception:
                    checkpoint_state = {}

            # =================================================================
            # STAGE 1: Person Research
            # =================================================================
            leader_data = None
            existing_person = session.execute(
                select(Person).where(Person.company_id == company.id)
            ).scalars().first()

            if (run.last_completed_stage in ["person_verified", "email_resolved", "draft_generated"] or
                (existing_person and (existing_person.person_confidence or 0.0) >= MIN_PERSON_CONFIDENCE)):
                if existing_person:
                    leader_data = {
                        "first_name": existing_person.first_name,
                        "last_name": existing_person.last_name,
                        "full_name": existing_person.full_name,
                        "role": existing_person.role,
                        "linkedin_url": existing_person.linkedin_url,
                        "source_url": existing_person.source_url,
                        "evidence_snippet": existing_person.evidence_snippet,
                        "person_confidence": existing_person.person_confidence,
                    }
                    logger.info(f"[JobManager] Recovered/Reused verified leader for {company.domain}: {existing_person.full_name}")

            if not leader_data:
                logger.info(f"[JobManager] Invoking Person Research for {company.domain}")
                target_roles = []
                if campaign.target_roles_json:
                    try:
                        target_roles = json.loads(campaign.target_roles_json)
                    except Exception:
                        target_roles = []

                person_adapter = AdapterFactory.get_person_research_adapter()
                leader_data = person_adapter.find_leader(
                    domain=company.domain,
                    company_name=company.company_name,
                    company_context=company_context,
                    target_roles=target_roles
                )

                person_conf = float(leader_data.get("person_confidence") or 0.0) if leader_data else 0.0
                if not leader_data or person_conf < MIN_PERSON_CONFIDENCE:
                    reason = f"No verified leader found (confidence {person_conf:.2f} < {MIN_PERSON_CONFIDENCE})"
                    logger.warning(f"[JobManager] {company.domain}: {reason}")
                    run.status = "skipped"
                    run.error_message = reason
                    run.last_completed_stage = "person_unverified"
                    run.completed_at = utc_now()
                    self._record_event(session, run, campaign, "stage1_leader_skipped", reason)
                    session.commit()
                    return

                # Persist Person entity
                person = session.execute(
                    select(Person).where(Person.company_id == company.id)
                ).scalar_one_or_none()
                if not person:
                    person = Person(
                        company_id=company.id,
                        first_name=leader_data.get("first_name", ""),
                        last_name=leader_data.get("last_name", ""),
                        full_name=leader_data.get("full_name") or f"{leader_data.get('first_name', '')} {leader_data.get('last_name', '')}".strip(),
                        role=leader_data.get("role", "Technical Leader"),
                        linkedin_url=leader_data.get("linkedin_url"),
                        source_url=leader_data.get("source_url"),
                        evidence_snippet=leader_data.get("evidence_snippet"),
                        person_confidence=person_conf,
                        grounding_sources_json=json.dumps(leader_data.get("grounding_sources") or []),
                    )
                    session.add(person)
                else:
                    person.first_name = leader_data.get("first_name", person.first_name)
                    person.last_name = leader_data.get("last_name", person.last_name)
                    person.full_name = leader_data.get("full_name", person.full_name)
                    person.role = leader_data.get("role", person.role)
                    person.person_confidence = person_conf

                checkpoint_state["leader"] = leader_data
                run.last_completed_stage = "person_verified"
                run.checkpoint_state_json = json.dumps(checkpoint_state)
                self._record_event(
                    session, run, campaign, "stage1_leader_found",
                    f"Identified verified leader: {leader_data.get('full_name')} ({leader_data.get('role')})"
                )
                session.commit()

            # =================================================================
            # STAGE 2: Email Resolution & Verification
            # =================================================================
            contact_data = None
            existing_contact = session.execute(
                select(Contact).where(Contact.company_id == company.id)
            ).scalars().first()

            if (run.last_completed_stage in ["email_resolved", "draft_generated"] or
                (existing_contact and existing_contact.email)):
                if existing_contact and existing_contact.email:
                    contact_data = {
                        "email": existing_contact.email,
                        "score": existing_contact.email_confidence,
                        "status": existing_contact.verification_status,
                        "provider": existing_contact.provider,
                        "sources_count": existing_contact.sources_count,
                    }
                    logger.info(f"[JobManager] Recovered/Reused resolved email for {company.domain}: {existing_contact.email}")

            if not contact_data:
                logger.info(f"[JobManager] Invoking Email Resolution for {company.domain}")
                email_adapter = AdapterFactory.get_email_resolution_adapter()
                contact_data = email_adapter.resolve_email(
                    domain=company.domain,
                    first_name=leader_data.get("first_name", ""),
                    last_name=leader_data.get("last_name", ""),
                    role=leader_data.get("role")
                )

                if not contact_data or not contact_data.get("email"):
                    reason = f"No deliverable email verified for {leader_data.get('full_name')} at {company.domain}"
                    logger.warning(f"[JobManager] {company.domain}: {reason}")
                    run.status = "skipped"
                    run.error_message = reason
                    run.last_completed_stage = "email_unresolved"
                    run.completed_at = utc_now()
                    self._record_event(session, run, campaign, "stage2_email_skipped", reason)
                    session.commit()
                    return

                person_obj = session.execute(
                    select(Person).where(Person.company_id == company.id)
                ).scalar_one_or_none()

                contact = Contact(
                    company_id=company.id,
                    person_id=person_obj.id if person_obj else None,
                    email=contact_data.get("email"),
                    email_confidence=float(contact_data.get("score") or 0.0),
                    verification_status=contact_data.get("status", "valid"),
                    provider=contact_data.get("provider", "hunter"),
                    sources_count=int(contact_data.get("sources_count") or 0),
                    raw_verification_json=json.dumps(contact_data),
                )
                session.add(contact)

                checkpoint_state["contact"] = contact_data
                run.last_completed_stage = "email_resolved"
                run.checkpoint_state_json = json.dumps(checkpoint_state)
                self._record_event(
                    session, run, campaign, "stage2_email_resolved",
                    f"Resolved business email: {contact_data.get('email')} (Confidence: {contact_data.get('score')}%)"
                )
                session.commit()

            # =================================================================
            # STAGE 3: Drafting
            # =================================================================
            draft_obj = None
            if run.last_completed_stage == "draft_generated":
                draft_obj = session.execute(
                    select(Draft).where(Draft.pipeline_run_id == run.id)
                ).scalars().first()
                if draft_obj:
                    logger.info(f"[JobManager] Recovered existing draft for run {run.id}")

            if not draft_obj:
                logger.info(f"[JobManager] Invoking Drafting for {company.domain}")
                drafting_adapter = AdapterFactory.get_drafting_adapter()
                contact_obj = session.execute(
                    select(Contact).where(Contact.company_id == company.id)
                ).scalars().first()

                raw_draft = drafting_adapter.draft(
                    role=leader_data.get("role"),
                    domain=company.domain,
                    resume_context=resume_context,
                    contact_name=leader_data.get("full_name") or leader_data.get("first_name"),
                    company_context=company_context
                )

                # Split Subject if present
                subject = f"Technical Collaboration & Opportunities at {company.domain}"
                body = raw_draft
                if raw_draft.startswith("Subject:"):
                    parts = raw_draft.split("\n\n", 1)
                    subject = parts[0].replace("Subject:", "").strip()
                    body = parts[1] if len(parts) > 1 else raw_draft

                persona = detect_persona(leader_data.get("role", ""))

                draft_obj = Draft(
                    pipeline_run_id=run.id,
                    company_id=company.id,
                    contact_id=contact_obj.id if contact_obj else None,
                    subject=subject,
                    body=body,
                    persona=persona,
                    raw_prompt_context_json=json.dumps({
                        "role": leader_data.get("role"),
                        "domain": company.domain,
                        "contact_name": leader_data.get("full_name"),
                    })
                )
                session.add(draft_obj)
                session.flush()

                # Create initial Review record in 'pending' status
                review = Review(
                    pipeline_run_id=run.id,
                    draft_id=draft_obj.id,
                    status="pending"
                )
                session.add(review)

                checkpoint_state["draft"] = {
                    "subject": subject,
                    "persona": persona
                }
                run.last_completed_stage = "draft_generated"
                run.checkpoint_state_json = json.dumps(checkpoint_state)
                self._record_event(
                    session, run, campaign, "stage3_draft_generated",
                    f"Generated personalized draft for {leader_data.get('full_name')} ({persona} persona)."
                )
                session.commit()

            # =================================================================
            # STAGE 4: Boundary Termination - Stop at waiting_for_review
            # =================================================================
            run.status = "waiting_for_review"
            run.completed_at = utc_now()
            self._record_event(
                session, run, campaign, "waiting_for_review",
                "Pipeline execution paused at Human-in-the-Loop review gate."
            )
            session.commit()
            logger.info(f"[JobManager] Run {run_id} successfully reached 'waiting_for_review'.")

        except Exception as e:
            logger.exception(f"[JobManager] Execution failed for run {run_id}: {e}")
            session.rollback()
            try:
                fail_session: Session = self.session_factory()
                run_to_fail = fail_session.execute(
                    select(PipelineRun).where(PipelineRun.id == run_id)
                ).scalar_one_or_none()
                if run_to_fail:
                    sanitized_msg = self._sanitize_error_message(e)
                    run_to_fail.status = "failed"
                    run_to_fail.error_message = sanitized_msg
                    run_to_fail.completed_at = utc_now()
                    fail_session.add(
                        PipelineEvent(
                            pipeline_run_id=run_id,
                            campaign_id=run_to_fail.campaign_id,
                            event_type="run_failed",
                            message=f"Pipeline run encountered fatal error: {sanitized_msg}",
                            data_json=json.dumps({"error_type": type(e).__name__, "error": sanitized_msg})
                        )
                    )
                    fail_session.commit()
                fail_session.close()
            except Exception as inner_e:
                logger.error(f"[JobManager] Failed to persist failure status for run {run_id}: {inner_e}")
        finally:
            session.close()

    def _resolve_resume_context(self, session: Session, campaign: Campaign) -> Dict[str, Any]:
        """Resolves resume data from campaign.resume_id or fallback."""
        if campaign.resume_id:
            resume = session.execute(
                select(Resume).where(Resume.id == campaign.resume_id)
            ).scalar_one_or_none()
            if resume and resume.parsed_data_json:
                try:
                    return json.loads(resume.parsed_data_json)
                except Exception:
                    pass

        # Fallback to active resume
        active_resume = session.execute(
            select(Resume).where(Resume.user_id == campaign.user_id, Resume.is_active.is_(True))
        ).scalars().first()
        if active_resume and active_resume.parsed_data_json:
            try:
                return json.loads(active_resume.parsed_data_json)
            except Exception:
                pass

        # Fallback to offline resume.json
        return load_resume_context()

    def _record_event(
        self,
        session: Session,
        run: PipelineRun,
        campaign: Campaign,
        event_type: str,
        message: str,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        event = PipelineEvent(
            pipeline_run_id=run.id,
            campaign_id=campaign.id,
            event_type=event_type,
            message=message,
            data_json=json.dumps(data) if data else None,
            created_at=utc_now()
        )
        session.add(event)

    def recover_stale_runs(self) -> List[str]:
        """
        Scans for interrupted runs in 'running' state on server startup and recovers them
        by resuming from their latest checkpointed stage.
        """
        session: Session = self.session_factory()
        recovered_ids: List[str] = []
        try:
            stale_runs = list(
                session.execute(
                    select(PipelineRun).where(PipelineRun.status == "running")
                ).scalars().all()
            )
            for r in stale_runs:
                logger.warning(
                    f"[JobManager] Found interrupted run {r.id} at stage '{r.last_completed_stage}'. "
                    "Re-submitting for recovery execution."
                )
                self.submit_run(r.id)
                recovered_ids.append(r.id)
            return recovered_ids
        finally:
            session.close()

    def shutdown(self, wait: bool = True) -> None:
        """Gracefully shuts down thread pool executor."""
        logger.info("[JobManager] Shutting down executor...")
        self.executor.shutdown(wait=wait)
        with JobManager._lock:
            if JobManager._instance is self:
                JobManager._instance = None

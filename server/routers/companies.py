"""
Company API routes.
Implements:
- GET /api/v1/campaigns/{campaign_id}/companies (list & filter candidates for Discovery Grid)
- POST /api/v1/campaigns/{campaign_id}/companies/select (operator selects companies)
- POST /api/v1/campaigns/{campaign_id}/enqueue-selected (prepares selected companies for Phase 6)
"""
import json
import threading
from datetime import datetime
from typing import List, Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from server.models.entities import (
    User,
    Campaign,
    Company,
    PipelineRun,
    PipelineEvent,
    Person,
    Contact,
    Review,
    Delivery,
    utc_now,
)
from server.database import get_db
from server.services.auth import get_current_user_and_refresh
from server.services.campaign import CampaignService
from server.services.job_manager import JobManager

router = APIRouter(prefix="/api/v1/campaigns/{campaign_id}", tags=["Companies"])
_enqueue_lock = threading.Lock()


# =====================================================================
# Request / Response Models
# =====================================================================

class CompanyGridItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campaign_id: str
    domain: str
    company_name: str
    location: Optional[str] = None
    industry: Optional[str] = None
    stage: Optional[str] = None
    size: Optional[int] = None
    match_score: Optional[int] = None
    why_match: List[str] = Field(default_factory=list)
    technical_signals: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    selection_status: str
    created_at: datetime
    updated_at: datetime


class SelectCompaniesRequest(BaseModel):
    company_ids: Optional[List[str]] = Field(default_factory=list)
    domains: Optional[List[str]] = Field(default_factory=list)


class PipelineRunItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campaign_id: str
    company_id: str
    company_name: Optional[str] = None
    domain: Optional[str] = None
    status: str
    last_completed_stage: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


def _format_company_grid_item(company: Company) -> CompanyGridItem:
    why_match = []
    if company.why_match_json:
        try:
            why_match = json.loads(company.why_match_json)
        except Exception:
            why_match = []

    tech_signals = []
    if company.technical_signals_json:
        try:
            tech_signals = json.loads(company.technical_signals_json)
        except Exception:
            tech_signals = []

    sources = []
    if company.sources_json:
        try:
            sources = json.loads(company.sources_json)
        except Exception:
            sources = []

    return CompanyGridItem(
        id=company.id,
        campaign_id=company.campaign_id,
        domain=company.domain,
        company_name=company.company_name,
        location=company.location,
        industry=company.industry,
        stage=company.stage,
        size=company.size,
        match_score=company.match_score,
        why_match=why_match,
        technical_signals=tech_signals,
        sources=sources,
        selection_status=company.selection_status,
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


# =====================================================================
# Route Handlers
# =====================================================================

@router.get("/companies", response_model=List[CompanyGridItem])
async def list_campaign_companies(
    campaign_id: str,
    selection_status: Optional[str] = Query(default=None, description="Filter: 'discovered', 'selected', 'rejected', 'contacted'"),
    min_score: Optional[int] = Query(default=None, ge=0, le=100),
    industry: Optional[str] = Query(default=None, description="Filter by industry"),
    stage: Optional[str] = Query(default=None, description="Filter by stage"),
    search: Optional[str] = Query(default=None, description="Search company name or domain"),
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Retrieves discovered Company records for the Discovery Grid.
    Supports filtering by selection status, minimum match score, industry, stage, and text search.
    """
    campaign = CampaignService.get_campaign(db, current_user.id, campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found."
        )

    stmt = select(Company).where(Company.campaign_id == campaign_id)
    if selection_status:
        stmt = stmt.where(Company.selection_status == selection_status.strip().lower())
    if min_score is not None:
        stmt = stmt.where(Company.match_score >= min_score)
    if industry:
        stmt = stmt.where(Company.industry.ilike(f"%{industry.strip()}%"))
    if stage:
        stmt = stmt.where(Company.stage.ilike(f"%{stage.strip()}%"))
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(Company.company_name.ilike(term) | Company.domain.ilike(term))

    stmt = stmt.order_by(Company.match_score.desc().nullslast(), Company.created_at.desc())
    companies = list(db.execute(stmt).scalars().all())

    return [_format_company_grid_item(c) for c in companies]


@router.post("/companies/select", status_code=status.HTTP_200_OK)
@router.post("/select", status_code=status.HTTP_200_OK)
async def select_companies(
    campaign_id: str,
    payload: SelectCompaniesRequest,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Marks target companies as 'selected' for future enrichment.
    Refuses to re-select already-contacted companies (authoritative safety).
    Does NOT trigger enrichment or outreach.
    """
    campaign = CampaignService.get_campaign(db, current_user.id, campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found."
        )

    requested_ids = set(payload.company_ids or [])
    requested_domains = {d.strip().lower() for d in (payload.domains or []) if d.strip()}

    if not requested_ids and not requested_domains:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No company IDs or domains provided for selection."
        )

    # Fetch matching companies strictly within this campaign
    stmt = select(Company).where(Company.campaign_id == campaign_id)
    all_campaign_comps = list(db.execute(stmt).scalars().all())

    selected_count = 0
    updated_comps = []

    for comp in all_campaign_comps:
        if comp.id in requested_ids or comp.domain.lower() in requested_domains:
            # Backend validation authoritative: already-contacted cannot be reselected
            if comp.selection_status == "contacted":
                continue
            comp.selection_status = "selected"
            selected_count += 1
            updated_comps.append(comp)

    if selected_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="None of the specified companies were found in this campaign or eligible for selection."
        )

    db.commit()
    return {
        "status": "success",
        "campaign_id": campaign_id,
        "selected_count": selected_count,
        "selected_company_ids": [c.id for c in updated_comps],
    }


@router.post("/companies/deselect", status_code=status.HTTP_200_OK)
@router.post("/deselect", status_code=status.HTTP_200_OK)
async def deselect_companies(
    campaign_id: str,
    payload: SelectCompaniesRequest,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Reverts selected companies back to 'discovered' status.
    """
    campaign = CampaignService.get_campaign(db, current_user.id, campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found."
        )

    requested_ids = set(payload.company_ids or [])
    requested_domains = {d.strip().lower() for d in (payload.domains or []) if d.strip()}

    if not requested_ids and not requested_domains:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No company IDs or domains provided for deselection."
        )

    stmt = select(Company).where(Company.campaign_id == campaign_id)
    all_campaign_comps = list(db.execute(stmt).scalars().all())

    deselected_count = 0
    updated_comps = []

    for comp in all_campaign_comps:
        if comp.id in requested_ids or comp.domain.lower() in requested_domains:
            if comp.selection_status == "selected":
                comp.selection_status = "discovered"
                deselected_count += 1
                updated_comps.append(comp)

    db.commit()
    return {
        "status": "success",
        "campaign_id": campaign_id,
        "deselected_count": deselected_count,
        "deselected_company_ids": [c.id for c in updated_comps],
    }


@router.post("/enqueue-selected", status_code=status.HTTP_200_OK)
@router.post("/companies/enqueue-selected", status_code=status.HTTP_200_OK)
async def enqueue_selected_companies(
    campaign_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Phase 6 Enqueue Selected:
    Validates selected companies, creates queued PipelineRun records, and submits
    them to the background JobManager for asynchronous pipeline execution.
    """
    campaign = CampaignService.get_campaign(db, current_user.id, campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found."
        )

    stmt = select(Company).where(
        Company.campaign_id == campaign_id,
        Company.selection_status == "selected"
    )
    selected_companies = list(db.execute(stmt).scalars().all())

    if not selected_companies:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No companies are currently marked as 'selected' in this campaign."
        )

    job_manager = JobManager.get_instance()
    runs_to_submit = []

    with _enqueue_lock:
        for comp in selected_companies:
            # Check if an existing run is already queued or running
            existing_run = db.execute(
                select(PipelineRun).where(
                    PipelineRun.campaign_id == campaign_id,
                    PipelineRun.company_id == comp.id,
                    PipelineRun.status.in_(["queued", "running"])
                )
            ).scalar_one_or_none()

            if existing_run:
                runs_to_submit.append(existing_run)
                continue

            run = PipelineRun(
                campaign_id=campaign_id,
                company_id=comp.id,
                status="queued",
                last_completed_stage="discovery_completed",
                started_at=None,
                completed_at=None
            )
            db.add(run)
            db.flush()

            event = PipelineEvent(
                pipeline_run_id=run.id,
                campaign_id=campaign_id,
                event_type="run_queued",
                message=f"Pipeline run queued for {comp.company_name} ({comp.domain}).",
                created_at=utc_now()
            )
            db.add(event)
            runs_to_submit.append(run)

        db.commit()

    # Submit newly queued runs to JobManager executor
    for r in runs_to_submit:
        if r.status == "queued":
            job_manager.submit_run(r.id)

    return {
        "status": "queued",
        "campaign_id": campaign_id,
        "enqueued_count": len(runs_to_submit),
        "enqueued_company_ids": [c.id for c in selected_companies],
        "runs": [
            {
                "id": r.id,
                "company_id": r.company_id,
                "status": r.status,
                "last_completed_stage": r.last_completed_stage
            }
            for r in runs_to_submit
        ],
        "message": "Companies verified and queued for Phase 6 background pipeline execution."
    }


@router.get("/runs", response_model=List[PipelineRunItem])
async def list_pipeline_runs(
    campaign_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Lists all pipeline execution runs for a given campaign."""
    campaign = CampaignService.get_campaign(db, current_user.id, campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found."
        )

    stmt = select(PipelineRun, Company).join(Company, PipelineRun.company_id == Company.id).where(
        PipelineRun.campaign_id == campaign_id
    )
    if status_filter:
        stmt = stmt.where(PipelineRun.status == status_filter.strip().lower())
    stmt = stmt.order_by(PipelineRun.started_at.desc().nulls_last())

    results = db.execute(stmt).all()
    items = []
    for run, comp in results:
        items.append(
            PipelineRunItem(
                id=run.id,
                campaign_id=run.campaign_id,
                company_id=run.company_id,
                company_name=comp.company_name,
                domain=comp.domain,
                status=run.status,
                last_completed_stage=run.last_completed_stage,
                error_message=run.error_message,
                started_at=run.started_at,
                completed_at=run.completed_at,
            )
        )
    return items


@router.get("/runs/{run_id}")
async def get_pipeline_run(
    campaign_id: str,
    run_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Retrieves full details of a specific pipeline execution run."""
    campaign = CampaignService.get_campaign(db, current_user.id, campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found."
        )

    run = db.execute(
        select(PipelineRun).where(
            PipelineRun.id == run_id,
            PipelineRun.campaign_id == campaign_id
        )
    ).scalar_one_or_none()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pipeline run not found."
        )

    company = db.execute(select(Company).where(Company.id == run.company_id)).scalar_one_or_none()
    events = list(
        db.execute(
            select(PipelineEvent)
            .where(PipelineEvent.pipeline_run_id == run.id)
            .order_by(PipelineEvent.created_at.asc())
        ).scalars().all()
    )

    draft_info = None
    if run.draft:
        draft_info = {
            "id": run.draft.id,
            "subject": run.draft.subject,
            "body": run.draft.body,
            "persona": run.draft.persona,
        }

    person_obj = db.execute(select(Person).where(Person.company_id == run.company_id)).scalars().first()
    contact_obj = db.execute(select(Contact).where(Contact.company_id == run.company_id)).scalars().first()
    review_obj = db.execute(select(Review).where(Review.pipeline_run_id == run.id)).scalars().first()
    delivery_obj = db.execute(select(Delivery).where(Delivery.pipeline_run_id == run.id)).scalars().first()

    person_info = None
    if person_obj:
        person_info = {
            "id": person_obj.id,
            "full_name": person_obj.full_name,
            "role": person_obj.role,
            "person_confidence": person_obj.person_confidence,
            "linkedin_url": person_obj.linkedin_url,
        }

    contact_info = None
    if contact_obj:
        contact_info = {
            "id": contact_obj.id,
            "email": contact_obj.email,
            "verification_status": contact_obj.verification_status,
            "email_confidence": contact_obj.email_confidence,
        }

    review_info = None
    if review_obj:
        review_info = {
            "id": review_obj.id,
            "status": review_obj.status,
            "reviewer_notes": review_obj.reviewer_notes,
            "reviewed_at": review_obj.reviewed_at,
            "edited_subject": review_obj.edited_subject,
            "edited_body": review_obj.edited_body,
        }

    delivery_info = None
    if delivery_obj:
        import os
        delivery_info = {
            "id": delivery_obj.id,
            "delivery_mode": delivery_obj.delivery_mode,
            "delivery_status": delivery_obj.delivery_status,
            "provider": delivery_obj.provider,
            "staged_file_path": os.path.basename(delivery_obj.staged_file_path) if delivery_obj.staged_file_path else None,
            "delivered_at": delivery_obj.delivered_at,
        }

    return {
        "id": run.id,
        "campaign_id": run.campaign_id,
        "company_id": run.company_id,
        "company_name": company.company_name if company else None,
        "domain": company.domain if company else None,
        "status": run.status,
        "last_completed_stage": run.last_completed_stage,
        "error_message": run.error_message,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "draft": draft_info,
        "person": person_info,
        "contact": contact_info,
        "review": review_info,
        "delivery": delivery_info,
        "events": [
            {
                "event_type": e.event_type,
                "message": e.message,
                "created_at": e.created_at
            }
            for e in events
        ]
    }

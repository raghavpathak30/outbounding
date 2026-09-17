"""
Campaign service and validation schemas.
Handles campaign creation, listing, retrieval, and resume association validation.
"""
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.entities import Campaign, Resume

logger = logging.getLogger("server.services.campaign")


# =====================================================================
# Pydantic Schemas
# =====================================================================

class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255, description="Campaign descriptive name")
    objective: str = Field(..., min_length=5, description="Primary campaign outreach goal")
    target_geography: str = Field(default="India", max_length=128)
    industry: str = Field(default="Cybersecurity", max_length=128)
    company_stage: str = Field(default="Seed / Early-Stage", max_length=128)
    company_size: str = Field(default="small", max_length=64, description="'small', 'established', or 'any'")
    target_roles: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)
    employment_type: str = Field(default="full_time", max_length=64)
    remote_preference: str = Field(default="any", max_length=64)
    resume_id: Optional[str] = Field(default=None, description="Optional associated resume UUID")

    @field_validator("target_roles", "technologies", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                return [x.strip() for x in v.split(",") if x.strip()]
        return [str(v).strip()]


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    resume_id: Optional[str] = None
    name: str
    objective: str
    target_geography: str
    industry: str
    company_stage: str
    company_size: str
    target_roles: List[str] = Field(default_factory=list)
    technologies: List[str] = Field(default_factory=list)
    employment_type: str
    remote_preference: str
    status: str
    created_at: datetime
    updated_at: datetime
    total_companies: int = 0
    selected_companies: int = 0
    in_progress_count: int = 0
    waiting_for_review_count: int = 0
    waiting_for_delivery_count: int = 0
    sent_count: int = 0
    staged_count: int = 0


def format_campaign_response(campaign: Campaign, db: Optional[Session] = None) -> CampaignResponse:
    """Helper to convert database Campaign model to response schema with parsed lists and optional metrics."""
    roles = []
    if campaign.target_roles_json:
        try:
            roles = json.loads(campaign.target_roles_json)
        except Exception:
            roles = []

    techs = []
    if campaign.technologies_json:
        try:
            techs = json.loads(campaign.technologies_json)
        except Exception:
            techs = []

    total_comps = 0
    selected_comps = 0
    in_prog = 0
    wait_rev = 0
    wait_deliv = 0
    sent_cnt = 0
    staged_cnt = 0

    if db is not None:
        from sqlalchemy import func
        from server.models.entities import Company, PipelineRun, Delivery
        total_comps = db.execute(select(func.count(Company.id)).where(Company.campaign_id == campaign.id)).scalar() or 0
        selected_comps = db.execute(select(func.count(Company.id)).where(Company.campaign_id == campaign.id, Company.selection_status == "selected")).scalar() or 0
        in_prog = db.execute(select(func.count(PipelineRun.id)).where(PipelineRun.campaign_id == campaign.id, PipelineRun.status.in_(["queued", "running"]))).scalar() or 0
        wait_rev = db.execute(select(func.count(PipelineRun.id)).where(PipelineRun.campaign_id == campaign.id, PipelineRun.status == "waiting_for_review")).scalar() or 0
        wait_deliv = db.execute(select(func.count(PipelineRun.id)).where(PipelineRun.campaign_id == campaign.id, PipelineRun.status == "waiting_for_delivery")).scalar() or 0
        sent_cnt = db.execute(
            select(func.count(Delivery.id))
            .join(PipelineRun, Delivery.pipeline_run_id == PipelineRun.id)
            .where(PipelineRun.campaign_id == campaign.id, Delivery.delivery_status == "sent")
        ).scalar() or 0
        staged_cnt = db.execute(
            select(func.count(Delivery.id))
            .join(PipelineRun, Delivery.pipeline_run_id == PipelineRun.id)
            .where(PipelineRun.campaign_id == campaign.id, Delivery.delivery_status == "staged")
        ).scalar() or 0

    return CampaignResponse(
        id=campaign.id,
        user_id=campaign.user_id,
        resume_id=campaign.resume_id,
        name=campaign.name,
        objective=campaign.objective,
        target_geography=campaign.target_geography,
        industry=campaign.industry,
        company_stage=campaign.company_stage,
        company_size=campaign.company_size,
        target_roles=roles,
        technologies=techs,
        employment_type=campaign.employment_type,
        remote_preference=campaign.remote_preference,
        status=campaign.status,
        created_at=campaign.created_at,
        updated_at=campaign.updated_at,
        total_companies=total_comps,
        selected_companies=selected_comps,
        in_progress_count=in_prog,
        waiting_for_review_count=wait_rev,
        waiting_for_delivery_count=wait_deliv,
        sent_count=sent_cnt,
        staged_count=staged_cnt,
    )


# =====================================================================
# CampaignService
# =====================================================================

class CampaignService:
    @classmethod
    def create_campaign(cls, db: Session, user_id: str, data: CampaignCreate) -> Campaign:
        """
        Creates a new campaign for the authenticated user.
        Validates referenced resume_id if provided.
        """
        if data.resume_id:
            resume = db.execute(
                select(Resume).where(Resume.id == data.resume_id, Resume.user_id == user_id)
            ).scalar_one_or_none()
            if not resume:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Referenced resume '{data.resume_id}' does not exist or does not belong to the user."
                )

        roles_json = json.dumps(data.target_roles) if data.target_roles else None
        techs_json = json.dumps(data.technologies) if data.technologies else None

        campaign = Campaign(
            user_id=user_id,
            resume_id=data.resume_id,
            name=data.name.strip(),
            objective=data.objective.strip(),
            target_geography=data.target_geography.strip(),
            industry=data.industry.strip(),
            company_size=data.company_size.strip().lower(),
            company_stage=data.company_stage.strip(),
            target_roles_json=roles_json,
            technologies_json=techs_json,
            employment_type=data.employment_type.strip(),
            remote_preference=data.remote_preference.strip(),
            status="draft",
        )

        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        logger.info(f"Created campaign: id={campaign.id}, user_id={user_id}, name='{campaign.name}'")
        return campaign

    @staticmethod
    def list_campaigns(db: Session, user_id: str) -> List[Campaign]:
        """Lists all campaigns belonging to the authenticated user, newest first."""
        stmt = (
            select(Campaign)
            .where(Campaign.user_id == user_id)
            .order_by(Campaign.created_at.desc())
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def get_campaign(db: Session, user_id: str, campaign_id: str) -> Optional[Campaign]:
        """Retrieves a campaign belonging to the authenticated user."""
        stmt = select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user_id)
        return db.execute(stmt).scalar_one_or_none()

"""
Dashboard API router for Outbound Lead Pipeline.
Provides authoritative, database-derived summary metrics and actionable items for /dashboard:
- Active campaigns
- Discovered companies
- Selected companies
- In-progress runs (queued + running)
- Waiting for review runs
- Waiting for delivery runs
- Delivered sent / staged
- Failed runs
- Daily & weekly volume cap usage
- Actionable 'Needs Attention' summaries
Enforces strict tenant isolation.
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from server.models.entities import (
    User,
    Campaign,
    Company,
    PipelineRun,
    Delivery,
    Review,
)
from server.database import get_db
from server.services.auth import get_current_user_and_refresh
from server.services.delivery import DeliveryService

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


class AttentionItem(BaseModel):
    id: str
    run_id: Optional[str] = None
    review_id: Optional[str] = None
    campaign_id: str
    campaign_name: str
    company_name: str
    domain: str
    status: str
    detail: Optional[str] = None
    timestamp: Optional[str] = None


class DashboardStatsResponse(BaseModel):
    active_campaigns_count: int
    companies_discovered_count: int
    companies_selected_count: int
    runs_processing_count: int
    waiting_for_review_count: int
    waiting_for_delivery_count: int
    sent_count: int
    staged_count: int
    failed_count: int
    volume_caps: Dict[str, Any]
    needs_attention: Dict[str, List[AttentionItem]]


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Returns live, tenant-isolated operational statistics for the dashboard cockpit.
    Every metric is derived directly from the database or authoritative DeliveryService.
    """
    user_id = current_user.id

    # 1. Active campaigns
    active_campaigns = db.execute(
        select(func.count(Campaign.id)).where(
            Campaign.user_id == user_id,
            Campaign.status.in_(["active", "draft"])
        )
    ).scalar() or 0

    # 2. Companies Discovered & Selected for user's campaigns
    discovered_comps = db.execute(
        select(func.count(Company.id))
        .join(Campaign, Company.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id)
    ).scalar() or 0

    selected_comps = db.execute(
        select(func.count(Company.id))
        .join(Campaign, Company.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id, Company.selection_status == "selected")
    ).scalar() or 0

    # 3. Pipeline Runs counts
    runs_processing = db.execute(
        select(func.count(PipelineRun.id))
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id, PipelineRun.status.in_(["queued", "running"]))
    ).scalar() or 0

    waiting_review = db.execute(
        select(func.count(PipelineRun.id))
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id, PipelineRun.status == "waiting_for_review")
    ).scalar() or 0

    waiting_delivery = db.execute(
        select(func.count(PipelineRun.id))
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id, PipelineRun.status == "waiting_for_delivery")
    ).scalar() or 0

    failed_runs_count = db.execute(
        select(func.count(PipelineRun.id))
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id, PipelineRun.status == "failed")
    ).scalar() or 0

    # 4. Deliveries
    sent_count = db.execute(
        select(func.count(Delivery.id))
        .join(PipelineRun, Delivery.pipeline_run_id == PipelineRun.id)
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id, Delivery.delivery_status == "sent")
    ).scalar() or 0

    staged_count = db.execute(
        select(func.count(Delivery.id))
        .join(PipelineRun, Delivery.pipeline_run_id == PipelineRun.id)
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id, Delivery.delivery_status == "staged")
    ).scalar() or 0

    # 5. Volume caps
    _, _, cap_stats = DeliveryService.check_volume_caps_unified(db)

    # 6. Actionable Needs Attention items
    # (a) Waiting for review items (limit 5)
    review_stmt = (
        select(Review, PipelineRun, Company, Campaign)
        .join(PipelineRun, Review.pipeline_run_id == PipelineRun.id)
        .join(Company, PipelineRun.company_id == Company.id)
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id, Review.status == "pending")
        .order_by(PipelineRun.started_at.desc().nulls_last())
        .limit(5)
    )
    rev_results = db.execute(review_stmt).all()
    attention_review = [
        AttentionItem(
            id=rev.id,
            run_id=run.id,
            review_id=rev.id,
            campaign_id=camp.id,
            campaign_name=camp.name,
            company_name=comp.company_name,
            domain=comp.domain,
            status="waiting_for_review",
            detail=f"Match Score: {comp.match_score or 0}/100",
            timestamp=run.started_at.isoformat() if run.started_at else None,
        )
        for rev, run, comp, camp in rev_results
    ]

    # (b) Waiting for delivery items (limit 5)
    delivery_stmt = (
        select(PipelineRun, Company, Campaign, Review)
        .join(Company, PipelineRun.company_id == Company.id)
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .outerjoin(Review, PipelineRun.id == Review.pipeline_run_id)
        .where(Campaign.user_id == user_id, PipelineRun.status == "waiting_for_delivery")
        .order_by(PipelineRun.completed_at.desc().nulls_last(), PipelineRun.started_at.desc().nulls_last())
        .limit(5)
    )
    deliv_results = db.execute(delivery_stmt).all()
    attention_delivery = [
        AttentionItem(
            id=run.id,
            run_id=run.id,
            review_id=rev.id if rev else None,
            campaign_id=camp.id,
            campaign_name=camp.name,
            company_name=comp.company_name,
            domain=comp.domain,
            status="waiting_for_delivery",
            detail="Human review approved; ready for authoritative delivery trigger.",
            timestamp=rev.reviewed_at.isoformat() if rev and rev.reviewed_at else None,
        )
        for run, comp, camp, rev in deliv_results
    ]

    # (c) Failed runs (limit 5)
    failed_stmt = (
        select(PipelineRun, Company, Campaign)
        .join(Company, PipelineRun.company_id == Company.id)
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Campaign.user_id == user_id, PipelineRun.status == "failed")
        .order_by(PipelineRun.completed_at.desc().nulls_last())
        .limit(5)
    )
    fail_results = db.execute(failed_stmt).all()
    attention_failed = [
        AttentionItem(
            id=run.id,
            run_id=run.id,
            campaign_id=camp.id,
            campaign_name=camp.name,
            company_name=comp.company_name,
            domain=comp.domain,
            status="failed",
            detail=run.error_message or "Execution failed",
            timestamp=run.completed_at.isoformat() if run.completed_at else None,
        )
        for run, comp, camp in fail_results
    ]

    return DashboardStatsResponse(
        active_campaigns_count=active_campaigns,
        companies_discovered_count=discovered_comps,
        companies_selected_count=selected_comps,
        runs_processing_count=runs_processing,
        waiting_for_review_count=waiting_review,
        waiting_for_delivery_count=waiting_delivery,
        sent_count=sent_count,
        staged_count=staged_count,
        failed_count=failed_runs_count,
        volume_caps=cap_stats,
        needs_attention={
            "waiting_for_review": attention_review,
            "waiting_for_delivery": attention_delivery,
            "failed_runs": attention_failed,
        }
    )

"""
Delivery API endpoints for Phase 8 Authoritative Delivery Safety, Staging & Live Send.
Provides authenticated endpoints to:
- Explicitly trigger delivery for an approved PipelineRun in 'waiting_for_delivery'
- Inspect delivery status, staging files, and safety audit logs
Enforces tenant isolation and never accepts safety decisions from the client.
"""
import os
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.entities import User, PipelineRun, Campaign, Delivery, Company, Contact, Person
from server.database import get_db
from server.services.auth import get_current_user_and_refresh
from server.services.delivery import DeliveryService, DeliveryResponse
from server.services.job_manager import JobManager

router = APIRouter(tags=["Delivery"])


class DeliveryListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_run_id: str
    campaign_id: str
    campaign_name: str
    company_id: str
    company_name: str
    domain: str
    recipient_email: Optional[str] = None
    recipient_name: Optional[str] = None
    delivery_mode: str
    delivery_status: str
    provider: str
    staged_file_path: Optional[str] = None
    delivered_at: datetime
    error_message: Optional[str] = None
    safety_audit: Optional[Dict[str, Any]] = None


@router.get(
    "/api/v1/deliveries",
    response_model=List[DeliveryListItem],
    summary="List delivery records for authenticated user's campaigns"
)
async def list_deliveries(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter: staged, sent, failed, blocked_safety, all"),
    campaign_id: Optional[str] = Query(None, description="Filter by campaign"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db)
):
    """
    Retrieves delivery history with strict tenant isolation.
    Sanitizes errors, hides server file paths, and never exposes provider credentials.
    """
    stmt = (
        select(Delivery, PipelineRun, Company, Campaign)
        .join(PipelineRun, Delivery.pipeline_run_id == PipelineRun.id)
        .join(Company, Delivery.company_id == Company.id)
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Campaign.user_id == current_user.id)
    )

    if campaign_id:
        stmt = stmt.where(Campaign.id == campaign_id)

    if status_filter and status_filter.strip().lower() != "all":
        stmt = stmt.where(Delivery.delivery_status == status_filter.strip().lower())

    stmt = stmt.order_by(Delivery.delivered_at.desc()).offset(offset).limit(limit)
    results = db.execute(stmt).all()

    items = []
    for deliv, run, comp, camp in results:
        contact = None
        if deliv.contact_id:
            contact = db.execute(select(Contact).where(Contact.id == deliv.contact_id)).scalar_one_or_none()
        person_name = None
        if contact and contact.person_id:
            person = db.execute(select(Person).where(Person.id == contact.person_id)).scalar_one_or_none()
            if person:
                person_name = person.full_name

        audit = None
        if deliv.safety_audit_json:
            try:
                audit = json.loads(deliv.safety_audit_json)
            except Exception:
                pass

        sanitized_path = None
        if deliv.staged_file_path:
            sanitized_path = os.path.basename(deliv.staged_file_path)

        items.append(
            DeliveryListItem(
                id=deliv.id,
                pipeline_run_id=deliv.pipeline_run_id,
                campaign_id=camp.id,
                campaign_name=camp.name,
                company_id=comp.id,
                company_name=comp.company_name,
                domain=comp.domain,
                recipient_email=contact.email if contact else None,
                recipient_name=person_name,
                delivery_mode=deliv.delivery_mode,
                delivery_status=deliv.delivery_status,
                provider=deliv.provider,
                staged_file_path=sanitized_path,
                delivered_at=deliv.delivered_at,
                error_message=run.error_message if deliv.delivery_status in ["failed", "blocked_safety"] else None,
                safety_audit=audit,
            )
        )
    return items


@router.post(
    "/api/v1/deliveries/{pipeline_run_id}",
    response_model=DeliveryResponse,
    status_code=status.HTTP_200_OK,
    summary="Explicitly execute delivery for an approved PipelineRun"
)
async def execute_delivery(
    pipeline_run_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db)
):
    """
    Authoritative Delivery Trigger.
    Revalidates all safety gates and dispatches live email or stages locally to disk.
    Strictly ignores client-provided safety parameters.
    """
    return DeliveryService.deliver_pipeline_run(
        db=db,
        run_id=pipeline_run_id,
        user_id=current_user.id
    )


@router.post(
    "/api/v1/deliveries/{pipeline_run_id}/enqueue",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue delivery execution asynchronously through background worker"
)
async def enqueue_delivery(
    pipeline_run_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db)
):
    """
    Asynchronously queues delivery for a PipelineRun via JobManager worker pool.
    Verifies tenant ownership and 'waiting_for_delivery' status before enqueuing.
    """
    # Verify ownership and status
    stmt = (
        select(PipelineRun)
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(PipelineRun.id == pipeline_run_id, Campaign.user_id == current_user.id)
    )
    run = db.execute(stmt).scalar_one_or_none()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PipelineRun '{pipeline_run_id}' not found or unauthorized access."
        )

    if run.status != "waiting_for_delivery":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PipelineRun is in '{run.status}' state (expected 'waiting_for_delivery')."
        )

    JobManager.get_instance().submit_delivery(pipeline_run_id, user_id=current_user.id)
    return {
        "message": "Delivery successfully enqueued for background processing.",
        "pipeline_run_id": pipeline_run_id,
        "status": "queued"
    }


@router.get(
    "/api/v1/deliveries/{pipeline_run_id}",
    response_model=DeliveryResponse,
    summary="Retrieve delivery record and safety audit for a PipelineRun"
)
async def get_delivery(
    pipeline_run_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db)
):
    """Retrieves delivery status and safety audit record for a specific PipelineRun."""
    stmt = (
        select(Delivery, PipelineRun, Campaign)
        .join(PipelineRun, Delivery.pipeline_run_id == PipelineRun.id)
        .join(Campaign, PipelineRun.campaign_id == Campaign.id)
        .where(Delivery.pipeline_run_id == pipeline_run_id, Campaign.user_id == current_user.id)
    )
    result = db.execute(stmt).first()
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery record for run '{pipeline_run_id}' not found or unauthorized access."
        )

    deliv, run, camp = result
    safety_audit = None
    if deliv.safety_audit_json:
        try:
            import json
            safety_audit = json.loads(deliv.safety_audit_json)
        except Exception:
            pass

    return DeliveryResponse(
        id=deliv.id,
        pipeline_run_id=deliv.pipeline_run_id,
        company_id=deliv.company_id,
        contact_id=deliv.contact_id,
        delivery_mode=deliv.delivery_mode,
        delivery_status=deliv.delivery_status,
        provider=deliv.provider,
        staged_file_path=deliv.staged_file_path,
        delivered_at=deliv.delivered_at,
        error=run.error_message if deliv.delivery_status in ["failed", "blocked_safety"] else None,
        safety_audit=safety_audit
    )

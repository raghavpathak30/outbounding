"""
Company API routes.
Implements:
- GET /api/v1/campaigns/{campaign_id}/companies (list & filter candidates for Discovery Grid)
- POST /api/v1/campaigns/{campaign_id}/companies/select (operator selects companies)
- POST /api/v1/campaigns/{campaign_id}/enqueue-selected (prepares selected companies for Phase 6)
"""
import json
from datetime import datetime
from typing import List, Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from server.models.entities import User, Campaign, Company
from server.database import get_db
from server.services.auth import get_current_user_and_refresh
from server.services.campaign import CampaignService

router = APIRouter(prefix="/api/v1/campaigns/{campaign_id}", tags=["Companies"])


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
    selection_status: Optional[str] = Query(default=None, description="Filter: 'discovered', 'selected', 'rejected'"),
    min_score: Optional[int] = Query(default=None, ge=0, le=100),
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Retrieves discovered Company records for the Discovery Grid.
    Supports filtering by selection status and minimum match score.
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

    stmt = stmt.order_by(Company.match_score.desc().nullslast(), Company.created_at.desc())
    companies = list(db.execute(stmt).scalars().all())

    return [_format_company_grid_item(c) for c in companies]


@router.post("/companies/select", status_code=status.HTTP_200_OK)
async def select_companies(
    campaign_id: str,
    payload: SelectCompaniesRequest,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Marks target companies as 'selected' for future enrichment.
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
            comp.selection_status = "selected"
            selected_count += 1
            updated_comps.append(comp)

    if selected_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="None of the specified companies were found in this campaign."
        )

    db.commit()
    return {
        "status": "success",
        "campaign_id": campaign_id,
        "selected_count": selected_count,
        "selected_company_ids": [c.id for c in updated_comps],
    }


@router.post("/enqueue-selected", status_code=status.HTTP_200_OK)
async def enqueue_selected_companies(
    campaign_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Establishes the boundary for Phase 6:
    Validates that candidate companies have been selected and are eligible for enrichment.
    Phase 5 stops here and does NOT invoke person research or email resolution.
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

    return {
        "status": "queued",
        "campaign_id": campaign_id,
        "enqueued_count": len(selected_companies),
        "enqueued_company_ids": [c.id for c in selected_companies],
        "message": "Companies verified and queued. Enrichment pipeline execution will commence in Phase 6.",
    }

"""
Campaign API routes.
Implements:
- GET /api/v1/campaigns (list user campaigns)
- POST /api/v1/campaigns (create campaign)
- GET /api/v1/campaigns/{id} (get campaign detail)
- POST /api/v1/campaigns/{id}/discover (trigger discovery for campaign)
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from server.models.entities import User
from server.database import get_db
from server.services.auth import get_current_user_and_refresh
from server.services.campaign import (
    CampaignService,
    CampaignCreate,
    CampaignResponse,
    format_campaign_response,
)
from server.services.discovery import DiscoveryService

router = APIRouter(prefix="/api/v1/campaigns", tags=["Campaigns"])


@router.get("", response_model=List[CampaignResponse])
async def list_campaigns(
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Lists all outreach campaigns created by the authenticated user."""
    campaigns = CampaignService.list_campaigns(db, current_user.id)
    return [format_campaign_response(c, db) for c in campaigns]


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Creates a new campaign for the authenticated user."""
    campaign = CampaignService.create_campaign(db, current_user.id, payload)
    return format_campaign_response(campaign, db)


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Retrieves campaign metadata. Rejects if not owned by authenticated user."""
    campaign = CampaignService.get_campaign(db, current_user.id, campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found."
        )
    return format_campaign_response(campaign, db)


@router.post("/{campaign_id}/discover", status_code=status.HTTP_200_OK)
async def discover_companies_for_campaign(
    campaign_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Triggers company discovery for the campaign:
    - Queries DiscoveryAdapter
    - Filters out contacted history & duplicates
    - Runs deterministic 100-point ranking
    - Persists Company records in 'discovered' status
    """
    campaign = CampaignService.get_campaign(db, current_user.id, campaign_id)
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found."
        )

    try:
        discovered_companies = DiscoveryService.discover_for_campaign(
            db=db,
            user_id=current_user.id,
            campaign_id=campaign_id,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Discovery failed: {str(e)}"
        )

    return {
        "status": "success",
        "campaign_id": campaign_id,
        "discovered_count": len(discovered_companies),
        "companies": [
            {
                "id": c.id,
                "domain": c.domain,
                "company_name": c.company_name,
                "match_score": c.match_score,
                "selection_status": c.selection_status,
            }
            for c in discovered_companies
        ],
    }

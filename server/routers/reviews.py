"""
Review API endpoints for Phase 7 Web Human Review.
Provides authenticated operations to:
- List reviews in queue with status/campaign filters
- Retrieve full review detail and decision context
- Edit draft subject/body
- Explicitly approve or reject drafts
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from server.models.entities import User
from server.database import get_db
from server.services.auth import get_current_user_and_refresh
from server.services.review import (
    ReviewService,
    ReviewListItem,
    ReviewDetailResponse,
    DraftUpdatePayload,
    ReviewActionPayload,
)

router = APIRouter(tags=["Review"])


@router.get("/api/v1/review", response_model=List[ReviewListItem])
@router.get("/api/v1/reviews", response_model=List[ReviewListItem])
async def list_reviews(
    campaign_id: Optional[str] = Query(None, description="Filter by campaign ID"),
    review_status: Optional[str] = Query(None, alias="status", description="Filter by status ('pending', 'approved', 'rejected', 'all')"),
    limit: int = Query(50, ge=1, le=100, description="Pagination limit"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Lists reviews belonging to the authenticated operator's campaigns."""
    return ReviewService.list_reviews(
        db=db,
        user_id=current_user.id,
        campaign_id=campaign_id,
        status_filter=review_status,
        limit=limit,
        offset=offset,
    )


@router.get("/api/v1/review/{review_id}", response_model=ReviewDetailResponse)
@router.get("/api/v1/reviews/{review_id}", response_model=ReviewDetailResponse)
async def get_review(
    review_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Retrieves complete decision context for a specific review."""
    return ReviewService.get_review_detail(
        db=db,
        user_id=current_user.id,
        review_id=review_id,
    )


@router.patch("/api/v1/review/{review_id}", response_model=ReviewDetailResponse)
@router.put("/api/v1/review/{review_id}", response_model=ReviewDetailResponse)
@router.patch("/api/v1/reviews/{review_id}", response_model=ReviewDetailResponse)
@router.put("/api/v1/reviews/{review_id}", response_model=ReviewDetailResponse)
async def edit_review_draft(
    review_id: str,
    payload: DraftUpdatePayload,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Updates the generated draft before review decision."""
    return ReviewService.edit_draft(
        db=db,
        user_id=current_user.id,
        review_id=review_id,
        payload=payload,
    )


@router.post("/api/v1/review/{review_id}/approve", response_model=ReviewDetailResponse, status_code=status.HTTP_200_OK)
@router.post("/api/v1/reviews/{review_id}/approve", response_model=ReviewDetailResponse, status_code=status.HTTP_200_OK)
async def approve_review(
    review_id: str,
    payload: Optional[ReviewActionPayload] = None,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Explicitly approves a draft.
    Transitions Review.status to 'approved' and PipelineRun.status to 'completed'.
    Does NOT trigger delivery or staging.
    """
    return ReviewService.approve_review(
        db=db,
        user_id=current_user.id,
        review_id=review_id,
        payload=payload,
    )


@router.post("/api/v1/review/{review_id}/reject", response_model=ReviewDetailResponse, status_code=status.HTTP_200_OK)
@router.post("/api/v1/reviews/{review_id}/reject", response_model=ReviewDetailResponse, status_code=status.HTTP_200_OK)
async def reject_review(
    review_id: str,
    payload: Optional[ReviewActionPayload] = None,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Explicitly rejects a draft with an optional rejection reason.
    Transitions Review.status to 'rejected' and PipelineRun.status to 'skipped'.
    Does NOT trigger delivery or staging.
    """
    return ReviewService.reject_review(
        db=db,
        user_id=current_user.id,
        review_id=review_id,
        payload=payload,
    )

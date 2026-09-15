"""
Candidate Profile API routes.
Implements:
- GET /api/v1/profile (returns candidate bio, links, and drafting instructions)
- PUT /api/v1/profile (updates candidate bio, links, and drafting instructions)
"""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.models.entities import User
from server.database import get_db
from server.services.auth import get_current_user_and_refresh
from server.services.profile import ProfileService

router = APIRouter(prefix="/api/v1/profile", tags=["Profile"])


class ProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    custom_instructions: Optional[str] = None
    work_preferences_json: Optional[str] = None


class ProfileResponse(BaseModel):
    id: str
    user_id: str
    full_name: str
    title: str
    email: str
    phone: Optional[str] = None
    location: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    custom_instructions: Optional[str] = None
    work_preferences_json: Optional[str] = None


@router.get("", response_model=ProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db)
):
    """Retrieves candidate profile for current authenticated user."""
    profile = ProfileService.get_or_create_profile(db, current_user.id, current_user.email)
    return profile


@router.put("", response_model=ProfileResponse)
async def update_profile(
    update_data: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db)
):
    """Updates candidate profile details and custom drafting instructions."""
    updated = ProfileService.update_profile(
        db=db,
        user_id=current_user.id,
        updates=update_data.model_dump(exclude_unset=True)
    )
    return updated

"""
Candidate Profile Service.
Handles fetching and updating the user's candidate profile, portfolio links,
and custom LLM drafting instructions backed by the Profile model.
"""
from typing import Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.entities import Profile


class ProfileService:
    """Service layer for candidate profile operations."""

    @staticmethod
    def get_profile(db: Session, user_id: str) -> Optional[Profile]:
        """Retrieves profile associated with user_id."""
        return db.execute(
            select(Profile).where(Profile.user_id == user_id)
        ).scalar_one_or_none()

    @staticmethod
    def get_or_create_profile(
        db: Session,
        user_id: str,
        default_email: str,
        default_name: str = "Candidate"
    ) -> Profile:
        """Retrieves existing profile or initializes a default profile for the user."""
        profile = ProfileService.get_profile(db, user_id)
        if not profile:
            profile = Profile(
                user_id=user_id,
                full_name=default_name,
                title="Software Engineer",
                email=default_email,
                custom_instructions=""
            )
            db.add(profile)
            db.commit()
            db.refresh(profile)
        return profile

    @staticmethod
    def update_profile(
        db: Session,
        user_id: str,
        updates: Dict[str, Any]
    ) -> Profile:
        """
        Updates profile fields for a user.
        Allowed fields: full_name, title, email, phone, location, github_url,
        portfolio_url, linkedin_url, custom_instructions, work_preferences_json.
        """
        profile = ProfileService.get_profile(db, user_id)
        if not profile:
            profile = Profile(user_id=user_id, email="", full_name="", title="")
            db.add(profile)

        updatable_fields = {
            "full_name",
            "title",
            "email",
            "phone",
            "location",
            "github_url",
            "portfolio_url",
            "linkedin_url",
            "custom_instructions",
            "work_preferences_json",
        }

        for field, value in updates.items():
            if field in updatable_fields and value is not None:
                setattr(profile, field, value)

        db.commit()
        db.refresh(profile)
        return profile

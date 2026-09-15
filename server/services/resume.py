"""
Resume upload and structured parsing service.
Handles validation, secure storage outside public web root,
structured extraction via ResumeParsingAdapter, Pydantic validation,
and resume activation lifecycle.
"""
import os
import re
import json
import uuid
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from fastapi import UploadFile, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from server.models.entities import Resume, Profile
from pipeline.adapters.resume_parsing import ResumeParsingAdapter
from pipeline.adapters.base import AdapterFactory

logger = logging.getLogger("server.services.resume")

# Base storage directory for uploaded resumes (outside public web paths)
UPLOAD_BASE_DIR = Path("uploads/resumes")
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".pdf", ".json"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/json",
    "text/json",
    "application/octet-stream",  # often sent by generic clients for pdf/json
}


# =====================================================================
# Pydantic Validation Schemas
# =====================================================================

class PersonalInfoSchema(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    github: Optional[str] = None
    linkedin: Optional[str] = None
    portfolio: Optional[str] = None


class PersonaCategorySchema(BaseModel):
    summary: str = Field(..., min_length=5, description="High-level narrative summary")
    highlights: List[str] = Field(default_factory=list, description="Bullet achievements")
    core_stack: List[str] = Field(default_factory=list, description="Relevant tools/technologies")

    @field_validator("highlights", "core_stack", mode="before")
    @classmethod
    def ensure_list_of_strings(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item) for item in v if item]
        return [str(v)]


class ResumeSchema(BaseModel):
    personal: PersonalInfoSchema
    security_infrastructure: PersonaCategorySchema
    ai_machine_learning: PersonaCategorySchema
    hr_talent_acquisition: PersonaCategorySchema


# =====================================================================
# ResumeService Implementation
# =====================================================================

class ResumeService:
    @staticmethod
    def sanitize_filename(filename: Optional[str]) -> str:
        """Sanitizes user-provided filename to prevent directory traversal."""
        if not filename:
            return "resume.pdf"
        base = Path(filename).name
        # Keep alphanumeric, dashes, underscores, and dots
        clean = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", base)
        return clean or "resume.pdf"

    @classmethod
    def validate_upload(cls, file: UploadFile, max_size_bytes: int = MAX_FILE_SIZE_BYTES) -> Tuple[str, str]:
        """
        Validates file extension and mime type.
        Returns: (sanitized_filename, extension)
        Raises: HTTPException on invalid format or excessive size.
        """
        original_name = file.filename or ""
        clean_name = cls.sanitize_filename(original_name)
        ext = Path(clean_name).suffix.lower()

        if ext not in ALLOWED_EXTENSIONS:
            logger.warning("Rejected file upload: disallowed extension")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file format '{ext}'. Only PDF and JSON resumes are accepted."
            )

        content_type = (file.content_type or "").lower()
        if content_type and content_type not in ALLOWED_CONTENT_TYPES:
            # If extension is valid but content_type is mismatched
            logger.warning("Rejected file upload: content-type mismatch")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Mismatched content type '{content_type}' for extension '{ext}'."
            )

        return clean_name, ext

    @classmethod
    def save_upload_to_disk(
        cls,
        user_id: str,
        resume_id: str,
        file: UploadFile,
        ext: str,
        upload_dir: Optional[Path] = None
    ) -> Tuple[str, int]:
        """
        Persists uploaded file bytes to secure storage outside public web root:
        uploads/resumes/{user_id}/{resume_id}.{ext}
        Enforces MAX_FILE_SIZE_BYTES during streaming write.
        """
        target_dir = (upload_dir or UPLOAD_BASE_DIR) / user_id
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / f"{resume_id}{ext}"

        total_bytes = 0
        try:
            with open(file_path, "wb") as dest:
                while chunk := file.file.read(64 * 1024):
                    total_bytes += len(chunk)
                    if total_bytes > MAX_FILE_SIZE_BYTES:
                        raise HTTPException(
                            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                            detail=f"File size exceeds limit of {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB."
                        )
                    dest.write(chunk)
        except Exception:
            if file_path.exists():
                file_path.unlink()
            raise

        logger.info(f"Persisted resume document: resume_id={resume_id}, bytes={total_bytes}")
        return str(file_path), total_bytes

    @classmethod
    def process_upload(
        cls,
        db: Session,
        user_id: str,
        file: UploadFile,
        adapter: Optional[ResumeParsingAdapter] = None,
        upload_dir: Optional[Path] = None
    ) -> Resume:
        """
        Uploads and triggers structured parsing for a candidate resume:
        1. Validates extension and content type.
        2. Persists file to uploads/resumes/{user_id}/{resume_id}.{ext}.
        3. Creates Resume record in DB with parsing_status='pending'.
        4. Invokes ResumeParsingAdapter (Stub or Gemini).
        5. Validates output with Pydantic ResumeSchema.
        6. Updates parsing_status='completed' or 'failed' (with sanitized error).
        """
        clean_name, ext = cls.validate_upload(file)
        resume_id = str(uuid.uuid4())

        # Save to disk
        persisted_path, file_size = cls.save_upload_to_disk(
            user_id=user_id,
            resume_id=resume_id,
            file=file,
            ext=ext,
            upload_dir=upload_dir
        )

        # Check if user already has an active resume
        existing_active = db.execute(
            select(Resume).where(Resume.user_id == user_id, Resume.is_active == True)
        ).scalar_one_or_none()

        is_active = (existing_active is None)

        resume = Resume(
            id=resume_id,
            user_id=user_id,
            filename=clean_name,
            file_path=persisted_path,
            parsing_status="pending",
            parsing_error=None,
            is_active=is_active,
        )
        db.add(resume)
        db.commit()
        db.refresh(resume)

        # Parse file using configured adapter
        active_adapter = adapter or AdapterFactory.get_resume_parsing_adapter()
        is_json = (ext == ".json")

        try:
            raw_parsed = active_adapter.parse(persisted_path, is_json=is_json)

            # Validate against Pydantic schema
            validated = ResumeSchema.model_validate(raw_parsed)
            clean_parsed_json = json.dumps(validated.model_dump())

            resume.parsing_status = "completed"
            resume.parsed_data_json = clean_parsed_json
            resume.parsing_error = None

            # Sync personal details to user's candidate Profile if empty
            profile = db.execute(
                select(Profile).where(Profile.user_id == user_id)
            ).scalar_one_or_none()
            if profile and validated.personal:
                p = validated.personal
                if not profile.full_name and p.name:
                    profile.full_name = p.name
                if not profile.title and p.title:
                    profile.title = p.title
                if not profile.phone and p.phone:
                    profile.phone = p.phone
                if not profile.location and p.location:
                    profile.location = p.location
                if not profile.github_url and p.github:
                    profile.github_url = p.github
                if not profile.linkedin_url and p.linkedin:
                    profile.linkedin_url = p.linkedin
                if not profile.portfolio_url and p.portfolio:
                    profile.portfolio_url = p.portfolio

            db.commit()
            db.refresh(resume)
            logger.info(f"Resume parsing completed successfully: resume_id={resume_id}")

        except Exception as e:
            db.rollback()
            # Strict PII sanitization: record exception type and generic reason, never candidate data
            sanitized_err = f"{type(e).__name__}: {str(e)[:160]}"
            resume.parsing_status = "failed"
            resume.parsing_error = sanitized_err
            db.commit()
            db.refresh(resume)
            logger.warning(f"Resume parsing failed for resume_id={resume_id}: {sanitized_err}")

        return resume

    @staticmethod
    def list_resumes(db: Session, user_id: str) -> List[Resume]:
        """Lists all resumes uploaded by the candidate, newest first."""
        stmt = (
            select(Resume)
            .where(Resume.user_id == user_id)
            .order_by(Resume.uploaded_at.desc())
        )
        return list(db.execute(stmt).scalars().all())

    @staticmethod
    def get_resume(db: Session, user_id: str, resume_id: str) -> Optional[Resume]:
        """Fetches a specific resume belonging to the user."""
        stmt = select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
        return db.execute(stmt).scalar_one_or_none()

    @staticmethod
    def activate_resume(db: Session, user_id: str, resume_id: str) -> Resume:
        """
        Activates the specified resume for outreach campaigns and deactivates all others.
        """
        target = db.execute(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
        ).scalar_one_or_none()

        if not target:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resume not found."
            )

        # Deactivate all user resumes
        db.execute(
            update(Resume)
            .where(Resume.user_id == user_id)
            .values(is_active=False)
        )

        # Activate target
        target.is_active = True
        db.commit()
        db.refresh(target)
        logger.info(f"Activated resume_id={resume_id} for user_id={user_id}")
        return target

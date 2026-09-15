"""
Resume management API routes.
Implements:
- POST /api/v1/resumes/upload (multipart upload of PDF or JSON resume)
- GET /api/v1/resumes (list resumes for authenticated user)
- GET /api/v1/resumes/{resume_id} (detail including parsed_data_json)
- POST /api/v1/resumes/{resume_id}/activate (activates resume for campaign generation)
"""
import json
from datetime import datetime
from typing import List, Optional, Any, Dict
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from server.models.entities import User
from server.database import get_db
from server.services.auth import get_current_user_and_refresh
from server.services.resume import ResumeService

router = APIRouter(prefix="/api/v1/resumes", tags=["Resumes"])


# =====================================================================
# Response Models
# =====================================================================

class ResumeSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    filename: str
    file_path: str
    parsing_status: str
    parsing_error: Optional[str] = None
    is_active: bool
    uploaded_at: datetime


class ResumeDetailResponse(ResumeSummaryResponse):
    model_config = ConfigDict(from_attributes=True)

    parsed_data: Optional[Dict[str, Any]] = None
    parsed_data_json: Optional[str] = None


def _format_resume_detail(resume) -> ResumeDetailResponse:
    parsed_dict = None
    if resume.parsed_data_json:
        try:
            parsed_dict = json.loads(resume.parsed_data_json)
        except Exception:
            parsed_dict = None

    return ResumeDetailResponse(
        id=resume.id,
        user_id=resume.user_id,
        filename=resume.filename,
        file_path=resume.file_path,
        parsing_status=resume.parsing_status,
        parsing_error=resume.parsing_error,
        is_active=resume.is_active,
        uploaded_at=resume.uploaded_at,
        parsed_data=parsed_dict,
        parsed_data_json=resume.parsed_data_json,
    )


# =====================================================================
# Route Handlers
# =====================================================================

@router.post("/upload", response_model=ResumeDetailResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """
    Uploads a candidate resume (PDF or JSON) and triggers structured parsing
    into outreach personas (security_infrastructure, ai_machine_learning, hr_talent_acquisition).
    """
    resume = ResumeService.process_upload(
        db=db,
        user_id=current_user.id,
        file=file,
    )
    return _format_resume_detail(resume)


@router.get("", response_model=List[ResumeSummaryResponse])
async def list_resumes(
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Lists all resumes uploaded by current candidate, ordered by newest first."""
    resumes = ResumeService.list_resumes(db, current_user.id)
    return resumes


@router.get("/{resume_id}", response_model=ResumeDetailResponse)
async def get_resume_detail(
    resume_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Retrieves full details of a specific resume including structured parsed persona data."""
    resume = ResumeService.get_resume(db, current_user.id, resume_id)
    if not resume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Resume not found."
        )
    return _format_resume_detail(resume)


@router.post("/{resume_id}/activate", response_model=ResumeSummaryResponse)
@router.put("/{resume_id}/activate", response_model=ResumeSummaryResponse)
async def activate_resume(
    resume_id: str,
    current_user: User = Depends(get_current_user_and_refresh),
    db: Session = Depends(get_db),
):
    """Activates the specified resume as the primary profile for outbound campaigns."""
    resume = ResumeService.activate_resume(db, current_user.id, resume_id)
    return resume

"""
Authentication API routes.
Implements:
- POST /api/v1/auth/login (with 5-attempt/15-min rate limiting and httpOnly cookie issuance)
- POST /api/v1/auth/logout (writes token JTI to RevokedToken database table and clears cookie)
- GET /api/v1/auth/me (returns current user and profile)
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.entities import User
from server.database import get_db
from server.config import Settings, get_settings
from server.services.auth import (
    AuthService,
    login_rate_limiter,
    get_current_user_and_refresh,
    extract_token_from_request,
    ACCESS_TOKEN_COOKIE_NAME,
    DEFAULT_EXPIRATION_HOURS,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: str
    password: str


class UserSummaryResponse(BaseModel):
    id: str
    email: str
    is_active: bool


class LoginResponse(BaseModel):
    status: str
    token: str
    user: UserSummaryResponse


@router.post("/login", response_model=LoginResponse)
async def login(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Authenticates user, checks rate limits, issues JWT access token,
    and sets secure httpOnly cookie.
    """
    clean_email = login_data.email.strip().lower()
    # Rate limit key tracks both email and client IP to prevent brute-force attacks
    client_ip = request.client.host if request.client else "unknown"
    rate_limit_key = f"{client_ip}:{clean_email}"

    if login_rate_limiter.is_rate_limited(rate_limit_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again in 15 minutes."
        )

    user = db.execute(
        select(User).where(User.email == clean_email)
    ).scalar_one_or_none()

    if not user or not AuthService.verify_password(login_data.password, user.password_hash):
        login_rate_limiter.record_failure(rate_limit_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password."
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account deactivated."
        )

    # Reset rate limit counter upon successful authentication
    login_rate_limiter.reset(rate_limit_key)

    # Issue 2-hour JWT
    token, jti, expire_dt = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )

    # Set httpOnly cookie
    max_age_seconds = int(DEFAULT_EXPIRATION_HOURS * 3600)
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True over HTTPS
        max_age=max_age_seconds
    )

    return LoginResponse(
        status="success",
        token=token,
        user=UserSummaryResponse(id=user.id, email=user.email, is_active=user.is_active)
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """
    Logs out the user by:
    1. Extracting the current token's JTI and writing it to the RevokedToken table.
    2. Deleting the client-side httpOnly cookie.
    """
    token = extract_token_from_request(request)
    if token:
        try:
            payload = AuthService.decode_token(token, settings.jwt_secret_key, settings.jwt_algorithm)
            jti = payload.get("jti")
            exp_ts = payload.get("exp")
            if jti and exp_ts:
                expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
                AuthService.revoke_token(db, jti, expires_at)
        except Exception:
            pass  # Even if token is malformed, ensure client cookie is erased

    response.delete_cookie(key=ACCESS_TOKEN_COOKIE_NAME)
    return {"status": "success", "message": "Successfully logged out"}


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user_and_refresh)
):
    """Returns currently authenticated user information and profile summary."""
    profile_data = None
    if current_user.profile:
        profile_data = {
            "id": current_user.profile.id,
            "full_name": current_user.profile.full_name,
            "title": current_user.profile.title,
            "email": current_user.profile.email,
            "location": current_user.profile.location,
            "portfolio_url": current_user.profile.portfolio_url,
            "github_url": current_user.profile.github_url,
            "linkedin_url": current_user.profile.linkedin_url,
            "custom_instructions": current_user.profile.custom_instructions,
        }

    return {
        "id": current_user.id,
        "email": current_user.email,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat(),
        "profile": profile_data
    }

"""
Authentication service for Outbound Lead Generation Pipeline.
Handles bcrypt password hashing (work factor 12), JWT issuance (2-hour expiry),
token revocation via the database, silent token refresh, and login rate limiting.
"""
import uuid
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import jwt
import bcrypt
from fastapi import Request, Response, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.entities import User, RevokedToken
from server.database import get_db
from server.config import Settings, get_settings

logger = logging.getLogger("server.auth")

ACCESS_TOKEN_COOKIE_NAME = "access_token"
DEFAULT_EXPIRATION_HOURS = 2
SILENT_REFRESH_THRESHOLD_SECONDS = 1800  # 30 minutes


class LoginRateLimiter:
    """
    In-memory sliding-window rate limiter for authentication attempts.
    Enforces a strict limit of 5 failed attempts in a 15-minute rolling window.
    """
    def __init__(self, max_attempts: int = 5, window_seconds: int = 900):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failed_attempts: Dict[str, list[float]] = {}

    def _cleanup_expired(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        valid = [t for t in self._failed_attempts.get(key, []) if t > cutoff]
        self._failed_attempts[key] = valid
        return valid

    def is_rate_limited(self, key: str) -> bool:
        now = time.time()
        valid = self._cleanup_expired(key, now)
        return len(valid) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        now = time.time()
        valid = self._cleanup_expired(key, now)
        valid.append(now)
        self._failed_attempts[key] = valid

    def reset(self, key: str) -> None:
        self._failed_attempts.pop(key, None)

    def clear_all(self) -> None:
        self._failed_attempts.clear()


# Global rate limiter instance for auth endpoints
login_rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=900)


class AuthService:
    """Core cryptographic and session management service."""

    @staticmethod
    def hash_password(plain_password: str) -> str:
        """Hashes password using bcrypt with a work factor (salt rounds) of 12."""
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(plain_password.encode("utf-8"), salt).decode("utf-8")

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verifies a plain password against the stored bcrypt hash."""
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                hashed_password.encode("utf-8")
            )
        except Exception:
            return False

    @staticmethod
    def create_access_token(
        user_id: str,
        email: str,
        secret_key: str,
        expires_delta: Optional[timedelta] = None,
        algorithm: str = "HS256"
    ) -> tuple[str, str, datetime]:
        """
        Issues a new JWT access token with a 2-hour default expiry and unique JTI.
        Returns: (encoded_jwt, jti, expiration_datetime)
        """
        now = datetime.now(timezone.utc)
        expire = now + (expires_delta or timedelta(hours=DEFAULT_EXPIRATION_HOURS))
        jti = uuid.uuid4().hex

        payload: Dict[str, Any] = {
            "sub": user_id,
            "email": email,
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp())
        }

        token = jwt.encode(payload, secret_key, algorithm=algorithm)
        return token, jti, expire

    @staticmethod
    def decode_token(token: str, secret_key: str, algorithm: str = "HS256") -> Dict[str, Any]:
        """Decodes and validates JWT token signature and expiration."""
        return jwt.decode(
            token,
            secret_key,
            algorithms=[algorithm],
            options={"require": ["sub", "email", "jti", "exp", "iat"]}
        )

    @staticmethod
    def revoke_token(session: Session, jti: str, expires_at: datetime) -> None:
        """Records a token's JTI in the RevokedToken table to invalidate it server-side."""
        existing = session.execute(
            select(RevokedToken).where(RevokedToken.jti == jti)
        ).scalar_one_or_none()
        if not existing:
            revocation = RevokedToken(jti=jti, expires_at=expires_at)
            session.add(revocation)
            session.commit()

    @staticmethod
    def is_token_revoked(session: Session, jti: str) -> bool:
        """Checks if a JTI has been revoked in the database."""
        revoked = session.execute(
            select(RevokedToken).where(RevokedToken.jti == jti)
        ).scalar_one_or_none()
        return revoked is not None


def extract_token_from_request(request: Request) -> Optional[str]:
    """Extracts access token from httpOnly cookie or Authorization Bearer header."""
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE_NAME)
    if cookie_token:
        return cookie_token

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()

    return None


async def get_current_user_and_refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings)
) -> User:
    """
    FastAPI dependency for authenticating users via JWT.
    - Validates token signature and expiration.
    - Enforces server-side revocation check against RevokedToken table on every request.
    - Silent Refresh: If token has < 30 minutes remaining, reissues a fresh cookie.
    """
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required: No access token provided."
        )

    try:
        payload = AuthService.decode_token(token, settings.jwt_secret_key, settings.jwt_algorithm)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again."
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token."
        )

    jti = payload.get("jti")
    if not jti or AuthService.is_token_revoked(db, jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please log in again."
        )

    user_id = payload.get("sub")
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or deactivated."
        )

    # Silent Refresh: Reissue cookie if remaining lifetime < 30 minutes
    now_ts = datetime.now(timezone.utc).timestamp()
    exp_ts = payload.get("exp", 0)
    remaining_seconds = exp_ts - now_ts

    if 0 < remaining_seconds < SILENT_REFRESH_THRESHOLD_SECONDS:
        fresh_token, _, fresh_expire = AuthService.create_access_token(
            user_id=user.id,
            email=user.email,
            secret_key=settings.jwt_secret_key,
            expires_delta=timedelta(hours=DEFAULT_EXPIRATION_HOURS),
            algorithm=settings.jwt_algorithm
        )
        response.set_cookie(
            key=ACCESS_TOKEN_COOKIE_NAME,
            value=fresh_token,
            httponly=True,
            samesite="lax",
            secure=False,  # Set to True in production over HTTPS
            max_age=int(timedelta(hours=DEFAULT_EXPIRATION_HOURS).total_seconds())
        )
        response.headers["X-Token-Refreshed"] = "true"

    return user

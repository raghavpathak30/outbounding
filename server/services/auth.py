"""
Authentication service for Outbound Lead Generation Pipeline.
Handles bcrypt password hashing (work factor 12), JWT issuance (2-hour expiry),
token revocation via the database, silent token refresh, and login rate limiting.
"""
import os
import uuid
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import jwt
import bcrypt
from fastapi import Request, Response, Depends, HTTPException, status
from sqlalchemy import select, func
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
        is_secure = (
            settings.secure_cookies
            if settings.secure_cookies is not None
            else (
                request.headers.get("x-forwarded-proto") == "https"
                or request.url.scheme == "https"
            )
        )
        response.set_cookie(
            key=ACCESS_TOKEN_COOKIE_NAME,
            value=fresh_token,
            httponly=True,
            samesite="lax",
            secure=is_secure,
            max_age=int(timedelta(hours=DEFAULT_EXPIRATION_HOURS).total_seconds())
        )
        response.headers["X-Token-Refreshed"] = "true"

    return user


def bootstrap_first_user(
    db: Session,
    admin_email: Optional[str] = None,
    admin_password: Optional[str] = None
) -> bool:
    """
    Idempotent startup bootstrap for the initial administrator user.
    If the users table is empty:
      - Reads BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD from args or env.
      - If both are present:
          - Validates password length >= 12 characters (raises RuntimeError if too short).
          - Validates email format contains '@'.
          - Hashes password using AuthService.hash_password (bcrypt rounds 12).
          - Inserts User and Profile records, committing transaction.
          - Logs at INFO with the email (never the password).
      - If either variable is missing or empty:
          - Logs a clear WARNING naming both variables.
          - Returns False without raising.
    If any user already exists in the users table:
      - Strictly no-ops and returns False. Never overwrites or resets existing accounts.
    """
    from server.models.entities import Profile

    user_count = db.execute(select(func.count(User.id))).scalar() or 0
    if user_count > 0:
        return False

    email = (admin_email if admin_email is not None else os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")).strip()
    password = admin_password if admin_password is not None else os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "")

    if not email or not password:
        logger.warning(
            "Users table is empty and BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD are not set in environment. "
            "Web login is unavailable until operator credentials are provided."
        )
        return False

    if len(password) < 12:
        error_msg = (
            "BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters long. "
            "Refusing startup to prevent weak admin credentials on host."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    clean_email = email.lower()
    if "@" not in clean_email:
        error_msg = f"Invalid BOOTSTRAP_ADMIN_EMAIL format: {email}. Must contain '@'."
        logger.error(error_msg)
        raise ValueError(error_msg)

    password_hash = AuthService.hash_password(password)
    user = User(
        email=clean_email,
        password_hash=password_hash,
        is_active=True
    )
    db.add(user)
    db.flush()

    profile = Profile(
        user_id=user.id,
        full_name="Admin Operator",
        title="Administrator",
        email=clean_email
    )
    db.add(profile)
    db.commit()

    logger.info("First-user bootstrap successfully initialized admin user: %s", clean_email)
    return True

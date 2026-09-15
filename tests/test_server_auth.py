"""
Unit Tests for Authentication, JWT Sessions, Profile Management, and CLI.
Validates Phase 3 requirements:
- Successful login issues httpOnly JWT cookie
- Wrong password rejected (401)
- Protected routes reject unauthenticated requests (401)
- Protected routes reject revoked tokens (401)
- Logout revokes token in RevokedToken database table
- Rate limiting kicks in after 5 failed attempts in 15 minutes (429)
- Silent refresh reissues cookie when <30 min remain and not when plenty of time remains
- Profile GET and PUT updates candidate bio and drafting instructions
- CLI create-admin command
- Frontend /login and /dashboard views
"""
import pytest
from datetime import datetime, timezone, timedelta
from starlette.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from server.models.base import Base
from server.models.entities import User, Profile, RevokedToken
from server.database import create_db_engine, get_db
from server.config import Settings, get_settings
from server.app import create_app
from server.services.auth import (
    AuthService,
    login_rate_limiter,
    ACCESS_TOKEN_COOKIE_NAME,
)
from server.cli import create_admin_user


@pytest.fixture
def auth_ctx(tmp_path):
    """Provides an isolated database, configured app, and TestClient for auth tests."""
    test_db_file = tmp_path / "test_auth.db"
    test_db_url = f"sqlite:///{test_db_file}"
    engine = create_db_engine(db_url=test_db_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    settings = Settings(
        jwt_secret_key="unit-test-secret-key-32-bytes-secure!",
        cors_allowed_origins=["https://work.raghavpathak.me", "http://localhost"],
        delivery_mode="staged",
        dry_run=True,
    )

    app = create_app(settings=settings)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings

    client = TestClient(app, raise_server_exceptions=False)
    session = TestingSessionLocal()

    # Always start with a clean rate limiter state
    login_rate_limiter.clear_all()

    yield {
        "client": client,
        "session": session,
        "settings": settings,
        "engine": engine,
        "db_factory": TestingSessionLocal,
    }

    session.close()
    app.dependency_overrides.clear()
    login_rate_limiter.clear_all()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def seed_user(session, email: str = "operator@raghavpathak.me", password: str = "SecurePass123!") -> User:
    """Helper to seed a test user with hashed password."""
    user = User(
        email=email,
        password_hash=AuthService.hash_password(password),
        is_active=True
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# 1. Successful Login Issues JWT Cookie
def test_successful_login_issues_jwt_cookie(auth_ctx):
    client = auth_ctx["client"]
    session = auth_ctx["session"]
    settings = auth_ctx["settings"]

    seed_user(session, email="operator@raghavpathak.me", password="ValidPassword123!")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "operator@raghavpathak.me", "password": "ValidPassword123!"}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "success"
    assert "token" in data
    assert data["user"]["email"] == "operator@raghavpathak.me"

    # Assert httpOnly cookie was set
    assert ACCESS_TOKEN_COOKIE_NAME in response.cookies
    token_from_cookie = response.cookies[ACCESS_TOKEN_COOKIE_NAME]

    # Verify token payload
    payload = AuthService.decode_token(token_from_cookie, settings.jwt_secret_key)
    assert payload["email"] == "operator@raghavpathak.me"
    assert payload["jti"] is not None
    assert payload["exp"] > datetime.now(timezone.utc).timestamp()


# 2. Wrong Password Rejected
def test_wrong_password_rejected(auth_ctx):
    client = auth_ctx["client"]
    session = auth_ctx["session"]

    seed_user(session, email="operator@raghavpathak.me", password="ValidPassword123!")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "operator@raghavpathak.me", "password": "WrongPassword999!"}
    )
    assert response.status_code == 401
    assert "access_token" not in response.cookies
    assert response.json()["detail"] == "Invalid email or password."


# 3. Protected Route Rejects Requests With No Cookie
def test_protected_route_rejects_no_cookie(auth_ctx):
    client = auth_ctx["client"]
    client.cookies.clear()

    # /api/v1/auth/me
    res_me = client.get("/api/v1/auth/me")
    assert res_me.status_code == 401
    assert "Authentication required" in res_me.json()["detail"]

    # /api/v1/profile
    res_profile = client.get("/api/v1/profile")
    assert res_profile.status_code == 401
    assert "Authentication required" in res_profile.json()["detail"]


# 4. Protected Route Rejects Requests With a Revoked Token
def test_protected_route_rejects_revoked_token(auth_ctx):
    client = auth_ctx["client"]
    session = auth_ctx["session"]
    settings = auth_ctx["settings"]

    user = seed_user(session, email="revoked_user@raghavpathak.me", password="Password123!")
    token, jti, expire_dt = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        secret_key=settings.jwt_secret_key
    )

    # Manually revoke token in the RevokedToken table
    AuthService.revoke_token(session, jti, expire_dt)

    client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"].lower()


# 5. Logout Actually Revokes Current Token
def test_logout_revokes_token_server_side(auth_ctx):
    client = auth_ctx["client"]
    session = auth_ctx["session"]
    settings = auth_ctx["settings"]

    seed_user(session, email="logout_user@raghavpathak.me", password="Password123!")

    # 1. Login
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "logout_user@raghavpathak.me", "password": "Password123!"}
    )
    assert login_res.status_code == 200
    token = login_res.cookies[ACCESS_TOKEN_COOKIE_NAME]

    # Verify access works before logout
    me_res = client.get("/api/v1/auth/me")
    assert me_res.status_code == 200

    # 2. Logout
    logout_res = client.post("/api/v1/auth/logout")
    assert logout_res.status_code == 200

    # 3. Verify server-side rejection even if client re-attaches the token
    payload = AuthService.decode_token(token, settings.jwt_secret_key)
    assert AuthService.is_token_revoked(session, payload["jti"]) is True

    # Attempt request with the logged-out token
    client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token)
    unauthorized_res = client.get("/api/v1/auth/me")
    assert unauthorized_res.status_code == 401
    assert "revoked" in unauthorized_res.json()["detail"].lower()


# 6. Rate Limiting Kicks In After 5 Failed Attempts in 15 Minutes
def test_rate_limiting_kicks_in_after_5_failed_attempts(auth_ctx):
    client = auth_ctx["client"]
    session = auth_ctx["session"]

    seed_user(session, email="ratelimit_user@raghavpathak.me", password="RealPassword123!")

    # First 5 wrong attempts: all return 401
    for i in range(5):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "ratelimit_user@raghavpathak.me", "password": f"WrongPass_{i}"}
        )
        assert res.status_code == 401, f"Attempt {i+1} should return 401"

    # 6th attempt: blocked by rate limiter with 429
    res_blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "ratelimit_user@raghavpathak.me", "password": "RealPassword123!"}
    )
    assert res_blocked.status_code == 429
    assert "too many failed login attempts" in res_blocked.json()["detail"].lower()


# 7. Silent Refresh Reissues Cookie When < 30 Min Remain (And Not When Plenty of Time)
def test_silent_refresh_behavior(auth_ctx):
    client = auth_ctx["client"]
    session = auth_ctx["session"]
    settings = auth_ctx["settings"]

    user = seed_user(session, email="refresh_user@raghavpathak.me", password="Password123!")

    # Case A: Plenty of time left (e.g., 60 minutes remaining > 30 minutes)
    token_60m, _, _ = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        secret_key=settings.jwt_secret_key,
        expires_delta=timedelta(minutes=60)
    )
    client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token_60m)
    res_plenty = client.get("/api/v1/auth/me")
    assert res_plenty.status_code == 200
    # No refresh header and no modified cookie
    assert "X-Token-Refreshed" not in res_plenty.headers
    assert res_plenty.headers.get("set-cookie") is None

    # Case B: < 30 minutes remaining (e.g., 15 minutes remaining)
    token_15m, _, _ = AuthService.create_access_token(
        user_id=user.id,
        email=user.email,
        secret_key=settings.jwt_secret_key,
        expires_delta=timedelta(minutes=15)
    )
    client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token_15m)
    res_refresh = client.get("/api/v1/auth/me")
    assert res_refresh.status_code == 200
    assert res_refresh.headers.get("X-Token-Refreshed") == "true"
    assert ACCESS_TOKEN_COOKIE_NAME in res_refresh.cookies

    # The reissued token must be different and have full 2-hour validity
    fresh_token = res_refresh.cookies[ACCESS_TOKEN_COOKIE_NAME]
    assert fresh_token != token_15m

    fresh_payload = AuthService.decode_token(fresh_token, settings.jwt_secret_key)
    remaining_lifetime = fresh_payload["exp"] - datetime.now(timezone.utc).timestamp()
    assert remaining_lifetime > 7000  # ~2 hours (7200s)


# 8. Profile GET and PUT Operations
def test_profile_get_and_put_lifecycle(auth_ctx):
    client = auth_ctx["client"]
    session = auth_ctx["session"]

    user = seed_user(session, email="profile_user@raghavpathak.me", password="Password123!")

    # Login to acquire session
    client.post(
        "/api/v1/auth/login",
        json={"email": "profile_user@raghavpathak.me", "password": "Password123!"}
    )

    # 1. GET initial profile
    get_res = client.get("/api/v1/profile")
    assert get_res.status_code == 200
    profile_data = get_res.json()
    assert profile_data["email"] == "profile_user@raghavpathak.me"

    # 2. PUT updated profile
    update_payload = {
        "full_name": "Raghav Pathak",
        "title": "Principal Security & AI Engineer",
        "phone": "+91-9876543210",
        "location": "Jaipur, India",
        "portfolio_url": "https://raghavpathak.dev",
        "github_url": "https://github.com/raghavpathak30",
        "linkedin_url": "https://linkedin.com/in/raghav-pathak",
        "custom_instructions": "Focus heavily on homomorphic encryption and LLM security."
    }
    put_res = client.put("/api/v1/profile", json=update_payload)
    assert put_res.status_code == 200
    updated_data = put_res.json()
    assert updated_data["full_name"] == "Raghav Pathak"
    assert updated_data["title"] == "Principal Security & AI Engineer"
    assert updated_data["portfolio_url"] == "https://raghavpathak.dev"
    assert "homomorphic encryption" in updated_data["custom_instructions"]

    # 3. GET again to verify persistence
    get_again = client.get("/api/v1/profile")
    assert get_again.status_code == 200
    assert get_again.json()["title"] == "Principal Security & AI Engineer"


# 9. CLI create-admin Command
def test_cli_create_admin(auth_ctx):
    session = auth_ctx["session"]

    # Seed user via CLI helper function
    create_admin_user("cli_admin@raghavpathak.me", "SuperSecurePassword123!", "CLI Admin", db=session)

    user = session.execute(
        select(User).where(User.email == "cli_admin@raghavpathak.me")
    ).scalar_one_or_none()

    assert user is not None
    assert user.is_active is True
    assert AuthService.verify_password("SuperSecurePassword123!", user.password_hash) is True
    assert user.profile is not None
    assert user.profile.full_name == "CLI Admin"


# 10. Frontend Shell Views (/login, /dashboard, /)
def test_frontend_shell_views(auth_ctx):
    client = auth_ctx["client"]

    # /login returns HTML form
    res_login = client.get("/login")
    assert res_login.status_code == 200
    assert "text/html" in res_login.headers.get("content-type", "")
    assert "Operator Security Gate" in res_login.text
    assert "Sign In" in res_login.text

    # /dashboard returns HTML console shell
    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    assert "text/html" in res_dash.headers.get("content-type", "")
    assert "Outbound Pipeline Console" in res_dash.text
    assert "Daily Volume Cap" in res_dash.text
    assert "Weekly Volume Cap" in res_dash.text

    # / redirects to /dashboard
    res_root = client.get("/", follow_redirects=False)
    assert res_root.status_code == 302
    assert res_root.headers.get("location") == "/dashboard"

"""
Tests for First-User Startup Bootstrap Flow.
Validates:
1. Provisions single admin User + Profile when users table is empty and env vars are set.
2. Password is verified by AuthService.verify_password (exact same bcrypt rounds 12).
3. Bootstrap logs at INFO with email and never the password.
4. If password is under 12 characters, raises RuntimeError to abort startup loudly.
5. If table is empty and env vars are missing, logs a clear WARNING naming both variables.
6. If any user already exists, strictly no-ops and never overwrites existing accounts.
7. Login page displays bootstrap hint without open registration form.
"""
import os
import logging
import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from server.models.base import Base
from server.models.entities import User, Profile
from server.database import create_db_engine, get_db
from server.config import Settings, get_settings
from server.services.auth import AuthService, bootstrap_first_user
from server.app import create_app


@pytest.fixture
def test_db(tmp_path):
    """Creates an isolated SQLite database file for testing."""
    db_file = tmp_path / "test_bootstrap.db"
    engine = create_db_engine(db_url=f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session, engine
    session.close()


def test_bootstrap_creates_admin_when_empty(test_db, caplog):
    session, _ = test_db
    email = "bootstrap-admin@example.com"
    password = "super-secure-admin-password-2026!"

    with caplog.at_level(logging.INFO):
        result = bootstrap_first_user(
            db=session,
            admin_email=email,
            admin_password=password
        )

    assert result is True

    # Verify user created in database
    users = session.execute(select(User)).scalars().all()
    assert len(users) == 1
    admin_user = users[0]
    assert admin_user.email == email
    assert admin_user.is_active is True

    # Verify password verified with exact same AuthService context
    assert AuthService.verify_password(password, admin_user.password_hash) is True
    assert AuthService.verify_password("wrong-password", admin_user.password_hash) is False

    # Verify profile created
    profile = session.execute(select(Profile).where(Profile.user_id == admin_user.id)).scalar_one_or_none()
    assert profile is not None
    assert profile.email == email

    # Verify INFO log includes email but NEVER the password
    bootstrap_logs = [r.message for r in caplog.records if "bootstrap" in r.message.lower()]
    assert any(email in msg for msg in bootstrap_logs)
    assert not any(password in msg for msg in bootstrap_logs)


def test_bootstrap_refuses_weak_password(test_db):
    session, _ = test_db
    email = "admin@example.com"
    weak_password = "short"  # 5 chars < 12

    with pytest.raises(RuntimeError) as exc_info:
        bootstrap_first_user(
            db=session,
            admin_email=email,
            admin_password=weak_password
        )

    assert "BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters long" in str(exc_info.value)

    # Verify nothing was created in database
    count = session.execute(select(func.count(User.id))).scalar()
    assert count == 0


def test_bootstrap_noop_when_user_exists(test_db, caplog):
    session, _ = test_db

    # Pre-create an existing user
    existing_hash = AuthService.hash_password("existing-secure-password-123")
    existing_user = User(
        email="existing@example.com",
        password_hash=existing_hash,
        is_active=True
    )
    session.add(existing_user)
    session.commit()

    # Attempt bootstrap with new credentials
    with caplog.at_level(logging.INFO):
        result = bootstrap_first_user(
            db=session,
            admin_email="newadmin@example.com",
            admin_password="brand-new-secure-password-123"
        )

    assert result is False

    # Verify existing user was untouched
    users = session.execute(select(User)).scalars().all()
    assert len(users) == 1
    assert users[0].email == "existing@example.com"
    assert users[0].password_hash == existing_hash


def test_bootstrap_warns_when_empty_and_vars_missing(test_db, monkeypatch, caplog):
    session, _ = test_db

    monkeypatch.delenv("BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)

    with caplog.at_level(logging.WARNING):
        result = bootstrap_first_user(db=session)

    assert result is False

    # Check that warning was logged naming both variables
    warning_logs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("BOOTSTRAP_ADMIN_EMAIL" in msg and "BOOTSTRAP_ADMIN_PASSWORD" in msg for msg in warning_logs)

    # Database remains empty
    count = session.execute(select(func.count(User.id))).scalar()
    assert count == 0


def test_login_page_renders_bootstrap_hint():
    """Validates that GET /login displays the bootstrap hint without a signup form."""
    settings = Settings(
        jwt_secret_key="unit-test-secret-key-32-bytes-secure!",
        cors_allowed_origins=["https://work.raghavpathak.me"],
        delivery_mode="staged",
        dry_run=True,
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/login")
    assert response.status_code == 200
    html = response.text
    assert "BOOTSTRAP_ADMIN_EMAIL" in html
    assert "BOOTSTRAP_ADMIN_PASSWORD" in html
    assert "Sign In" in html
    # Ensure no open signup / registration form is present
    assert "action=\"/register\"" not in html
    assert "Create account" not in html


def test_lifespan_refuses_weak_password(tmp_path, monkeypatch):
    """Verifies that application lifespan fails loudly with RuntimeError if password < 12 chars."""
    db_file = tmp_path / "test_lifespan_weak.db"
    engine = create_db_engine(db_url=f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "short")

    settings = Settings(
        jwt_secret_key="unit-test-secret-key-32-bytes-secure!",
        cors_allowed_origins=["https://work.raghavpathak.me"],
        delivery_mode="staged",
        dry_run=True,
    )
    app = create_app(settings=settings)
    app.state.db_session_factory = TestingSessionLocal

    with pytest.raises(RuntimeError) as exc_info:
        with TestClient(app):
            pass

    assert "BOOTSTRAP_ADMIN_PASSWORD must be at least 12 characters long" in str(exc_info.value)


def test_lifespan_bootstrap_and_login_flow(tmp_path, monkeypatch):
    """Verifies full startup bootstrap and subsequent successful login."""
    db_file = tmp_path / "test_lifespan_success.db"
    engine = create_db_engine(db_url=f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)

    admin_email = "prod-operator@domain.com"
    admin_password = "very-secure-password-123456!"

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", admin_email)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", admin_password)

    settings = Settings(
        jwt_secret_key="unit-test-secret-key-32-bytes-secure!",
        cors_allowed_origins=["https://work.raghavpathak.me"],
        delivery_mode="staged",
        dry_run=True,
    )
    app = create_app(settings=settings)
    app.state.db_session_factory = TestingSessionLocal

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        # Test login with bootstrapped credentials
        res = client.post("/api/v1/auth/login", json={"email": admin_email, "password": admin_password})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert data["user"]["email"] == admin_email
        assert "token" in data


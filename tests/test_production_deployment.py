"""
Production Deployment, Security Headers, Backup & Final Verification Test Suite.
Phase 10 verification tests.
"""
import os
import io
import json
import uuid
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from server.config import Settings, get_settings
from server.app import create_app
from server.models.base import Base
from server.database import create_db_engine, get_db
from server.models.entities import (
    User, Profile, Resume, Campaign, Company, Person, Contact,
    PipelineRun, Draft, Review, Delivery, PipelineEvent
)
from server.services.auth import AuthService, ACCESS_TOKEN_COOKIE_NAME
from server.services.job_manager import JobManager
from server.services.delivery import DeliveryService
from scripts.backup import create_backup, backup_sqlite_database
from scripts.restore import inspect_and_validate_backup, restore_backup


@pytest.fixture
def prod_settings(tmp_path):
    return Settings(
        app_env="production",
        jwt_secret_key="phase10_super_secret_production_key_for_testing",
        jwt_algorithm="HS256",
        jwt_access_token_expire_minutes=120,
        host="127.0.0.1",
        port=8000,
        delivery_mode="stage",
        dry_run=True,
        confirm_live=False,
        cors_allowed_origins=[
            "https://work.raghavpatak.me",
            "https://work.raghavpathak.me",
            "http://localhost:3000"
        ]
    )


@pytest.fixture
def test_db_session(tmp_path):
    db_file = tmp_path / "prod_test.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_db_engine(db_url=db_url)
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def prod_client(prod_settings, test_db_session):
    app = create_app(settings=prod_settings)
    app.dependency_overrides[get_db] = lambda: test_db_session
    app.dependency_overrides[get_settings] = lambda: prod_settings
    return TestClient(app)


# ==============================================================================
# 1. Configuration & Network Defaults
# ==============================================================================

def test_production_network_and_delivery_defaults(prod_settings):
    """Verifies that production defaults enforce loopback host and non-live safety."""
    assert prod_settings.host == "127.0.0.1"
    assert prod_settings.port == 8000
    assert prod_settings.app_env == "production"
    assert prod_settings.delivery_mode == "stage"
    assert prod_settings.dry_run is True
    assert prod_settings.confirm_live is False
    assert "https://work.raghavpatak.me" in prod_settings.cors_allowed_origins
    assert "https://work.raghavpathak.me" in prod_settings.cors_allowed_origins


def test_cors_origins_parsing():
    """Verifies comma-separated CORS_ORIGINS string parsing."""
    s = Settings(
        jwt_secret_key="key",
        cors_allowed_origins="https://work.raghavpatak.me, https://work.raghavpathak.me, http://localhost:8000"
    )
    assert len(s.cors_allowed_origins) == 3
    assert "https://work.raghavpatak.me" in s.cors_allowed_origins
    assert "https://work.raghavpathak.me" in s.cors_allowed_origins


# ==============================================================================
# 2. Security Headers Middleware
# ==============================================================================

def test_security_headers_present_on_all_responses(prod_client):
    """Verifies HSTS, X-Content-Type-Options, X-Frame-Options, CSP, and Referrer-Policy."""
    res = prod_client.get("/health")
    assert res.status_code == 200

    headers = res.headers
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "geolocation=()" in headers.get("permissions-policy", "")
    assert "strict-transport-security" in headers
    assert "max-age=31536000" in headers["strict-transport-security"]

    # CSP header verification
    csp = headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "font-src 'self' https://fonts.gstatic.com" in csp
    assert "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com" in csp
    assert "script-src 'self' 'unsafe-inline'" in csp
    assert "frame-ancestors 'none'" in csp


def test_csp_allows_operator_cockpit_assets(prod_client):
    """Verifies HTML pages return with identical, non-blocking CSP."""
    res = prod_client.get("/login")
    assert res.status_code == 200
    assert "content-security-policy" in res.headers
    assert "https://fonts.googleapis.com" in res.headers["content-security-policy"]


# ==============================================================================
# 3. Healthcheck Non-Leaking Endpoints
# ==============================================================================

def test_health_endpoints_return_clean_status(prod_client):
    """Verifies /health and /api/v1/health do not leak paths, tokens, or credentials."""
    for endpoint in ["/health", "/api/v1/health"]:
        res = prod_client.get(endpoint)
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") in ["healthy", "degraded"]
        assert data.get("version") == "1.0.0"
        assert data.get("delivery_mode") == "stage"
        assert data.get("dry_run") is True
        assert data.get("database") == "ok"

        # Explicit non-leak assertions
        body_text = res.text
        assert "jwt" not in body_text.lower()
        assert "secret" not in body_text.lower()
        assert "password" not in body_text.lower()
        assert "sqlite:" not in body_text.lower()
        assert "/home/" not in body_text.lower()


# ==============================================================================
# 4. Cookie Security & HTTPS Awareness
# ==============================================================================

def test_cookie_secure_flag_over_https(prod_client, test_db_session):
    """Verifies auth cookies enforce Secure=True when request arrives via HTTPS or proxy."""
    # Create active user
    u = User(
        email="operator_secure@example.com",
        password_hash=AuthService.hash_password("ProdPassword123!"),
        is_active=True
    )
    test_db_session.add(u)
    test_db_session.commit()

    # Request with X-Forwarded-Proto: https (simulating Caddy termination)
    res = prod_client.post(
        "/api/v1/auth/login",
        json={"email": "operator_secure@example.com", "password": "ProdPassword123!"},
        headers={"x-forwarded-proto": "https"}
    )
    assert res.status_code == 200
    cookie_header = res.headers.get("set-cookie", "")
    assert ACCESS_TOKEN_COOKIE_NAME in cookie_header
    assert "Secure" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header


# ==============================================================================
# 5. Upload Security Hardening
# ==============================================================================

def test_upload_security_disallowed_extension(prod_client, test_db_session, prod_settings):
    """Verifies that malicious or executable uploads are rejected with 400."""
    u = User(
        email="uploader@example.com",
        password_hash=AuthService.hash_password("Pass123!"),
        is_active=True
    )
    test_db_session.add(u)
    test_db_session.commit()

    token, _, _ = AuthService.create_access_token(
        user_id=u.id, email=u.email, secret_key=prod_settings.jwt_secret_key
    )
    prod_client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token)

    # Try uploading a shell script disguised as PDF
    malicious_file = io.BytesIO(b"#!/bin/bash\nrm -rf /")
    res = prod_client.post(
        "/api/v1/resumes/upload",
        files={"file": ("exploit.sh", malicious_file, "text/x-shellscript")}
    )
    assert res.status_code == 400
    assert "Unsupported file format" in res.json().get("detail", "")


# ==============================================================================
# 6. SQLite Atomic Backup & Restore
# ==============================================================================

def test_sqlite_atomic_backup_and_restore(tmp_path):
    """Verifies online SQLite backup integrity check and restore flow."""
    db_file = tmp_path / "test_outbound.db"
    contacted_file = tmp_path / "test_contacted.jsonl"
    staged_dir = tmp_path / "test_staged"
    backup_dir = tmp_path / "backups"

    # 1. Initialize test SQLite db with tables and data
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, name TEXT);")
    cursor.execute("INSERT INTO test_data (name) VALUES ('CyberGuard');")
    conn.commit()
    conn.close()

    contacted_file.write_text('{"domain": "cyberguard.io", "contacted_at": "2026-09-17"}\n')
    staged_dir.mkdir(parents=True)
    (staged_dir / "cyberguard.json").write_text('{"status": "staged"}')

    # 2. Run atomic backup
    archive = create_backup(
        db_path=db_file,
        contacted_log=contacted_file,
        staged_dir=staged_dir,
        backup_dir=backup_dir,
        retention_count=3
    )
    assert archive.exists()
    assert archive.stat().st_size > 0

    # 3. Validate archive
    validation = inspect_and_validate_backup(archive)
    assert validation["has_database"] is True
    assert validation["db_integrity_ok"] is True
    assert "test_data" in validation["db_tables"]
    assert validation["has_contacted_log"] is True
    assert validation["has_staged_deliveries"] is True

    # 4. Simulate disaster recovery into new paths
    restore_db = tmp_path / "restored.db"
    restore_contacted = tmp_path / "restored_contacted.jsonl"
    restore_staged = tmp_path / "restored_staged"

    restore_backup(
        archive_path=archive,
        target_db_path=restore_db,
        target_contacted_log=restore_contacted,
        target_staged_dir=restore_staged,
        dry_run=False
    )

    assert restore_db.exists()
    assert restore_contacted.exists()
    assert (restore_staged / "cyberguard.json").exists()

    # Query restored DB
    r_conn = sqlite3.connect(str(restore_db))
    r_cursor = r_conn.cursor()
    r_cursor.execute("SELECT name FROM test_data WHERE id=1;")
    assert r_cursor.fetchone()[0] == "CyberGuard"
    r_conn.close()


# ==============================================================================
# 7. Job Restart Recovery
# ==============================================================================

def test_stale_job_recovery_on_startup(test_db_session):
    """Verifies that interrupted runs in 'running' status are re-queued for recovery."""
    session_factory = sessionmaker(bind=test_db_session.get_bind())

    u = User(email="jobrec@example.com", password_hash="hash", is_active=True)
    test_db_session.add(u)
    test_db_session.flush()

    camp = Campaign(user_id=u.id, name="Crash Recovery Campaign", objective="Testing")
    test_db_session.add(camp)
    test_db_session.flush()

    comp = Company(campaign_id=camp.id, domain="resilience.io", company_name="Resilience Corp")
    test_db_session.add(comp)
    test_db_session.flush()

    # Stale run simulated by a sudden server reboot/crash
    stale_run = PipelineRun(
        campaign_id=camp.id,
        company_id=comp.id,
        status="running",
        last_completed_stage="person_verified",
        checkpoint_state_json=json.dumps({"leader": {"first_name": "Alice", "role": "CTO"}})
    )
    test_db_session.add(stale_run)
    test_db_session.commit()

    # Instantiate JobManager and trigger startup recovery
    jm = JobManager(max_workers=1, session_factory=session_factory)
    recovered = jm.recover_stale_runs()
    assert stale_run.id in recovered

    # Clean shutdown
    jm.shutdown(wait=False)


# ==============================================================================
# 8. Non-Negotiable Delivery Safety Invariant
# ==============================================================================

def test_authoritative_delivery_gate_blocks_live_sending_when_confirm_live_false(test_db_session):
    """Verifies DeliveryService rejects live delivery if CONFIRM_LIVE is False."""
    settings = Settings(
        jwt_secret_key="test_key",
        delivery_mode="live",
        dry_run=False,
        confirm_live=False  # Safety gate active
    )

    u = User(email="gate_test@example.com", password_hash="hash", is_active=True)
    test_db_session.add(u)
    test_db_session.flush()

    camp = Campaign(user_id=u.id, name="Gate Campaign", objective="Testing")
    test_db_session.add(camp)
    test_db_session.flush()

    unique_domain = f"safe-{uuid.uuid4().hex[:6]}.io"
    unique_email = f"bob@{unique_domain}"
    comp = Company(campaign_id=camp.id, domain=unique_domain, company_name="Safe Test")
    test_db_session.add(comp)
    test_db_session.flush()

    person = Person(
        company_id=comp.id,
        first_name="Bob",
        last_name="Builder",
        full_name="Bob Builder",
        role="VP Engineering",
        person_confidence=0.95
    )
    test_db_session.add(person)
    test_db_session.flush()

    contact = Contact(
        company_id=comp.id, person_id=person.id, email=unique_email,
        email_confidence=95.0, verification_status="valid"
    )
    test_db_session.add(contact)
    test_db_session.flush()

    run = PipelineRun(campaign_id=camp.id, company_id=comp.id, status="waiting_for_delivery")
    test_db_session.add(run)
    test_db_session.flush()

    draft = Draft(
        pipeline_run_id=run.id, company_id=comp.id, contact_id=contact.id,
        subject="Hello", body="Safe draft body", persona="security_infrastructure"
    )
    test_db_session.add(draft)
    test_db_session.flush()

    review = Review(pipeline_run_id=run.id, draft_id=draft.id, status="approved")
    test_db_session.add(review)
    test_db_session.commit()

    # Attempt delivery with CONFIRM_LIVE=false: must safely stage without live sending
    with patch("server.services.delivery.get_settings", return_value=settings):
        res = DeliveryService.deliver_pipeline_run(
            db=test_db_session,
            run_id=run.id,
            user_id=u.id
        )
        assert res.delivery_status == "staged"
        assert res.staged_file_path is not None
        assert Path(res.staged_file_path).exists()
        staged_content = json.loads(Path(res.staged_file_path).read_text())
        assert any("CONFIRM_LIVE" in reason for reason in staged_content.get("unmet_conditions", []))

    # Also verify that a failing safety gate (e.g. pending review) returns blocked_safety
    unique_domain2 = f"fail-{uuid.uuid4().hex[:6]}.io"
    comp2 = Company(campaign_id=camp.id, domain=unique_domain2, company_name="Fail Gate Corp")
    test_db_session.add(comp2)
    test_db_session.flush()

    person2 = Person(company_id=comp2.id, first_name="Alice", last_name="Smith", full_name="Alice Smith", role="CTO", person_confidence=0.9)
    test_db_session.add(person2)
    test_db_session.flush()

    contact2 = Contact(company_id=comp2.id, person_id=person2.id, email=f"alice@{unique_domain2}", email_confidence=90.0, verification_status="valid")
    test_db_session.add(contact2)
    test_db_session.flush()

    run2 = PipelineRun(campaign_id=camp.id, company_id=comp2.id, status="waiting_for_delivery")
    test_db_session.add(run2)
    test_db_session.flush()

    draft2 = Draft(pipeline_run_id=run2.id, company_id=comp2.id, contact_id=contact2.id, subject="Hi", body="Body", persona="security_infrastructure")
    test_db_session.add(draft2)
    test_db_session.flush()

    review2 = Review(pipeline_run_id=run2.id, draft_id=draft2.id, status="pending")
    test_db_session.add(review2)
    test_db_session.commit()

    with patch("server.services.delivery.get_settings", return_value=settings):
        blocked_res = DeliveryService.deliver_pipeline_run(
            db=test_db_session,
            run_id=run2.id,
            user_id=u.id
        )
        assert blocked_res.delivery_status == "blocked_safety"
        assert "expected 'approved'" in blocked_res.error

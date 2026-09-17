"""
Exhaustive Unit and Integration Safety Tests for Phase 8:
Authoritative Delivery Safety, Staging & Live Send.

Verifies:
1. Approval Decoupling: POST /api/v1/review/{id}/approve never calls external provider.
2. State Eligibility Gate: Only 'waiting_for_delivery' can be delivered; all others blocked.
3. Review Association Gate: Unapproved or foreign reviews blocked.
4. Draft Integrity Gate: Missing or empty draft blocked; approved edits preserved.
5. Email Syntax Gate: RFC syntax enforcement; invalid/missing emails blocked.
6. Blacklist & Anti-Fabrication Gate: alex.morgan@, placeholder@, synthetic@, and blacklisted domains blocked.
7. Verification Status Gate: unverified/invalid blocked; accept_all requires ALLOW_ACCEPT_ALL=True.
8. Person Confidence Gate: 0.69 blocked, 0.70 allowed, 0.71 allowed, None blocked.
9. Deduplication Union Gate: JSONL + DB Delivery (staged/sent) + Company contacted blocks duplicate.
10. Volume Caps Gate: 10/day and 50/week unified limits enforced.
11. Staging / Dry-Run Safety: DRY_RUN=True, DELIVERY_MODE!=live, CONFIRM_LIVE=False guarantee 0 external provider calls.
12. Live Send Dispatch: All gates passing in live mode executes provider once and persists sent status.
13. Provider Failure Handling: Provider exceptions or rejection mark delivery failed; never mark sent prematurely.
14. Concurrency & Race-Safety: Concurrent deliveries for same run produce 1 execution, 0 duplicate sends.
15. Tenant Isolation: User 2 cannot deliver User 1's runs (IDOR protected).
16. Secret Hygiene: Delivery responses, DB records, and events never expose provider keys or tokens.
17. Background Worker Integration: JobManager.submit_delivery executes delivery asynchronously.
18. Startup Recovery Invariant: Server startup recovery never auto-delivers waiting_for_delivery runs.
"""
import os
import json
import pytest
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from server.models.base import Base
from server.models.entities import (
    User,
    Campaign,
    Company,
    PipelineRun,
    Person,
    Contact,
    Draft,
    Review,
    Delivery,
    PipelineEvent,
    utc_now,
)
from server.database import create_db_engine, get_db
from server.config import Settings, get_settings
from server.app import create_app
from server.services.auth import AuthService, ACCESS_TOKEN_COOKIE_NAME
from server.services.delivery import DeliveryService
from server.services.job_manager import JobManager
from pipeline.adapters.base import DeliveryAdapter


class MockTestDeliveryAdapter(DeliveryAdapter):
    """Test mock provider tracking calls and payloads with configurable behavior."""
    def __init__(self, should_fail: bool = False, fail_error: str = "Simulated provider failure"):
        self.call_count = 0
        self.calls = []
        self.should_fail = should_fail
        self.fail_error = fail_error

    def deliver(self, payload, dry_run=True, confirm_live=False, review_status=None):
        self.call_count += 1
        self.calls.append({
            "payload": payload,
            "dry_run": dry_run,
            "confirm_live": confirm_live,
            "review_status": review_status,
        })
        if self.should_fail:
            return {"status": "failed", "error": self.fail_error}
        return {"status": "sent", "http_status": 200, "response": '{"message": "lead_added"}'}


@pytest.fixture
def delivery_ctx(tmp_path, monkeypatch):
    """Provides isolated DB, sessionmaker, TestClients for 2 distinct users, and delivery seed helper."""
    test_db_file = tmp_path / "test_delivery.db"
    test_db_url = f"sqlite:///{test_db_file}"
    engine = create_db_engine(db_url=test_db_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    # Isolated contacted log and staged deliveries
    test_log_file = tmp_path / "test_contacted.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log_file))
    monkeypatch.setenv("JWT_SECRET_KEY", "super-secret-key-for-phase-8-delivery-testing-min-32-chars")
    get_settings.cache_clear()

    # Reset JobManager singleton to use test session factory
    JobManager.get_instance(max_workers=2, session_factory=TestingSessionLocal, reset=True)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    settings = Settings(
        jwt_secret_key="super-secret-key-for-phase-8-delivery-testing-min-32-chars",
        cors_allowed_origins=["https://work.raghavpathak.me", "http://localhost"],
        delivery_mode="staged",
        dry_run=True,
        confirm_live=False,
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings

    # Seed 2 distinct operators
    session = TestingSessionLocal()
    u1 = User(email="operator1@example.com", password_hash=AuthService.hash_password("Password123!"), is_active=True)
    u2 = User(email="operator2@example.com", password_hash=AuthService.hash_password("Password123!"), is_active=True)
    session.add_all([u1, u2])
    session.commit()

    u1_id = u1.id
    u2_id = u2.id
    session.close()

    client1 = TestClient(app, raise_server_exceptions=False)
    t1, _, _ = AuthService.create_access_token(u1_id, "operator1@example.com", settings.jwt_secret_key)
    client1.cookies.set(ACCESS_TOKEN_COOKIE_NAME, t1)

    client2 = TestClient(app, raise_server_exceptions=False)
    t2, _, _ = AuthService.create_access_token(u2_id, "operator2@example.com", settings.jwt_secret_key)
    client2.cookies.set(ACCESS_TOKEN_COOKIE_NAME, t2)

    def seed_delivery_run(
        user_id=u1_id,
        company_name=None,
        domain=None,
        email=None,
        review_status="approved",
        run_status="waiting_for_delivery",
        person_confidence=0.90,
        verification_status="valid",
        draft_subject=None,
        draft_body=None,
        selection_status="selected",
    ):
        import uuid
        unique_suffix = uuid.uuid4().hex[:8]
        comp_name = company_name if company_name is not None else f"SecureTech Labs {unique_suffix}"
        dom = domain if domain is not None else f"securetech-{unique_suffix}.io"

        s = TestingSessionLocal()
        camp = Campaign(user_id=user_id, name="Security Q3", objective="Recruiting")
        s.add(camp)
        s.commit()

        comp = Company(
            campaign_id=camp.id,
            company_name=comp_name,
            domain=dom,
            industry="Security",
            stage="Series A",
            size=30,
            location="SF, CA",
            match_score=95,
            selection_status=selection_status,
        )
        s.add(comp)
        s.commit()

        recipient_email = email if email is not None else f"leader@{dom}"

        person = Person(
            company_id=comp.id,
            first_name="Rohan",
            last_name="Verma",
            full_name="Rohan Verma",
            role="VP of Engineering",
            person_confidence=person_confidence,
        )
        contact = Contact(
            company_id=comp.id,
            email=recipient_email,
            email_confidence=0.95,
            verification_status=verification_status,
            provider="hunter",
        )
        s.add_all([person, contact])
        s.commit()

        run = PipelineRun(
            campaign_id=camp.id,
            company_id=comp.id,
            status=run_status,
            last_completed_stage="review_approved" if review_status == "approved" else "draft_generated",
            started_at=utc_now(),
        )
        s.add(run)
        s.commit()

        draft = Draft(
            pipeline_run_id=run.id,
            company_id=comp.id,
            contact_id=contact.id,
            subject=draft_subject if draft_subject is not None else f"Leadership at {company_name}",
            body=draft_body if draft_body is not None else "Hi Rohan,\n\nI was impressed by your platform.",
            persona="security",
        )
        s.add(draft)
        s.commit()

        review = Review(
            pipeline_run_id=run.id,
            draft_id=draft.id,
            status=review_status,
            reviewed_at=utc_now() if review_status in ["approved", "rejected"] else None,
        )
        s.add(review)
        s.commit()

        # Capture IDs before closing session
        run_id = str(run.id)
        review_id = str(review.id)
        comp_id = str(comp.id)
        camp_id = str(camp.id)
        contact_id = str(contact.id)
        draft_id = str(draft.id)
        s.close()

        res_dict = {
            "campaign": camp,
            "company": comp,
            "person": person,
            "contact": contact,
            "run": run,
            "draft": draft,
            "review": review,
            "user_id": user_id,
            "run_id": run_id,
            "review_id": review_id,
            "company_id": comp_id,
            "campaign_id": camp_id,
            "contact_id": contact_id,
            "draft_id": draft_id,
        }
        return res_dict

    yield {
        "db": TestingSessionLocal,
        "engine": engine,
        "client1": client1,
        "client2": client2,
        "u1_id": u1_id,
        "u2_id": u2_id,
        "seed_delivery_run": seed_delivery_run,
        "test_log_file": test_log_file,
    }

    JobManager.get_instance().shutdown(wait=False)


# =====================================================================
# 1. Approval Decoupling Test
# =====================================================================

def test_approval_decoupling_does_not_call_provider(delivery_ctx):
    """
    CRITICAL INVARIANT: POST /api/v1/review/{id}/approve transitions to 'waiting_for_delivery'
    and NEVER calls external delivery provider or stages deliveries.
    """
    seed = delivery_ctx["seed_delivery_run"](review_status="pending", run_status="waiting_for_review")
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/review/{seed['review'].id}/approve")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "approved"
        assert data["run"]["status"] == "waiting_for_delivery"

        # Zero provider calls
        assert mock_adapter.call_count == 0

        # Zero DB Delivery records created
        db = delivery_ctx["db"]()
        deliv = db.execute(select(Delivery).where(Delivery.pipeline_run_id == seed["run"].id)).scalar_one_or_none()
        assert deliv is None
        db.close()


# =====================================================================
# 2. State Eligibility Gate Tests
# =====================================================================

@pytest.mark.parametrize("invalid_status", [
    "queued", "running", "waiting_for_review", "completed", "skipped", "failed"
])
def test_delivery_blocked_for_ineligible_run_statuses(delivery_ctx, invalid_status):
    """Only 'waiting_for_delivery' status is eligible for delivery attempt."""
    seed = delivery_ctx["seed_delivery_run"](run_status=invalid_status)
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.status_code == 200
        data = res.json()
        assert data["delivery_status"] == "blocked_safety"
        assert "expected 'waiting_for_delivery'" in data["error"]
        assert mock_adapter.call_count == 0


# =====================================================================
# 3. Review Association & Approval Gate Tests
# =====================================================================

def test_delivery_blocked_if_review_not_approved(delivery_ctx):
    """Delivery is blocked if associated Review is pending or rejected."""
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        # 1. Pending review
        seed_pending = delivery_ctx["seed_delivery_run"](review_status="pending")
        res_pen = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_pending['run'].id}")
        assert res_pen.status_code == 200
        assert res_pen.json()["delivery_status"] == "blocked_safety"
        assert "expected 'approved'" in res_pen.json()["error"]
        assert mock_adapter.call_count == 0

        # 2. Rejected review
        seed_rej = delivery_ctx["seed_delivery_run"](review_status="rejected")
        res_rej = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_rej['run'].id}")
        assert res_rej.status_code == 200
        assert res_rej.json()["delivery_status"] == "blocked_safety"
        assert mock_adapter.call_count == 0


# =====================================================================
# 4. Draft Integrity Gate Tests
# =====================================================================

def test_delivery_blocked_on_empty_or_missing_draft(delivery_ctx):
    """Delivery requires non-empty draft subject and body."""
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        # Empty subject
        seed_empty_subj = delivery_ctx["seed_delivery_run"](draft_subject="")
        res1 = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_empty_subj['run'].id}")
        assert res1.json()["delivery_status"] == "blocked_safety"
        assert "subject is empty" in res1.json()["error"]
        assert mock_adapter.call_count == 0

        # Empty body
        seed_empty_body = delivery_ctx["seed_delivery_run"](draft_body="")
        res2 = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_empty_body['run'].id}")
        assert res2.json()["delivery_status"] == "blocked_safety"
        assert "body is empty" in res2.json()["error"]
        assert mock_adapter.call_count == 0


# =====================================================================
# 5. Email Syntax Gate Tests
# =====================================================================

@pytest.mark.parametrize("invalid_email", [
    "not-an-email",
    "user@",
    "@domain.com",
    "user space@domain.com",
    "",
    "user@domain..com",
])
def test_delivery_blocked_on_invalid_email_syntax(delivery_ctx, invalid_email):
    """Delivery validates final recipient RFC email syntax."""
    seed = delivery_ctx["seed_delivery_run"](email=invalid_email)
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.json()["delivery_status"] == "blocked_safety"
        assert mock_adapter.call_count == 0


# =====================================================================
# 6. Blacklist & Anti-Fabrication Gate Tests
# =====================================================================

@pytest.mark.parametrize("blacklisted_email", [
    "alex.morgan@company.com",
    "placeholder@company.com",
    "synthetic@company.com",
    "ALEX.MORGAN@company.com",  # Case-insensitive
    "alex.morgan.lead@company.com",
])
def test_delivery_blocked_on_synthetic_and_blacklisted_emails(delivery_ctx, blacklisted_email):
    """Rejects anti-fabrication patterns and synthetic placeholder leads."""
    seed = delivery_ctx["seed_delivery_run"](email=blacklisted_email)
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.json()["delivery_status"] == "blocked_safety"
        assert "blacklisted" in res.json()["error"].lower() or "synthetic" in res.json()["error"].lower()
        assert mock_adapter.call_count == 0


def test_delivery_blocked_on_blacklisted_domain(delivery_ctx, monkeypatch):
    """Rejects configured blacklisted domain."""
    monkeypatch.setenv("BLACKLISTED_DOMAINS", "blockeddomain.io,competitor.com")
    seed = delivery_ctx["seed_delivery_run"](domain="blockeddomain.io", email="lead@blockeddomain.io")
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.json()["delivery_status"] == "blocked_safety"
        assert mock_adapter.call_count == 0


# =====================================================================
# 7. Email Verification Status Gate Tests
# =====================================================================

@pytest.mark.parametrize("bad_status", [
    "unverified", "invalid", "low_confidence", "not_found", "provider_error"
])
def test_delivery_blocked_on_unverified_email_status(delivery_ctx, bad_status):
    """Rejects any unverified, invalid, or low-confidence email verification state."""
    seed = delivery_ctx["seed_delivery_run"](verification_status=bad_status)
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.json()["delivery_status"] == "blocked_safety"
        assert bad_status in res.json()["error"]
        assert mock_adapter.call_count == 0


def test_delivery_catch_all_policy(delivery_ctx, monkeypatch):
    """Tests accept_all behavior controlled by ALLOW_ACCEPT_ALL."""
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        # 1. When ALLOW_ACCEPT_ALL=False -> blocked
        monkeypatch.setenv("ALLOW_ACCEPT_ALL", "false")
        seed1 = delivery_ctx["seed_delivery_run"](verification_status="accept_all")
        res1 = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed1['run'].id}")
        assert res1.json()["delivery_status"] == "blocked_safety"
        assert "accept_all" in res1.json()["error"]
        assert mock_adapter.call_count == 0

        # 2. When ALLOW_ACCEPT_ALL=True -> allowed to proceed to staging
        monkeypatch.setenv("ALLOW_ACCEPT_ALL", "true")
        seed2 = delivery_ctx["seed_delivery_run"](verification_status="accept_all")
        res2 = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed2['run'].id}")
        assert res2.json()["delivery_status"] == "staged"


# =====================================================================
# 8. Person Confidence Threshold Gate Tests (>= 0.70)
# =====================================================================

def test_delivery_person_confidence_threshold(delivery_ctx):
    """Validates strict person confidence threshold (0.69 blocked, 0.70 allowed, 0.71 allowed, None blocked)."""
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        # 0.69 -> blocked
        seed_low = delivery_ctx["seed_delivery_run"](person_confidence=0.69)
        res_low = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_low['run'].id}")
        assert res_low.json()["delivery_status"] == "blocked_safety"
        assert "below minimum threshold" in res_low.json()["error"]
        assert mock_adapter.call_count == 0

        # None -> blocked
        seed_none = delivery_ctx["seed_delivery_run"](person_confidence=None)
        res_none = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_none['run'].id}")
        assert res_none.json()["delivery_status"] == "blocked_safety"
        assert mock_adapter.call_count == 0

        # 0.70 -> allowed (staged)
        seed_boundary = delivery_ctx["seed_delivery_run"](person_confidence=0.70)
        res_boundary = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_boundary['run'].id}")
        assert res_boundary.json()["delivery_status"] == "staged"

        # 0.71 -> allowed (staged)
        seed_high = delivery_ctx["seed_delivery_run"](person_confidence=0.71)
        res_high = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_high['run'].id}")
        assert res_high.json()["delivery_status"] == "staged"


# =====================================================================
# 9. Deduplication Union Gate Tests
# =====================================================================

def test_delivery_dedupe_union_jsonl_source(delivery_ctx):
    """Blocks delivery if domain or email already exists in contacted_companies.jsonl."""
    from pipeline.contacted_log import record_contacted

    record_contacted(
        domain="priorcontacted.com",
        contact_email="prior@priorcontacted.com",
        delivery_status="sent",
        log_file=str(delivery_ctx["test_log_file"])
    )

    seed = delivery_ctx["seed_delivery_run"](domain="priorcontacted.com", email="prior@priorcontacted.com")
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.json()["delivery_status"] == "blocked_safety"
        assert "previously contacted in CLI history" in res.json()["error"]
        assert mock_adapter.call_count == 0


def test_delivery_dedupe_union_company_selection_status(delivery_ctx):
    """Blocks delivery if Company.selection_status is already 'contacted'."""
    seed = delivery_ctx["seed_delivery_run"](selection_status="contacted")
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.json()["delivery_status"] == "blocked_safety"
        assert "already marked as contacted" in res.json()["error"]
        assert mock_adapter.call_count == 0


# =====================================================================
# 10. Volume Caps Gate Tests (10/day, 50/week)
# =====================================================================

def test_delivery_daily_volume_cap_enforcement(delivery_ctx, monkeypatch):
    """Enforces daily cap: 10 allowed, 11th blocked."""
    monkeypatch.setenv("MAX_SENDS_PER_DAY", "10")
    db = delivery_ctx["db"]()

    # Pre-populate 10 delivery records in DB
    for i in range(10):
        camp = Campaign(user_id=delivery_ctx["u1_id"], name=f"Cap Camp {i}", objective="Cap Test")
        db.add(camp)
        db.flush()
        comp = Company(campaign_id=camp.id, company_name=f"Cap Comp {i}", domain=f"cap{i}.io", selection_status="contacted")
        db.add(comp)
        db.flush()
        run = PipelineRun(campaign_id=camp.id, company_id=comp.id, status="completed")
        db.add(run)
        db.flush()
        deliv = Delivery(
            pipeline_run_id=run.id,
            company_id=comp.id,
            delivery_mode="staged",
            delivery_status="staged",
            provider="instantly",
            delivered_at=utc_now()
        )
        db.add(deliv)
    db.commit()
    db.close()

    # 11th delivery attempt
    seed_11 = delivery_ctx["seed_delivery_run"](domain="eleventhcompany.io")
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_11['run'].id}")
        assert res.json()["delivery_status"] == "blocked_safety"
        assert "Daily volume cap exceeded" in res.json()["error"]
        assert mock_adapter.call_count == 0


def test_delivery_weekly_volume_cap_enforcement(delivery_ctx, monkeypatch):
    """Enforces weekly cap: 50 allowed, 51st blocked."""
    monkeypatch.setenv("MAX_SENDS_PER_DAY", "100")  # Avoid tripping daily cap
    monkeypatch.setenv("MAX_SENDS_PER_WEEK", "50")
    db = delivery_ctx["db"]()

    # Pre-populate 50 delivery records spread across the week
    for i in range(50):
        camp = Campaign(user_id=delivery_ctx["u1_id"], name=f"Week Camp {i}", objective="Cap Test")
        db.add(camp)
        db.flush()
        comp = Company(campaign_id=camp.id, company_name=f"Week Comp {i}", domain=f"weekcap{i}.io", selection_status="contacted")
        db.add(comp)
        db.flush()
        run = PipelineRun(campaign_id=camp.id, company_id=comp.id, status="completed")
        db.add(run)
        db.flush()
        deliv = Delivery(
            pipeline_run_id=run.id,
            company_id=comp.id,
            delivery_mode="staged",
            delivery_status="staged",
            provider="instantly",
            delivered_at=utc_now() - timedelta(hours=i * 2 + 1)
        )
        db.add(deliv)
    db.commit()
    db.close()

    # 51st delivery attempt
    seed_51 = delivery_ctx["seed_delivery_run"](domain="fiftyfirstcompany.io")
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed_51['run'].id}")
        assert res.json()["delivery_status"] == "blocked_safety"
        assert "Weekly volume cap exceeded" in res.json()["error"]
        assert mock_adapter.call_count == 0


# =====================================================================
# 11. Staging & Dry-Run Safety Tests (Triple-Key Guard)
# =====================================================================

@pytest.mark.parametrize("deliv_mode,dry_run,confirm_live", [
    ("stub", "false", "true"),
    ("staged", "false", "true"),
    ("live", "true", "true"),      # Blocked by DRY_RUN=true
    ("live", "false", "false"),    # Blocked by CONFIRM_LIVE=false
])
def test_staging_safety_gate_zero_provider_calls(delivery_ctx, monkeypatch, deliv_mode, dry_run, confirm_live):
    """
    If ANY of the 3 live gates is not satisfied, delivery is staged to disk with ZERO external provider calls.
    """
    monkeypatch.setenv("DELIVERY_MODE", deliv_mode)
    monkeypatch.setenv("DRY_RUN", dry_run)
    monkeypatch.setenv("CONFIRM_LIVE", confirm_live)

    seed = delivery_ctx["seed_delivery_run"](domain=f"stage-{deliv_mode}-{dry_run}.com")
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.status_code == 200
        data = res.json()
        assert data["delivery_status"] == "staged"
        assert data["staged_file_path"] is not None
        assert os.path.exists(data["staged_file_path"])

        # Zero external provider calls
        assert mock_adapter.call_count == 0

        # DB PipelineRun is completed with delivery_staged
        db = delivery_ctx["db"]()
        run = db.execute(select(PipelineRun).where(PipelineRun.id == seed["run"].id)).scalar_one()
        assert run.status == "completed"
        assert run.last_completed_stage == "delivery_staged"
        db.close()


# =====================================================================
# 12. Live Send Dispatch Test
# =====================================================================

def test_live_send_dispatch_when_all_gates_pass(delivery_ctx, monkeypatch):
    """
    When all 11 gates are satisfied and live mode is activated, provider is called exactly once
    and status is persisted as sent.
    """
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")

    seed = delivery_ctx["seed_delivery_run"](domain="livesend.io", email="lead@livesend.io")
    mock_adapter = MockTestDeliveryAdapter(should_fail=False)

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.status_code == 200
        data = res.json()
        assert data["delivery_status"] == "sent"

        # Exactly 1 provider call
        assert mock_adapter.call_count == 1
        call_info = mock_adapter.calls[0]
        assert call_info["payload"]["recipient"]["email"] == "lead@livesend.io"
        assert call_info["dry_run"] is False
        assert call_info["confirm_live"] is True

        # DB PipelineRun completed as delivery_sent
        db = delivery_ctx["db"]()
        run = db.execute(select(PipelineRun).where(PipelineRun.id == seed["run"].id)).scalar_one()
        assert run.status == "completed"
        assert run.last_completed_stage == "delivery_sent"

        # Event emitted
        events = list(db.execute(select(PipelineEvent).where(PipelineEvent.pipeline_run_id == run.id)).scalars().all())
        event_types = [e.event_type for e in events]
        assert "delivery_attempted" in event_types
        assert "delivery_sent" in event_types
        db.close()


# =====================================================================
# 13. Provider Failure Handling Tests
# =====================================================================

def test_provider_failure_does_not_mark_sent(delivery_ctx, monkeypatch):
    """
    When external provider fails or throws, delivery status is 'failed',
    PipelineRun is 'failed', and it is NEVER marked sent.
    """
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")

    seed = delivery_ctx["seed_delivery_run"](domain="failtest.io")
    mock_adapter = MockTestDeliveryAdapter(should_fail=True, fail_error="Instantly 503 Service Unavailable")

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        assert res.status_code == 200
        data = res.json()
        assert data["delivery_status"] == "failed"
        assert "Instantly 503" in data["error"]

        db = delivery_ctx["db"]()
        run = db.execute(select(PipelineRun).where(PipelineRun.id == seed["run"].id)).scalar_one()
        assert run.status == "failed"
        assert "Instantly 503" in run.error_message

        # Delivery row status is failed
        deliv = db.execute(select(Delivery).where(Delivery.pipeline_run_id == run.id)).scalar_one()
        assert deliv.delivery_status == "failed"
        db.close()


# =====================================================================
# 14. Concurrency & Race Safety Test
# =====================================================================

def test_concurrent_delivery_attempts_single_execution(delivery_ctx, monkeypatch):
    """
    Simultaneous delivery requests for the same run execute only once;
    the second is recognized as duplicate/completed without duplicate provider calls.
    """
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")

    seed = delivery_ctx["seed_delivery_run"](domain="racecondition.io")
    mock_adapter = MockTestDeliveryAdapter(should_fail=False)

    results = []

    def dispatch():
        with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
            r = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
            results.append(r)

    t1 = threading.Thread(target=dispatch)
    t2 = threading.Thread(target=dispatch)

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    # Provider called at most once
    assert mock_adapter.call_count == 1
    assert len(results) == 2
    assert all(r.status_code == 200 for r in results)


# =====================================================================
# 15. Tenant Isolation Test (IDOR Prevention)
# =====================================================================

def test_tenant_isolation_idor_prevention(delivery_ctx):
    """User 2 cannot deliver a run belonging to User 1."""
    seed_u1 = delivery_ctx["seed_delivery_run"](user_id=delivery_ctx["u1_id"])
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client2"].post(f"/api/v1/deliveries/{seed_u1['run'].id}")
        assert res.status_code == 404
        assert mock_adapter.call_count == 0


# =====================================================================
# 16. Secret Hygiene Test
# =====================================================================

def test_secret_hygiene_in_delivery_and_events(delivery_ctx, monkeypatch):
    """Ensures responses, DB fields, and events never leak provider API keys."""
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")

    seed = delivery_ctx["seed_delivery_run"](domain="secrets.io")
    mock_adapter = MockTestDeliveryAdapter(should_fail=True, fail_error="Error with API_KEY=inst_secret_token_123456789")

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        res = delivery_ctx["client1"].post(f"/api/v1/deliveries/{seed['run'].id}")
        data = res.json()
        assert "inst_secret_token" not in json.dumps(data)

        db = delivery_ctx["db"]()
        deliv = db.execute(select(Delivery).where(Delivery.pipeline_run_id == seed["run"].id)).scalar_one()
        assert "inst_secret_token" not in (deliv.webhook_response_json or "")
        events = list(db.execute(select(PipelineEvent).where(PipelineEvent.pipeline_run_id == seed["run"].id)).scalars().all())
        for e in events:
            assert "inst_secret_token" not in e.message
            assert "inst_secret_token" not in (e.data_json or "")
        db.close()


# =====================================================================
# 17. Background Worker Integration Test
# =====================================================================

def test_background_worker_submit_delivery(delivery_ctx):
    """JobManager.submit_delivery executes delivery asynchronously."""
    seed = delivery_ctx["seed_delivery_run"](domain="worker-test.io")
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        future = JobManager.get_instance().submit_delivery(seed["run"].id)
        future.result(timeout=5)  # Wait for worker thread to finish

        db = delivery_ctx["db"]()
        deliv = db.execute(select(Delivery).where(Delivery.pipeline_run_id == seed["run"].id)).scalar_one_or_none()
        assert deliv is not None
        assert deliv.delivery_status == "staged"
        db.close()


# =====================================================================
# 18. Startup Recovery Invariant Test
# =====================================================================

def test_startup_recovery_does_not_deliver_waiting_for_delivery(delivery_ctx):
    """
    CRITICAL INVARIANT: Server restart and recover_stale_runs strictly recovers runs
    in 'running' status and NEVER triggers delivery for 'waiting_for_delivery' runs.
    """
    seed_waiting = delivery_ctx["seed_delivery_run"](run_status="waiting_for_delivery")
    mock_adapter = MockTestDeliveryAdapter()

    with patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        recovered = JobManager.get_instance().recover_stale_runs()
        assert seed_waiting["run"].id not in recovered
        assert mock_adapter.call_count == 0

        # Run remains strictly in waiting_for_delivery
        db = delivery_ctx["db"]()
        run = db.execute(select(PipelineRun).where(PipelineRun.id == seed_waiting["run"].id)).scalar_one()
        assert run.status == "waiting_for_delivery"
        deliv = db.execute(select(Delivery).where(Delivery.pipeline_run_id == run.id)).scalar_one_or_none()
        assert deliv is None
        db.close()

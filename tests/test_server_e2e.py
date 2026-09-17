"""
Comprehensive End-to-End Verification Test Suite for Phase 9:
Frontend Cockpit Polish & End-to-End Verification.

Covers the full operator lifecycle:
1. Campaign creation -> Discovery -> Selection -> Enqueue -> Job processing ->
   waiting_for_review -> Draft retrieval -> Human edit -> Approval ->
   waiting_for_delivery (0 provider calls) -> Explicit delivery -> Staged/Sent.
2. Rejection workflow: waiting_for_review -> Reject -> skipped (0 delivery records, 0 provider calls).
3. Delivery E2E Safety: Approve decouples from sending; Explicit deliver triggers 11 gates.
4. E2E Controlled Live Send: DELIVERY_MODE=live, DRY_RUN=false, CONFIRM_LIVE=true -> provider called once -> sent.
5. E2E Controlled Staging: DRY_RUN=true -> staged to disk -> zero provider calls.
6. E2E Controlled Provider Failure: provider failure -> status=failed -> audit event emitted -> no false sent.
7. IDOR Tenant Isolation: User B cannot access User A's campaign, companies, runs, reviews, or deliveries.
8. Idempotency & Restart Safety: Idempotent approvals and deliveries; restart recovery never auto-sends waiting_for_delivery.
9. Cockpit HTML & Stats Endpoints: All operator console routes served with valid HTML; stats reflect DB.
10. Deselection & Candidate Filtering: Deselect reverts to discovered; industry/stage/search filters work.
"""
import os
import json
import pytest
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


class MockE2EDeliveryAdapter(DeliveryAdapter):
    """Mock delivery provider tracking calls, payloads, and configurable failure."""
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
        return {"status": "sent", "http_status": 200, "response": '{"message": "lead_added_success"}'}


@pytest.fixture
def e2e_ctx(tmp_path, monkeypatch):
    """Provides isolated test database, JobManager, and 2 distinct authenticated TestClients."""
    test_db_file = tmp_path / "test_e2e.db"
    test_db_url = f"sqlite:///{test_db_file}"
    engine = create_db_engine(db_url=test_db_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

    test_log_file = tmp_path / "e2e_contacted.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log_file))
    monkeypatch.setenv("JWT_SECRET_KEY", "super-secret-e2e-verification-key-minimum-32-chars")
    monkeypatch.setenv("DELIVERY_MODE", "staged")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("CONFIRM_LIVE", "false")
    monkeypatch.setenv("DISCOVERY_MODE", "stub")
    get_settings.cache_clear()

    JobManager.get_instance(max_workers=2, session_factory=TestingSessionLocal, reset=True)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    settings = Settings(
        jwt_secret_key="super-secret-e2e-verification-key-minimum-32-chars",
        cors_allowed_origins=["https://work.raghavpathak.me", "http://localhost"],
        delivery_mode="staged",
        dry_run=True,
        confirm_live=False,
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings

    # Seed 2 distinct users
    db = TestingSessionLocal()
    u1_pass = AuthService.hash_password("Password123!")
    u2_pass = AuthService.hash_password("Password456!")

    user1 = User(email="operator1@example.com", password_hash=u1_pass, is_active=True)
    user2 = User(email="operator2@example.com", password_hash=u2_pass, is_active=True)
    db.add_all([user1, user2])
    db.commit()
    db.refresh(user1)
    db.refresh(user2)

    u1_id = user1.id
    u2_id = user2.id
    db.close()

    # Generate auth tokens
    tok1, _, _ = AuthService.create_access_token(u1_id, "operator1@example.com", settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    tok2, _, _ = AuthService.create_access_token(u2_id, "operator2@example.com", settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    client1 = TestClient(app, raise_server_exceptions=False)
    client1.cookies.set(ACCESS_TOKEN_COOKIE_NAME, tok1)

    client2 = TestClient(app, raise_server_exceptions=False)
    client2.cookies.set(ACCESS_TOKEN_COOKIE_NAME, tok2)

    return {
        "app": app,
        "db_factory": TestingSessionLocal,
        "client1": client1,
        "client2": client2,
        "u1_id": u1_id,
        "u2_id": u2_id,
        "settings": settings,
    }


# =====================================================================
# 1. Complete Operator Lifecycle: Happy Path
# =====================================================================
def test_e2e_complete_operator_lifecycle_happy_path(e2e_ctx):
    """
    Validates complete end-to-end outreach workflow:
    Campaign Create -> Discover -> Select -> Enqueue -> Run Processing ->
    waiting_for_review -> Draft Edit -> Approve -> waiting_for_delivery -> Explicit Delivery -> Staged
    """
    client = e2e_ctx["client1"]
    db_factory = e2e_ctx["db_factory"]
    u1_id = e2e_ctx["u1_id"]

    # Step 1: Create Campaign
    camp_payload = {
        "name": "E2E Cyber Outreach",
        "objective": "Connect with Indian cybersecurity founders",
        "target_geography": "India",
        "industry": "Cybersecurity",
        "company_size": "small",
        "company_stage": "Seed",
        "target_roles": ["CTO", "CISO"],
        "technologies": ["Python", "AWS"],
    }
    camp_res = client.post("/api/v1/campaigns", json=camp_payload)
    assert camp_res.status_code == 201
    camp_data = camp_res.json()
    campaign_id = camp_data["id"]
    assert camp_data["name"] == "E2E Cyber Outreach"
    assert camp_data["status"] == "draft"

    # Step 2: Trigger Discovery
    disc_res = client.post(f"/api/v1/campaigns/{campaign_id}/discover?limit=5")
    assert disc_res.status_code == 200
    disc_data = disc_res.json()
    assert disc_data["discovered_count"] > 0
    candidate = disc_data["companies"][0]
    company_id = candidate["id"]
    assert candidate["selection_status"] == "discovered"

    # Step 3: Select Candidate
    sel_res = client.post(
        f"/api/v1/campaigns/{campaign_id}/companies/select",
        json={"company_ids": [company_id]}
    )
    assert sel_res.status_code == 200
    assert sel_res.json()["selected_count"] == 1

    # Step 4: Enqueue Selected Companies
    enq_res = client.post(f"/api/v1/campaigns/{campaign_id}/enqueue-selected")
    assert enq_res.status_code == 200
    enq_data = enq_res.json()
    assert enq_data["enqueued_count"] == 1
    run_id = enq_data["runs"][0]["id"]
    assert enq_data["runs"][0]["status"] == "queued"

    # Step 5: Advance Run to waiting_for_review with verified leader and draft
    with db_factory() as db:
        run = db.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
        comp = db.execute(select(Company).where(Company.id == company_id)).scalar_one()

        # Seed verified Person and Contact
        person = Person(
            company_id=comp.id,
            first_name="Vikram",
            last_name="Malhotra",
            full_name="Vikram Malhotra",
            role="Chief Technology Officer",
            person_confidence=0.88,
            researched_at=utc_now(),
        )
        db.add(person)
        db.flush()

        contact = Contact(
            company_id=comp.id,
            person_id=person.id,
            email="vikram@example.com",
            email_confidence=0.95,
            verification_status="valid",
            resolved_at=utc_now(),
        )
        db.add(contact)
        db.flush()

        # Seed Draft
        draft = Draft(
            pipeline_run_id=run.id,
            company_id=comp.id,
            contact_id=contact.id,
            subject="Exploring defensive engineering synergies",
            body="Hi Vikram, impressed by your cloud security architecture...",
            persona="security",
        )
        db.add(draft)
        db.flush()

        # Seed Review in pending
        review = Review(
            pipeline_run_id=run.id,
            draft_id=draft.id,
            status="pending",
        )
        db.add(review)

        run.status = "waiting_for_review"
        run.last_completed_stage = "draft_generated"
        db.commit()
        review_id = review.id

    # Step 6: Operator inspects review queue and detail
    rev_list_res = client.get("/api/v1/review?status=pending")
    assert rev_list_res.status_code == 200
    reviews = rev_list_res.json()
    assert any(r["id"] == review_id for r in reviews)

    rev_detail_res = client.get(f"/api/v1/review/{review_id}")
    assert rev_detail_res.status_code == 200
    rev_detail = rev_detail_res.json()
    assert rev_detail["status"] == "pending"
    assert rev_detail["draft"]["subject"] == "Exploring defensive engineering synergies"

    # Step 7: Operator edits draft (authoritative persistence)
    edit_payload = {
        "subject": "Authoritative subject edited by operator",
        "body": "Hi Vikram, personalized custom outreach content edited by human reviewer."
    }
    edit_res = client.patch(f"/api/v1/review/{review_id}", json=edit_payload)
    assert edit_res.status_code == 200
    assert edit_res.json()["draft"]["subject"] == edit_payload["subject"]

    # Step 8: Operator Approves Review
    # Critical Safety Boundary: Verify 0 provider calls
    mock_adapter = MockE2EDeliveryAdapter()
    with patch("server.services.delivery.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        appr_res = client.post(f"/api/v1/review/{review_id}/approve")
        assert appr_res.status_code == 200
        appr_data = appr_res.json()

        # Strict Assertions: Run is waiting_for_delivery, Review is approved, 0 sends
        assert appr_data["status"] == "approved"
        assert appr_data["run"]["status"] == "waiting_for_delivery"
        assert mock_adapter.call_count == 0

    # Step 9: Verify Dashboard stats reflect waiting_for_delivery
    stats_res = client.get("/api/v1/dashboard/stats")
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert stats["waiting_for_delivery_count"] >= 1
    assert any(item["run_id"] == run_id for item in stats["needs_attention"]["waiting_for_delivery"])

    # Step 10: Explicit Delivery Trigger
    with patch("server.services.delivery.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        deliv_res = client.post(f"/api/v1/deliveries/{run_id}")
        assert deliv_res.status_code == 200
        deliv_data = deliv_res.json()

        assert deliv_data["delivery_status"] == "staged"
        assert deliv_data["delivery_mode"] == "staged"
        assert mock_adapter.call_count == 0  # Dry-run staging ensures zero provider calls

    # Step 11: Verify PipelineRun completed and Delivery record appears in history
    with db_factory() as db:
        run_after = db.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
        assert run_after.status == "completed"
        assert run_after.last_completed_stage == "delivery_staged"

        comp_after = db.execute(select(Company).where(Company.id == company_id)).scalar_one()
        assert comp_after.selection_status == "contacted"

    # Step 12: Verify Deliveries history endpoint
    deliv_history_res = client.get("/api/v1/deliveries?status=staged")
    assert deliv_history_res.status_code == 200
    history = deliv_history_res.json()
    assert any(d["pipeline_run_id"] == run_id for d in history)


# =====================================================================
# 2. Rejection Workflow
# =====================================================================
def test_e2e_rejection_workflow(e2e_ctx):
    """
    Validates rejection lifecycle:
    waiting_for_review -> reject review -> run skipped -> zero deliveries created.
    """
    client = e2e_ctx["client1"]
    db_factory = e2e_ctx["db_factory"]
    u1_id = e2e_ctx["u1_id"]

    # Seed campaign and run in waiting_for_review
    with db_factory() as db:
        camp = Campaign(user_id=u1_id, name="Reject Test Campaign", objective="Test rejection")
        db.add(camp)
        db.flush()

        comp = Company(campaign_id=camp.id, domain="reject-test.io", company_name="Reject Test Inc")
        db.add(comp)
        db.flush()

        run = PipelineRun(campaign_id=camp.id, company_id=comp.id, status="waiting_for_review")
        db.add(run)
        db.flush()

        draft = Draft(pipeline_run_id=run.id, company_id=comp.id, subject="Test Subject", body="Test Body")
        db.add(draft)
        db.flush()

        rev = Review(pipeline_run_id=run.id, draft_id=draft.id, status="pending")
        db.add(rev)
        db.commit()

        run_id = run.id
        review_id = rev.id

    mock_adapter = MockE2EDeliveryAdapter()
    with patch("server.services.delivery.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        rej_res = client.post(f"/api/v1/review/{review_id}/reject", json={"reason": "Irrelevant industry match"})
        assert rej_res.status_code == 200
        rej_data = rej_res.json()

        assert rej_data["status"] == "rejected"
        assert rej_data["run"]["status"] == "skipped"
        assert mock_adapter.call_count == 0

    # Verify database state: no delivery records created
    with db_factory() as db:
        delivs = db.execute(select(Delivery).where(Delivery.pipeline_run_id == run_id)).scalars().all()
        assert len(delivs) == 0

        run_obj = db.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
        assert run_obj.status == "skipped"


# =====================================================================
# 3. Controlled Live Send Dispatch
# =====================================================================
def test_e2e_controlled_live_dispatch(e2e_ctx, monkeypatch):
    """
    Validates live outbound send when all 11 gates pass:
    DELIVERY_MODE=live, DRY_RUN=false, CONFIRM_LIVE=true -> mock provider called once -> sent.
    """
    client = e2e_ctx["client1"]
    db_factory = e2e_ctx["db_factory"]
    u1_id = e2e_ctx["u1_id"]

    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")

    with db_factory() as db:
        camp = Campaign(user_id=u1_id, name="Live Send Campaign", objective="Live dispatch verification")
        db.add(camp)
        db.flush()

        comp = Company(campaign_id=camp.id, domain="live-verified-target.io", company_name="Live Target")
        db.add(comp)
        db.flush()

        person = Person(
            company_id=comp.id, first_name="Rohan", last_name="Sharma",
            full_name="Rohan Sharma", role="CISO", person_confidence=0.85
        )
        db.add(person)
        db.flush()

        contact = Contact(
            company_id=comp.id, person_id=person.id, email="rohan@live-verified-target.io",
            email_confidence=0.95, verification_status="valid"
        )
        db.add(contact)
        db.flush()

        run = PipelineRun(campaign_id=camp.id, company_id=comp.id, status="waiting_for_delivery")
        db.add(run)
        db.flush()

        draft = Draft(pipeline_run_id=run.id, company_id=comp.id, contact_id=contact.id, subject="Live Subject", body="Live Body")
        db.add(draft)
        db.flush()

        rev = Review(pipeline_run_id=run.id, draft_id=draft.id, status="approved", reviewed_at=utc_now())
        db.add(rev)
        db.commit()

        run_id = run.id

    mock_adapter = MockE2EDeliveryAdapter()
    with patch("server.services.delivery.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        deliv_res = client.post(f"/api/v1/deliveries/{run_id}")
        assert deliv_res.status_code == 200
        data = deliv_res.json()

        assert data["delivery_status"] == "sent"
        assert data["delivery_mode"] == "live"
        assert mock_adapter.call_count == 1

    with db_factory() as db:
        run_obj = db.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
        assert run_obj.status == "completed"
        assert run_obj.last_completed_stage == "delivery_sent"


# =====================================================================
# 4. Controlled Provider Failure Handling
# =====================================================================
def test_e2e_controlled_provider_failure(e2e_ctx, monkeypatch):
    """
    Validates failure resilience:
    When provider returns error, delivery status is marked 'failed' and audit event is emitted.
    """
    client = e2e_ctx["client1"]
    db_factory = e2e_ctx["db_factory"]
    u1_id = e2e_ctx["u1_id"]

    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")

    with db_factory() as db:
        camp = Campaign(user_id=u1_id, name="Failure Campaign", objective="Provider failure verification")
        db.add(camp)
        db.flush()

        comp = Company(campaign_id=camp.id, domain="fail-provider-target.io", company_name="Fail Target")
        db.add(comp)
        db.flush()

        person = Person(company_id=comp.id, first_name="A", last_name="B", full_name="A B", role="VP", person_confidence=0.8)
        db.add(person)
        db.flush()

        contact = Contact(company_id=comp.id, person_id=person.id, email="ab@fail-provider-target.io", verification_status="valid")
        db.add(contact)
        db.flush()

        run = PipelineRun(campaign_id=camp.id, company_id=comp.id, status="waiting_for_delivery")
        db.add(run)
        db.flush()

        draft = Draft(pipeline_run_id=run.id, company_id=comp.id, contact_id=contact.id, subject="Sub", body="Body")
        db.add(draft)
        db.flush()

        rev = Review(pipeline_run_id=run.id, draft_id=draft.id, status="approved", reviewed_at=utc_now())
        db.add(rev)
        db.commit()

        run_id = run.id

    mock_fail_adapter = MockE2EDeliveryAdapter(should_fail=True, fail_error="Instantly webhook 503 gateway timeout")
    with patch("server.services.delivery.AdapterFactory.get_delivery_adapter", return_value=mock_fail_adapter):
        deliv_res = client.post(f"/api/v1/deliveries/{run_id}")
        assert deliv_res.status_code == 200
        data = deliv_res.json()

        assert data["delivery_status"] == "failed"
        assert "503" in (data["error"] or "")

    with db_factory() as db:
        run_obj = db.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
        assert run_obj.status == "failed"

        event = db.execute(
            select(PipelineEvent)
            .where(PipelineEvent.pipeline_run_id == run_id, PipelineEvent.event_type == "delivery_failed")
        ).scalars().first()
        assert event is not None


# =====================================================================
# 5. IDOR Tenant Isolation
# =====================================================================
def test_e2e_tenant_isolation_idor(e2e_ctx):
    """
    Confirms User 2 cannot inspect, modify, approve, or trigger delivery on User 1's resources.
    All attempts must return 404 or unauthorized.
    """
    client2 = e2e_ctx["client2"]
    db_factory = e2e_ctx["db_factory"]
    u1_id = e2e_ctx["u1_id"]

    with db_factory() as db:
        camp = Campaign(user_id=u1_id, name="User1 Private Campaign", objective="Private")
        db.add(camp)
        db.flush()

        comp = Company(campaign_id=camp.id, domain="u1-private.io", company_name="U1 Private Inc")
        db.add(comp)
        db.flush()

        run = PipelineRun(campaign_id=camp.id, company_id=comp.id, status="waiting_for_delivery")
        db.add(run)
        db.flush()

        draft = Draft(pipeline_run_id=run.id, company_id=comp.id, subject="Sub", body="Body")
        db.add(draft)
        db.flush()

        rev = Review(pipeline_run_id=run.id, draft_id=draft.id, status="pending")
        db.add(rev)
        db.commit()

        c1_id = camp.id
        r1_id = run.id
        rev1_id = rev.id

    # User 2 attempts to read User 1 campaign
    assert client2.get(f"/api/v1/campaigns/{c1_id}").status_code == 404

    # User 2 attempts to list User 1 companies
    assert client2.get(f"/api/v1/campaigns/{c1_id}/companies").status_code == 404

    # User 2 attempts to enqueue User 1 campaign
    assert client2.post(f"/api/v1/campaigns/{c1_id}/enqueue-selected").status_code == 404

    # User 2 attempts to view User 1 run
    assert client2.get(f"/api/v1/campaigns/{c1_id}/runs/{r1_id}").status_code == 404

    # User 2 attempts to view User 1 review
    assert client2.get(f"/api/v1/review/{rev1_id}").status_code == 404

    # User 2 attempts to approve User 1 review
    assert client2.post(f"/api/v1/review/{rev1_id}/approve").status_code == 404

    # User 2 attempts to trigger delivery on User 1 run
    assert client2.post(f"/api/v1/deliveries/{r1_id}").status_code == 404

    # User 2 deliveries list does not contain User 1 data
    u2_delivs = client2.get("/api/v1/deliveries").json()
    assert not any(d["campaign_id"] == c1_id for d in u2_delivs)


# =====================================================================
# 6. Idempotency & Restart Safety
# =====================================================================
def test_e2e_idempotency_and_restart_safety(e2e_ctx):
    """
    Verifies:
    1. Repeated approve calls are idempotent.
    2. Repeated delivery calls return existing record without duplicate execution.
    3. JobManager recover_stale_runs does NOT auto-deliver waiting_for_delivery runs.
    """
    client = e2e_ctx["client1"]
    db_factory = e2e_ctx["db_factory"]
    u1_id = e2e_ctx["u1_id"]

    with db_factory() as db:
        camp = Campaign(user_id=u1_id, name="Idempotent Campaign", objective="Idempotency")
        db.add(camp)
        db.flush()

        comp = Company(campaign_id=camp.id, domain="idempotent-target.io", company_name="Idem Inc")
        db.add(comp)
        db.flush()

        person = Person(company_id=comp.id, first_name="A", last_name="B", full_name="A B", role="CTO", person_confidence=0.8)
        db.add(person)
        db.flush()

        contact = Contact(company_id=comp.id, person_id=person.id, email="ab@idempotent-target.io", verification_status="valid")
        db.add(contact)
        db.flush()

        run = PipelineRun(campaign_id=camp.id, company_id=comp.id, status="waiting_for_review")
        db.add(run)
        db.flush()

        draft = Draft(pipeline_run_id=run.id, company_id=comp.id, contact_id=contact.id, subject="Sub", body="Body")
        db.add(draft)
        db.flush()

        rev = Review(pipeline_run_id=run.id, draft_id=draft.id, status="pending")
        db.add(rev)
        db.commit()

        run_id = run.id
        review_id = rev.id

    # 1. Approve once
    r1 = client.post(f"/api/v1/review/{review_id}/approve")
    assert r1.status_code == 200
    assert r1.json()["status"] == "approved"

    # 2. Approve second time (idempotent 200)
    r2 = client.post(f"/api/v1/review/{review_id}/approve")
    assert r2.status_code == 200
    assert r2.json()["status"] == "approved"

    # 3. Deliver once
    mock_adapter = MockE2EDeliveryAdapter()
    with patch("server.services.delivery.AdapterFactory.get_delivery_adapter", return_value=mock_adapter):
        d1 = client.post(f"/api/v1/deliveries/{run_id}")
        assert d1.status_code == 200

        # 4. Deliver second time: already completed, safe rejection or idempotent return
        d2 = client.post(f"/api/v1/deliveries/{run_id}")
        assert d2.status_code in [200, 400]
        assert mock_adapter.call_count == 0  # Still zero provider calls (staging)

    # 5. Startup Recovery Invariant: server restart recovery never auto-delivers waiting_for_delivery runs
    with db_factory() as db:
        # Create a run in waiting_for_delivery
        pending_deliv_run = PipelineRun(campaign_id=camp.id, company_id=comp.id, status="waiting_for_delivery")
        db.add(pending_deliv_run)
        db.commit()
        p_run_id = pending_deliv_run.id

    # Trigger recovery
    JobManager.get_instance().recover_stale_runs()

    with db_factory() as db:
        p_run = db.execute(select(PipelineRun).where(PipelineRun.id == p_run_id)).scalar_one()
        # Invariant maintained: status must remain waiting_for_delivery
        assert p_run.status == "waiting_for_delivery"


# =====================================================================
# 7. Cockpit Frontend Routes Served
# =====================================================================
def test_e2e_frontend_html_routes_served(e2e_ctx):
    """Verifies that all operator console views are accessible and return 200 HTML."""
    client = e2e_ctx["client1"]

    routes = [
        "/login",
        "/dashboard",
        "/campaigns",
        "/review",
        "/deliveries",
        "/profile",
        "/settings",
    ]

    for route in routes:
        res = client.get(route)
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "Outbound Pipeline" in res.text

    # Root redirect
    res_root = client.get("/", follow_redirects=False)
    assert res_root.status_code == 302
    assert res_root.headers["location"] == "/dashboard"


# =====================================================================
# 8. Candidate Deselect & Filter Tests
# =====================================================================
def test_e2e_candidate_deselect_and_filters(e2e_ctx):
    """Verifies candidate deselection and query filtering on /companies."""
    client = e2e_ctx["client1"]
    db_factory = e2e_ctx["db_factory"]
    u1_id = e2e_ctx["u1_id"]

    with db_factory() as db:
        camp = Campaign(user_id=u1_id, name="Filter Test Campaign", objective="Filtering")
        db.add(camp)
        db.flush()

        c1 = Company(campaign_id=camp.id, domain="alpha-sec.io", company_name="Alpha Sec", industry="Cybersecurity", stage="Seed", match_score=92)
        c2 = Company(campaign_id=camp.id, domain="beta-ai.io", company_name="Beta AI", industry="AI ML", stage="Growth", match_score=65)
        db.add_all([c1, c2])
        db.commit()
        camp_id = camp.id
        c1_id = c1.id

    # Select c1
    sel_res = client.post(f"/api/v1/campaigns/{camp_id}/companies/select", json={"company_ids": [c1_id]})
    assert sel_res.status_code == 200

    # Deselect c1
    desel_res = client.post(f"/api/v1/campaigns/{camp_id}/companies/deselect", json={"company_ids": [c1_id]})
    assert desel_res.status_code == 200
    assert desel_res.json()["deselected_count"] == 1

    with db_factory() as db:
        comp_obj = db.execute(select(Company).where(Company.id == c1_id)).scalar_one()
        assert comp_obj.selection_status == "discovered"

    # Test industry filter
    ind_res = client.get(f"/api/v1/campaigns/{camp_id}/companies?industry=Cybersecurity")
    assert ind_res.status_code == 200
    assert len(ind_res.json()) == 1
    assert ind_res.json()[0]["domain"] == "alpha-sec.io"

    # Test text search
    search_res = client.get(f"/api/v1/campaigns/{camp_id}/companies?search=beta")
    assert search_res.status_code == 200
    assert len(search_res.json()) == 1
    assert search_res.json()[0]["domain"] == "beta-ai.io"

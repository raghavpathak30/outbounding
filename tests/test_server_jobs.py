"""
Unit tests for Phase 6 — Background Pipeline Execution & Job Manager.
Verifies:
1. Enqueue selected creates queued PipelineRun records.
2. Max 2 concurrent workers in ThreadPoolExecutor.
3. Asynchronous execution traverses stages and halts strictly at 'waiting_for_review'.
4. Zero delivery or staging triggered (review & delivery nodes untouched).
5. Stage checkpointing and persistent domain entities (Person, Contact, Draft, Review, Events).
6. Crash recovery: resumes from latest checkpoint without re-invoking previous stages (credit conservation).
7. Skipped transitions when leader or email resolution fails.
8. Error capture transitions to 'failed'.
9. Thread-safe Gemini pacing lock across concurrent threads.
10. Run listing and inspection endpoints with user isolation.
"""
import os
import time
import json
import pytest
import threading
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from server.models.base import Base
from server.models.entities import (
    User,
    Resume,
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
from server.services.job_manager import JobManager
from pipeline.config import pace_gemini_call, reset_pacing_state, _gemini_pacing_lock


@pytest.fixture
def job_ctx(tmp_path, monkeypatch):
    """Provides isolated DB, sessionmaker, JobManager, and TestClients for 2 users."""
    test_db_file = tmp_path / "test_jobs.db"
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

    # Force stub mode for adapters
    monkeypatch.setenv("DISCOVERY_MODE", "stub")
    monkeypatch.setenv("ENRICHMENT_MODE", "stub")
    monkeypatch.setenv("PERSON_RESEARCH_MODE", "stub")
    monkeypatch.setenv("EMAIL_RESOLUTION_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")

    # Reset JobManager singleton with test session factory
    job_manager = JobManager.get_instance(
        max_workers=2,
        session_factory=TestingSessionLocal,
        reset=True
    )

    settings = Settings(
        jwt_secret_key="super-secret-key-for-phase-6-job-testing-min-32-chars",
        cors_allowed_origins=["https://work.raghavpathak.me", "http://localhost"],
        delivery_mode="staged",
        dry_run=True,
    )
    app = create_app(settings)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings

    # Seed 2 distinct users
    session = TestingSessionLocal()
    u1 = User(email="operator1@raghavpathak.me", password_hash=AuthService.hash_password("Password123!"), is_active=True)
    u2 = User(email="operator2@raghavpathak.me", password_hash=AuthService.hash_password("Password123!"), is_active=True)
    session.add_all([u1, u2])
    session.commit()

    u1_id = u1.id
    u2_id = u2.id
    session.close()

    token1, _, _ = AuthService.create_access_token(u1_id, "operator1@raghavpathak.me", settings.jwt_secret_key)
    token2, _, _ = AuthService.create_access_token(u2_id, "operator2@raghavpathak.me", settings.jwt_secret_key)

    client1 = TestClient(app, raise_server_exceptions=False)
    client1.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token1)
    client2 = TestClient(app, raise_server_exceptions=False)
    client2.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token2)

    yield {
        "engine": engine,
        "session_factory": TestingSessionLocal,
        "job_manager": job_manager,
        "u1_id": u1_id,
        "u2_id": u2_id,
        "client1": client1,
        "client2": client2,
    }

    job_manager.shutdown(wait=False)
    engine.dispose()


# =====================================================================
# 1. Enqueue Selected and Worker Cap
# =====================================================================

def test_enqueue_selected_creates_queued_runs_and_submits(job_ctx):
    """Verifies selected companies generate PipelineRun records in 'queued' status."""
    client1 = job_ctx["client1"]
    session_factory = job_ctx["session_factory"]
    u1_id = job_ctx["u1_id"]

    session = session_factory()
    campaign = Campaign(user_id=u1_id, name="Job Campaign", objective="Objective")
    session.add(campaign)
    session.commit()

    comp1 = Company(campaign_id=campaign.id, domain="target-alpha.io", company_name="Target Alpha", selection_status="selected")
    comp2 = Company(campaign_id=campaign.id, domain="target-beta.io", company_name="Target Beta", selection_status="selected")
    comp3 = Company(campaign_id=campaign.id, domain="target-gamma.io", company_name="Target Gamma", selection_status="discovered")
    session.add_all([comp1, comp2, comp3])
    session.commit()
    campaign_id = campaign.id
    session.close()

    # Call enqueue-selected
    res = client1.post(f"/api/v1/campaigns/{campaign_id}/enqueue-selected")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "queued"
    assert data["enqueued_count"] == 2
    assert len(data["runs"]) == 2

    # Verify runs exist in DB
    session = session_factory()
    runs = list(session.execute(select(PipelineRun).where(PipelineRun.campaign_id == campaign_id)).scalars().all())
    assert len(runs) == 2
    for r in runs:
        assert r.status in ["queued", "running", "waiting_for_review", "skipped"]
        assert r.last_completed_stage is not None
    session.close()


def test_job_manager_respects_max_two_workers(job_ctx):
    """Confirms the thread pool is capped at max 2 workers."""
    jm = job_ctx["job_manager"]
    assert jm.max_workers == 2
    assert jm.executor._max_workers == 2


# =====================================================================
# 2. Stage Execution & Review Boundary
# =====================================================================

def test_pipeline_execution_halts_at_waiting_for_review_without_delivery(job_ctx):
    """
    Tests complete background pipeline execution:
    - Traverses Stage 1 (Person) -> Stage 2 (Email) -> Stage 3 (Draft).
    - Terminates cleanly at 'waiting_for_review'.
    - Confirms zero delivery staging/dispatch.
    """
    session_factory = job_ctx["session_factory"]
    jm = job_ctx["job_manager"]
    u1_id = job_ctx["u1_id"]

    session = session_factory()
    campaign = Campaign(
        user_id=u1_id,
        name="Security Outreach",
        objective="Find CISO / Head of Security",
        industry="Cybersecurity"
    )
    session.add(campaign)
    session.commit()

    company = Company(
        campaign_id=campaign.id,
        domain="apex-vault-fintech.io",
        company_name="Apex Vault Fintech",
        selection_status="selected",
        industry="Cybersecurity",
        technical_signals_json=json.dumps(["Zero-Knowledge", "Rust"]),
        why_match_json=json.dumps(["High security alignment (+30)"])
    )
    session.add(company)
    session.commit()

    run = PipelineRun(
        campaign_id=campaign.id,
        company_id=company.id,
        status="queued"
    )
    session.add(run)
    session.commit()
    run_id = run.id
    company_id = company.id
    session.close()

    # Execute run
    future = jm.submit_run(run_id)
    future.result(timeout=10.0)  # Wait for execution

    # Verify final state in DB
    session = session_factory()
    completed_run = session.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()

    # Boundary invariant: MUST be waiting_for_review, NEVER completed/sent
    assert completed_run.status == "waiting_for_review"
    assert completed_run.last_completed_stage == "draft_generated"
    assert completed_run.started_at is not None
    assert completed_run.completed_at is not None

    # Checkpoint state captured
    assert completed_run.checkpoint_state_json is not None
    ckpt = json.loads(completed_run.checkpoint_state_json)
    assert "leader" in ckpt
    assert "contact" in ckpt
    assert "draft" in ckpt

    # Verify Person persisted
    person = session.execute(select(Person).where(Person.company_id == company_id)).scalar_one()
    assert person.first_name != ""
    assert person.person_confidence >= 0.70

    # Verify Contact persisted
    contact = session.execute(select(Contact).where(Contact.company_id == company_id)).scalar_one()
    assert contact.email is not None
    assert "@" in contact.email

    # Verify Draft persisted
    draft = session.execute(select(Draft).where(Draft.pipeline_run_id == run_id)).scalar_one()
    assert draft.subject != ""
    assert draft.body != ""
    assert draft.persona in ["security", "ai_ml", "hr_talent"]

    # Verify pending Review created
    review = session.execute(select(Review).where(Review.pipeline_run_id == run_id)).scalar_one()
    assert review.status == "pending"
    assert review.draft_id == draft.id

    # Strict safety invariant: Delivery table must have ZERO records
    deliveries = list(session.execute(select(Delivery).where(Delivery.pipeline_run_id == run_id)).scalars().all())
    assert len(deliveries) == 0

    session.close()


# =====================================================================
# 3. Crash Recovery (Credit Conservation)
# =====================================================================

def test_recovery_resumes_from_email_resolved_without_re_calling_research(job_ctx):
    """
    Verifies that when a run was interrupted after 'email_resolved':
    - Recovery resumes directly at drafting.
    - Person research and email resolution are NOT re-invoked (credit conservation).
    """
    session_factory = job_ctx["session_factory"]
    jm = job_ctx["job_manager"]
    u1_id = job_ctx["u1_id"]

    session = session_factory()
    campaign = Campaign(user_id=u1_id, name="Resume Campaign", objective="Obj")
    session.add(campaign)
    session.commit()

    company = Company(
        campaign_id=campaign.id,
        domain="crash-recovery.io",
        company_name="Crash Recovery Labs",
        selection_status="selected"
    )
    session.add(company)
    session.commit()

    # Pre-populate Stage 1 Person and Stage 2 Contact
    person = Person(
        company_id=company.id,
        first_name="Elena",
        last_name="Rostova",
        full_name="Elena Rostova",
        role="VP of Engineering",
        person_confidence=0.92
    )
    contact = Contact(
        company_id=company.id,
        email="elena.rostova@crash-recovery.io",
        email_confidence=95.0,
        verification_status="valid",
        provider="hunter"
    )
    session.add_all([person, contact])
    session.commit()

    # Simulate run interrupted while running at stage 'email_resolved'
    run = PipelineRun(
        campaign_id=campaign.id,
        company_id=company.id,
        status="running",
        last_completed_stage="email_resolved",
        checkpoint_state_json=json.dumps({
            "leader": {"full_name": "Elena Rostova", "role": "VP of Engineering"},
            "contact": {"email": "elena.rostova@crash-recovery.io"}
        }),
        started_at=datetime.now(timezone.utc)
    )
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    # Spy on adapters to ensure Stage 1 and Stage 2 are NEVER called
    mock_person_adapter = MagicMock()
    mock_email_adapter = MagicMock()

    with patch("pipeline.adapters.base.AdapterFactory.get_person_research_adapter", return_value=mock_person_adapter), \
         patch("pipeline.adapters.base.AdapterFactory.get_email_resolution_adapter", return_value=mock_email_adapter):

        recovered_ids = jm.recover_stale_runs()
        assert run_id in recovered_ids

        fut = jm.get_future(run_id)
        assert fut is not None
        fut.result(timeout=10.0)

        # Assert zero calls to Stage 1 and Stage 2 adapters!
        mock_person_adapter.find_leader.assert_not_called()
        mock_email_adapter.resolve_email.assert_not_called()

    # Confirm run successfully finished drafting and is waiting for review
    session = session_factory()
    resumed_run = session.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
    assert resumed_run.status == "waiting_for_review"
    assert resumed_run.last_completed_stage == "draft_generated"

    draft = session.execute(select(Draft).where(Draft.pipeline_run_id == run_id)).scalar_one()
    assert draft is not None
    assert "Elena Rostova" in draft.body or "crash-recovery.io" in draft.body
    session.close()


# =====================================================================
# 4. Graceful Skipping & Failure Handling
# =====================================================================

def test_pipeline_skips_when_no_leader_found(job_ctx):
    """Verifies that low/missing leader confidence cleanly transitions to 'skipped'."""
    session_factory = job_ctx["session_factory"]
    jm = job_ctx["job_manager"]
    u1_id = job_ctx["u1_id"]

    session = session_factory()
    campaign = Campaign(user_id=u1_id, name="Skip Campaign", objective="Obj")
    company = Company(campaign=campaign, domain="ghost-corp.io", company_name="Ghost Corp")
    run = PipelineRun(campaign=campaign, company=company, status="queued")
    session.add_all([campaign, company, run])
    session.commit()
    run_id = run.id
    session.close()

    mock_person = MagicMock()
    mock_person.find_leader.return_value = {
        "full_name": None,
        "person_confidence": 0.30  # Below MIN_PERSON_CONFIDENCE (0.70)
    }

    with patch("pipeline.adapters.base.AdapterFactory.get_person_research_adapter", return_value=mock_person):
        fut = jm.submit_run(run_id)
        fut.result(timeout=10.0)

    session = session_factory()
    run_obj = session.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
    assert run_obj.status == "skipped"
    assert "No verified leader found" in run_obj.error_message
    assert run_obj.last_completed_stage == "person_unverified"
    session.close()


def test_pipeline_skips_when_no_email_resolved(job_ctx):
    """Verifies that failure to resolve deliverable email cleanly transitions to 'skipped'."""
    session_factory = job_ctx["session_factory"]
    jm = job_ctx["job_manager"]
    u1_id = job_ctx["u1_id"]

    session = session_factory()
    campaign = Campaign(user_id=u1_id, name="Skip Email Campaign", objective="Obj")
    company = Company(campaign=campaign, domain="no-email-target.io", company_name="No Email Target")
    run = PipelineRun(campaign=campaign, company=company, status="queued")
    session.add_all([campaign, company, run])
    session.commit()
    run_id = run.id
    session.close()

    mock_person = MagicMock()
    mock_person.find_leader.return_value = {
        "first_name": "Marcus",
        "last_name": "Vance",
        "full_name": "Marcus Vance",
        "role": "CTO",
        "person_confidence": 0.95
    }
    mock_email = MagicMock()
    mock_email.resolve_email.return_value = None  # No valid email found

    with patch("pipeline.adapters.base.AdapterFactory.get_person_research_adapter", return_value=mock_person), \
         patch("pipeline.adapters.base.AdapterFactory.get_email_resolution_adapter", return_value=mock_email):
        fut = jm.submit_run(run_id)
        fut.result(timeout=10.0)

    session = session_factory()
    run_obj = session.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
    assert run_obj.status == "skipped"
    assert "No deliverable email verified" in run_obj.error_message
    assert run_obj.last_completed_stage == "email_unresolved"
    session.close()


def test_pipeline_captures_unhandled_fatal_exceptions(job_ctx):
    """Verifies that unexpected runtime errors mark run as 'failed' and log event."""
    session_factory = job_ctx["session_factory"]
    jm = job_ctx["job_manager"]
    u1_id = job_ctx["u1_id"]

    session = session_factory()
    campaign = Campaign(user_id=u1_id, name="Fail Campaign", objective="Obj")
    company = Company(campaign=campaign, domain="fail-test.io", company_name="Fail Test")
    run = PipelineRun(campaign=campaign, company=company, status="queued")
    session.add_all([campaign, company, run])
    session.commit()
    run_id = run.id
    session.close()

    mock_person = MagicMock()
    mock_person.find_leader.side_effect = RuntimeError("Simulated external connection failure")

    with patch("pipeline.adapters.base.AdapterFactory.get_person_research_adapter", return_value=mock_person):
        fut = jm.submit_run(run_id)
        fut.result(timeout=10.0)

    session = session_factory()
    run_obj = session.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
    assert run_obj.status == "failed"
    assert "Simulated external connection failure" in run_obj.error_message
    session.close()


# =====================================================================
# 5. Gemini Global Pacing Lock
# =====================================================================

def test_gemini_pacing_lock_thread_safety():
    """Verifies that concurrent threads cannot interleave or bypass Gemini call pacing."""
    reset_pacing_state()
    call_timestamps = []
    lock = threading.Lock()

    def worker():
        # Request 100ms pacing delay
        pace_gemini_call(delay_ms=100)
        with lock:
            call_timestamps.append(time.time())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(call_timestamps) == 4
    # Check that each consecutive call was paced by ~100ms (allow slight timer variance)
    sorted_ts = sorted(call_timestamps)
    for i in range(1, len(sorted_ts)):
        delta_ms = (sorted_ts[i] - sorted_ts[i - 1]) * 1000.0
        assert delta_ms >= 70.0, f"Call {i} paced too close to call {i-1}: {delta_ms:.1f}ms < 70ms"


# =====================================================================
# 6. Run Listing & Inspection Endpoints
# =====================================================================

def test_runs_api_listing_and_isolation(job_ctx):
    """Verifies GET /runs and GET /runs/{run_id} with tenant isolation."""
    client1 = job_ctx["client1"]
    client2 = job_ctx["client2"]
    session_factory = job_ctx["session_factory"]
    u1_id = job_ctx["u1_id"]

    session = session_factory()
    c1 = Campaign(user_id=u1_id, name="Campaign 1", objective="Obj")
    session.add(c1)
    session.commit()

    comp = Company(campaign_id=c1.id, domain="run-inspection.io", company_name="Inspection Corp")
    session.add(comp)
    session.commit()

    run = PipelineRun(
        campaign_id=c1.id,
        company_id=comp.id,
        status="waiting_for_review",
        last_completed_stage="draft_generated",
        started_at=utc_now()
    )
    session.add(run)
    session.commit()
    c1_id = c1.id
    run_id = run.id
    session.close()

    # 1. User 1 can list runs
    res_list = client1.get(f"/api/v1/campaigns/{c1_id}/runs")
    assert res_list.status_code == 200
    data = res_list.json()
    assert len(data) == 1
    assert data[0]["id"] == run_id
    assert data[0]["company_name"] == "Inspection Corp"
    assert data[0]["status"] == "waiting_for_review"

    # 2. User 1 can retrieve run detail
    res_detail = client1.get(f"/api/v1/campaigns/{c1_id}/runs/{run_id}")
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["id"] == run_id
    assert detail["status"] == "waiting_for_review"

    # 3. User 2 is rejected with 404
    res_cross = client2.get(f"/api/v1/campaigns/{c1_id}/runs")
    assert res_cross.status_code == 404
    res_cross_detail = client2.get(f"/api/v1/campaigns/{c1_id}/runs/{run_id}")
    assert res_cross_detail.status_code == 404


# =====================================================================
# 7. Phase 6 Hardening Regression Tests
# =====================================================================

def test_sqlite_phase5_to_phase6_schema_migration(tmp_path):
    """
    Simulates an existing Phase 5 SQLite database where the pipeline_runs table
    was created without checkpoint_state_json.
    Verifies that init_db() non-destructively upgrades the schema by adding
    the missing column while keeping existing rows intact.
    """
    from sqlalchemy import create_engine, text, inspect
    from server.database import init_db

    db_path = tmp_path / "legacy_phase5.db"
    legacy_engine = create_engine(f"sqlite:///{db_path}")

    # Create Phase 5 legacy table without checkpoint_state_json
    with legacy_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE pipeline_runs (
                id VARCHAR(36) PRIMARY KEY,
                campaign_id VARCHAR(36) NOT NULL,
                company_id VARCHAR(36) NOT NULL,
                status VARCHAR(32) NOT NULL,
                last_completed_stage VARCHAR(64),
                error_message TEXT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP
            );
        """))
        conn.execute(text("""
            INSERT INTO pipeline_runs (id, campaign_id, company_id, status, last_completed_stage)
            VALUES ('run-legacy-1', 'camp-1', 'comp-1', 'completed', 'draft_generated');
        """))

    inspector_before = inspect(legacy_engine)
    cols_before = [c["name"] for c in inspector_before.get_columns("pipeline_runs")]
    assert "checkpoint_state_json" not in cols_before

    # Run safe schema migration via init_db
    init_db(target_engine=legacy_engine)

    inspector_after = inspect(legacy_engine)
    cols_after = [c["name"] for c in inspector_after.get_columns("pipeline_runs")]
    assert "checkpoint_state_json" in cols_after

    # Verify existing data is completely preserved
    with legacy_engine.connect() as conn:
        row = conn.execute(text("SELECT id, status, checkpoint_state_json FROM pipeline_runs WHERE id='run-legacy-1'")).fetchone()
        assert row[0] == "run-legacy-1"
        assert row[1] == "completed"
        assert row[2] is None

        # Verify new writes to checkpoint_state_json succeed
        conn.execute(text("UPDATE pipeline_runs SET checkpoint_state_json='{\"test\": true}' WHERE id='run-legacy-1'"))
        conn.commit()
        val = conn.execute(text("SELECT checkpoint_state_json FROM pipeline_runs WHERE id='run-legacy-1'")).scalar()
        assert val == '{\"test\": true}'


def test_concurrent_enqueue_prevents_duplicate_active_runs(job_ctx):
    """
    Verifies that concurrent requests calling /enqueue-selected cannot create
    duplicate active (queued/running) PipelineRun records for the same company.
    Also verifies that after a run reaches a terminal state, a new run CAN be enqueued.
    """
    client1 = job_ctx["client1"]
    session_factory = job_ctx["session_factory"]
    u1_id = job_ctx["u1_id"]

    session = session_factory()
    c1 = Campaign(user_id=u1_id, name="Race Campaign", objective="Testing concurrency")
    session.add(c1)
    session.commit()

    comp = Company(
        campaign_id=c1.id,
        domain="concurrent-test.io",
        company_name="Concurrent Test Corp",
        selection_status="selected"
    )
    session.add(comp)
    session.commit()
    c1_id = c1.id
    comp_id = comp.id
    session.close()

    # Simulate 5 concurrent threads attempting to enqueue the same selected company simultaneously
    results = []
    def call_enqueue():
        res = client1.post(f"/api/v1/campaigns/{c1_id}/enqueue-selected")
        results.append(res)

    threads = [threading.Thread(target=call_enqueue) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All requests should return 200 OK
    for r in results:
        assert r.status_code == 200

    # Query the database: exactly ONE active PipelineRun should exist
    session = session_factory()
    runs = list(session.execute(
        select(PipelineRun).where(
            PipelineRun.campaign_id == c1_id,
            PipelineRun.company_id == comp_id
        )
    ).scalars().all())
    assert len(runs) == 1, f"Expected exactly 1 run, but found {len(runs)}"
    run_obj = runs[0]

    # Wait for the first run's background future to complete to a terminal state
    jm = job_ctx["job_manager"]
    fut = jm.get_future(run_obj.id)
    if fut:
        fut.result(timeout=10.0)

    session.refresh(run_obj)
    assert run_obj.status in ["waiting_for_review", "skipped", "failed"]
    session.close()

    # Re-enqueuing after reaching terminal/review state should allow creating a new run
    res_after = client1.post(f"/api/v1/campaigns/{c1_id}/enqueue-selected")
    assert res_after.status_code == 200
    session = session_factory()
    runs_after = list(session.execute(
        select(PipelineRun).where(
            PipelineRun.campaign_id == c1_id,
            PipelineRun.company_id == comp_id
        )
    ).scalars().all())
    # Should now have 2 runs (one previous terminal run, one newly queued run)
    assert len(runs_after) == 2
    session.close()


def test_error_message_sanitization_prevents_traceback_and_credential_leaks(job_ctx):
    """
    Verifies that when an unhandled exception occurs with file paths, stack traces,
    and API credentials, PipelineRun.error_message is strictly sanitized and contains no tracebacks,
    absolute paths, or API keys.
    """
    session_factory = job_ctx["session_factory"]
    u1_id = job_ctx["u1_id"]
    jm = job_ctx["job_manager"]

    session = session_factory()
    c = Campaign(user_id=u1_id, name="Error Test Camp", objective="Sanitization")
    session.add(c)
    session.commit()

    comp = Company(campaign_id=c.id, domain="leak-test.io", company_name="Leak Test Corp")
    session.add(comp)
    session.commit()

    run = PipelineRun(
        campaign_id=c.id,
        company_id=comp.id,
        status="queued",
        last_completed_stage="discovery_completed"
    )
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    # Create a noisy exception with traceback, absolute file path, and sensitive credential
    noisy_error_message = (
        'Traceback (most recent call last):\n'
        '  File "/home/raghavp/projects/outbound-pipeline/secret_module.py", line 42, in connect\n'
        'ConnectionError: Provider rejected sk-1234567890abcdef1234567890 with api_key=secret_token_12345678 at /var/log/app/secrets.txt'
    )
    mock_person = MagicMock()
    mock_person.find_leader.side_effect = RuntimeError(noisy_error_message)

    with patch("pipeline.adapters.base.AdapterFactory.get_person_research_adapter", return_value=mock_person):
        fut = jm.submit_run(run_id)
        fut.result(timeout=10.0)

    session = session_factory()
    run_obj = session.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
    assert run_obj.status == "failed"

    # Verify no tracebacks, file paths, or credentials in error_message
    assert "Traceback" not in run_obj.error_message
    assert 'File "/home' not in run_obj.error_message
    assert "/home/raghavp" not in run_obj.error_message
    assert "/var/log/app" not in run_obj.error_message
    assert "sk-1234567890" not in run_obj.error_message
    assert "secret_token_12345678" not in run_obj.error_message
    assert "[internal_path]" in run_obj.error_message or "[REDACTED" in run_obj.error_message
    session.close()


def test_database_entity_reuse_avoids_duplicate_provider_calls(job_ctx):
    """
    Verifies that if Person and Contact already exist in the database for a company,
    JobManager reuses them directly and does NOT invoke external adapters again,
    minimizing duplicate provider calls and conserving credits.
    """
    session_factory = job_ctx["session_factory"]
    u1_id = job_ctx["u1_id"]
    jm = job_ctx["job_manager"]

    session = session_factory()
    c = Campaign(user_id=u1_id, name="Reuse Campaign", objective="Credit conservation")
    session.add(c)
    session.commit()

    comp = Company(campaign_id=c.id, domain="credit-save.io", company_name="Credit Save Inc")
    session.add(comp)
    session.commit()

    # Pre-populate Person and Contact in DB
    person = Person(
        company_id=comp.id,
        first_name="Alice",
        last_name="Smith",
        full_name="Alice Smith",
        role="VP Engineering",
        person_confidence=0.95
    )
    contact = Contact(
        company_id=comp.id,
        email="alice@credit-save.io",
        email_confidence=0.90,
        verification_status="valid"
    )
    session.add_all([person, contact])
    session.commit()

    run = PipelineRun(
        campaign_id=c.id,
        company_id=comp.id,
        status="queued",
        last_completed_stage="discovery_completed"
    )
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    mock_person = MagicMock()
    mock_email = MagicMock()

    with patch("pipeline.adapters.base.AdapterFactory.get_person_research_adapter", return_value=mock_person), \
         patch("pipeline.adapters.base.AdapterFactory.get_email_resolution_adapter", return_value=mock_email):
        fut = jm.submit_run(run_id)
        fut.result(timeout=10.0)

    # Adapters should NEVER have been called!
    assert mock_person.find_leader.call_count == 0
    assert mock_email.resolve_email.call_count == 0

    session = session_factory()
    run_obj = session.execute(select(PipelineRun).where(PipelineRun.id == run_id)).scalar_one()
    assert run_obj.status == "waiting_for_review"
    assert run_obj.last_completed_stage == "draft_generated"
    session.close()

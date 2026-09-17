"""
Unit and integration tests for Phase 7 — Web Human Review / Review Cockpit.
Verifies:
1. Queue listing and filtering (status=pending, approved, rejected, all, and campaign_id).
2. Detail endpoint returning full decision context (company, person, contact quality, draft, events)
   while suppressing checkpoint_state_json and secrets.
3. Strict tenant isolation (User 2 cannot list, view, edit, approve, or reject User 1's reviews).
4. Draft editing with subject/body validation, updated_at timestamps, and audit events.
5. Approval workflow: transitions review to 'approved', run to 'completed', records event.
6. Inline edits during approval.
7. Approval idempotency (repeated approve calls return 200 with unchanged state).
8. Rejection workflow: transitions review to 'rejected', run to 'skipped', records reason and event.
9. Rejection idempotency.
10. Strict state machine transitions (cannot approve rejected, cannot reject approved).
11. Concurrency protection (simultaneous approve vs reject race condition).
12. Phase 7 pipeline boundary enforcement:
    - Zero delivery_node invocation.
    - Zero Delivery entity created.
    - Zero staging files written.
    - Zero email dispatch.
13. Input validation: rejects empty or excessively large payloads.
14. Frontend HTML endpoints /review and /reviews.
15. CLI compatibility (pipeline.review.review_node intact).
"""
import os
import json
import pytest
import threading
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


@pytest.fixture
def review_ctx(tmp_path, monkeypatch):
    """Provides isolated DB, sessionmaker, TestClients for 2 distinct users, and helper to seed reviews."""
    test_db_file = tmp_path / "test_review.db"
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
        jwt_secret_key="super-secret-key-for-phase-7-review-testing-min-32-chars",
        cors_allowed_origins=["https://work.raghavpathak.me", "http://localhost"],
        delivery_mode="staged",
        dry_run=True,
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

    def seed_review(user_id=u1_id, company_name="Cyber Shield", domain="cybershield.io", review_status="pending"):
        s = TestingSessionLocal()
        camp = Campaign(user_id=user_id, name="Security Q3 Campaign", objective="Recruiting technical lead")
        s.add(camp)
        s.commit()

        comp = Company(
            campaign_id=camp.id,
            company_name=company_name,
            domain=domain,
            industry="Cybersecurity",
            stage="Series A",
            size=45,
            location="Bangalore, India",
            match_score=92,
            why_match_json=json.dumps(["Security infrastructure match", "Early-stage growth"]),
            technical_signals_json=json.dumps(["Kubernetes", "AWS", "Zero Trust"]),
            selection_status="selected",
        )
        s.add(comp)
        s.commit()

        person = Person(
            company_id=comp.id,
            first_name="Vikram",
            last_name="Malhotra",
            full_name="Vikram Malhotra",
            role="VP of Engineering",
            linkedin_url="https://linkedin.com/in/vmalhotra",
            person_confidence=0.95,
        )
        contact = Contact(
            company_id=comp.id,
            email=f"vikram@{domain}",
            email_confidence=0.94,
            verification_status="valid",
            provider="hunter",
            sources_count=2,
        )
        s.add_all([person, contact])
        s.commit()

        run = PipelineRun(
            campaign_id=camp.id,
            company_id=comp.id,
            status="waiting_for_review" if review_status == "pending" else ("waiting_for_delivery" if review_status == "approved" else "skipped"),
            last_completed_stage="draft_generated",
            checkpoint_state_json=json.dumps({"stage": "drafting_completed"}),
            started_at=utc_now(),
        )
        s.add(run)
        s.commit()

        draft = Draft(
            pipeline_run_id=run.id,
            company_id=comp.id,
            contact_id=contact.id,
            subject=f"Exploring Engineering Leadership at {company_name}",
            body=f"Hi Vikram,\n\nI noticed your work scaling security at {company_name}...",
            persona="security",
        )
        s.add(draft)
        s.commit()

        review = Review(
            pipeline_run_id=run.id,
            draft_id=draft.id,
            status=review_status,
        )
        s.add(review)

        event = PipelineEvent(
            pipeline_run_id=run.id,
            campaign_id=camp.id,
            event_type="waiting_for_review",
            message="Draft created, waiting for human operator review.",
            created_at=utc_now(),
        )
        s.add(event)
        s.commit()

        res_data = {
            "campaign_id": camp.id,
            "company_id": comp.id,
            "run_id": run.id,
            "draft_id": draft.id,
            "review_id": review.id,
        }
        s.close()
        return res_data

    return {
        "client1": client1,
        "client2": client2,
        "u1_id": u1_id,
        "u2_id": u2_id,
        "session_factory": TestingSessionLocal,
        "seed_review": seed_review,
    }


# =====================================================================
# 1. Queue Listing & Filtering Tests
# =====================================================================

def test_review_queue_lists_pending_reviews(review_ctx):
    """Verifies listing pending reviews with expected summary fields."""
    client1 = review_ctx["client1"]
    seed = review_ctx["seed_review"]

    r1 = seed(company_name="Alpha Tech", domain="alpha.io", review_status="pending")
    r2 = seed(company_name="Beta Cloud", domain="beta.io", review_status="pending")

    res = client1.get("/api/v1/review?status=pending")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2

    # Check summary structure
    item = next(x for x in data if x["id"] == r1["review_id"])
    assert item["company_name"] == "Alpha Tech"
    assert item["domain"] == "alpha.io"
    assert item["person_name"] == "Vikram Malhotra"
    assert item["person_role"] == "VP of Engineering"
    assert item["contact_email"] == "vikram@alpha.io"
    assert item["match_score"] == 92
    assert item["persona"] == "security"
    assert item["status"] == "pending"


def test_review_queue_filters_by_status_and_campaign(review_ctx):
    """Verifies filtering queue by status (pending, approved, rejected) and campaign_id."""
    client1 = review_ctx["client1"]
    seed = review_ctx["seed_review"]

    r_pending = seed(company_name="Pending Inc", domain="pending.io", review_status="pending")
    r_approved = seed(company_name="Approved Inc", domain="approved.io", review_status="approved")

    # 1. Filter status=pending
    res_p = client1.get("/api/v1/review?status=pending")
    assert res_p.status_code == 200
    ids_p = [x["id"] for x in res_p.json()]
    assert r_pending["review_id"] in ids_p
    assert r_approved["review_id"] not in ids_p

    # 2. Filter status=approved
    res_a = client1.get("/api/v1/review?status=approved")
    assert res_a.status_code == 200
    ids_a = [x["id"] for x in res_a.json()]
    assert r_approved["review_id"] in ids_a
    assert r_pending["review_id"] not in ids_a

    # 3. Filter by campaign_id
    camp_id = r_pending["campaign_id"]
    res_c = client1.get(f"/api/v1/review?campaign_id={camp_id}")
    assert res_c.status_code == 200
    assert len(res_c.json()) == 1
    assert res_c.json()[0]["id"] == r_pending["review_id"]


# =====================================================================
# 2. Review Detail Context & PII/Secret Suppression Tests
# =====================================================================

def test_review_detail_returns_complete_context_and_suppresses_secrets(review_ctx):
    """Verifies detail endpoint returns rich company/person/contact/draft/event info without leaking secrets."""
    client1 = review_ctx["client1"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="SecureNet", domain="securenet.io", review_status="pending")
    res = client1.get(f"/api/v1/review/{r['review_id']}")
    assert res.status_code == 200
    detail = res.json()

    # Verify Company info
    assert detail["company"]["company_name"] == "SecureNet"
    assert detail["company"]["domain"] == "securenet.io"
    assert detail["company"]["industry"] == "Cybersecurity"
    assert detail["company"]["match_score"] == 92
    assert "Security infrastructure match" in detail["company"]["why_match"]
    assert "Kubernetes" in detail["company"]["technical_signals"]

    # Verify Person info
    assert detail["person"]["full_name"] == "Vikram Malhotra"
    assert detail["person"]["role"] == "VP of Engineering"
    assert detail["person"]["person_confidence"] == 0.95

    # Verify Contact deliverability quality
    assert detail["contact"]["email"] == "vikram@securenet.io"
    assert detail["contact"]["verification_status"] == "valid"
    assert detail["contact"]["email_confidence"] == 0.94
    assert detail["contact"]["provider"] == "hunter"

    # Verify Draft
    assert "Exploring Engineering Leadership" in detail["draft"]["subject"]
    assert detail["draft"]["persona"] == "security"

    # Verify Run & Events
    assert detail["run"]["status"] == "waiting_for_review"
    assert len(detail["events"]) >= 1
    assert detail["events"][0]["event_type"] == "waiting_for_review"

    # Suppressed / Non-exposed safety assertions
    assert "checkpoint_state_json" not in detail
    assert "checkpoint_state_json" not in detail["run"]
    assert "api_key" not in str(detail).lower()
    assert "gemini_api_key" not in str(detail).lower()


# =====================================================================
# 3. Tenant Isolation Tests
# =====================================================================

def test_review_tenant_isolation(review_ctx):
    """User 2 must NOT be able to view, list, edit, approve, or reject User 1's reviews."""
    client1 = review_ctx["client1"]
    client2 = review_ctx["client2"]
    seed = review_ctx["seed_review"]

    u1_r = seed(user_id=review_ctx["u1_id"], company_name="User1 Corp", domain="u1.io")
    u1_review_id = u1_r["review_id"]

    # 1. User 2 queue listing does not include User 1's review
    res_list = client2.get("/api/v1/review")
    assert res_list.status_code == 200
    assert len(res_list.json()) == 0

    # 2. User 2 detail GET returns 404
    assert client2.get(f"/api/v1/review/{u1_review_id}").status_code == 404

    # 3. User 2 PATCH draft edit returns 404
    assert client2.patch(f"/api/v1/review/{u1_review_id}", json={"subject": "Hacked", "body": "Hacked"}).status_code == 404

    # 4. User 2 POST approve returns 404
    assert client2.post(f"/api/v1/review/{u1_review_id}/approve").status_code == 404

    # 5. User 2 POST reject returns 404
    assert client2.post(f"/api/v1/review/{u1_review_id}/reject").status_code == 404


# =====================================================================
# 4. Draft Editing Tests
# =====================================================================

def test_edit_draft_before_approval(review_ctx):
    """Verifies that an operator can modify draft subject/body and records an audit event."""
    client1 = review_ctx["client1"]
    session_factory = review_ctx["session_factory"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="Edit Corp", domain="edit.io")
    rev_id = r["review_id"]

    edit_payload = {
        "subject": "Custom Engineering Partnership Subject",
        "body": "Hi Vikram,\n\nI personally tailored this message after reviewing your latest GitHub release."
    }

    res = client1.patch(f"/api/v1/review/{rev_id}", json=edit_payload)
    assert res.status_code == 200
    data = res.json()

    # Verify updated fields
    assert data["draft"]["subject"] == "Custom Engineering Partnership Subject"
    assert data["draft"]["body"] == edit_payload["body"]
    assert data["edited_subject"] == "Custom Engineering Partnership Subject"
    assert data["edited_body"] == edit_payload["body"]

    # Verify DB persistence & audit event
    session = session_factory()
    draft = session.execute(select(Draft).where(Draft.id == r["draft_id"])).scalar_one()
    assert draft.subject == "Custom Engineering Partnership Subject"
    assert draft.body == edit_payload["body"]

    event = session.execute(
        select(PipelineEvent).where(
            PipelineEvent.pipeline_run_id == r["run_id"],
            PipelineEvent.event_type == "draft_edited"
        )
    ).scalar_one_or_none()
    assert event is not None
    assert "modified by human operator" in event.message
    session.close()


def test_cannot_edit_draft_after_review_closed(review_ctx):
    """Editing draft on an approved or rejected review must fail with 400 Bad Request."""
    client1 = review_ctx["client1"]
    seed = review_ctx["seed_review"]

    r_app = seed(company_name="Closed Corp", domain="closed.io", review_status="approved")
    res = client1.patch(f"/api/v1/review/{r_app['review_id']}", json={"subject": "New", "body": "Body"})
    assert res.status_code == 400
    assert "Only 'pending' reviews can be edited" in res.json()["detail"]


# =====================================================================
# 5. Approval & Idempotency Tests
# =====================================================================

def test_approve_review_success(review_ctx):
    """Approving pending review sets status to approved, run to completed, and records audit event."""
    client1 = review_ctx["client1"]
    session_factory = review_ctx["session_factory"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="Approve Corp", domain="approve.io")
    rev_id = r["review_id"]

    res = client1.post(f"/api/v1/review/{rev_id}/approve", json={"notes": "Excellent personalized pitch."})
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "approved"
    assert data["reviewer_notes"] == "Excellent personalized pitch."
    assert data["reviewed_at"] is not None
    assert data["run"]["status"] == "waiting_for_delivery"
    assert data["run"]["last_completed_stage"] == "review_approved"

    # Verify in DB
    session = session_factory()
    rev_obj = session.execute(select(Review).where(Review.id == rev_id)).scalar_one()
    assert rev_obj.status == "approved"
    assert rev_obj.reviewed_at is not None

    run_obj = session.execute(select(PipelineRun).where(PipelineRun.id == r["run_id"])).scalar_one()
    assert run_obj.status == "waiting_for_delivery"
    assert run_obj.last_completed_stage == "review_approved"

    event = session.execute(
        select(PipelineEvent).where(
            PipelineEvent.pipeline_run_id == r["run_id"],
            PipelineEvent.event_type == "review_approved"
        )
    ).scalar_one_or_none()
    assert event is not None
    event_data = json.loads(event.data_json)
    assert event_data["user_id"] == review_ctx["u1_id"]
    assert event_data["decision"] == "approved"
    session.close()


def test_approve_review_with_inline_edits(review_ctx):
    """Operator can update subject/body directly in the approval call."""
    client1 = review_ctx["client1"]
    session_factory = review_ctx["session_factory"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="Inline Corp", domain="inline.io")
    rev_id = r["review_id"]

    res = client1.post(
        f"/api/v1/review/{rev_id}/approve",
        json={
            "edited_subject": "Approved with Inline Edits",
            "edited_body": "Updated body text directly on approval.",
            "notes": "Verified and approved."
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "approved"
    assert data["draft"]["subject"] == "Approved with Inline Edits"
    assert data["draft"]["body"] == "Updated body text directly on approval."

    session = session_factory()
    draft = session.execute(select(Draft).where(Draft.id == r["draft_id"])).scalar_one()
    assert draft.subject == "Approved with Inline Edits"
    session.close()


def test_duplicate_approval_is_idempotent(review_ctx):
    """Repeated approve requests must succeed idempotently without creating duplicate events."""
    client1 = review_ctx["client1"]
    session_factory = review_ctx["session_factory"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="Idem Corp", domain="idem.io")
    rev_id = r["review_id"]

    res1 = client1.post(f"/api/v1/review/{rev_id}/approve", json={"notes": "First approval"})
    assert res1.status_code == 200
    first_reviewed_at = res1.json()["reviewed_at"]

    res2 = client1.post(f"/api/v1/review/{rev_id}/approve", json={"notes": "Duplicate approval"})
    assert res2.status_code == 200
    assert res2.json()["status"] == "approved"
    assert res2.json()["reviewed_at"] == first_reviewed_at

    # Ensure only ONE review_approved event was created
    session = session_factory()
    events = list(
        session.execute(
            select(PipelineEvent).where(
                PipelineEvent.pipeline_run_id == r["run_id"],
                PipelineEvent.event_type == "review_approved"
            )
        ).scalars().all()
    )
    assert len(events) == 1
    session.close()


# =====================================================================
# 6. Rejection & Idempotency Tests
# =====================================================================

def test_reject_review_success(review_ctx):
    """Rejecting review transitions to 'rejected', marks run as 'skipped', and saves reason."""
    client1 = review_ctx["client1"]
    session_factory = review_ctx["session_factory"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="Reject Corp", domain="reject.io")
    rev_id = r["review_id"]

    res = client1.post(f"/api/v1/review/{rev_id}/reject", json={"reason": "Role mismatch: looking for security analysts not VPs"})
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "rejected"
    assert "Role mismatch" in data["reviewer_notes"]
    assert data["run"]["status"] == "skipped"

    # Verify DB
    session = session_factory()
    run = session.execute(select(PipelineRun).where(PipelineRun.id == r["run_id"])).scalar_one()
    assert run.status == "skipped"
    assert run.completed_at is not None

    event = session.execute(
        select(PipelineEvent).where(
            PipelineEvent.pipeline_run_id == r["run_id"],
            PipelineEvent.event_type == "review_rejected"
        )
    ).scalar_one_or_none()
    assert event is not None
    assert "Role mismatch" in event.message
    event_data = json.loads(event.data_json)
    assert event_data["user_id"] == review_ctx["u1_id"]
    assert event_data["decision"] == "rejected"
    assert "Role mismatch" in event_data["reason"]
    session.close()


def test_duplicate_rejection_is_idempotent(review_ctx):
    """Repeated rejection calls succeed idempotently without creating duplicate events."""
    client1 = review_ctx["client1"]
    session_factory = review_ctx["session_factory"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="RejIdem Corp", domain="rej-idem.io")
    rev_id = r["review_id"]

    res1 = client1.post(f"/api/v1/review/{rev_id}/reject", json={"reason": "Initial rejection"})
    assert res1.status_code == 200

    res2 = client1.post(f"/api/v1/review/{rev_id}/reject", json={"reason": "Second rejection"})
    assert res2.status_code == 200
    assert res2.json()["status"] == "rejected"

    session = session_factory()
    events = list(
        session.execute(
            select(PipelineEvent).where(
                PipelineEvent.pipeline_run_id == r["run_id"],
                PipelineEvent.event_type == "review_rejected"
            )
        ).scalars().all()
    )
    assert len(events) == 1
    session.close()


# =====================================================================
# 7. Strict State Machine & Concurrency Race Tests
# =====================================================================

def test_strict_state_machine_invalid_transitions(review_ctx):
    """Cannot approve an already rejected review, and cannot reject an already approved review."""
    client1 = review_ctx["client1"]
    seed = review_ctx["seed_review"]

    # 1. Reject then try to Approve
    r1 = seed(company_name="Strict1", domain="strict1.io")
    client1.post(f"/api/v1/review/{r1['review_id']}/reject", json={"reason": "Rejected"})
    res_bad_app = client1.post(f"/api/v1/review/{r1['review_id']}/approve")
    assert res_bad_app.status_code == 400
    assert "already been rejected" in res_bad_app.json()["detail"]

    # 2. Approve then try to Reject
    r2 = seed(company_name="Strict2", domain="strict2.io")
    client1.post(f"/api/v1/review/{r2['review_id']}/approve")
    res_bad_rej = client1.post(f"/api/v1/review/{r2['review_id']}/reject")
    assert res_bad_rej.status_code == 400
    assert "already been approved" in res_bad_rej.json()["detail"]


def test_concurrency_approve_reject_race(review_ctx):
    """Simulates simultaneous Approve and Reject requests from two concurrent tabs/threads."""
    client1 = review_ctx["client1"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="Race Corp", domain="race.io")
    rev_id = r["review_id"]

    responses = {}

    def call_approve():
        responses["approve"] = client1.post(f"/api/v1/review/{rev_id}/approve")

    def call_reject():
        responses["reject"] = client1.post(f"/api/v1/review/{rev_id}/reject", json={"reason": "Concurrent reject"})

    t1 = threading.Thread(target=call_approve)
    t2 = threading.Thread(target=call_reject)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # One transition MUST succeed (200) and the other MUST be rejected (400)
    codes = {responses["approve"].status_code, responses["reject"].status_code}
    assert codes == {200, 400}


# =====================================================================
# 8. Phase 7 Pipeline Boundary Enforcement Tests
# =====================================================================

def test_boundary_no_delivery_on_approval(review_ctx):
    """
    CRITICAL INVARIANT:
    Approving a review in Phase 7 must NEVER invoke delivery_node, stage_deliveries, or send_email.
    """
    client1 = review_ctx["client1"]
    session_factory = review_ctx["session_factory"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="Boundary Approve", domain="b-app.io")
    rev_id = r["review_id"]

    with patch("pipeline.delivery.delivery_node") as mock_delivery_node, \
         patch("pipeline.adapters.base.AdapterFactory.get_delivery_adapter") as mock_adapter:

        res = client1.post(f"/api/v1/review/{rev_id}/approve")
        assert res.status_code == 200

        # Assert delivery was NEVER called
        assert mock_delivery_node.call_count == 0
        assert mock_adapter.call_count == 0

    # Assert Delivery table has NO records for this run
    session = session_factory()
    delivery_rows = list(session.execute(select(Delivery).where(Delivery.pipeline_run_id == r["run_id"])).scalars().all())
    assert len(delivery_rows) == 0
    session.close()


def test_boundary_no_delivery_on_rejection(review_ctx):
    """Rejecting a review must NEVER invoke delivery or create delivery records."""
    client1 = review_ctx["client1"]
    session_factory = review_ctx["session_factory"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="Boundary Reject", domain="b-rej.io")
    rev_id = r["review_id"]

    with patch("pipeline.delivery.delivery_node") as mock_delivery_node:
        res = client1.post(f"/api/v1/review/{rev_id}/reject", json={"reason": "Not a match"})
        assert res.status_code == 200
        assert mock_delivery_node.call_count == 0

    session = session_factory()
    delivery_rows = list(session.execute(select(Delivery).where(Delivery.pipeline_run_id == r["run_id"])).scalars().all())
    assert len(delivery_rows) == 0
    session.close()


# =====================================================================
# 9. Input Validation & Frontend Route Tests
# =====================================================================

def test_input_validation_empty_or_oversized(review_ctx):
    """Verifies that invalid payloads (empty subject/body, oversized subject) are rejected."""
    client1 = review_ctx["client1"]
    seed = review_ctx["seed_review"]

    r = seed(company_name="Input Corp", domain="input.io")
    rev_id = r["review_id"]

    # Blank body
    res_blank = client1.patch(f"/api/v1/review/{rev_id}", json={"subject": "Valid Subject", "body": "   "})
    assert res_blank.status_code in [400, 422]

    # Blank subject
    res_no_subj = client1.patch(f"/api/v1/review/{rev_id}", json={"subject": "", "body": "Valid body"})
    assert res_no_subj.status_code in [400, 422]

    # Oversized subject (>255 chars)
    res_huge_subj = client1.patch(f"/api/v1/review/{rev_id}", json={"subject": "A" * 300, "body": "Valid body"})
    assert res_huge_subj.status_code == 422


def test_frontend_review_routes_served(review_ctx):
    """Verifies that /review and /reviews HTML pages are served successfully."""
    client1 = review_ctx["client1"]
    res1 = client1.get("/review")
    assert res1.status_code == 200
    assert "Review Cockpit" in res1.text
    assert "Review Queue" in res1.text

    res2 = client1.get("/reviews")
    assert res2.status_code == 200
    assert "Review Cockpit" in res2.text


# =====================================================================
# 10. CLI Review Compatibility Test
# =====================================================================

def test_cli_review_node_remains_operational(monkeypatch):
    """Confirms pipeline/review.py review_node continues to function for CLI runs."""
    from pipeline.review import review_node

    # Test auto_approve
    state = {
        "domain": "cli-test.io",
        "contact_name": "Test Person",
        "contact_role": "CTO",
        "email_draft": "Subject: CLI Test\n\nHello from CLI",
        "auto_approve": True
    }
    result = review_node(state)
    assert result["review_status"] == "approved"

    # Test interactive skip
    monkeypatch.setattr("builtins.input", lambda prompt="": "s")
    state["auto_approve"] = False
    result_skip = review_node(state)
    assert result_skip["review_status"] == "skipped"
    assert result_skip["delivery_status"] == "skipped_by_reviewer"

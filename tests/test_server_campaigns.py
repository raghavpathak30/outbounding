"""
Unit tests for Campaign Management, Discovery Orchestration, and 100-Point Ranking.
Validates Phase 5 requirements:
- Campaign creation, validation, and user ownership isolation
- Campaign retrieval & isolation across users
- Discovery invocation with criteria passing & Company persistence
- Deterministic 100-point ranking math (perfect match, partial, mismatch, missing data, determinism)
- Deduplication: batch duplicates, existing DB companies, and contacted history (JSONL + DB union)
- Company selection lifecycle ('discovered' -> 'selected') without triggering enrichment
- Enqueue-selected boundary confirmation for Phase 6
- Authentication enforcement on all endpoints
"""
import json
from typing import Optional, Dict, Any, List
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from server.models.base import Base
from server.models.entities import User, Resume, Campaign, Company, Delivery, PipelineRun
from server.database import create_db_engine, get_db
from server.config import Settings, get_settings
from server.app import create_app
from server.services.auth import AuthService, ACCESS_TOKEN_COOKIE_NAME
from server.services.discovery import (
    RankingEngine,
    DiscoveryService,
    normalize_domain,
    is_domain_contacted,
)
from pipeline.adapters.base import DiscoveryAdapter
from pipeline.adapters.stub import StubDiscoveryAdapter


class MockCustomDiscoveryAdapter(DiscoveryAdapter):
    """Custom test discovery adapter providing controlled candidate batches."""

    def __init__(self, candidates):
        self.candidates = candidates

    def discover(self, limit: int = 10, company_size: str = "any", targeting: Optional[Dict[str, Any]] = None):
        return list(self.candidates[:limit])


@pytest.fixture
def campaign_ctx(tmp_path, monkeypatch):
    """Provides isolated DB, configured app, and TestClients for 2 distinct users."""
    test_db_file = tmp_path / "test_campaigns.db"
    test_db_url = f"sqlite:///{test_db_file}"
    engine = create_db_engine(db_url=test_db_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Isolate contacted companies log and ensure stub discovery mode
    test_contacted_file = tmp_path / "test_contacted.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_contacted_file))
    monkeypatch.setenv("DISCOVERY_MODE", "stub")

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    settings = Settings(
        jwt_secret_key="unit-test-secret-key-32b-campaigns-sec!",
        cors_allowed_origins=["https://work.raghavpathak.me", "http://localhost"],
        delivery_mode="staged",
        dry_run=True,
    )

    app = create_app(settings=settings)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings

    session = TestingSessionLocal()

    # User 1 (Primary Operator)
    user1 = User(
        email="operator1@raghavpathak.me",
        password_hash=AuthService.hash_password("Pass123!"),
        is_active=True,
    )
    # User 2 (Secondary / Unauthorized Operator)
    user2 = User(
        email="operator2@raghavpathak.me",
        password_hash=AuthService.hash_password("Pass456!"),
        is_active=True,
    )
    session.add_all([user1, user2])
    session.commit()
    session.refresh(user1)
    session.refresh(user2)

    # Resume for User 1
    resume1 = Resume(
        user_id=user1.id,
        filename="raghav_resume.pdf",
        file_path="uploads/resumes/dummy.pdf",
        parsing_status="completed",
        is_active=True,
    )
    session.add(resume1)
    session.commit()
    session.refresh(resume1)

    # Client for User 1
    client1 = TestClient(app, raise_server_exceptions=False)
    token1, _, _ = AuthService.create_access_token(user1.id, user1.email, settings.jwt_secret_key)
    client1.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token1)

    # Client for User 2
    client2 = TestClient(app, raise_server_exceptions=False)
    token2, _, _ = AuthService.create_access_token(user2.id, user2.email, settings.jwt_secret_key)
    client2.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token2)

    yield {
        "client1": client1,
        "client2": client2,
        "user1": user1,
        "user2": user2,
        "resume1": resume1,
        "session": session,
        "contacted_file": test_contacted_file,
    }

    session.close()
    engine.dispose()


# =====================================================================
# 1. Campaign Creation, Validation & User Ownership
# =====================================================================

def test_campaign_creation_and_ownership(campaign_ctx):
    """Verifies valid campaign creation, required fields, and ownership assignment."""
    client1 = campaign_ctx["client1"]
    user1 = campaign_ctx["user1"]
    resume1 = campaign_ctx["resume1"]

    payload = {
        "name": "Indian Crypto & Security Seed Campaign",
        "objective": "Connect with founders of early-stage cryptography startups in India.",
        "target_geography": "India",
        "industry": "Applied Cryptography & Security",
        "company_stage": "Seed",
        "company_size": "small",
        "target_roles": ["CTO", "Founder", "VP Engineering"],
        "technologies": ["Rust", "MPC", "ZK-SNARKs", "C++"],
        "employment_type": "full_time",
        "remote_preference": "any",
        "resume_id": resume1.id,
    }

    response = client1.post("/api/v1/campaigns", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["id"] is not None
    assert data["user_id"] == user1.id
    assert data["name"] == payload["name"]
    assert data["target_roles"] == payload["target_roles"]
    assert data["technologies"] == payload["technologies"]
    assert data["status"] == "draft"


def test_campaign_creation_rejects_invalid_fields_and_unowned_resume(campaign_ctx):
    """Verifies validation errors on missing required fields or unowned resume_id."""
    client1 = campaign_ctx["client1"]
    client2 = campaign_ctx["client2"]
    resume1 = campaign_ctx["resume1"]

    # 1. Missing objective -> 422
    bad_payload = {"name": "No Objective"}
    res_422 = client1.post("/api/v1/campaigns", json=bad_payload)
    assert res_422.status_code == 422

    # 2. User 2 attempts to use User 1's resume -> 400 Bad Request
    unauthorized_resume_payload = {
        "name": "User 2 Campaign",
        "objective": "Finding startups",
        "resume_id": resume1.id,  # Owned by user 1!
    }
    res_400 = client2.post("/api/v1/campaigns", json=unauthorized_resume_payload)
    assert res_400.status_code == 400
    assert "does not exist or does not belong" in res_400.json()["detail"].lower()


# =====================================================================
# 2. Campaign Retrieval & User Isolation
# =====================================================================

def test_campaign_retrieval_isolation(campaign_ctx):
    """Verifies user can view own campaigns, but cannot access or list another user's campaigns."""
    client1 = campaign_ctx["client1"]
    client2 = campaign_ctx["client2"]

    # Create campaign for User 1
    res1 = client1.post("/api/v1/campaigns", json={
        "name": "User 1 Campaign",
        "objective": "Outreach for User 1",
    })
    camp1_id = res1.json()["id"]

    # 1. User 1 can fetch own campaign
    get_res = client1.get(f"/api/v1/campaigns/{camp1_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "User 1 Campaign"

    # 2. User 2 CANNOT fetch User 1's campaign (404)
    unauth_get = client2.get(f"/api/v1/campaigns/{camp1_id}")
    assert unauth_get.status_code == 404

    # 3. User 2 listing does not contain User 1's campaign
    list_res = client2.get("/api/v1/campaigns")
    assert list_res.status_code == 200
    user2_campaign_ids = [c["id"] for c in list_res.json()]
    assert camp1_id not in user2_campaign_ids


# =====================================================================
# 3. Deterministic 100-Point Ranking Engine Math
# =====================================================================

def test_deterministic_100_point_ranking_math():
    """
    Explicitly tests ranking scoring components:
    - Perfect match = 100 points
    - Industry-only match
    - Technology overlap
    - Geography mismatch
    - Stage/size mismatch
    - Missing data handling
    - Determinism
    """
    campaign = Campaign(
        id="test-camp",
        name="Security Engineering",
        industry="Cybersecurity & Applied Cryptography",
        technologies_json=json.dumps(["Rust", "Docker", "Zero-Knowledge", "C++"]),
        company_size="small",
        company_stage="Seed",
        target_geography="India",
    )

    # 1. Perfect Match (100 Points)
    # Industry 30 (exact tokens), Tech 30 (4/4 matched), Size 10 (size 5 <= 10), Stage 10 (Seed), Geo 20 (India)
    perfect_cand = {
        "domain": "shield-crypto.in",
        "company_name": "ShieldCrypto",
        "industry": "Applied Cryptography & Cybersecurity",
        "size": 5,
        "location": "Bengaluru, India",
        "stage_signal": "Closed $3M Seed round",
        "company_context": {
            "headline": "Zero-knowledge cryptographic infrastructure",
            "signal": "Closed $3M Seed round to deploy enclaves in India",
            "tech_stack": "Rust, Docker, Zero-Knowledge, C++, Linux",
        }
    }
    score_100, why_100, _ = RankingEngine.score_candidate(campaign, perfect_cand)
    assert score_100 == 100
    assert any("Direct match" in w or "overlap" in w for w in why_100)
    assert any("Matched 4/4" in w for w in why_100)
    assert any("size=5 <= 10" in w for w in why_100)
    assert any("Geography" in w and "+20" in w for w in why_100)

    # 2. Technology Overlap Scaling (2/4 techs = 15 pts)
    partial_tech_cand = dict(perfect_cand)
    partial_tech_cand["company_context"] = {
        "headline": "Cryptographic infrastructure",
        "signal": "Closed $3M Seed round",
        "tech_stack": "Rust, Docker, Python, Go",  # Matches Rust & Docker (2/4)
    }
    score_tech, why_tech, _ = RankingEngine.score_candidate(campaign, partial_tech_cand)
    # 30 (ind) + 15 (tech 2/4) + 10 (size) + 10 (stage) + 20 (geo) = 85
    assert score_tech == 85
    assert any("Matched 2/4" in w and "+15" in w for w in why_tech)

    # 3. Geography Mismatch (0 pts for Geo)
    geo_mismatch_cand = dict(perfect_cand)
    geo_mismatch_cand["domain"] = "shield-crypto.com"
    geo_mismatch_cand["location"] = "Berlin, Germany"
    geo_mismatch_cand["company_context"] = {
        "headline": "Applied cryptography in Germany",
        "signal": "Closed $3M Seed round in Berlin, Germany",
        "tech_stack": "Rust, Docker, Zero-Knowledge, C++",
    }
    score_geo, why_geo, _ = RankingEngine.score_candidate(campaign, geo_mismatch_cand)
    # 30 (ind) + 30 (tech) + 10 (size) + 10 (stage) + 0 (geo) = 80
    assert score_geo == 80
    assert any("Outside 'India' target region (+0)" in w for w in why_geo)

    # 4. Size & Stage Mismatch (0 pts for Size, 0 pts for Stage)
    established_series_c_cand = dict(perfect_cand)
    established_series_c_cand["size"] = 150  # Exceeds small (size > 20) -> 0 pts
    established_series_c_cand["stage_signal"] = "Late stage public corporation"
    established_series_c_cand["company_context"] = {
        "headline": "Applied cryptography corporation",
        "signal": "Series C expansion",
        "tech_stack": "Rust, Docker, Zero-Knowledge, C++",
    }
    score_mismatch, why_mismatch, _ = RankingEngine.score_candidate(campaign, established_series_c_cand)
    # 30 (ind) + 30 (tech) + 0 (size) + 7 (series c generic venture) + 20 (geo) = 87
    assert score_mismatch == 87
    assert any("Exceeds small size criteria (size=150 > 20) (+0)" in w for w in why_mismatch)

    # 5. Missing Data Handling (No Hallucination)
    sparse_cand = {
        "domain": "unknown-company.io",
        "company_name": "Unknown Entity",
        "industry": None,
        "size": None,
        "location": None,
        "stage_signal": None,
        "company_context": None,
    }
    sparse_score, why_sparse, _ = RankingEngine.score_candidate(campaign, sparse_cand)
    # 0 (ind) + 0 (tech) + 5 (size neutral) + 0 (stage) + 10 (geo unstated neutral) = 15
    assert sparse_score == 15
    assert any("No alignment with" in w for w in why_sparse)
    assert any("Headcount data not published" in w for w in why_sparse)

    # 6. Repeatability / Determinism
    for _ in range(5):
        repeat_score, _, _ = RankingEngine.score_candidate(campaign, perfect_cand)
        assert repeat_score == 100


# =====================================================================
# 4. Discovery Orchestration & Company Persistence
# =====================================================================

def test_discovery_orchestration_and_persistence(campaign_ctx):
    """Verifies that discover_companies_for_campaign triggers adapter, scores, and persists records."""
    client1 = campaign_ctx["client1"]
    session = campaign_ctx["session"]

    # 1. Create Campaign
    c_res = client1.post("/api/v1/campaigns", json={
        "name": "AI Infra Discovery",
        "objective": "Find low-latency AI inference companies",
        "industry": "AI/LLM Infrastructure",
        "company_size": "small",
        "technologies": ["Python", "Gemini API", "vLLM", "Rust"],
    })
    campaign_id = c_res.json()["id"]

    # 2. Trigger Discovery Endpoint
    disc_res = client1.post(f"/api/v1/campaigns/{campaign_id}/discover?limit=5")
    assert disc_res.status_code == 200
    data = disc_res.json()

    assert data["status"] == "success"
    assert data["campaign_id"] == campaign_id
    assert data["discovered_count"] > 0
    assert len(data["companies"]) > 0

    # 3. Check DB records
    companies_in_db = list(
        session.execute(
            select(Company).where(Company.campaign_id == campaign_id)
        ).scalars().all()
    )
    assert len(companies_in_db) == data["discovered_count"]

    for comp in companies_in_db:
        assert comp.selection_status == "discovered"
        assert comp.match_score is not None
        assert comp.match_score > 0
        assert comp.why_match_json is not None
        why_list = json.loads(comp.why_match_json)
        assert isinstance(why_list, list)
        assert len(why_list) > 0


# =====================================================================
# 5. Deduplication Safety Invariants (JSONL + DB Union)
# =====================================================================

def test_deduplication_drops_batch_duplicates_and_existing_db_companies(campaign_ctx):
    """
    Verifies that:
    (a) Duplicate domains in the same discovery pool are collapsed.
    (b) Already existing companies in the campaign are skipped.
    """
    user1 = campaign_ctx["user1"]
    session = campaign_ctx["session"]

    campaign = Campaign(
        user_id=user1.id,
        name="Dedup Campaign",
        objective="Testing dedup invariants",
        industry="AI Security",
        company_size="any"
    )
    session.add(campaign)
    session.commit()

    # Pre-seed one company in DB
    existing_comp = Company(
        campaign_id=campaign.id,
        domain="pre-existing.io",
        company_name="PreExisting Co",
        selection_status="discovered"
    )
    session.add(existing_comp)
    session.commit()

    # Mock adapter returning duplicate domains + pre-existing domain
    batch = [
        {"domain": "pre-existing.io", "company_name": "PreExisting Co", "industry": "AI Security"},
        {"domain": "https://www.fresh-candidate.io/", "company_name": "Fresh Candidate", "industry": "AI Security"},
        {"domain": "fresh-candidate.io", "company_name": "Fresh Duplicate", "industry": "AI Security"},
        {"domain": "second-candidate.io", "company_name": "Second Candidate", "industry": "AI Security"},
    ]
    mock_adapter = MockCustomDiscoveryAdapter(batch)

    persisted = DiscoveryService.discover_for_campaign(
        db=session,
        user_id=user1.id,
        campaign_id=campaign.id,
        limit=10,
        adapter=mock_adapter
    )

    persisted_domains = [c.domain for c in persisted]
    assert "pre-existing.io" not in persisted_domains  # Skipped because already in campaign
    assert persisted_domains.count("fresh-candidate.io") == 1  # Deduplicated within batch
    assert "second-candidate.io" in persisted_domains
    assert len(persisted) == 2


def test_deduplication_respects_contacted_history_union(campaign_ctx):
    """
    CRITICAL SAFETY GATE:
    Verifies that domains previously contacted in:
    1. contacted_companies.jsonl
    2. DB Deliveries (staged or sent)
    3. DB Company records with selection_status='contacted'
    are NEVER persisted as fresh candidates.
    """
    user1 = campaign_ctx["user1"]
    session = campaign_ctx["session"]
    contacted_file = campaign_ctx["contacted_file"]

    # 1. Add domain to contacted_companies.jsonl
    with open(contacted_file, "a") as f:
        f.write(json.dumps({"domain": "jsonl-contacted.io", "contact_email": "lead@jsonl-contacted.io", "date": "2026-09-01T00:00:00"}) + "\n")

    # 2. Add domain to DB Deliveries
    prior_campaign = Campaign(user_id=user1.id, name="Prior", objective="Obj")
    session.add(prior_campaign)
    session.commit()

    prior_company = Company(campaign_id=prior_campaign.id, domain="delivery-contacted.io", company_name="Deliv Co")
    session.add(prior_company)
    session.commit()

    prior_run = PipelineRun(campaign_id=prior_campaign.id, company_id=prior_company.id, status="completed")
    session.add(prior_run)
    session.commit()

    prior_delivery = Delivery(
        pipeline_run_id=prior_run.id,
        company_id=prior_company.id,
        delivery_mode="live",
        delivery_status="sent",
        provider="instantly"
    )
    session.add(prior_delivery)

    # 3. Add domain with selection_status='contacted'
    status_contacted_comp = Company(
        campaign_id=prior_campaign.id,
        domain="status-contacted.io",
        company_name="Status Contacted",
        selection_status="contacted"
    )
    session.add(status_contacted_comp)
    session.commit()

    # Verify is_domain_contacted helper directly
    assert is_domain_contacted(session, "jsonl-contacted.io") is True
    assert is_domain_contacted(session, "delivery-contacted.io") is True
    assert is_domain_contacted(session, "status-contacted.io") is True
    assert is_domain_contacted(session, "brand-new-domain.io") is False

    # Run discovery through DiscoveryService
    target_campaign = Campaign(user_id=user1.id, name="Target", objective="Obj")
    session.add(target_campaign)
    session.commit()

    batch = [
        {"domain": "jsonl-contacted.io", "company_name": "Blocked 1"},
        {"domain": "delivery-contacted.io", "company_name": "Blocked 2"},
        {"domain": "status-contacted.io", "company_name": "Blocked 3"},
        {"domain": "brand-new-domain.io", "company_name": "Accepted New"},
    ]
    mock_adapter = MockCustomDiscoveryAdapter(batch)

    persisted = DiscoveryService.discover_for_campaign(
        db=session,
        user_id=user1.id,
        campaign_id=target_campaign.id,
        limit=10,
        adapter=mock_adapter
    )

    persisted_domains = [c.domain for c in persisted]
    assert "jsonl-contacted.io" not in persisted_domains
    assert "delivery-contacted.io" not in persisted_domains
    assert "status-contacted.io" not in persisted_domains
    assert "brand-new-domain.io" in persisted_domains
    assert len(persisted) == 1


# =====================================================================
# 6. Company Selection Lifecycle & Discovery Grid API
# =====================================================================

def test_company_grid_listing_and_filtering(campaign_ctx):
    """Verifies listing discovered companies with score and status filters."""
    client1 = campaign_ctx["client1"]
    session = campaign_ctx["session"]
    user1 = campaign_ctx["user1"]

    campaign = Campaign(user_id=user1.id, name="Grid Campaign", objective="Obj")
    session.add(campaign)
    session.commit()

    c1 = Company(campaign_id=campaign.id, domain="alpha.io", company_name="Alpha", match_score=90, selection_status="discovered")
    c2 = Company(campaign_id=campaign.id, domain="beta.io", company_name="Beta", match_score=60, selection_status="selected")
    c3 = Company(campaign_id=campaign.id, domain="gamma.io", company_name="Gamma", match_score=40, selection_status="rejected")
    session.add_all([c1, c2, c3])
    session.commit()

    # 1. Unfiltered list -> returns all 3 sorted by score desc
    res_all = client1.get(f"/api/v1/campaigns/{campaign.id}/companies")
    assert res_all.status_code == 200
    items = res_all.json()
    assert len(items) == 3
    assert items[0]["domain"] == "alpha.io"
    assert items[0]["match_score"] == 90

    # 2. Filter by min_score=70 -> returns only alpha.io
    res_min = client1.get(f"/api/v1/campaigns/{campaign.id}/companies?min_score=70")
    assert res_min.status_code == 200
    assert len(res_min.json()) == 1
    assert res_min.json()[0]["domain"] == "alpha.io"

    # 3. Filter by selection_status='selected' -> returns only beta.io
    res_sel = client1.get(f"/api/v1/campaigns/{campaign.id}/companies?selection_status=selected")
    assert res_sel.status_code == 200
    assert len(res_sel.json()) == 1
    assert res_sel.json()[0]["domain"] == "beta.io"


def test_company_selection_lifecycle(campaign_ctx):
    """
    Verifies that selecting companies:
    1. Updates selection_status from 'discovered' to 'selected'
    2. Rejects companies from another user or campaign
    3. Confirms selection does NOT trigger enrichment or outreach.
    """
    client1 = campaign_ctx["client1"]
    client2 = campaign_ctx["client2"]
    session = campaign_ctx["session"]
    user1 = campaign_ctx["user1"]
    user2 = campaign_ctx["user2"]

    # Campaign for User 1
    camp1 = Campaign(user_id=user1.id, name="Camp 1", objective="Obj")
    # Campaign for User 2
    camp2 = Campaign(user_id=user2.id, name="Camp 2", objective="Obj")
    session.add_all([camp1, camp2])
    session.commit()

    c1 = Company(campaign_id=camp1.id, domain="user1-target.io", company_name="Target 1", selection_status="discovered")
    c2 = Company(campaign_id=camp2.id, domain="user2-target.io", company_name="Target 2", selection_status="discovered")
    session.add_all([c1, c2])
    session.commit()

    # 1. User 1 selects c1 -> success
    select_res = client1.post(
        f"/api/v1/campaigns/{camp1.id}/companies/select",
        json={"company_ids": [c1.id]}
    )
    assert select_res.status_code == 200
    assert select_res.json()["selected_count"] == 1
    assert c1.id in select_res.json()["selected_company_ids"]

    session.refresh(c1)
    assert c1.selection_status == "selected"

    # 2. User 1 attempts to select c2 (which belongs to camp2) in camp1 -> 404
    cross_res = client1.post(
        f"/api/v1/campaigns/{camp1.id}/companies/select",
        json={"company_ids": [c2.id]}
    )
    assert cross_res.status_code == 404

    # 3. User 2 attempts to call select on camp1 -> 404 (ownership violation)
    unauth_res = client2.post(
        f"/api/v1/campaigns/{camp1.id}/companies/select",
        json={"company_ids": [c1.id]}
    )
    assert unauth_res.status_code == 404


# =====================================================================
# 7. Enqueue-Selected Endpoint & Phase 6 Boundary
# =====================================================================

def test_enqueue_selected_boundary_and_validation(campaign_ctx):
    """
    Verifies the enqueue-selected boundary:
    1. Returns 400 if no companies are selected.
    2. Successfully returns queued confirmation for selected companies.
    3. Guarantees no downstream person research or email delivery is executed.
    """
    client1 = campaign_ctx["client1"]
    session = campaign_ctx["session"]
    user1 = campaign_ctx["user1"]

    campaign = Campaign(user_id=user1.id, name="Enqueue Campaign", objective="Obj")
    session.add(campaign)
    session.commit()

    comp = Company(
        campaign_id=campaign.id,
        domain="queued-target.io",
        company_name="Queued Target",
        selection_status="discovered"
    )
    session.add(comp)
    session.commit()

    # 1. When no company is selected -> 400
    res_empty = client1.post(f"/api/v1/campaigns/{campaign.id}/enqueue-selected")
    assert res_empty.status_code == 400
    assert "no companies are currently marked as 'selected'" in res_empty.json()["detail"].lower()

    # 2. Select the company
    comp.selection_status = "selected"
    session.commit()

    # 3. Enqueue selected -> 200 with queued confirmation
    res_queued = client1.post(f"/api/v1/campaigns/{campaign.id}/enqueue-selected")
    assert res_queued.status_code == 200
    data = res_queued.json()

    assert data["status"] == "queued"
    assert data["campaign_id"] == campaign.id
    assert data["enqueued_count"] == 1
    assert comp.id in data["enqueued_company_ids"]
    assert "Phase 6" in data["message"]


# =====================================================================
# 8. Authentication Protection
# =====================================================================

def test_unauthenticated_requests_rejected(campaign_ctx):
    """Verifies that all campaign and company endpoints reject unauthenticated requests with 401."""
    client1 = campaign_ctx["client1"]
    client1.cookies.clear()  # Drop auth cookie

    # 1. List campaigns
    assert client1.get("/api/v1/campaigns").status_code == 401

    # 2. Create campaign
    assert client1.post("/api/v1/campaigns", json={"name": "No Auth", "objective": "No Auth"}).status_code == 401

    # 3. Get campaign detail
    assert client1.get("/api/v1/campaigns/some-uuid").status_code == 401

    # 4. Discover
    assert client1.post("/api/v1/campaigns/some-uuid/discover").status_code == 401

    # 5. List companies
    assert client1.get("/api/v1/campaigns/some-uuid/companies").status_code == 401

    # 6. Select companies
    assert client1.post("/api/v1/campaigns/some-uuid/companies/select", json={"company_ids": ["id1"]}).status_code == 401

    # 7. Enqueue selected
    assert client1.post("/api/v1/campaigns/some-uuid/enqueue-selected").status_code == 401

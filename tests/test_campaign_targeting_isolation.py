"""
Regression Test Suite: Campaign Targeting Isolation & Modularity.
Verifies that LiveDiscoveryAdapter and DiscoveryService execute fully isolated,
per-campaign searches without hardcoded constants, cross-campaign leakage, or shared state.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pipeline.adapters.live import LiveDiscoveryAdapter
from pipeline.adapters.base import AdapterFactory, DiscoveryAdapter
from server.models.entities import Base, User, Campaign, Company
from server.services.discovery import DiscoveryService


def test_live_discovery_adapter_has_no_hardcoded_class_constants():
    """
    Constraint check: LiveDiscoveryAdapter must NOT have ANY hardcoded targeting
    defaults or constants baked into the class itself (e.g. TARGET_KEYWORDS).
    """
    assert not hasattr(LiveDiscoveryAdapter, "TARGET_KEYWORDS"), (
        "TARGET_KEYWORDS must not exist as a class constant on LiveDiscoveryAdapter."
    )


def test_campaign_targeting_payload_isolation(monkeypatch):
    """
    Regression Test: Proves complete isolation between two distinct campaigns.
    Campaign A: India, Cybersecurity, small, techs=["Rust", "ZK-SNARKs"]
    Campaign B: Germany, AI Infrastructure, established, techs=["PyTorch", "CUDA"]
    Asserts each produces a distinct Apollo payload matching only its own fields with zero leakage.
    """
    monkeypatch.setenv("APOLLO_API_KEY", "test_apollo_key")

    targeting_a = {
        "geography": "India",
        "industry": "Cybersecurity",
        "company_size": "small",
        "company_stage": "Seed",
        "technologies": ["Rust", "ZK-SNARKs"],
        "target_roles": ["CISO", "Head of Security"]
    }

    targeting_b = {
        "geography": "Germany",
        "industry": "AI Infrastructure",
        "company_size": "established",
        "company_stage": "Series B",
        "technologies": ["PyTorch", "CUDA"],
        "target_roles": ["VP of AI", "Head of ML Infrastructure"]
    }

    mock_resp_data = {
        "organizations": [
            {
                "id": "org_1",
                "name": "Target Org",
                "primary_domain": "target.io",
                "city": "Bengaluru",
                "country": "India",
                "industry": "Cybersecurity",
                "estimated_num_employees": 5
            }
        ]
    }

    # Test via same adapter instance sequentially to verify zero shared mutable state
    adapter = LiveDiscoveryAdapter()

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_resp_data)

        # 1. Run discovery for Campaign A
        adapter.discover(limit=5, targeting=targeting_a)
        assert mock_post.called
        payload_a = mock_post.call_args[1]["json"]

        # 2. Run discovery for Campaign B
        adapter.discover(limit=5, targeting=targeting_b)
        payload_b = mock_post.call_args[1]["json"]

    # --- Verify Campaign A Payload ---
    assert payload_a["organization_locations"] == ["India"]
    assert "Cybersecurity" in payload_a["q_organization_keyword_tags"]
    assert "Rust" in payload_a["q_organization_keyword_tags"]
    assert "ZK-SNARKs" in payload_a["q_organization_keyword_tags"]
    assert payload_a["organization_num_employees_ranges"] == ["1,10"]

    # Assert NO Campaign B values in Campaign A payload
    assert "Germany" not in payload_a["organization_locations"]
    assert "AI Infrastructure" not in payload_a["q_organization_keyword_tags"]
    assert "PyTorch" not in payload_a["q_organization_keyword_tags"]
    assert "CUDA" not in payload_a["q_organization_keyword_tags"]

    # --- Verify Campaign B Payload ---
    assert payload_b["organization_locations"] == ["Germany"]
    assert "AI Infrastructure" in payload_b["q_organization_keyword_tags"]
    assert "PyTorch" in payload_b["q_organization_keyword_tags"]
    assert "CUDA" in payload_b["q_organization_keyword_tags"]
    assert "21,50" in payload_b["organization_num_employees_ranges"]

    # Assert NO Campaign A values in Campaign B payload
    assert "India" not in payload_b["organization_locations"]
    assert "Cybersecurity" not in payload_b["q_organization_keyword_tags"]
    assert "Rust" not in payload_b["q_organization_keyword_tags"]
    assert "ZK-SNARKs" not in payload_b["q_organization_keyword_tags"]
    assert payload_b["organization_num_employees_ranges"] != ["1,10"]


def test_campaign_targeting_instantiation_isolation(monkeypatch):
    """
    Verifies that separate LiveDiscoveryAdapter instances initialized with per-campaign
    targeting maintain complete independence.
    """
    monkeypatch.setenv("APOLLO_API_KEY", "test_apollo_key")

    adapter_a = LiveDiscoveryAdapter(targeting={
        "geography": "United Kingdom",
        "industry": "Fintech Fraud Detection",
        "company_size": "small"
    })
    adapter_b = LiveDiscoveryAdapter(targeting={
        "geography": "Japan",
        "industry": "Autonomous Robotics",
        "company_size": "established"
    })

    payload_a = adapter_a.build_payload(limit=10)
    payload_b = adapter_b.build_payload(limit=10)

    assert payload_a["organization_locations"] == ["United Kingdom"]
    assert payload_a["q_organization_keyword_tags"] == ["Fintech Fraud Detection"]
    assert payload_a["organization_num_employees_ranges"] == ["1,10"]

    assert payload_b["organization_locations"] == ["Japan"]
    assert payload_b["q_organization_keyword_tags"] == ["Autonomous Robotics"]
    assert "21,50" in payload_b["organization_num_employees_ranges"]


def test_targeting_empty_or_unconstrained_fallbacks(monkeypatch):
    """
    Verifies graceful fallback behavior when campaign leaves fields blank:
    - No location filter if geography is blank or 'any' or 'global'.
    - No keyword tags filter if industry and technologies are blank.
    - No employee range filter if company_size is 'any' or unstated.
    """
    monkeypatch.setenv("APOLLO_API_KEY", "test_apollo_key")

    # (a) Completely empty targeting
    adapter_empty = LiveDiscoveryAdapter(targeting={})
    payload_empty = adapter_empty.build_payload(limit=10)
    assert "organization_locations" not in payload_empty
    assert "q_organization_keyword_tags" not in payload_empty
    assert "organization_num_employees_ranges" not in payload_empty
    assert payload_empty["page"] == 1
    assert payload_empty["per_page"] == 20

    # (b) Geography = 'any', 'global', 'worldwide'
    for generic_geo in ["any", "global", "worldwide", "remote", ""]:
        payload = LiveDiscoveryAdapter(targeting={"geography": generic_geo}).build_payload()
        assert "organization_locations" not in payload, f"Expected no location filter for '{generic_geo}'"

    # (c) Multiple comma-separated locations
    payload_multi = LiveDiscoveryAdapter(targeting={"geography": "United States, Canada"}).build_payload()
    assert payload_multi["organization_locations"] == ["United States", "Canada"]


def test_discovery_service_wires_all_campaign_fields_to_adapter():
    """
    End-to-End Test: Verifies that DiscoveryService.discover_for_campaign extracts
    all stored targeting fields from the database Campaign entity and passes them
    to the DiscoveryAdapter without loss or distortion.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    user = User(
        id="user_test_123",
        email="test@example.com",
        password_hash="test_hash"
    )
    db.add(user)

    campaign = Campaign(
        id="camp_targeting_test",
        user_id="user_test_123",
        name="Targeting Test Campaign",
        objective="Find specialized security startups",
        target_geography="Germany",
        industry="Confidential Computing",
        company_size="small",
        company_stage="Seed",
        target_roles_json=json.dumps(["Chief Information Security Officer", "VP Engineering"]),
        technologies_json=json.dumps(["Rust", "Intel SGX", "AMD SEV"]),
        employment_type="full_time",
        remote_preference="any",
        status="active"
    )
    db.add(campaign)
    db.commit()

    # Create a mock adapter that captures the received targeting dictionary
    captured_calls = []

    class MockCapturingDiscoveryAdapter(DiscoveryAdapter):
        def discover(self, limit=10, company_size="any", targeting=None):
            captured_calls.append({
                "limit": limit,
                "company_size": company_size,
                "targeting": targeting
            })
            return [
                {
                    "domain": "enclave-guard.de",
                    "company_name": "Enclave Guard GmbH",
                    "industry": "Confidential Computing",
                    "location": "Berlin, Germany",
                    "size": 7,
                    "stage": "Seed",
                    "company_context": {
                        "headline": "Enclave security",
                        "signal": "Seed funded confidential computing",
                        "tech_stack": "Rust, Intel SGX"
                    }
                }
            ]

    mock_adapter = MockCapturingDiscoveryAdapter()

    companies = DiscoveryService.discover_for_campaign(
        db=db,
        user_id="user_test_123",
        campaign_id="camp_targeting_test",
        limit=5,
        adapter=mock_adapter
    )

    assert len(captured_calls) == 1
    call = captured_calls[0]
    passed_targeting = call["targeting"]

    assert passed_targeting is not None
    assert passed_targeting["industry"] == "Confidential Computing"
    assert passed_targeting["geography"] == "Germany"
    assert passed_targeting["company_size"] == "small"
    assert passed_targeting["company_stage"] == "Seed"
    assert passed_targeting["target_roles"] == ["Chief Information Security Officer", "VP Engineering"]
    assert passed_targeting["technologies"] == ["Rust", "Intel SGX", "AMD SEV"]

    # Verify candidate was persisted to DB with location extracted
    assert len(companies) == 1
    persisted = companies[0]
    assert persisted.domain == "enclave-guard.de"
    assert persisted.location == "Berlin, Germany"
    assert persisted.industry == "Confidential Computing"
    assert persisted.match_score > 0

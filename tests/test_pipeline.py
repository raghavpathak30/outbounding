"""
Comprehensive Unit Test Suite for LangGraph Outbound Pipeline.
100% Offline with Zero Network Access.
"""
import os
import json
import pytest
import requests
from pathlib import Path
from unittest.mock import patch, MagicMock

from pipeline.state import PipelineState
from pipeline.graph import pipeline_app, has_valid_email
from pipeline.adapters.base import AdapterFactory
from pipeline.adapters.stub import StubEnrichmentAdapter, StubDraftingAdapter, StubDeliveryAdapter, StubDiscoveryAdapter
from pipeline.adapters.live import LiveEnrichmentAdapter, LiveDraftingAdapter, LiveDeliveryAdapter, LiveDiscoveryAdapter, confirm_recipient_count
from pipeline.adapters.research import ResearchDiscoveryAdapter
from pipeline.adapters.person_research import GeminiPersonResearchAdapter, StubPersonResearchAdapter
from pipeline.adapters.email_resolution import HunterEmailResolver, StubEmailResolver
from pipeline.adapters.two_stage import TwoStageEnrichmentAdapter
from pipeline.config import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_DISCOVERY_MODEL,
    DEFAULT_DRAFTING_MODEL,
    DEFAULT_PERSON_RESEARCH_MODEL,
    get_discovery_model,
    get_drafting_model,
    get_person_research_model,
    MIN_EMAIL_CONFIDENCE,
    MIN_PERSON_CONFIDENCE,
    ALLOW_ACCEPT_ALL,
    pace_gemini_call,
    reset_pacing_state,
    execute_with_quota_retry,
    DailyQuotaExhaustedError,
    DAILY_QUOTA_RESET_MESSAGE,
    is_429_error,
    is_daily_quota_error,
    reset_quota_state,
)
from pipeline.drafting import detect_persona, load_resume_context
from pipeline.contacted_log import record_contacted, is_already_contacted, check_volume_caps, load_contacted_log
from main import run_discovered_flow

@pytest.fixture
def resume_data():
    return load_resume_context()

@pytest.fixture(autouse=True)
def isolate_contacted_log(tmp_path, monkeypatch):
    reset_quota_state()
    reset_pacing_state()
    test_log = tmp_path / "test_contacted_companies.jsonl"
    discarded_log = tmp_path / "test_discarded_candidates.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log))
    monkeypatch.setenv("DISCARDED_LOG_FILE", str(discarded_log))
    yield test_log
    reset_quota_state()
    reset_pacing_state()


# 1. Full Pipeline End-to-End against Stub Adapters
def test_stub_pipeline_end_to_end(resume_data, monkeypatch):
    """Verifies complete execution through enrichment, drafting, review, and delivery staging."""
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("AUTO_APPROVE", "true")
    state = {
        "domain": "cyber-corp.com",
        "resume_context": resume_data,
        "auto_approve": True
    }
    result = pipeline_app.invoke(state)
    assert result["domain"] == "cyber-corp.com"
    assert result["contact_name"] == "Marcus Vance"
    assert result["contact_email"] == "marcus.vance@cyber-corp.com"
    assert "Security" in result["contact_role"]
    assert result["email_draft"] is not None
    assert "timing side-channel" in result["email_draft"].lower() or "cryptography" in result["email_draft"].lower()
    assert result["review_status"] == "approved"
    assert result["delivery_status"] == "staged"

# 2. Conditional Routing Bypass on Missing/Invalid Email
def test_conditional_bypass_no_email(resume_data):
    """Verifies that invalid/missing email bypasses drafting and delivery directly to END."""
    # Test router helper
    invalid_state = {"contact_email": None}
    assert has_valid_email(invalid_state) == "skip_node"
    
    bad_format_state = {"contact_email": "invalid-email-string"}
    assert has_valid_email(bad_format_state) == "skip_node"

    # Test full graph execution on bypass domain
    state = {
        "domain": "invalid-domain.org",
        "resume_context": resume_data
    }
    result = pipeline_app.invoke(state)
    assert result["contact_email"] is None
    assert result.get("email_draft") is None
    assert result["delivery_status"] == "skipped_no_email"

# 3. Persona Detection and Pitch Adaptation
def test_persona_drafting_security(resume_data):
    adapter = StubDraftingAdapter()
    draft = adapter.draft(
        role="CISO & Head of Infrastructure",
        domain="fintech-bank.com",
        resume_context=resume_data,
        contact_name="Alice Smith"
    )
    assert "Alice Smith" in draft
    assert "timing side-channel" in draft.lower() or "dss modular arithmetic" in draft.lower() or "homomorphic" in draft.lower()

def test_persona_drafting_ai_ml(resume_data):
    adapter = StubDraftingAdapter()
    draft = adapter.draft(
        role="VP of AI & Applied Machine Learning",
        domain="ai-cloud.io",
        resume_context=resume_data,
        contact_name="Bob Jones"
    )
    assert "Bob Jones" in draft
    assert "gemini" in draft.lower() or "google ai studio" in draft.lower() or "multi-agent" in draft.lower()

def test_persona_drafting_hr_talent(resume_data):
    adapter = StubDraftingAdapter()
    draft = adapter.draft(
        role="Director of Technical Recruiting",
        domain="scale-talent.com",
        resume_context=resume_data,
        contact_name="Carol White"
    )
    assert "Carol White" in draft
    assert "lnmiit" in draft.lower() or "iit hyderabad" in draft.lower()

# 4. Enrichment Fallback Cascade (Apollo -> PhantomBuster -> Hunter)
def test_live_enrichment_fallback_cascade(monkeypatch):
    """Mocks API failures sequentially to verify Apollo -> PhantomBuster -> Hunter fallback."""
    monkeypatch.setenv("APOLLO_API_KEY", "fake_apollo")
    monkeypatch.setenv("PHANTOMBUSTER_API_KEY", "fake_phantom")
    monkeypatch.setenv("HUNTER_API_KEY", "fake_hunter")
    
    adapter = LiveEnrichmentAdapter()

    # Scenario A: Apollo succeeds
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"person": {"first_name": "John", "last_name": "Doe", "email": "johndoe@test.com", "title": "CTO"}}
        )
        res = adapter.enrich("test.com")
        assert res["contact_email"] == "johndoe@test.com"

    # Scenario B: Apollo fails (500), PhantomBuster succeeds
    with patch("requests.post") as mock_post:
        mock_post.side_effect = [
            MagicMock(status_code=500), # Apollo fails
            MagicMock(status_code=200, json=lambda: {"output": {"name": "Jane Roe", "email": "janeroe@test.com", "role": "Lead"}}) # Phantom succeeds
        ]
        res = adapter.enrich("test.com")
        assert res["contact_email"] == "janeroe@test.com"

# 5. Hunter Verification Rejection Test
def test_hunter_unverified_email_rejected(monkeypatch):
    """Ensures Live Hunter fallback rejects pattern-guessed emails if unverified."""
    monkeypatch.setenv("HUNTER_API_KEY", "fake_hunter")
    adapter = LiveEnrichmentAdapter()

    with patch.object(adapter, "_try_apollo", return_value=None):
        with patch.object(adapter, "_try_phantombuster", return_value=None):
            with patch("requests.get") as mock_get:
                # 1st call: domain-search finds candidate email
                # 2nd call: email-verifier returns status="invalid"
                mock_get.side_effect = [
                    MagicMock(status_code=200, json=lambda: {"data": {"emails": [{"value": "guessed@unverified.com"}]}}),
                    MagicMock(status_code=200, json=lambda: {"data": {"status": "invalid"}})
                ]
                res = adapter.enrich("unverified.com")
                assert res["contact_email"] is None

# 6. Delivery Staging & Safety Invariants
def test_delivery_staging_creates_file():
    adapter = StubDeliveryAdapter()
    payload = {
        "domain": "safety-check.com",
        "recipient": {"name": "Dave", "email": "dave@safety-check.com"},
        "email_body": "Test outreach body"
    }
    res = adapter.deliver(payload, dry_run=True, confirm_live=False)
    assert res["status"] == "staged"
    staged_file = Path(res["file"])
    assert staged_file.exists()
    content = json.loads(staged_file.read_text())
    assert content["payload"]["domain"] == "safety-check.com"

def test_live_delivery_dry_run_blocks_network(monkeypatch):
    """Verifies that LiveDeliveryAdapter never touches requests.post when dry_run=True."""
    adapter = LiveDeliveryAdapter()
    payload = {"domain": "secure.io", "recipient": {"email": "test@secure.io"}}
    
    with patch("requests.post") as mock_post:
        res = adapter.deliver(payload, dry_run=True, confirm_live=False)
        assert res["status"] == "staged"
        mock_post.assert_not_called()

# 7. Mocked Gemini Prompt Construction Test
def test_live_drafting_prompt_construction(monkeypatch, resume_data):
    """
    Mocks the Gemini call (not a live call) to verify prompt construction:
    checks persona instructions, recipient metadata, and exact resume bullets passed to the model.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock_gemini_key_for_test")
    adapter = LiveDraftingAdapter()

    # 1. Security Persona Prompt Check
    sec_prompt, sec_bullets, sec_cat = adapter.build_prompt(
        role="Principal Security Engineer & Cryptography Lead",
        domain="apex-vault-fintech.io",
        resume_context=resume_data,
        contact_name="Devon Sterling"
    )
    assert sec_cat == "security_infrastructure"
    assert "timing side-channel" in sec_prompt.lower()
    assert "dss modular arithmetic" in sec_prompt.lower()
    assert "ckks homomorphic encryption" in sec_prompt.lower()
    assert "Devon Sterling" in sec_prompt
    assert "apex-vault-fintech.io" in sec_prompt
    # Assert prompt instructions for length cap, portfolio link, anti-fabrication prohibition, and low-friction ask
    assert "80-100 words" in sec_prompt or "80-100" in sec_prompt
    assert "portfolio link" in sec_prompt.lower()
    assert resume_data.get("personal", {}).get("portfolio", "https://raghavpathak.dev") in sec_prompt
    assert "anti-fabrication" in sec_prompt.lower() or "strict prohibition" in sec_prompt.lower()
    assert "never claim" in sec_prompt.lower()
    assert "grounded" in sec_prompt.lower()
    assert "low-friction" in sec_prompt.lower()
    assert len(sec_bullets) >= 2
    for bullet in sec_bullets:
        assert bullet in sec_prompt

    # 2. AI/ML Persona Prompt Check
    ai_prompt, ai_bullets, ai_cat = adapter.build_prompt(
        role="VP of AI Systems & Low-Latency LLM Infrastructure",
        domain="hyperion-inference-labs.io",
        resume_context=resume_data,
        contact_name="Dr. Maya Lin"
    )
    assert ai_cat == "ai_machine_learning"
    assert "gemini api integrations" in ai_prompt.lower()
    assert "google ai studio" in ai_prompt.lower()
    assert "Dr. Maya Lin" in ai_prompt
    assert "hyperion-inference-labs.io" in ai_prompt
    for bullet in ai_bullets:
        assert bullet in ai_prompt

    # 3. HR/Talent Persona Prompt Check
    hr_prompt, hr_bullets, hr_cat = adapter.build_prompt(
        role="Director of Technical Talent Acquisition",
        domain="nexus-talent-partners.co",
        resume_context=resume_data,
        contact_name="Julian Rivera"
    )
    assert hr_cat == "hr_talent_acquisition"
    assert "ats-optimized" in hr_prompt.lower()
    assert "lnmiit" in hr_prompt.lower()
    assert "Julian Rivera" in hr_prompt
    assert "nexus-talent-partners.co" in hr_prompt
    for bullet in hr_bullets:
        assert bullet in hr_prompt

    # 4. Mock the Gemini ChatGoogleGenerativeAI call to verify exact payload invocation
    with patch("langchain_google_genai.ChatGoogleGenerativeAI") as MockLLMClass:
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value = MagicMock(
            content="Mocked Gemini Draft: Impressed by your security architecture at apex-vault-fintech.io."
        )
        MockLLMClass.return_value = mock_llm_instance

        draft = adapter.draft(
            role="Chief Information Security Officer",
            domain="apex-vault-fintech.io",
            resume_context=resume_data,
            contact_name="Devon Sterling"
        )
        assert "Mocked Gemini Draft" in draft

        # Verify MockLLMClass was instantiated with gemini model and api_key
        MockLLMClass.assert_called_once()
        call_kwargs = MockLLMClass.call_args[1]
        assert "gemini" in call_kwargs.get("model", "")
        assert call_kwargs.get("google_api_key") == "mock_gemini_key_for_test"

        # Verify invoke was passed the constructed prompt containing our persona instructions
        mock_llm_instance.invoke.assert_called_once()
        invoked_payload = mock_llm_instance.invoke.call_args[0][0]
        assert isinstance(invoked_payload, list)
        prompt_content = invoked_payload[0]["content"]
        assert "timing side-channel" in prompt_content.lower()
        assert "Devon Sterling" in prompt_content

# 8. Groundable Company Context Test
def test_live_drafting_company_context_grounding(resume_data, monkeypatch):
    """
    Verifies that LiveDraftingAdapter:
    (a) Uses company_context in the prompt and grounds opener in fallback when present.
    (b) Falls back to honest generic opener and strict anti-fabrication prohibition when company_context is missing/empty.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    adapter = LiveDraftingAdapter()

    # (a) When company_context is present
    company_ctx = {
        "headline": "Series B fintech scaling zero-knowledge asset custody",
        "signal": "Announced $28M Series B expansion to build out privacy-preserving encrypted settlement architecture",
        "tech_stack": "Rust, AWS Nitro Enclaves, HSMs"
    }
    prompt_with_ctx, _, _ = adapter.build_prompt(
        role="Chief Information Security Officer & VP Infrastructure",
        domain="apex-vault-fintech.io",
        resume_context=resume_data,
        contact_name="Devon Sterling",
        company_context=company_ctx
    )
    assert "Verified Target Company Signal" in prompt_with_ctx
    assert "Announced $28M Series B expansion" in prompt_with_ctx
    assert "GROUNDED OPENING REQUIRED" in prompt_with_ctx

    # Offline fallback with company_context
    draft_with_ctx = adapter.draft(
        role="Chief Information Security Officer & VP Infrastructure",
        domain="apex-vault-fintech.io",
        resume_context=resume_data,
        contact_name="Devon Sterling",
        company_context=company_ctx
    )
    assert "Series B expansion" in draft_with_ctx
    assert "Saw apex-vault-fintech.io's announcement" in draft_with_ctx

    # (b) When company_context is missing or None
    prompt_no_ctx, _, _ = adapter.build_prompt(
        role="Chief Information Security Officer & VP Infrastructure",
        domain="apex-vault-fintech.io",
        resume_context=resume_data,
        contact_name="Devon Sterling",
        company_context=None
    )
    assert "Verified Target Company Signal: None" in prompt_no_ctx
    assert "STRICT PROHIBITION: NEVER claim or imply prior familiarity" in prompt_no_ctx

    # Offline fallback with missing company_context
    draft_no_ctx = adapter.draft(
        role="Chief Information Security Officer & VP Infrastructure",
        domain="apex-vault-fintech.io",
        resume_context=resume_data,
        contact_name="Devon Sterling",
        company_context=None
    )
    assert "I'm reaching out directly given your infrastructure security leadership" in draft_no_ctx
    assert "saw your team's work" not in draft_no_ctx.lower()
    assert "following your engineering updates" not in draft_no_ctx.lower()

# 9. Hunter.io Verification: Valid Email Flows to Drafting
def test_hunter_email_verification_valid_flows_to_drafting(monkeypatch, resume_data):
    """
    Verifies that when Hunter pattern fallback returns a verified 'valid' email,
    it successfully passes the gate, flows into drafting_node, and gets staged.
    """
    monkeypatch.setenv("APOLLO_MODE", "live")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("AUTO_APPROVE", "true")
    monkeypatch.setenv("HUNTER_API_KEY", "fake_hunter")

    adapter = LiveEnrichmentAdapter()
    with patch.object(adapter, "_try_apollo", return_value=None):
        with patch.object(adapter, "_try_phantombuster", return_value=None):
            with patch("requests.get") as mock_get:
                mock_get.side_effect = [
                    MagicMock(status_code=200, json=lambda: {"data": {"emails": [{"value": "lead@verified-security.com"}]}}),
                    MagicMock(status_code=200, json=lambda: {"data": {"status": "valid"}})
                ]
                enriched = adapter.enrich("verified-security.com")
                assert enriched["contact_email"] == "lead@verified-security.com"

    # End-to-end graph test with LiveEnrichmentAdapter mocked to return valid email
    with patch("pipeline.enrichment.AdapterFactory.get_enrichment_adapter") as mock_get_adapter:
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.enrich.return_value = {
            "domain": "verified-security.com",
            "contact_name": "Devon Sterling",
            "contact_email": "devon.sterling@verified-security.com",
            "contact_role": "Head of Security",
            "source": "live_hunter_verified"
        }
        mock_get_adapter.return_value = mock_adapter_instance

        state = {
            "domain": "verified-security.com",
            "resume_context": resume_data,
            "auto_approve": True
        }
        result = pipeline_app.invoke(state)
        assert result["contact_email"] == "devon.sterling@verified-security.com"
        assert result["email_draft"] is not None
        assert result["delivery_status"] == "staged"

# 10. Hunter.io Verification: Ambiguous and Invalid Emails Route to Skip Node
def test_hunter_email_verification_ambiguous_and_invalid_rejected(monkeypatch, resume_data):
    """
    Verifies that when Hunter verifier returns 'accept_all', 'unknown', or 'invalid',
    the pattern guess is rejected (contact_email=None) and routes to skip_node.
    """
    monkeypatch.setenv("APOLLO_MODE", "live")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("AUTO_APPROVE", "true")
    monkeypatch.setenv("HUNTER_API_KEY", "fake_hunter")

    adapter = LiveEnrichmentAdapter()

    # Test status extraction in _verify_email
    for status in ["accept_all", "unknown", "invalid"]:
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda s=status: {"data": {"status": s}})
            assert adapter._verify_email(f"test@{status}.com") == status

    # Test cascade rejection for each non-valid status
    for reject_status in ["accept_all", "unknown", "invalid"]:
        with patch.object(adapter, "_try_apollo", return_value=None):
            with patch.object(adapter, "_try_phantombuster", return_value=None):
                with patch("requests.get") as mock_get:
                    mock_get.side_effect = [
                        MagicMock(status_code=200, json=lambda: {"data": {"emails": [{"value": f"guess@{reject_status}.com"}]}}),
                        MagicMock(status_code=200, json=lambda s=reject_status: {"data": {"status": s}})
                    ]
                    enriched = adapter.enrich(f"{reject_status}-target.com")
                    assert enriched["contact_email"] is None

    # End-to-end graph test with rejected unverified email routing to skip_node
    with patch("pipeline.enrichment.AdapterFactory.get_enrichment_adapter") as mock_get_adapter:
        mock_adapter_instance = MagicMock()
        mock_adapter_instance.enrich.return_value = {
            "domain": "ambiguous-corp.com",
            "contact_name": None,
            "contact_email": None,
            "contact_role": None,
            "source": "live_unverified_rejected"
        }
        mock_get_adapter.return_value = mock_adapter_instance

        state = {
            "domain": "ambiguous-corp.com",
            "resume_context": resume_data,
            "auto_approve": True
        }
        result = pipeline_app.invoke(state)
        assert result["contact_email"] is None
        assert result.get("email_draft") is None
        assert result["delivery_status"] == "skipped_no_email"

# 11. Stub Verification Gate: Accept and Reject Paths
def test_stub_verification_accept_and_reject(resume_data, monkeypatch):
    """
    Verifies StubEnrichmentAdapter's stub verifier returns valid vs invalid/accept_all/unknown,
    and tests both accept and reject routing through the graph.
    """
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("AUTO_APPROVE", "true")

    adapter = StubEnrichmentAdapter()
    assert adapter._verify_email("user@verified-corp.io") == "valid"
    assert adapter._verify_email("user@unverified-test.io") == "invalid"
    assert adapter._verify_email("user@accept-all-test.io") == "accept_all"
    assert adapter._verify_email("user@ambiguous-test.io") == "unknown"
    assert adapter._verify_email("user@unknown-test.io") == "unknown"

    # Accept path: valid domain flows through to drafting and staging
    accept_state = {
        "domain": "apex-vault-fintech.io",
        "resume_context": resume_data,
        "auto_approve": True
    }
    accept_result = pipeline_app.invoke(accept_state)
    assert accept_result["contact_email"] is not None
    assert accept_result["email_draft"] is not None
    assert accept_result["delivery_status"] == "staged"

    # Reject path: unverified domain routes to skip_node
    reject_state = {
        "domain": "unverified-fintech.io",
        "resume_context": resume_data,
        "auto_approve": True
    }
    reject_result = pipeline_app.invoke(reject_state)
    assert reject_result["contact_email"] is None
    assert reject_result.get("email_draft") is None
    assert reject_result["delivery_status"] == "skipped_no_email"

# 12. Manual Review Checkpoint: Approve Path
def test_review_checkpoint_approve(resume_data, monkeypatch):
    """Verifies that entering 'a' approves the draft and proceeds to delivery staging."""
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("AUTO_APPROVE", "false")

    state = {
        "domain": "apex-vault-fintech.io",
        "resume_context": resume_data,
        "auto_approve": False
    }
    with patch("builtins.input", return_value="a"):
        result = pipeline_app.invoke(state)

    assert result["review_status"] == "approved"
    assert result["delivery_status"] == "staged"
    assert result["email_draft"] is not None

# 13. Manual Review Checkpoint: Edit Path
def test_review_checkpoint_edit(resume_data, monkeypatch):
    """
    Verifies that entering 'e' allows entering a replacement body,
    which updates email_draft in PipelineState and flows through to delivery staging.
    """
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("AUTO_APPROVE", "false")

    state = {
        "domain": "apex-vault-fintech.io",
        "resume_context": resume_data,
        "auto_approve": False
    }
    replacement_text = "I reviewed your enclave architecture and wanted to share our CKKS benchmarks directly."
    input_sequence = ["e", replacement_text, "END"]

    with patch("builtins.input", side_effect=input_sequence):
        result = pipeline_app.invoke(state)

    assert result["review_status"] == "approved"
    assert result["delivery_status"] == "staged"
    assert replacement_text in result["email_draft"]

    # Verify staged payload file on disk contains the edited replacement text
    staged_dir = Path("staged_deliveries")
    assert staged_dir.exists()
    staged_files = sorted(staged_dir.glob("staged_apex-vault-fintech*.json"))
    assert len(staged_files) > 0
    latest_staged = staged_files[-1]
    payload = json.loads(latest_staged.read_text())
    assert replacement_text in payload["payload"]["email_body"]

# 14. Manual Review Checkpoint: Skip Path
def test_review_checkpoint_skip(resume_data, monkeypatch):
    """
    Verifies that entering 's' sets delivery_status='skipped_by_reviewer',
    routes to END, and bypasses delivery staging.
    """
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("AUTO_APPROVE", "false")

    state = {
        "domain": "apex-vault-fintech.io",
        "resume_context": resume_data,
        "auto_approve": False
    }
    with patch("builtins.input", return_value="s"):
        result = pipeline_app.invoke(state)

    assert result["review_status"] == "skipped"
    assert result["delivery_status"] == "skipped_by_reviewer"

# 15. Manual Review Checkpoint: Auto-Approve Flag
def test_review_checkpoint_auto_approve(resume_data, monkeypatch):
    """Verifies that auto_approve=True bypasses the interactive prompt entirely."""
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")

    state = {
        "domain": "apex-vault-fintech.io",
        "resume_context": resume_data,
        "auto_approve": True
    }
    with patch("builtins.input") as mock_input:
        result = pipeline_app.invoke(state)
        mock_input.assert_not_called()

    assert result["review_status"] == "approved"
    assert result["delivery_status"] == "staged"

# 16. CLI Safety Invariant: --confirm-live cannot coexist with --auto-approve
def test_cli_safety_rejects_confirm_live_with_auto_approve(monkeypatch, capsys):
    """
    Asserts that passing --confirm-live together with --auto-approve immediately exits
    with a safety violation error before the pipeline graph is ever invoked.
    """
    import main as main_module

    test_args = ["main.py", "--domain", "apex-vault-fintech.io", "--confirm-live", "--auto-approve"]
    monkeypatch.setattr("sys.argv", test_args)

    with patch("main.pipeline_app.invoke") as mock_invoke:
        with pytest.raises(SystemExit) as exc_info:
            main_module.main()

        assert exc_info.value.code != 0
        mock_invoke.assert_not_called()

    captured = capsys.readouterr()
    err_output = captured.err
    assert "cannot be combined with --auto-approve" in err_output
    assert "manual review" in err_output

# 17. Apollo.io Enrichment: Successful Match with Organization Context
def test_apollo_enrichment_success_with_company_context(monkeypatch):
    """Verifies that LiveEnrichmentAdapter correctly queries Apollo.io, parses person & org data."""
    monkeypatch.setenv("APOLLO_API_KEY", "real_like_apollo_key")
    adapter = LiveEnrichmentAdapter()

    apollo_response = {
        "person": {
            "first_name": "Devon",
            "last_name": "Sterling",
            "name": "Devon Sterling",
            "title": "Chief Information Security Officer & VP Infrastructure",
            "email": "devon.sterling@apex-vault-fintech.io",
            "organization": {
                "name": "Apex Vault Fintech",
                "short_description": "Series B fintech scaling zero-knowledge asset custody",
                "industry": "Financial Technology & Cybersecurity",
                "total_funding_printed": "$28M",
                "keywords": ["Fintech", "Security", "Custody", "Zero-Knowledge"],
                "technology_names": ["Rust", "AWS Nitro Enclaves", "HSMs", "C++"]
            }
        }
    }

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: apollo_response)
        result = adapter.enrich("apex-vault-fintech.io")

        mock_post.assert_called_once()
        call_args, call_kwargs = mock_post.call_args
        assert "api.apollo.io/v1/people/match" in call_args[0]
        assert call_kwargs["json"]["domain"] == "apex-vault-fintech.io"
        assert call_kwargs["headers"]["X-Api-Key"] == "real_like_apollo_key"

        assert result["contact_name"] == "Devon Sterling"
        assert result["contact_email"] == "devon.sterling@apex-vault-fintech.io"
        assert result["contact_role"] == "Chief Information Security Officer & VP Infrastructure"
        assert result["company_context"] is not None
        assert "zero-knowledge asset custody" in result["company_context"]["headline"].lower()
        assert "$28M" in result["company_context"]["signal"]
        assert "Rust" in result["company_context"]["tech_stack"]

# 18. Apollo.io Enrichment: Rate Limit (429) Graceful Fallback
def test_apollo_enrichment_rate_limit_429_graceful_fallback(monkeypatch):
    """Verifies that Apollo 429 rate limit logs a warning and falls through to PhantomBuster."""
    monkeypatch.setenv("APOLLO_API_KEY", "test_key")
    monkeypatch.setenv("PHANTOMBUSTER_API_KEY", "test_phantom_key")
    adapter = LiveEnrichmentAdapter()

    with patch("requests.post") as mock_post:
        # 1st call Apollo (429), 2nd call PhantomBuster (200)
        mock_post.side_effect = [
            MagicMock(status_code=429, text="Rate limit exceeded"),
            MagicMock(status_code=200, json=lambda: {"output": {"name": "Jane Roe", "email": "janeroe@test.com", "role": "Lead"}})
        ]
        result = adapter.enrich("ratelimit-domain.com")
        assert result["contact_email"] == "janeroe@test.com"

# 19. Apollo.io Enrichment: Auth Failure (401/403) Graceful Fallback
def test_apollo_enrichment_auth_failure_401_403_graceful_fallback(monkeypatch):
    """Verifies that Apollo 401/403 auth failure degrades gracefully into fallback."""
    monkeypatch.setenv("APOLLO_API_KEY", "bad_key")
    monkeypatch.setenv("PHANTOMBUSTER_API_KEY", "test_phantom_key")
    adapter = LiveEnrichmentAdapter()

    for auth_code in [401, 403]:
        with patch("requests.post") as mock_post:
            mock_post.side_effect = [
                MagicMock(status_code=auth_code, text="Unauthorized"),
                MagicMock(status_code=200, json=lambda: {"output": {"name": "Jane Roe", "email": f"jane_{auth_code}@test.com", "role": "Lead"}})
            ]
            result = adapter.enrich("auth-fail-domain.com")
            assert result["contact_email"] == f"jane_{auth_code}@test.com"

# 20. Apollo.io Enrichment: No Match & Malformed Responses
def test_apollo_enrichment_no_match_and_malformed_response(monkeypatch):
    """Verifies that empty/malformed responses from Apollo fall through gracefully."""
    monkeypatch.setenv("APOLLO_API_KEY", "test_key")
    monkeypatch.setenv("PHANTOMBUSTER_API_KEY", "test_phantom_key")
    adapter = LiveEnrichmentAdapter()

    # Case A: No person in payload
    with patch("requests.post") as mock_post:
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"person": None}),
            MagicMock(status_code=200, json=lambda: {"output": {"name": "Jane Roe", "email": "janeroe@test.com", "role": "Lead"}})
        ]
        res = adapter.enrich("no-match.com")
        assert res["contact_email"] == "janeroe@test.com"

    # Case B: Person has no email
    with patch("requests.post") as mock_post:
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"person": {"name": "No Email", "email": None}}),
            MagicMock(status_code=200, json=lambda: {"output": {"name": "Jane Roe", "email": "janeroe@test.com", "role": "Lead"}})
        ]
        res = adapter.enrich("no-email.com")
        assert res["contact_email"] == "janeroe@test.com"

# 21. PhantomBuster Error Handling: Rate Limit and Auth Failure
def test_phantombuster_rate_limit_and_auth_failure(monkeypatch):
    """Verifies PhantomBuster rate limits and auth errors fall through to Hunter."""
    monkeypatch.setenv("APOLLO_API_KEY", "fake_apollo")
    monkeypatch.setenv("PHANTOMBUSTER_API_KEY", "fake_phantom")
    monkeypatch.setenv("HUNTER_API_KEY", "fake_hunter")
    adapter = LiveEnrichmentAdapter()

    with patch("requests.post") as mock_post:
        with patch("requests.get") as mock_get:
            # Apollo fails (429), PhantomBuster fails (429)
            mock_post.side_effect = [
                MagicMock(status_code=429),
                MagicMock(status_code=429)
            ]
            # Hunter succeeds with valid candidate
            mock_get.side_effect = [
                MagicMock(status_code=200, json=lambda: {"data": {"emails": [{"value": "hunter_lead@test.com"}]}}),
                MagicMock(status_code=200, json=lambda: {"data": {"status": "valid"}})
            ]
            result = adapter.enrich("hunter-fallback.com")
            assert result["contact_email"] == "hunter_lead@test.com"

# 22. Full Fallback Cascade: Apollo Fails -> PhantomBuster Fails -> Hunter Succeeds
def test_full_fallback_cascade_apollo_to_phantombuster_to_hunter(monkeypatch):
    """
    Simulates complete fallback cascade:
    Apollo (auth 401) -> PhantomBuster (rate limit 429) -> Hunter (domain-search + email-verifier valid).
    """
    monkeypatch.setenv("APOLLO_API_KEY", "bad_key")
    monkeypatch.setenv("PHANTOMBUSTER_API_KEY", "ratelimited_key")
    monkeypatch.setenv("HUNTER_API_KEY", "valid_hunter_key")

    adapter = LiveEnrichmentAdapter()

    with patch("requests.post") as mock_post:
        with patch("requests.get") as mock_get:
            mock_post.side_effect = [
                MagicMock(status_code=401), # Apollo auth fail
                MagicMock(status_code=429)  # PhantomBuster rate limit
            ]
            mock_get.side_effect = [
                MagicMock(status_code=200, json=lambda: {"data": {"emails": [{"value": "fallback@cascade.com"}]}}), # Hunter search
                MagicMock(status_code=200, json=lambda: {"data": {"status": "valid"}})                                # Hunter verifier
            ]
            result = adapter.enrich("cascade.com")
            assert result["contact_email"] == "fallback@cascade.com"

# 23. Rate Limiting Politeness: ENRICHMENT_DELAY_MS configuration in Batch Run
def test_enrichment_batch_delay_ms_config(monkeypatch):
    """Verifies that ENRICHMENT_DELAY_MS env var induces a polite sleep between batch domain queries."""
    import main as main_module

    monkeypatch.setenv("ENRICHMENT_DELAY_MS", "250")
    monkeypatch.setenv("AUTO_APPROVE", "true")
    monkeypatch.setattr("sys.argv", ["main.py", "--auto-approve"])

    with patch("time.sleep") as mock_sleep:
        with patch("main.run_single_domain") as mock_run:
            main_module.main()

            # Default sample run has 3 domains: sleep should be called for 2nd and 3rd domains
            assert mock_sleep.call_count == 2
            mock_sleep.assert_called_with(0.25)
            assert mock_run.call_count == 3

# 24. Live Delivery Safety Gate: Webhook Never Called Unless All 4 Conditions Met
def test_live_delivery_safety_gate_blocks_unless_all_conditions_met(monkeypatch, caplog):
    """
    CRITICAL SAFETY INVARIANT:
    Asserts that if DRY_RUN=true OR --confirm-live is absent OR review_status is not 'approved'
    OR DELIVERY_MODE is 'stub', the live send webhook POST is NEVER called (zero calls in each case),
    and execution safely falls back to staging-only behavior with a clear log reason.
    """
    adapter = LiveDeliveryAdapter()
    LiveDeliveryAdapter.reset_safety_state()
    sample_payload = {
        "domain": "safety-test.io",
        "recipient": {"name": "Jordan Lee", "email": "jordan@safety-test.io", "role": "VP Security"},
        "email_subject": "Quick collab",
        "email_body": "Hello Jordan"
    }

    # Case A: DRY_RUN=true (even with confirm_live=True, review_status='approved', DELIVERY_MODE='live')
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("CONFIRM_LIVE", "true")
    with patch("requests.post") as mock_post:
        res = adapter.deliver(sample_payload, dry_run=True, confirm_live=True, review_status="approved")
        assert res["status"] == "staged"
        mock_post.assert_not_called()

    # Case B: --confirm-live is False / absent (even with dry_run=False, review_status='approved', DELIVERY_MODE='live')
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "false")
    with patch("requests.post") as mock_post:
        res = adapter.deliver(sample_payload, dry_run=False, confirm_live=False, review_status="approved")
        assert res["status"] == "staged"
        mock_post.assert_not_called()

    # Case C: review_status is not 'approved' (e.g. 'skipped' or None, even with dry_run=False, confirm_live=True, DELIVERY_MODE='live')
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")
    for unapproved_status in ["skipped", None, "pending", "rejected"]:
        with patch("requests.post") as mock_post:
            res = adapter.deliver(sample_payload, dry_run=False, confirm_live=True, review_status=unapproved_status)
            assert res["status"] == "staged"
            mock_post.assert_not_called()

    # Case D: DELIVERY_MODE is 'stub' (even with dry_run=False, confirm_live=True, review_status='approved')
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")
    with patch("requests.post") as mock_post:
        res = adapter.deliver(sample_payload, dry_run=False, confirm_live=True, review_status="approved")
        assert res["status"] == "staged"
        mock_post.assert_not_called()

# 25. First-Real-Send Confirmation Gate: Reject Mismatched Typed Number
def test_live_delivery_recipient_count_confirmation_gate(monkeypatch):
    """
    Verifies that the first-real-send confirmation friction gate:
    (a) Rejects mismatched typed numbers (returns False)
    (b) Accepts matching typed number (returns True)
    (c) In LiveDeliveryAdapter, a rejected confirmation halts dispatch and marks status='failed' without calling requests.post.
    """
    LiveDeliveryAdapter.reset_safety_state()

    sample_recipients = [
        {"email": "lead1@alpha.io", "domain": "alpha.io", "name": "Lead Alpha"},
        {"email": "lead2@beta.io", "domain": "beta.io", "name": "Lead Beta"},
        {"email": "lead3@gamma.io", "domain": "gamma.io", "name": "Lead Gamma"},
    ]

    # (a) Mismatched typed number (types "2" when count is 3, or "no", or wrong input)
    with patch("builtins.input", return_value="2"):
        assert confirm_recipient_count(sample_recipients) is False

    with patch("builtins.input", return_value="yes"):
        assert confirm_recipient_count(sample_recipients) is False

    # (b) Correct typed count (types "3" when count is 3)
    with patch("builtins.input", return_value="3"):
        assert confirm_recipient_count(sample_recipients) is True

    # (c) LiveDeliveryAdapter integration: rejected confirmation halts live dispatch
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")
    monkeypatch.setenv("INSTANTLY_API_KEY", "real_like_key")

    adapter = LiveDeliveryAdapter()
    LiveDeliveryAdapter.reset_safety_state()

    payload = {
        "domain": "reject-confirm.io",
        "recipient": {"name": "Test User", "email": "test@reject-confirm.io"},
        "email_subject": "Test",
        "email_body": "Body"
    }

    with patch("builtins.input", return_value="999"):  # Mismatched number
        with patch("requests.post") as mock_post:
            res = adapter.deliver(payload, dry_run=False, confirm_live=True, review_status="approved")
            assert res["status"] == "failed"
            assert "confirmation rejected" in res["error"]
            mock_post.assert_not_called()

# 26. Live Delivery Webhook: Successful Dispatch (Instantly API)
def test_live_delivery_success_instantly(monkeypatch):
    """Verifies successful live webhook dispatch to Instantly when all safety conditions and confirmation pass."""
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")
    monkeypatch.setenv("INSTANTLY_API_KEY", "instantly_prod_key_123")

    adapter = LiveDeliveryAdapter()
    LiveDeliveryAdapter.reset_safety_state()

    payload = {
        "campaign_id": "outbound_tech_lead_sequence_v1",
        "domain": "hyperion-inference.io",
        "recipient": {"name": "Dr. Elena Rostova", "email": "elena@hyperion-inference.io", "role": "VP AI"},
        "email_subject": "Distributed Tensor Parallelism",
        "email_body": "Hi Elena, shared our benchmarks.",
        "custom_variables": {"domain": "hyperion-inference.io"}
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json.dumps({"status": "success", "lead_id": "lead_987"})

    with patch("builtins.input", return_value="1"):  # Confirm 1 recipient
        with patch("requests.post", return_value=mock_resp) as mock_post:
            res = adapter.deliver(payload, dry_run=False, confirm_live=True, review_status="approved")

            assert res["status"] == "sent"
            assert res["http_status"] == 200
            mock_post.assert_called_once()
            call_url, call_kwargs = mock_post.call_args
            assert "api.instantly.ai/api/v1/lead/add" in call_url[0]
            assert call_kwargs["json"]["api_key"] == "instantly_prod_key_123"
            assert call_kwargs["json"]["email"] == "elena@hyperion-inference.io"
            assert call_kwargs["json"]["first_name"] == "Dr."

# 27. Live Delivery Error Modes: Rate Limit (429), Auth Failure (401), Payload Rejection (422), Timeout
def test_live_delivery_error_modes(monkeypatch):
    """Verifies that real HTTP error modes and timeouts gracefully mark status='failed' without crashing."""
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")
    monkeypatch.setenv("INSTANTLY_API_KEY", "test_key")

    adapter = LiveDeliveryAdapter()
    LiveDeliveryAdapter.reset_safety_state()
    LiveDeliveryAdapter._first_send_confirmed = True  # Bypass confirmation prompt for error-mode tests

    payload = {
        "domain": "error-test.io",
        "recipient": {"name": "Alex Smith", "email": "alex@error-test.io"},
        "email_subject": "Collab",
        "email_body": "Hi Alex"
    }

    # 1. Rate limit (429)
    with patch("requests.post", return_value=MagicMock(status_code=429, text="Rate limit exceeded")):
        res = adapter.deliver(payload, dry_run=False, confirm_live=True, review_status="approved")
        assert res["status"] == "failed"
        assert "429" in res["error"] or "Rate limit" in res["error"]

    # 2. Auth failure (401)
    with patch("requests.post", return_value=MagicMock(status_code=401, text="Unauthorized key")):
        res = adapter.deliver(payload, dry_run=False, confirm_live=True, review_status="approved")
        assert res["status"] == "failed"
        assert "401" in res["error"] or "Authentication failure" in res["error"]

    # 3. Payload rejection (422)
    with patch("requests.post", return_value=MagicMock(status_code=422, text="Unprocessable Entity")):
        res = adapter.deliver(payload, dry_run=False, confirm_live=True, review_status="approved")
        assert res["status"] == "failed"
        assert "422" in res["error"] or "rejected" in res["error"]

    # 4. Network timeout
    import requests
    with patch("requests.post", side_effect=requests.exceptions.Timeout("Connection timed out")):
        res = adapter.deliver(payload, dry_run=False, confirm_live=True, review_status="approved")
        assert res["status"] == "failed"
        assert "timeout" in res["error"].lower()

# 28. Send-Rate Pacing: DELIVERY_DELAY_MS Between Live Sends
def test_live_delivery_pacing_delay_ms(monkeypatch):
    """Verifies that DELIVERY_DELAY_MS enforces pacing sleep between consecutive live sends."""
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")
    monkeypatch.setenv("INSTANTLY_API_KEY", "test_key")
    monkeypatch.setenv("DELIVERY_DELAY_MS", "300")

    adapter = LiveDeliveryAdapter()
    LiveDeliveryAdapter.reset_safety_state()
    LiveDeliveryAdapter._first_send_confirmed = True

    payload = {
        "domain": "pace-test.io",
        "recipient": {"name": "Pace User", "email": "user@pace-test.io"},
        "email_subject": "Hello",
        "email_body": "Body"
    }

    mock_resp = MagicMock(status_code=200, text="ok")

    with patch("time.sleep") as mock_sleep:
        with patch("requests.post", return_value=mock_resp):
            # Send 1
            adapter.deliver(payload, dry_run=False, confirm_live=True, review_status="approved")
            # Send 2 (immediately after)
            adapter.deliver(payload, dry_run=False, confirm_live=True, review_status="approved")

            # Pacing sleep must have been called between send 1 and send 2
            assert mock_sleep.called

# 29. Delivery Node in StateGraph: End-to-End Status Propagation
def test_delivery_node_in_graph_sets_delivery_status_and_error(monkeypatch, resume_data):
    """
    Verifies that when the LangGraph pipeline invokes delivery_node:
    (a) Failed live dispatch sets delivery_status='failed' and records delivery_error in state.
    (b) Successful live dispatch sets delivery_status='sent'.
    """
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CONFIRM_LIVE", "true")
    monkeypatch.setenv("AUTO_APPROVE", "true")
    monkeypatch.setenv("INSTANTLY_API_KEY", "prod_key")

    LiveDeliveryAdapter.reset_safety_state()
    LiveDeliveryAdapter._first_send_confirmed = True

    state = {
        "domain": "apex-vault-fintech.io",
        "resume_context": resume_data,
        "auto_approve": True
    }

    # (a) Simulate live dispatch failure in StateGraph
    with patch("requests.post", return_value=MagicMock(status_code=429, text="Rate limit hit")):
        result_failed = pipeline_app.invoke(state)
        assert result_failed["delivery_status"] == "failed"
        assert "429" in result_failed.get("delivery_error", "")

    # (b) Simulate live dispatch success in StateGraph
    with patch("requests.post", return_value=MagicMock(status_code=200, text="success")):
        result_success = pipeline_app.invoke(state)
        assert result_success["delivery_status"] == "sent"

# 30. Mock Apollo Organization Search for Discovery
def test_apollo_org_search_mock(monkeypatch):
    """
    Verifies LiveDiscoveryAdapter querying Apollo's /v1/organizations/search endpoint:
    - Filters by keyword tags matching technical profile (applied cryptography, cybersecurity, etc.).
    - Translates company_size into Apollo employee count ranges (small vs established).
    - Maps Apollo organization fields into company_context (headline, signal, tech_stack).
    - Handles rate limits and auth errors gracefully.
    """
    monkeypatch.setenv("APOLLO_API_KEY", "test_apollo_org_key")
    adapter = LiveDiscoveryAdapter()

    mock_apollo_response = {
        "organizations": [
            {
                "id": "org_1",
                "name": "ZKLattice Labs",
                "primary_domain": "zklattice.io",
                "website_url": "https://zklattice.io",
                "short_description": "Building zero-knowledge hardware acceleration for cryptographic rollups.",
                "industry": "Computer & Network Security",
                "estimated_num_employees": 8,
                "total_funding_printed": "$3.8M",
                "technology_names": ["Rust", "CUDA", "Circom", "AWS"],
                "keywords": ["zero knowledge", "cryptography", "rollups"]
            },
            {
                "id": "org_2",
                "name": "FraudGuard Inference",
                "primary_domain": "fraudguard-ai.com",
                "website_url": "https://fraudguard-ai.com",
                "short_description": "Graph neural networks for payment fraud detection.",
                "industry": "Financial Services",
                "estimated_num_employees": 45,
                "total_funding_printed": "$18M",
                "technology_names": ["Python", "PyTorch", "Kafka", "Kubernetes"],
                "keywords": ["fraud detection", "fintech", "machine learning"]
            }
        ],
        "pagination": {"page": 1, "per_page": 10, "total_entries": 2}
    }

    # (a) Successful search with size='small'
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_apollo_response)
        candidates = adapter.discover(limit=5, company_size="small")

        assert len(candidates) == 2
        cand1 = candidates[0]
        assert cand1["domain"] == "zklattice.io"
        assert cand1["company_name"] == "ZKLattice Labs"
        assert cand1["size"] == 8
        assert cand1["funding"] == "$3.8M"
        assert "zero-knowledge hardware" in cand1["company_context"]["headline"]
        assert "Rust" in cand1["company_context"]["tech_stack"]
        assert "$3.8M" in cand1["company_context"]["signal"]

        # Verify request parameters
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://api.apollo.io/v1/organizations/search"
        payload = call_args[1]["json"]
        assert payload["organization_num_employees_ranges"] == ["1,10"]
        assert "applied cryptography" in payload["q_organization_keyword_tags"]
        assert "cybersecurity" in payload["q_organization_keyword_tags"]

    # (b) Test size='established' passes correct employee range
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=lambda: mock_apollo_response)
        adapter.discover(limit=5, company_size="established")
        payload = mock_post.call_args[1]["json"]
        assert "21,50" in payload["organization_num_employees_ranges"]

    # (c) Graceful degradation on 429 rate limit and 401 auth error
    with patch("requests.post", return_value=MagicMock(status_code=429, text="Rate limited")):
        assert adapter.discover(limit=5) == []
    with patch("requests.post", return_value=MagicMock(status_code=401, text="Unauthorized")):
        assert adapter.discover(limit=5) == []

# 31. Stub Discovery Rotation & Company Size Filtering
def test_stub_discovery_rotation_and_size_filtering():
    """
    Verifies that StubDiscoveryAdapter:
    - Filters companies by 'small' (<=10 emp), 'established' (>20 emp), and 'any'.
    - Rotates deterministically across calls for repeatable offline testing.
    """
    adapter = StubDiscoveryAdapter()
    StubDiscoveryAdapter.reset_rotation()

    # (a) Small filter
    small_candidates = adapter.discover(limit=3, company_size="small")
    assert len(small_candidates) == 3
    for c in small_candidates:
        assert c["size"] <= 10
        assert c["domain"]
        assert c["company_name"]
        assert c["company_context"]["headline"]

    # (b) Established filter
    est_candidates = adapter.discover(limit=3, company_size="established")
    assert len(est_candidates) == 3
    for c in est_candidates:
        assert c["size"] > 20

    # (c) Deterministic rotation
    StubDiscoveryAdapter.reset_rotation()
    batch_1 = adapter.discover(limit=2, company_size="any")
    batch_2 = adapter.discover(limit=2, company_size="any")
    assert batch_1[0]["domain"] != batch_2[0]["domain"]

# 32. Contacted Log Persistence & Replacement of Already-Contacted Companies
def test_contacted_log_skips_and_replaces_already_contacted(tmp_path, monkeypatch, resume_data):
    """
    Verifies that:
    - Companies reaching delivery (staged or sent) are recorded in contacted_companies.jsonl.
    - An already contacted company is skipped automatically.
    - Discovery replaces skipped candidates so target count N is still achieved.
    """
    test_log = tmp_path / "contacted_companies.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log))
    monkeypatch.setenv("DISCOVERY_MODE", "stub")
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("AUTO_APPROVE", "true")

    StubDiscoveryAdapter.reset_rotation()
    first_candidate = StubDiscoveryAdapter.CANDIDATES[0]
    already_contacted_domain = first_candidate["domain"]

    # Pre-populate log with the first candidate domain
    record_contacted(
        domain=already_contacted_domain,
        contact_email="devon@example.com",
        delivery_status="staged",
        log_file=str(test_log)
    )
    assert is_already_contacted(domain=already_contacted_domain, log_file=str(test_log)) is True

    # Run discovered flow targeting 2 companies
    run_discovered_flow(
        target_count=2,
        company_size="any",
        resume_context=resume_data,
        auto_approve=True
    )

    records = load_contacted_log(str(test_log))
    # Original pre-populated record + 2 new processed replacements = 3 total records
    assert len(records) == 3

    contacted_domains = [r["domain"] for r in records]
    assert already_contacted_domain in contacted_domains
    assert contacted_domains.count(already_contacted_domain) == 1

# 33. Hard Volume Caps: Daily & Weekly Limits Enforced
def test_volume_caps_limits_run_and_reports_skip(tmp_path, monkeypatch, resume_data, capsys):
    """
    Verifies that:
    - MAX_SENDS_PER_DAY correctly limits run even when more candidates are requested.
    - Skip count and reason are clearly reported.
    - When cap is completely exhausted (0 remaining), run halts without dispatch.
    """
    test_log = tmp_path / "contacted_companies.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log))
    monkeypatch.setenv("MAX_SENDS_PER_DAY", "3")
    monkeypatch.setenv("MAX_SENDS_PER_WEEK", "10")
    monkeypatch.setenv("DISCOVERY_MODE", "stub")
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")

    # (a) Pre-record 2 entries today in the log
    record_contacted("pre1.com", "contact1@pre1.com", "staged", log_file=str(test_log))
    record_contacted("pre2.com", "contact2@pre2.com", "staged", log_file=str(test_log))

    cap_check = check_volume_caps(log_file=str(test_log))
    assert cap_check["sends_today"] == 2
    assert cap_check["remaining_day"] == 1
    assert cap_check["effective_allowance"] == 1

    # Request 3 companies when only 1 is allowed
    StubDiscoveryAdapter.reset_rotation()
    run_discovered_flow(
        target_count=3,
        company_size="any",
        resume_context=resume_data,
        auto_approve=True
    )

    captured = capsys.readouterr().out
    assert "VOLUME CAP THROTTLED" in captured
    assert "Skipping 2 candidate(s)" in captured

    records = load_contacted_log(str(test_log))
    # Exactly 2 pre-existing + 1 allowed = 3 records
    assert len(records) == 3

    # (b) Now day cap is completely exhausted (3/3)
    cap_check_exhausted = check_volume_caps(log_file=str(test_log))
    assert cap_check_exhausted["effective_allowance"] == 0

    run_discovered_flow(
        target_count=2,
        company_size="any",
        resume_context=resume_data,
        auto_approve=True
    )
    captured_exhausted = capsys.readouterr().out
    assert "VOLUME CAP EXCEEDED" in captured_exhausted
    assert "Skipped all 2 requested candidate(s)" in captured_exhausted
    assert len(load_contacted_log(str(test_log))) == 3

# 34. Discovery Node in StateGraph End-to-End
def test_discovery_node_in_graph_end_to_end(tmp_path, monkeypatch, resume_data):
    """
    Verifies that invoking pipeline_app with discover=True and no domain:
    - Discovery node automatically surfaces an uncontacted candidate.
    - Flows through enrichment -> drafting -> review -> delivery staging.
    - Records the discovered candidate in contacted_companies.jsonl.
    """
    test_log = tmp_path / "contacted_companies.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log))
    monkeypatch.setenv("DISCOVERY_MODE", "stub")
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")

    StubDiscoveryAdapter.reset_rotation()

    state = {
        "discover": True,
        "company_size": "small",
        "resume_context": resume_data,
        "auto_approve": True
    }
    result = pipeline_app.invoke(state)

    assert result.get("domain") is not None
    assert result.get("company_name") is not None
    assert result.get("contact_email") is not None
    assert result.get("email_draft") is not None
    assert result.get("review_status") == "approved"
    assert result.get("delivery_status") == "staged"

    records = load_contacted_log(str(test_log))
    assert len(records) == 1
    assert records[0]["domain"] == result["domain"]

# 35. Bound Discovery Replacement Retries: Exhausted Candidate Pool
def test_discovery_max_attempts_exhausted_pool(tmp_path, monkeypatch, resume_data, capsys):
    """
    Verifies that when all discovered candidates are already contacted:
    - Discovery attempts are bounded by MAX_DISCOVERY_ATTEMPTS.
    - Run halts cleanly with clear error message instead of looping infinitely.
    """
    test_log = tmp_path / "contacted_companies.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log))
    monkeypatch.setenv("MAX_SENDS_PER_DAY", "50")
    monkeypatch.setenv("MAX_SENDS_PER_WEEK", "100")
    monkeypatch.setenv("DISCOVERY_MODE", "stub")
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")

    # Pre-populate log with all stub candidates so candidate pool is exhausted
    for cand in StubDiscoveryAdapter.CANDIDATES:
        record_contacted(
            domain=cand["domain"],
            contact_email="test@example.com",
            delivery_status="staged",
            log_file=str(test_log)
        )

    # Request 2 candidates with max_attempts=4
    with pytest.raises(RuntimeError) as exc_info:
        run_discovered_flow(
            target_count=2,
            company_size="any",
            resume_context=resume_data,
            auto_approve=True,
            max_attempts=4
        )

    assert "could not find 2 new uncontacted candidates after 4 attempts" in str(exc_info.value)
    captured = capsys.readouterr().out
    assert "could not find 2 new uncontacted candidates after 4 attempts" in captured


# 36. Domain Verification HTTP Check Unit Tests (Separate from LLM)
def test_research_discovery_domain_verification_http_checks():
    """
    Verifies that ResearchDiscoveryAdapter.verify_domain():
    - Succeeds on HTTP HEAD returning 200 or 301/302 redirects.
    - Falls back to GET stream when HEAD returns 405 Method Not Allowed or 403.
    - Rejects when connection fails / DNS does not resolve (ConnectionError, Timeout).
    - Rejects invalid domain syntax without making outbound network calls.
    """
    adapter = ResearchDiscoveryAdapter()

    # (a) Successful HEAD check (200 OK)
    with patch("requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=200)
        assert adapter.verify_domain("valid-startup.io") is True
        mock_head.assert_called_once()
        assert "valid-startup.io" in mock_head.call_args[0][0]

    # (b) Successful redirect (301)
    with patch("requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=301)
        assert adapter.verify_domain("https://redirect-startup.ai/about") is True

    # (c) HEAD returns 405 (Method Not Allowed), GET fallback succeeds (200 OK)
    with patch("requests.head") as mock_head, patch("requests.get") as mock_get:
        mock_head.return_value = MagicMock(status_code=405)
        mock_get.return_value = MagicMock(status_code=200)
        assert adapter.verify_domain("get-fallback.com") is True
        mock_head.assert_called_once()
        mock_get.assert_called_once()

    # (d) ConnectionError / DNS failure (fake non-resolving domain)
    with patch("requests.head", side_effect=requests.exceptions.ConnectionError("Name or service not known")):
        assert adapter.verify_domain("nonexistent-hallucination-xyz.io") is False

    # (e) Timeout
    with patch("requests.head", side_effect=requests.exceptions.Timeout("Timed out")):
        assert adapter.verify_domain("timed-out-server.org") is False

    # (f) Invalid domain syntax
    with patch("requests.head") as mock_head:
        assert adapter.verify_domain("") is False
        assert adapter.verify_domain("notadomain") is False
        mock_head.assert_not_called()


# 37. Grounded LLM Search with Hallucination Discard & Logging
def test_research_discovery_grounded_search_and_hallucination_discard(monkeypatch, caplog):
    """
    Verifies that ResearchDiscoveryAdapter:
    - Uses ChatGoogleGenerativeAI with Gemini's search-grounding tool enabled (.bind_tools([{"google_search": {}}])).
    - Prompts with profile criteria (cryptography, cybersecurity, fraud detection, AI infra, AI security).
    - When LLM returns 1 real domain and 1 fake/non-resolving domain:
      * The fake/non-resolving domain is discarded and NOT passed downstream.
      * The discarded candidate is logged separately with a warning and recorded in discarded_candidates.
      * The real domain passes verification and is returned in the exact Apollo adapter output shape.
    """
    import logging
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    adapter = ResearchDiscoveryAdapter()

    # Mock candidate LLM response: 1 real, 1 fake hallucination
    mock_llm_json = json.dumps([
        {
            "company_name": "ZKMesh Labs",
            "domain": "zkmesh-crypto.io",
            "size": 7,
            "industry": "Applied Cryptography",
            "stage_signal": "Raised $3.5M Seed in 2025",
            "company_context": "Building zero-knowledge threshold MPC infrastructure for cross-chain settlements",
            "tech_stack": "Rust, ZK-SNARKs, AWS Nitro Enclaves"
        },
        {
            "company_name": "PhantomAI Hallucination Systems",
            "domain": "phantom-ai-hallucination-fake.io",
            "size": 10,
            "industry": "AI Security",
            "stage_signal": "Stealth",
            "company_context": "Invented startup that does not exist on the public internet",
            "tech_stack": "Python, CUDA"
        }
    ])

    with patch("google.genai.Client") as MockClientClass:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_response = MagicMock(text=mock_llm_json)
        mock_chat.send_message.return_value = mock_response
        mock_client.chats.create.return_value = mock_chat
        MockClientClass.return_value = mock_client

        # Mock the domain-verification HTTP check separately:
        # zkmesh-crypto.io resolves, phantom-ai-hallucination-fake.io fails to resolve
        def fake_verify(domain: str) -> bool:
            return domain == "zkmesh-crypto.io"

        with patch.object(adapter, "verify_domain", side_effect=fake_verify) as mock_verify_domain:
            with caplog.at_level(logging.WARNING):
                candidates = adapter.discover(limit=5, company_size="small")

        # 1. Assert Client was initialized and chats.create called with model & tools via Chat.send_message
        MockClientClass.assert_called_once_with(api_key="test_gemini_key")
        mock_client.chats.create.assert_called_once()
        create_kwargs = mock_client.chats.create.call_args[1]
        assert get_discovery_model() in create_kwargs.get("model", "") or "gemini" in create_kwargs.get("model", "")
        config = create_kwargs.get("config")
        assert config is not None
        assert getattr(config, "tools", None) is not None or "tools" in str(config)

        # 2. Assert send_message was passed prompt with target criteria and company size
        mock_chat.send_message.assert_called_once()
        invoked_content = mock_chat.send_message.call_args[0][0]
        assert "applied cryptography" in invoked_content.lower()
        assert "cybersecurity" in invoked_content.lower()
        assert "fintech fraud detection" in invoked_content.lower()
        assert "ai/llm infrastructure" in invoked_content.lower() or "ai infrastructure" in invoked_content.lower()
        assert "ai security" in invoked_content.lower()
        assert "early-stage" in invoked_content.lower() or "small" in invoked_content.lower()

        # 3. Assert verify_domain was called for each domain returned by LLM
        assert mock_verify_domain.call_count == 2

        # 4. Assert fake candidate was discarded and NOT passed downstream
        assert len(candidates) == 1
        real_cand = candidates[0]
        assert real_cand["domain"] == "zkmesh-crypto.io"
        assert real_cand["company_name"] == "ZKMesh Labs"
        assert real_cand["size"] == 7
        assert real_cand["industry"] == "Applied Cryptography"
        assert "zero-knowledge threshold" in real_cand["company_context"]["headline"].lower()
        assert "Rust" in real_cand["company_context"]["tech_stack"]
        assert "Seed" in real_cand["company_context"]["signal"]

        returned_domains = [c["domain"] for c in candidates]
        assert "phantom-ai-hallucination-fake.io" not in returned_domains

        # 5. Assert discarded candidate is recorded in discarded_candidates and logged
        assert len(adapter.discarded_candidates) == 1
        discarded = adapter.discarded_candidates[0]
        assert discarded["domain"] == "phantom-ai-hallucination-fake.io"
        assert discarded["company_name"] == "PhantomAI Hallucination Systems"
        assert discarded["reason"] == "domain_does_not_resolve_or_respond"

        # Check log output
        assert "[DISCARDED_CANDIDATE]" in caplog.text
        assert "phantom-ai-hallucination-fake.io" in caplog.text


# 38. Research-Mode Discovery Respects Contacted-Log Dedup and Replaces
def test_research_discovery_respects_contacted_dedup(tmp_path, monkeypatch, resume_data):
    """
    Verifies that in DISCOVERY_MODE=research:
    - Already contacted companies are skipped and replaced until target count is reached.
    - Resulting run records only newly contacted companies into contacted_companies.jsonl.
    """
    test_log = tmp_path / "contacted_companies.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log))
    monkeypatch.setenv("DISCOVERY_MODE", "research")
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")
    monkeypatch.setenv("AUTO_APPROVE", "true")

    # Pre-populate log with already-contacted research domain
    already_contacted = "prior-crypto-firm.io"
    record_contacted(already_contacted, "lead@prior-crypto-firm.io", "staged", log_file=str(test_log))

    # Mock ResearchDiscoveryAdapter.discover returning already-contacted candidate first, then new replacement
    candidates_pool = [
        {
            "domain": already_contacted,
            "company_name": "Prior Crypto Firm",
            "size": 6,
            "industry": "Applied Cryptography",
            "stage_signal": "Seed $2M",
            "company_context": {
                "headline": "Prior crypto firm research",
                "signal": "Seed $2M",
                "tech_stack": "Rust, ZK"
            }
        },
        {
            "domain": "fresh-ai-guardrail.io",
            "company_name": "Fresh AI Guardrail",
            "size": 8,
            "industry": "AI Security",
            "stage_signal": "Pre-Seed $1.5M",
            "company_context": {
                "headline": "Real-time prompt injection defense",
                "signal": "Pre-Seed $1.5M",
                "tech_stack": "Python, vLLM"
            }
        }
    ]

    with patch("pipeline.adapters.research.ResearchDiscoveryAdapter.discover", return_value=candidates_pool):
        run_discovered_flow(
            target_count=1,
            company_size="small",
            resume_context=resume_data,
            auto_approve=True
        )

    records = load_contacted_log(str(test_log))
    # 1 pre-existing + 1 new replacement = 2 records
    assert len(records) == 2
    domains = [r["domain"] for r in records]
    assert already_contacted in domains
    assert "fresh-ai-guardrail.io" in domains


# 39. Research-Mode Discovery Respects Hard Volume Caps
def test_research_discovery_respects_volume_caps(tmp_path, monkeypatch, resume_data, capsys):
    """
    Verifies that in DISCOVERY_MODE=research:
    - Hard volume caps (daily and weekly) throttle and halt execution identically to live/stub mode.
    """
    test_log = tmp_path / "contacted_companies.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log))
    monkeypatch.setenv("MAX_SENDS_PER_DAY", "2")
    monkeypatch.setenv("MAX_SENDS_PER_WEEK", "10")
    monkeypatch.setenv("DISCOVERY_MODE", "research")
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")

    # (a) Day cap exhausted (2/2 used)
    record_contacted("pre1.io", "c1@pre1.io", "staged", log_file=str(test_log))
    record_contacted("pre2.io", "c2@pre2.io", "staged", log_file=str(test_log))

    with patch("pipeline.adapters.research.ResearchDiscoveryAdapter.discover") as mock_discover:
        run_discovered_flow(
            target_count=2,
            company_size="any",
            resume_context=resume_data,
            auto_approve=True
        )
        mock_discover.assert_not_called()

    captured = capsys.readouterr().out
    assert "VOLUME CAP EXCEEDED" in captured
    assert "Skipped all 2 requested candidate(s)" in captured


# 40. Research-Mode Discovery Respects Bounded Discovery Retries on Exhaustion
def test_research_discovery_max_attempts_exhausted(tmp_path, monkeypatch, resume_data, capsys):
    """
    Verifies that in DISCOVERY_MODE=research, if candidates are exhausted or all already contacted:
    - Discovery attempts are strictly bounded by max_attempts.
    - Halts with RuntimeError rather than looping infinitely.
    """
    test_log = tmp_path / "contacted_companies.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log))
    monkeypatch.setenv("MAX_SENDS_PER_DAY", "50")
    monkeypatch.setenv("MAX_SENDS_PER_WEEK", "100")
    monkeypatch.setenv("DISCOVERY_MODE", "research")
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")

    already_domain = "seen-company.io"
    record_contacted(already_domain, "c@seen.io", "staged", log_file=str(test_log))

    # Adapter repeatedly returns already-contacted candidate
    repeating_batch = [{
        "domain": already_domain,
        "company_name": "Seen Company",
        "company_context": {"headline": "...", "signal": "...", "tech_stack": "..."}
    }]

    with patch("pipeline.adapters.research.ResearchDiscoveryAdapter.discover", return_value=repeating_batch):
        with pytest.raises(RuntimeError) as exc_info:
            run_discovered_flow(
                target_count=2,
                company_size="any",
                resume_context=resume_data,
                auto_approve=True,
                max_attempts=3
            )

    assert "could not find 2 new uncontacted candidates after 3 attempts" in str(exc_info.value)


# 41. Discovery Node in StateGraph with Research Discovery Adapter
def test_research_discovery_node_in_graph_end_to_end(tmp_path, monkeypatch, resume_data):
    """
    Verifies invoking pipeline_app with discover=True and DISCOVERY_MODE=research:
    - Routes through discovery_node using ResearchDiscoveryAdapter.
    - Discovers verified candidate, enriches contact, drafts email, stages delivery.
    - Records candidate in contacted_companies.jsonl.
    """
    test_log = tmp_path / "contacted_companies.jsonl"
    monkeypatch.setenv("CONTACTED_LOG_FILE", str(test_log))
    monkeypatch.setenv("DISCOVERY_MODE", "research")
    monkeypatch.setenv("APOLLO_MODE", "stub")
    monkeypatch.setenv("DRAFTING_MODE", "stub")
    monkeypatch.setenv("DELIVERY_MODE", "stub")

    mock_candidates = [{
        "domain": "verified-quantum-sec.io",
        "company_name": "Verified Quantum Sec",
        "size": 5,
        "industry": "Applied Cryptography",
        "stage_signal": "Seed $3M",
        "company_context": {
            "headline": "Post-quantum lattice cryptography toolkit",
            "signal": "Seed $3M expansion",
            "tech_stack": "Rust, C, Dilithium"
        }
    }]

    with patch("pipeline.adapters.research.ResearchDiscoveryAdapter.discover", return_value=mock_candidates):
        state = {
            "discover": True,
            "company_size": "small",
            "resume_context": resume_data,
            "auto_approve": True
        }
        result = pipeline_app.invoke(state)

    assert result.get("domain") == "verified-quantum-sec.io"
    assert result.get("company_name") == "Verified Quantum Sec"
    assert result.get("delivery_status") == "staged"

    records = load_contacted_log(str(test_log))
    assert len(records) == 1
    assert records[0]["domain"] == "verified-quantum-sec.io"


# 42. Default Config Invariant: DISCOVERY_MODE defaults to stub
def test_default_discovery_mode_defaults_to_stub(monkeypatch):
    """
    Confirms default configuration is unaffected:
    - DISCOVERY_MODE defaults to 'stub' when unset.
    - Explicit 'research' instantiates ResearchDiscoveryAdapter.
    - Explicit 'live' instantiates LiveDiscoveryAdapter.
    """
    # (a) Unset -> Stub
    monkeypatch.delenv("DISCOVERY_MODE", raising=False)
    adapter = AdapterFactory.get_discovery_adapter()
    assert isinstance(adapter, StubDiscoveryAdapter)

    # (b) Explicit 'stub' -> Stub
    monkeypatch.setenv("DISCOVERY_MODE", "stub")
    assert isinstance(AdapterFactory.get_discovery_adapter(), StubDiscoveryAdapter)

    # (c) Explicit 'research' -> Research
    monkeypatch.setenv("DISCOVERY_MODE", "research")
    assert isinstance(AdapterFactory.get_discovery_adapter(), ResearchDiscoveryAdapter)

    # (d) Explicit 'live' -> Live
    monkeypatch.setenv("DISCOVERY_MODE", "live")
    assert isinstance(AdapterFactory.get_discovery_adapter(), LiveDiscoveryAdapter)


# 43. Centralized Model Configuration & Precedence
def test_centralized_model_config_precedence(monkeypatch):
    """
    Verifies:
    1. Default constants: DEFAULT_DISCOVERY_MODEL is gemini-3.6-flash, DEFAULT_DRAFTING_MODEL is gemini-3.6-flash.
    2. Specific env vars take precedence: GEMINI_DISCOVERY_MODEL and GEMINI_DRAFTING_MODEL.
    3. Fallback to unified GEMINI_MODEL env var if specific ones are unset.
    4. Fallback to DEFAULT_* when no env vars are set.
    """
    assert DEFAULT_DISCOVERY_MODEL == "gemini-3.6-flash"
    assert DEFAULT_DRAFTING_MODEL == "gemini-3.6-flash"
    assert DEFAULT_GEMINI_MODEL == "gemini-3.6-flash"

    # Default fallback
    monkeypatch.delenv("GEMINI_DISCOVERY_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_DRAFTING_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert get_discovery_model() == "gemini-3.6-flash"
    assert get_drafting_model() == "gemini-3.6-flash"

    # Unified GEMINI_MODEL fallback
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-custom")
    assert get_discovery_model() == "gemini-test-custom"
    assert get_drafting_model() == "gemini-test-custom"

    # Specific override takes precedence over unified
    monkeypatch.setenv("GEMINI_DISCOVERY_MODEL", "gemini-override-discovery")
    monkeypatch.setenv("GEMINI_DRAFTING_MODEL", "gemini-override-drafting")
    assert get_discovery_model() == "gemini-override-discovery"
    assert get_drafting_model() == "gemini-override-drafting"


# 44. LiveDraftingAdapter Model Resolution and AFC Chat.send_message Refactoring
def test_live_drafting_adapter_afc_chat_send_message_with_tools(monkeypatch, resume_data):
    """
    Verifies that:
    1. LiveDraftingAdapter defaults to get_drafting_model() and accepts constructor model_name.
    2. When tools are provided to adapter.draft(), it uses google.genai.Client, client.chats.create,
       and chat.send_message (avoiding Models.generate_content AFC warning).
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_afc_test")
    monkeypatch.setenv("GEMINI_DRAFTING_MODEL", "gemini-custom-drafting")

    adapter = LiveDraftingAdapter()
    assert adapter.model_name == "gemini-custom-drafting"

    custom_adapter = LiveDraftingAdapter(model_name="explicit-model-123")
    assert custom_adapter.model_name == "explicit-model-123"

    # Verify tool-bound drafting refactor to Chat.send_message
    from google.genai import types
    fake_tool = types.Tool(google_search=types.GoogleSearch())
    with patch("google.genai.Client") as MockGenaiClient:
        mock_client_instance = MagicMock()
        mock_chat_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Subject: Custom AFC Draft\n\nVerified drafted outreach body."

        mock_chat_instance.send_message.return_value = mock_response
        mock_client_instance.chats.create.return_value = mock_chat_instance
        MockGenaiClient.return_value = mock_client_instance

        draft = adapter.draft(
            role="VP Engineering",
            domain="acme-cyber.io",
            resume_context=resume_data,
            contact_name="Alice Vance",
            tools=[fake_tool]
        )

        assert "Subject: Custom AFC Draft" in draft
        MockGenaiClient.assert_called_once_with(api_key="mock_key_afc_test")
        mock_client_instance.chats.create.assert_called_once()
        create_kwargs = mock_client_instance.chats.create.call_args[1]
        assert create_kwargs["model"] == "gemini-custom-drafting"
        assert create_kwargs["config"].tools == [fake_tool]
        mock_chat_instance.send_message.assert_called_once()


# 45. ResearchDiscoveryAdapter Model Resolution and AFC Grounded Search Refactoring
def test_research_discovery_adapter_model_and_afc_chat_refactor(monkeypatch):
    """
    Verifies that:
    1. ResearchDiscoveryAdapter defaults to get_discovery_model() and accepts constructor model_name.
    2. ResearchDiscoveryAdapter._query_gemini uses client.chats.create and chat.send_message
       with GoogleSearch tool, eliminating direct AFC calls on Models.generate_content.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_search_test")
    monkeypatch.setenv("GEMINI_DISCOVERY_MODEL", "gemini-custom-discovery")

    adapter = ResearchDiscoveryAdapter()
    assert adapter.model_name == "gemini-custom-discovery"

    custom_adapter = ResearchDiscoveryAdapter(model_name="explicit-discovery-model")
    assert custom_adapter.model_name == "explicit-discovery-model"

    with patch("google.genai.Client") as MockGenaiClient:
        mock_client_instance = MagicMock()
        mock_chat_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps([{"domain": "verified-test.io", "company_name": "Verified Test"}])

        mock_chat_instance.send_message.return_value = mock_response
        mock_client_instance.chats.create.return_value = mock_chat_instance
        MockGenaiClient.return_value = mock_client_instance

        raw_output = adapter._query_gemini("Find security startups")
        assert "verified-test.io" in raw_output

        MockGenaiClient.assert_called_once_with(api_key="mock_key_search_test")
        mock_client_instance.chats.create.assert_called_once()
        create_kwargs = mock_client_instance.chats.create.call_args[1]
        assert create_kwargs["model"] == "gemini-custom-discovery"
        tools = create_kwargs["config"].tools
        assert len(tools) == 1
        assert hasattr(tools[0], "google_search")
        mock_chat_instance.send_message.assert_called_once_with("Find security startups")


# 46. Quota Retry/Backoff for 429 RPM Throttling
def test_gemini_429_rpm_retry_success(monkeypatch):
    """
    Verifies that when Gemini returns 429 RESOURCE_EXHAUSTED (transient RPM limit),
    execute_with_quota_retry backs off and retries, returning the successful result
    once the throttle clears.
    """
    attempts = 0

    class Mock429Error(Exception):
        status = "RESOURCE_EXHAUSTED"
        code = 429

    def mock_call():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise Mock429Error("429 RESOURCE_EXHAUSTED: Rate limit exceeded. Please wait before retrying.")
        return "success_response"

    monkeypatch.setenv("GEMINI_CALL_DELAY_MS", "0")
    reset_pacing_state()
    with patch("time.sleep") as mock_sleep:
        result = execute_with_quota_retry(mock_call, adapter_name="TestAdapter", max_retries=2, initial_delay=1.0)
        assert result == "success_response"
        assert attempts == 2
        mock_sleep.assert_called_once_with(1.0)


# 47. Persistent 429 Daily Quota Exhaustion Reporting
def test_gemini_persistent_429_daily_quota_exhausted_message(monkeypatch, capsys):
    """
    Verifies that when 429 persists across retries or has explicit daily quota language:
    1. DailyQuotaExhaustedError is raised.
    2. DAILY_QUOTA_RESET_MESSAGE is printed, clearly stating the free daily quota is used up
       and resets at midnight Pacific Time.
    """
    class MockDailyQuotaError(Exception):
        status = "RESOURCE_EXHAUSTED"
        code = 429

    # (a) Explicit daily quota message in error body
    def mock_explicit_rpd_call():
        raise MockDailyQuotaError("429 Quota exceeded for quota metric 'requests' and limit 'Requests per day'")

    with pytest.raises(DailyQuotaExhaustedError):
        execute_with_quota_retry(mock_explicit_rpd_call, max_retries=3)

    captured = capsys.readouterr()
    assert "GEMINI FREE TIER DAILY QUOTA EXHAUSTED" in captured.out
    assert "midnight Pacific Time" in captured.out

    # (b) Persistent 429 after max retries
    reset_quota_state()
    persistent_attempts = 0
    def mock_persistent_rpm_call():
        nonlocal persistent_attempts
        persistent_attempts += 1
        raise MockDailyQuotaError("429 RESOURCE_EXHAUSTED: Too many requests")

    with patch("time.sleep"):
        with pytest.raises(DailyQuotaExhaustedError):
            execute_with_quota_retry(mock_persistent_rpm_call, max_retries=2, initial_delay=0.1)

    assert persistent_attempts == 3  # 1 initial + 2 retries
    captured_pers = capsys.readouterr()
    assert "GEMINI FREE TIER DAILY QUOTA EXHAUSTED" in captured_pers.out
    assert "midnight Pacific Time" in captured_pers.out


# 48. Research Discovery Aborts on Daily Quota Without Looping Max Attempts
def test_research_discovery_aborts_on_daily_quota_without_candidate_looping(monkeypatch, capsys):
    """
    Verifies that when ResearchDiscoveryAdapter encounters DailyQuotaExhaustedError,
    it re-raises immediately without repeatedly looping max_attempts or masking the error
    with generic 'could not find N candidates'.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_quota_test")
    adapter = ResearchDiscoveryAdapter()

    class Mock429(Exception):
        status = "RESOURCE_EXHAUSTED"
        code = 429

    with patch("google.genai.Client") as MockClient:
        mock_client_instance = MagicMock()
        mock_chat_instance = MagicMock()
        mock_chat_instance.send_message.side_effect = Mock429("429 RESOURCE_EXHAUSTED: daily limit reached")
        mock_client_instance.chats.create.return_value = mock_chat_instance
        MockClient.return_value = mock_client_instance

        with pytest.raises(DailyQuotaExhaustedError):
            adapter.discover(limit=3, company_size="small")

    captured = capsys.readouterr()
    assert "GEMINI FREE TIER DAILY QUOTA EXHAUSTED" in captured.out
    assert "midnight Pacific Time" in captured.out


# 49. Live Drafting Adapter Gracefully Handles Daily Quota Exhaustion
def test_live_drafting_adapter_daily_quota_fallback(monkeypatch, resume_data, capsys):
    """
    Verifies that when LiveDraftingAdapter encounters DailyQuotaExhaustedError,
    it prints the clear daily quota message and falls back to structured local synthesis.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_drafting_quota")
    adapter = LiveDraftingAdapter()

    class Mock429(Exception):
        status = "RESOURCE_EXHAUSTED"
        code = 429

    with patch("langchain_google_genai.ChatGoogleGenerativeAI") as MockLLM:
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.side_effect = Mock429("429 Quota exceeded: requests per day")
        MockLLM.return_value = mock_llm_instance

        draft = adapter.draft(
            role="Principal Security Engineer",
            domain="vault-guard.io",
            resume_context=resume_data,
            contact_name="Bob Security"
        )

    # Asserts structured local offline fallback draft was returned
    assert "Subject: Encrypted transaction compute & security" in draft
    assert "Bob Security" in draft
    captured = capsys.readouterr()
    assert "GEMINI FREE TIER DAILY QUOTA EXHAUSTED" in captured.out
    assert "midnight Pacific Time" in captured.out


# 50. Proactive Gemini Call Pacing (RPM Protection)
def test_proactive_gemini_call_pacing(monkeypatch):
    """
    Verifies that pace_gemini_call proactively pauses execution
    when consecutive calls occur within GEMINI_CALL_DELAY_MS.
    """
    reset_pacing_state()
    monkeypatch.setenv("GEMINI_CALL_DELAY_MS", "3000")

    with patch("time.sleep") as mock_sleep:
        # First call sets timestamp, no sleep
        pace_gemini_call(delay_ms=3000)
        mock_sleep.assert_not_called()

        # Immediate second call triggers sleep for remaining time
        pace_gemini_call(delay_ms=3000)
        mock_sleep.assert_called_once()
        sleep_arg = mock_sleep.call_args[0][0]
        assert 2.0 <= sleep_arg <= 3.0

    reset_pacing_state()


# 51. Codebase Audit: Free-Tier Defaults with Zero Pro Models
def test_free_tier_no_pro_models_in_defaults():
    """
    Verifies that DEFAULT_GEMINI_MODEL, DEFAULT_DISCOVERY_MODEL, and DEFAULT_DRAFTING_MODEL
    run on Gemini free-tier Flash models, and zero Pro models are set as defaults.
    """
    assert "flash" in DEFAULT_GEMINI_MODEL.lower()
    assert "pro" not in DEFAULT_GEMINI_MODEL.lower()

    assert "flash" in DEFAULT_DISCOVERY_MODEL.lower()
    assert "pro" not in DEFAULT_DISCOVERY_MODEL.lower()

    assert "flash" in DEFAULT_DRAFTING_MODEL.lower()
    assert "pro" not in DEFAULT_DRAFTING_MODEL.lower()


# 52. Daily Quota Banner Printed Exactly Once Across Multiple Exhaustion Invocations
def test_daily_quota_banner_printed_exactly_once(capsys):
    """
    Verifies that when multiple calls/iterations encounter DailyQuotaExhaustedError,
    the 'GEMINI FREE TIER DAILY QUOTA EXHAUSTED' banner is printed EXACTLY ONCE
    and never repeated across iterations of loops or consecutive calls.
    """
    reset_quota_state()

    class Mock429(Exception):
        status = "RESOURCE_EXHAUSTED"
        code = 429

    def mock_daily_exhaustion_call():
        raise Mock429("429 RESOURCE_EXHAUSTED: daily limit reached for requests per day")

    # Call execute_with_quota_retry 10 consecutive times simulating loop iterations
    for _ in range(10):
        with pytest.raises(DailyQuotaExhaustedError):
            execute_with_quota_retry(mock_daily_exhaustion_call, adapter_name="TestLoop")

    captured = capsys.readouterr()
    assert captured.out.count("GEMINI FREE TIER DAILY QUOTA EXHAUSTED") == 1
    assert "midnight Pacific Time" in captured.out


# 53. Discovery Flow Halts Cleanly on Daily Quota Without Candidate Replacement Looping
def test_run_discovered_flow_halts_cleanly_on_daily_quota(monkeypatch, capsys):
    """
    Verifies that run_discovered_flow halts immediately when DailyQuotaExhaustedError occurs
    and does not cycle through replacement candidate attempts.
    """
    reset_quota_state()
    monkeypatch.setenv("DISCOVERY_MODE", "research")
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_flow_halt")

    call_count = 0
    class Mock429(Exception):
        status = "RESOURCE_EXHAUSTED"
        code = 429

    with patch("google.genai.Client") as MockClient:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        def _mock_send(prompt):
            nonlocal call_count
            call_count += 1
            raise Mock429("429 RESOURCE_EXHAUSTED: daily limit reached for requests per day")
        mock_chat.send_message.side_effect = _mock_send
        mock_client.chats.create.return_value = mock_chat
        MockClient.return_value = mock_client

        with pytest.raises(DailyQuotaExhaustedError):
            run_discovered_flow(
                target_count=3,
                company_size="small",
                resume_context={},
                auto_approve=True,
                max_attempts=15
            )

    # Asserts it halted on the very first discovery attempt and did not cycle through 15 attempts
    assert call_count == 1
    captured = capsys.readouterr()
    assert captured.out.count("GEMINI FREE TIER DAILY QUOTA EXHAUSTED") == 1


# ==============================================================================
# Decoupled Two-Stage Enrichment Pipeline Unit Tests (100% Offline)
# ==============================================================================

def test_gemini_person_research_grounded_success(monkeypatch):
    """Verifies that GeminiPersonResearchAdapter discovers and verifies a real technical leader via search grounding."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    adapter = GeminiPersonResearchAdapter()

    mock_llm_json = json.dumps({
        "found": True,
        "first_name": "Elena",
        "last_name": "Vasiliev",
        "full_name": "Dr. Elena Vasiliev",
        "role": "Chief Technology Officer & Co-Founder",
        "linkedin_url": "https://www.linkedin.com/in/elena-vasiliev",
        "source_url": "https://tech-innovations.io/leadership",
        "reasoning": "Verified current CTO from company leadership directory and recent 2025 conference keynotes.",
        "confidence_score": 0.95
    })

    with patch("google.genai.Client") as MockClientClass:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = MagicMock(text=mock_llm_json)
        mock_client.chats.create.return_value = mock_chat
        MockClientClass.return_value = mock_client

        leader = adapter.find_leader("tech-innovations.io", company_name="Tech Innovations", company_context={"signal": "Applied ML"})

        assert leader is not None
        assert leader["first_name"] == "Elena"
        assert leader["last_name"] == "Vasiliev"
        assert "Chief Technology Officer" in leader["role"]
        assert leader["person_confidence"] == 0.95
        assert leader["linkedin_url"] == "https://www.linkedin.com/in/elena-vasiliev"

        # Verify Google Search tool was configured
        MockClientClass.assert_called_once_with(api_key="test_gemini_key")
        create_kwargs = mock_client.chats.create.call_args[1]
        assert getattr(create_kwargs.get("config"), "tools", None) is not None


def test_gemini_person_research_anti_hallucination_and_blacklist(monkeypatch):
    """Verifies that GeminiPersonResearchAdapter rejects blacklisted, generic, incomplete, or low-confidence names."""
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    adapter = GeminiPersonResearchAdapter()

    # 1. Blacklisted name: Alex Morgan
    assert adapter.validate_leader({
        "found": True, "first_name": "Alex", "last_name": "Morgan", "role": "CTO", "confidence_score": 0.95
    }) is None

    # 2. Generic token: Admin / Support / Founder
    assert adapter.validate_leader({
        "found": True, "first_name": "Admin", "last_name": "User", "role": "Head of Engineering", "confidence_score": 0.90
    }) is None

    # 3. Name containing digits or symbols
    assert adapter.validate_leader({
        "found": True, "first_name": "John123", "last_name": "Doe", "role": "CTO", "confidence_score": 0.90
    }) is None

    # 4. Incomplete single-word name
    assert adapter.validate_leader({
        "found": True, "first_name": "Satoshi", "last_name": "", "full_name": "Satoshi", "role": "Chief Architect", "confidence_score": 0.90
    }) is None

    # 5. Non-leadership role
    assert adapter.validate_leader({
        "found": True, "first_name": "Bob", "last_name": "Smith", "role": "Junior Marketing Intern", "confidence_score": 0.90
    }) is None

    # 6. Low confidence (< 0.70)
    assert adapter.validate_leader({
        "found": True, "first_name": "Alice", "last_name": "Smith", "role": "CTO", "confidence_score": 0.50
    }) is None

    # 7. Explicit found: false
    assert adapter.validate_leader({
        "found": False, "reason": "no_verified_technical_leader_found", "confidence_score": 0.0
    }) is None


def test_gemini_person_research_failure_modes_and_grounding(monkeypatch):
    """
    Verifies that GeminiPersonResearchAdapter handles:
    1. Missing API key (returns None cleanly, zero network calls).
    2. Malformed / non-JSON LLM response (returns None cleanly, zero fabrication).
    3. Network/API exception (returns None cleanly, zero fabrication).
    4. SDK-level grounding chunk extraction for citation URL.
    """
    # 1. Missing API key
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    adapter = GeminiPersonResearchAdapter()
    assert adapter.find_leader("unconfigured-key.io") is None

    # 2. Malformed / non-JSON LLM response
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    adapter = GeminiPersonResearchAdapter()

    with patch("google.genai.Client") as MockClientClass:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = MagicMock(text="Sorry, I could not find any technical leadership.")
        mock_client.chats.create.return_value = mock_chat
        MockClientClass.return_value = mock_client

        leader = adapter.find_leader("broken-response.io")
        assert leader is None

    # 3. Network/API exception
    with patch("google.genai.Client") as MockClientClass:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_chat.send_message.side_effect = RuntimeError("Connection reset by peer")
        mock_client.chats.create.return_value = mock_chat
        MockClientClass.return_value = mock_client

        leader = adapter.find_leader("api-error.io")
        assert leader is None

    # 4. SDK grounding metadata fallback when JSON lacks source_url
    json_without_source = json.dumps({
        "found": True,
        "first_name": "Liam",
        "last_name": "Chen",
        "full_name": "Liam Chen",
        "role": "Head of Engineering",
        "evidence_snippet": "Leading engineering and platform infrastructure at Horizon AI.",
        "confidence_score": 0.88
    })
    mock_resp = MagicMock()
    mock_resp.text = json_without_source
    mock_chunk = MagicMock()
    mock_chunk.web.uri = "https://techcrunch.com/2026/horizon-ai-series-a"
    mock_chunk.web.title = "Horizon AI raises Series A"
    mock_chunk.web.domain = "techcrunch.com"
    mock_candidate = MagicMock()
    mock_candidate.grounding_metadata.grounding_chunks = [mock_chunk]
    mock_resp.candidates = [mock_candidate]

    with patch("google.genai.Client") as MockClientClass:
        mock_client = MagicMock()
        mock_chat = MagicMock()
        mock_chat.send_message.return_value = mock_resp
        mock_client.chats.create.return_value = mock_chat
        MockClientClass.return_value = mock_client

        leader = adapter.find_leader("horizon-ai.io")
        assert leader is not None
        assert leader["full_name"] == "Liam Chen"
        assert leader["source_url"] == "https://techcrunch.com/2026/horizon-ai-series-a"
        assert len(leader["grounding_sources"]) == 1


def test_hunter_email_resolver_valid_acceptance(monkeypatch):
    """Verifies that HunterEmailResolver accepts a valid deliverable email meeting confidence thresholds."""
    monkeypatch.setenv("HUNTER_API_KEY", "test_hunter_key")
    resolver = HunterEmailResolver()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "jane.doe@cryptosec.io",
            "score": 94,
            "verification": {
                "status": "valid",
                "date": "2026-09-14"
            },
            "sources": [{"uri": "https://cryptosec.io/team"}]
        }
    }

    with patch("requests.get", return_value=mock_resp) as mock_get:
        res = resolver.resolve_email(
            domain="cryptosec.io",
            first_name="Jane",
            last_name="Doe",
            role="CTO"
        )
        assert res is not None
        assert res["email"] == "jane.doe@cryptosec.io"
        assert res["score"] == 94
        assert res["status"] == "valid"
        assert res["provider"] == "hunter"
        assert res["sources_count"] == 1


def test_hunter_email_resolver_catch_all_handling(monkeypatch):
    """Verifies that catch-all (accept_all) domains are rejected by default, and only accepted when explicitly permitted with score >= 85."""
    monkeypatch.setenv("HUNTER_API_KEY", "test_hunter_key")
    resolver = HunterEmailResolver()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "first_name": "Dave",
            "last_name": "Miller",
            "email": "dave@catchall.io",
            "score": 88,
            "verification": {"status": "accept_all"},
            "sources": [{"uri": "https://catchall.io"}]
        }
    }

    with patch("requests.get", return_value=mock_resp):
        # Case A: ALLOW_ACCEPT_ALL is false (default safety invariant)
        monkeypatch.setattr("pipeline.adapters.email_resolution.ALLOW_ACCEPT_ALL", False)
        res = resolver.resolve_email("catchall.io", "Dave", "Miller")
        assert res is not None
        assert res.get("email") is None, "Catch-all email must be rejected when ALLOW_ACCEPT_ALL=False"
        assert res.get("status") == "accept_all"
        assert res.get("reason") == "catch_all_rejected_by_policy"

        # Case B: ALLOW_ACCEPT_ALL is true and score >= 85 with web sources
        monkeypatch.setattr("pipeline.adapters.email_resolution.ALLOW_ACCEPT_ALL", True)
        res_allowed = resolver.resolve_email("catchall.io", "Dave", "Miller")
        assert res_allowed is not None
        assert res_allowed["email"] == "dave@catchall.io"
        assert res_allowed["status"] == "accept_all"


def test_hunter_email_resolver_rejection_rules(monkeypatch):
    """Verifies that HunterEmailResolver rejects low confidence, invalid status, rate limits, and missing keys."""
    # 1. Missing API Key
    monkeypatch.delenv("HUNTER_API_KEY", raising=False)
    resolver = HunterEmailResolver(api_key="")
    res = resolver.resolve_email("test.com", "John", "Doe")
    assert res is not None
    assert res.get("email") is None
    assert res.get("status") == "provider_error"
    assert res.get("reason") == "missing_api_key"

    monkeypatch.setenv("HUNTER_API_KEY", "test_hunter_key")
    resolver = HunterEmailResolver(api_key="test_hunter_key")

    # 2. Score below MIN_EMAIL_CONFIDENCE (e.g. 60 < 80)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"email": "john@test.com", "score": 60, "verification": {"status": "valid"}}}
        )
        res = resolver.resolve_email("test.com", "John", "Doe")
        assert res is not None
        assert res.get("email") is None
        assert res.get("status") == "low_confidence"

    # 3. Status invalid
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"email": "john@test.com", "score": 90, "verification": {"status": "invalid"}}}
        )
        res = resolver.resolve_email("test.com", "John", "Doe")
        assert res is not None
        assert res.get("email") is None
        assert res.get("status") == "invalid"

    # 4. HTTP 429 Rate Limit
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=429)
        res = resolver.resolve_email("test.com", "John", "Doe")
        assert res is not None
        assert res.get("email") is None
        assert res.get("status") == "provider_error"
        assert res.get("reason") == "rate_limit_exceeded"

    # 5. Empty email returned
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"data": {"email": None}})
        res = resolver.resolve_email("test.com", "John", "Doe")
        assert res is not None
        assert res.get("email") is None
        assert res.get("status") == "not_found"


def test_hunter_email_resolver_http_and_network_errors(monkeypatch):
    """Verifies that HunterEmailResolver safely handles network timeouts, auth errors, 500s, and malformed syntax."""
    monkeypatch.setenv("HUNTER_API_KEY", "test_hunter_key")
    resolver = HunterEmailResolver()

    # 1. Network timeout / RequestException
    with patch("requests.get", side_effect=requests.exceptions.Timeout("Connection timed out")):
        res = resolver.resolve_email("timeout.io", "Bob", "Stone")
        assert res is not None
        assert res.get("email") is None
        assert res.get("status") == "provider_error"
        assert "request_exception" in res.get("reason", "")

    # 2. HTTP 401 Unauthorized
    with patch("requests.get", return_value=MagicMock(status_code=401)):
        res = resolver.resolve_email("auth-fail.io", "Bob", "Stone")
        assert res is not None
        assert res.get("email") is None
        assert res.get("status") == "provider_error"
        assert res.get("reason") == "auth_failure_401"

    # 3. HTTP 500 Internal Server Error
    with patch("requests.get", return_value=MagicMock(status_code=500)):
        res = resolver.resolve_email("server-err.io", "Bob", "Stone")
        assert res is not None
        assert res.get("email") is None
        assert res.get("status") == "provider_error"
        assert res.get("reason") == "http_status_500"

    # 4. Malformed email syntax returned by provider
    with patch("requests.get", return_value=MagicMock(
        status_code=200,
        json=lambda: {"data": {"email": "not-an-email", "score": 90, "verification": {"status": "valid"}}}
    )):
        res = resolver.resolve_email("bad-syntax.io", "Bob", "Stone")
        assert res is not None
        assert res.get("email") is None
        assert res.get("status") == "invalid"
        assert res.get("reason") == "invalid_syntax"


def test_two_stage_enrichment_credit_conservation():
    """
    CRITICAL INVARIANT TEST:
    Verifies that when Stage 1 (Person Research) fails to identify a verified leader,
    Stage 2 (Email Resolution) is NEVER invoked, conserving API credits.
    """
    mock_person_adapter = MagicMock()
    mock_person_adapter.find_leader.return_value = None  # No leader identified

    mock_email_adapter = MagicMock()

    orchestrator = TwoStageEnrichmentAdapter(
        person_adapter=mock_person_adapter,
        email_adapter=mock_email_adapter
    )

    result = orchestrator.enrich("stealth-crypto-lab.io")

    # 1. Assert Stage 1 was invoked
    mock_person_adapter.find_leader.assert_called_once_with(
        domain="stealth-crypto-lab.io",
        company_name=None,
        company_context=None
    )

    # 2. Assert Stage 2 was NEVER invoked
    mock_email_adapter.resolve_email.assert_not_called()

    # 3. Assert clean return contract with zero fabrication
    assert result["contact_name"] is None
    assert result["contact_email"] is None
    assert result["contact_role"] is None
    assert result["person_confidence"] == 0.0
    assert result["email_confidence"] == 0.0
    assert result["enrichment_stage_reached"] == "person_research_failed"


def test_two_stage_enrichment_full_flow_success():
    """Verifies successful two-stage enrichment returning both verified leader and deliverable email."""
    mock_person_adapter = MagicMock()
    mock_person_adapter.find_leader.return_value = {
        "first_name": "Sergei",
        "last_name": "Petrov",
        "full_name": "Sergei Petrov",
        "role": "VP of Engineering & Cryptography",
        "linkedin_url": "https://www.linkedin.com/in/sergei-petrov",
        "source_url": "https://zk-vault.io/about",
        "person_confidence": 0.94
    }

    mock_email_adapter = MagicMock()
    mock_email_adapter.resolve_email.return_value = {
        "email": "sergei@zk-vault.io",
        "score": 92,
        "status": "valid",
        "provider": "hunter",
        "sources_count": 2
    }

    orchestrator = TwoStageEnrichmentAdapter(
        person_adapter=mock_person_adapter,
        email_adapter=mock_email_adapter
    )

    result = orchestrator.enrich(
        domain="zk-vault.io",
        company_name="ZK Vault",
        company_context={"signal": "Series A MPC"}
    )

    assert result["contact_name"] == "Sergei Petrov"
    assert result["contact_email"] == "sergei@zk-vault.io"
    assert result["contact_role"] == "VP of Engineering & Cryptography"
    assert result["person_confidence"] == 0.94
    assert result["email_confidence"] == 0.92
    assert result["email_verification_status"] == "valid"
    assert result["enrichment_provider"] == "hunter"
    assert result["enrichment_stage_reached"] == "completed"


def test_two_stage_enrichment_email_unresolved_routes_to_skip(resume_data, monkeypatch):
    """
    Verifies that when Stage 1 finds a leader but Stage 2 cannot verify an email,
    the pipeline cleanly routes to skip_node, setting delivery_status='skipped_no_email'
    and bypassing drafting and delivery.
    """
    monkeypatch.setenv("AUTO_APPROVE", "true")

    mock_person_adapter = MagicMock()
    mock_person_adapter.find_leader.return_value = {
        "first_name": "Marcus",
        "last_name": "Brody",
        "full_name": "Marcus Brody",
        "role": "Chief Technology Officer",
        "person_confidence": 0.90
    }

    mock_email_adapter = MagicMock()
    mock_email_adapter.resolve_email.return_value = None  # No verified email

    mock_enrichment_adapter = TwoStageEnrichmentAdapter(
        person_adapter=mock_person_adapter,
        email_adapter=mock_email_adapter
    )

    with patch("pipeline.adapters.base.AdapterFactory.get_enrichment_adapter", return_value=mock_enrichment_adapter):
        initial_state = {
            "domain": "stealth-ai-systems.io",
            "resume_context": resume_data,
            "auto_approve": True
        }
        result = pipeline_app.invoke(initial_state)

        assert result["contact_name"] == "Marcus Brody"
        assert result["contact_email"] is None
        assert result.get("email_draft") is None  # Drafting bypassed!
        assert result["delivery_status"] == "skipped_no_email"  # Delivery bypassed!


def test_two_stage_enrichment_end_to_end_success_through_graph(resume_data, monkeypatch):
    """
    Verifies that a fully successful two-stage enrichment:
    1. Passes leader info from Stage 1 to Stage 2.
    2. Maps all decoupled and core fields into PipelineState.
    3. Traverses has_valid_email router to drafting_node and stages payload.
    """
    monkeypatch.setenv("AUTO_APPROVE", "true")

    mock_person_adapter = MagicMock()
    mock_person_adapter.find_leader.return_value = {
        "first_name": "Nadia",
        "last_name": "Kovacs",
        "full_name": "Nadia Kovacs",
        "role": "CTO & Co-Founder",
        "linkedin_url": "https://linkedin.com/in/nadia-kovacs",
        "source_url": "https://quantum-grid.io/team",
        "evidence_snippet": "Co-Founder & CTO leading distributed consensus algorithms.",
        "person_confidence": 0.95
    }

    mock_email_adapter = MagicMock()
    mock_email_adapter.resolve_email.return_value = {
        "email": "nadia@quantum-grid.io",
        "score": 96,
        "status": "valid",
        "provider": "hunter",
        "sources_count": 3
    }

    mock_enrichment = TwoStageEnrichmentAdapter(
        person_adapter=mock_person_adapter,
        email_adapter=mock_email_adapter
    )

    with patch("pipeline.adapters.base.AdapterFactory.get_enrichment_adapter", return_value=mock_enrichment):
        initial_state = {
            "domain": "quantum-grid.io",
            "resume_context": resume_data,
            "auto_approve": True
        }
        result = pipeline_app.invoke(initial_state)

        # 1. Assert input passed correctly to Hunter
        mock_email_adapter.resolve_email.assert_called_once_with(
            domain="quantum-grid.io",
            first_name="Nadia",
            last_name="Kovacs",
            role="CTO & Co-Founder"
        )

        # 2. Assert PipelineState mappings
        assert result["contact_name"] == "Nadia Kovacs"
        assert result["contact_role"] == "CTO & Co-Founder"
        assert result["contact_email"] == "nadia@quantum-grid.io"
        assert result["person_name"] == "Nadia Kovacs"
        assert result["person_role"] == "CTO & Co-Founder"
        assert result["person_confidence"] == 0.95
        assert result["person_linkedin"] == "https://linkedin.com/in/nadia-kovacs"
        assert result["person_source"] == "https://quantum-grid.io/team"
        assert result["email_confidence"] == 0.96
        assert result["email_verification_status"] == "valid"
        assert result["enrichment_provider"] == "hunter"
        assert result["enrichment_metadata"]["status"] == "valid"
        assert result["enrichment_metadata"]["stage_reached"] == "completed"

        # 3. Assert graph continued to drafting and delivery
        assert result.get("email_draft") is not None
        assert result.get("delivery_status") == "staged"


def test_two_stage_enrichment_all_failure_modes_and_routing(resume_data, monkeypatch):
    """
    Verifies that all failure modes correctly result in contact_email=None,
    preserve failure semantics, and route safely to skip_node ('skipped_no_email').
    """
    monkeypatch.setenv("AUTO_APPROVE", "true")

    failure_scenarios = [
        # Scenario 1: No person identified by Stage 1
        {
            "leader": None,
            "expected_hunter_calls": 0,
            "email_res": None,
            "expected_status": "not_evaluated"
        },
        # Scenario 2: Person confidence below MIN_PERSON_CONFIDENCE (0.70)
        {
            "leader": {
                "first_name": "Low", "last_name": "Conf", "full_name": "Low Conf",
                "role": "CTO", "person_confidence": 0.50
            },
            "expected_hunter_calls": 0,
            "email_res": None,
            "expected_status": "not_evaluated"
        },
        # Scenario 3: Hunter returns not_found
        {
            "leader": {
                "first_name": "Marcus", "last_name": "Vance", "full_name": "Marcus Vance",
                "role": "CTO", "person_confidence": 0.90
            },
            "expected_hunter_calls": 1,
            "email_res": {"email": None, "score": 0, "status": "not_found", "reason": "no_email_returned_by_provider"},
            "expected_status": "not_found"
        },
        # Scenario 4: Hunter returns invalid status
        {
            "leader": {
                "first_name": "Marcus", "last_name": "Vance", "full_name": "Marcus Vance",
                "role": "CTO", "person_confidence": 0.90
            },
            "expected_hunter_calls": 1,
            "email_res": {"email": None, "score": 0, "status": "invalid", "reason": "mailbox_invalid_or_nonexistent"},
            "expected_status": "invalid"
        },
        # Scenario 5: Hunter returns low confidence (< 80)
        {
            "leader": {
                "first_name": "Marcus", "last_name": "Vance", "full_name": "Marcus Vance",
                "role": "CTO", "person_confidence": 0.90
            },
            "expected_hunter_calls": 1,
            "email_res": {"email": None, "score": 60, "status": "low_confidence", "reason": "score_60_below_threshold_80"},
            "expected_status": "low_confidence"
        },
        # Scenario 6: Hunter returns accept_all (rejected by default policy)
        {
            "leader": {
                "first_name": "Marcus", "last_name": "Vance", "full_name": "Marcus Vance",
                "role": "CTO", "person_confidence": 0.90
            },
            "expected_hunter_calls": 1,
            "email_res": {"email": None, "score": 88, "status": "accept_all", "reason": "catch_all_rejected_by_policy"},
            "expected_status": "accept_all"
        },
        # Scenario 7: Hunter returns provider_error (rate limit, auth, network)
        {
            "leader": {
                "first_name": "Marcus", "last_name": "Vance", "full_name": "Marcus Vance",
                "role": "CTO", "person_confidence": 0.90
            },
            "expected_hunter_calls": 1,
            "email_res": {"email": None, "score": 0, "status": "provider_error", "reason": "rate_limit_exceeded"},
            "expected_status": "provider_error"
        },
    ]

    for idx, scen in enumerate(failure_scenarios):
        mock_person = MagicMock()
        mock_person.find_leader.return_value = scen["leader"]

        mock_email = MagicMock()
        mock_email.resolve_email.return_value = scen["email_res"]

        orchestrator = TwoStageEnrichmentAdapter(
            person_adapter=mock_person,
            email_adapter=mock_email
        )

        with patch("pipeline.adapters.base.AdapterFactory.get_enrichment_adapter", return_value=orchestrator):
            state = {
                "domain": f"test-failure-domain-{idx}.io",
                "resume_context": resume_data,
                "auto_approve": True
            }
            res = pipeline_app.invoke(state)

            # Assert Hunter call count invariant
            assert mock_email.resolve_email.call_count == scen["expected_hunter_calls"], (
                f"Scenario {idx} failed Hunter call count check"
            )

            # Assert contact_email is strictly None
            assert res["contact_email"] is None

            # Assert status semantics are preserved (not collapsed to not_found)
            assert res["email_verification_status"] == scen["expected_status"]

            # Assert routing bypassed drafting and delivery
            assert res.get("email_draft") is None
            assert res["delivery_status"] == "skipped_no_email"


def test_delivery_node_anti_fabrication_safety_gate():
    """Verifies that delivery_node explicitly refuses to stage known synthetic placeholder leads."""
    from pipeline.delivery import delivery_node

    # 1. Fabricated email pattern: alex.morgan@
    fake_state = {
        "domain": "victim-domain.com",
        "contact_name": "Alex Morgan",
        "contact_email": "alex.morgan@victim-domain.com",
        "contact_role": "Lead Infrastructure Architect",
        "email_draft": "Subject: Test\n\nHello"
    }
    res = delivery_node(fake_state)
    assert res["delivery_status"] == "skipped_fabricated_contact"
    assert res["delivery_error"] == "refused_fabrication_attempt"

    # 2. Missing email
    missing_state = {
        "domain": "victim-domain.com",
        "contact_name": "Real Name",
        "contact_email": None,
        "email_draft": "Subject: Test\n\nHello"
    }
    res = delivery_node(missing_state)
    assert res["delivery_status"] == "skipped_no_email"

    # 3. Unverified / invalid verification status
    for bad_status in ["invalid", "low_confidence", "not_found", "provider_error"]:
        unverified_state = {
            "domain": "unverified-domain.com",
            "contact_name": "Real Name",
            "contact_email": "real.name@unverified-domain.com",
            "email_verification_status": bad_status,
            "email_draft": "Subject: Test\n\nHello"
        }
        res = delivery_node(unverified_state)
        assert res["delivery_status"] == "skipped_unverified_email"
        assert f"refused_verification_status_{bad_status}" in res["delivery_error"]

    # 4. Catch-all domain with ALLOW_ACCEPT_ALL=False
    catchall_state = {
        "domain": "catchall-domain.com",
        "contact_name": "Real Name",
        "contact_email": "real.name@catchall-domain.com",
        "email_verification_status": "accept_all",
        "email_draft": "Subject: Test\n\nHello"
    }
    res = delivery_node(catchall_state)
    assert res["delivery_status"] == "skipped_unverified_email"
    assert res["delivery_error"] == "refused_catch_all_policy"


def test_stub_enrichment_unknown_domain_never_fabricates():
    """Verifies that StubEnrichmentAdapter returns None for unknown domains and never generates Alex Morgan."""
    adapter = StubEnrichmentAdapter()

    # Unknown real domain
    res = adapter.enrich("random-startup-domain-999.io")
    assert res["contact_name"] is None
    assert res["contact_email"] is None
    assert res["contact_role"] is None


def test_adapter_factory_two_stage_mode(monkeypatch):
    """Verifies AdapterFactory correctly instantiates TwoStageEnrichmentAdapter in live/two_stage modes."""
    monkeypatch.setenv("ENRICHMENT_MODE", "two_stage")
    adapter = AdapterFactory.get_enrichment_adapter()
    assert isinstance(adapter, TwoStageEnrichmentAdapter)

    monkeypatch.setenv("ENRICHMENT_MODE", "stub")
    adapter_stub = AdapterFactory.get_enrichment_adapter()
    assert isinstance(adapter_stub, StubEnrichmentAdapter)


def test_enrichment_node_persists_enrichment_metadata():
    """Verifies that enrichment_node preserves enrichment_metadata in the output state."""
    from pipeline.enrichment import enrichment_node

    mock_adapter = MagicMock()
    mock_adapter.enrich.return_value = {
        "contact_name": "Sarah Connor",
        "contact_email": "sarah@cyberdyne.io",
        "contact_role": "CTO",
        "person_confidence": 0.95,
        "email_confidence": 0.90,
        "email_verification_status": "valid",
        "enrichment_metadata": {
            "evidence_snippet": "Founder and CTO of Cyberdyne Systems",
            "sources_count": 3
        }
    }

    with patch("pipeline.adapters.base.AdapterFactory.get_enrichment_adapter", return_value=mock_adapter):
        state = {"domain": "cyberdyne.io"}
        res = enrichment_node(state)
        assert res["contact_name"] == "Sarah Connor"
        assert res["contact_email"] == "sarah@cyberdyne.io"
        assert res["enrichment_metadata"] == {
            "evidence_snippet": "Founder and CTO of Cyberdyne Systems",
            "sources_count": 3
        }


def test_run_discovered_flow_session_deduplication(monkeypatch):
    """Verifies that run_discovered_flow skips duplicate domains returned across multiple discovery batches."""
    from main import run_discovered_flow

    monkeypatch.setenv("MAX_DISCOVERY_ATTEMPTS", "10")
    monkeypatch.setattr("main.check_volume_caps", lambda: {
        "effective_allowance": 2,
        "max_day": 3,
        "max_week": 10,
        "sends_today": 0,
        "sends_week": 0,
        "remaining_day": 3,
        "remaining_week": 10
    })

    # Mock discovery adapter returning duplicate domains in subsequent batches
    batches = [
        [{"domain": "candidate-one.com", "company_name": "One"}, {"domain": "dup-domain.com", "company_name": "Dup"}],
        [{"domain": "dup-domain.com", "company_name": "Dup"}, {"domain": "candidate-two.com", "company_name": "Two"}]
    ]
    batch_idx = {"val": 0}

    mock_disc_adapter = MagicMock()
    def mock_discover(*args, **kwargs):
        if batch_idx["val"] < len(batches):
            b = batches[batch_idx["val"]]
            batch_idx["val"] += 1
            return list(b)
        return []

    mock_disc_adapter.discover.side_effect = mock_discover

    invoked_domains = []
    def mock_pipeline_invoke(state):
        invoked_domains.append(state["domain"])
        # Both succeed
        return {
            "domain": state["domain"],
            "contact_name": "Leader",
            "contact_email": f"leader@{state['domain']}",
            "contact_role": "CTO",
            "delivery_status": "staged"
        }

    with patch("pipeline.adapters.base.AdapterFactory.get_discovery_adapter", return_value=mock_disc_adapter), \
         patch("main.pipeline_app.invoke", side_effect=mock_pipeline_invoke), \
         patch("main.is_already_contacted", return_value=False):
        run_discovered_flow(
            target_count=2,
            company_size="small",
            resume_context={"name": "Candidate"},
            auto_approve=True,
            max_attempts=10
        )

    # dup-domain.com was returned in batch 1 and batch 2, but should only be invoked once
    assert invoked_domains == ["candidate-one.com", "dup-domain.com"]







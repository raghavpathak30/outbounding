"""
Tests that the operator's Profile drives email drafting at the adapter and
graph-node level. Job manager and delivery service wiring against real Profile
rows is covered in test_server_jobs.py and test_server_delivery.py.
"""
from unittest.mock import MagicMock, patch

import pytest

from pipeline.adapters.live import LiveDraftingAdapter
from pipeline.adapters.stub import StubDraftingAdapter
from pipeline.delivery import delivery_node
from pipeline.drafting import drafting_node

SECTION_TITLE = (
    "OPERATOR INSTRUCTIONS (follow these; they override the persona strategy "
    "but never the anti-fabrication rules)"
)
SECURITY_ROLE = "Head of Security"
AI_ROLE = "VP of Machine Learning"
GENERAL_ROLE = "Director of Talent"
ALL_ROLES = [SECURITY_ROLE, AI_ROLE, GENERAL_ROLE]
PROFILE_URL = "https://profile.example/me"
RESUME_URL = "https://resume.example/me"


def build_prompt(resume_context=None, operator_profile=None, role=SECURITY_ROLE):
    prompt, _bullets, _persona = LiveDraftingAdapter().build_prompt(
        role=role,
        domain="target.example",
        resume_context={} if resume_context is None else resume_context,
        contact_name="Sam Rivera",
        operator_profile=operator_profile,
    )
    return prompt


# ---------------------------------------------------------------------
# custom_instructions
# ---------------------------------------------------------------------

def test_custom_instructions_appear_in_prompt_under_titled_section():
    prompt = build_prompt(operator_profile={"custom_instructions": "Mention my open-source work first."})

    assert SECTION_TITLE in prompt
    assert "Mention my open-source work first." in prompt
    assert prompt.index(SECTION_TITLE) < prompt.index("Mention my open-source work first.")
    # Appended after the writing rules, not spliced into them.
    assert prompt.index("CRITICAL WRITING REQUIREMENTS") < prompt.index(SECTION_TITLE)


@pytest.mark.parametrize("operator_profile", [
    None,
    {},
    {"custom_instructions": None},
    {"custom_instructions": ""},
    {"custom_instructions": "  \n\t "},
])
def test_blank_custom_instructions_add_no_section(operator_profile):
    assert "OPERATOR INSTRUCTIONS" not in build_prompt(operator_profile=operator_profile)


def test_draft_sends_custom_instructions_to_the_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key")
    with patch("langchain_google_genai.ChatGoogleGenerativeAI") as mock_llm_class, \
            patch("pipeline.adapters.live.execute_with_quota_retry", lambda fn, adapter_name: fn()):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Subject: Hi\n\nBody")
        mock_llm_class.return_value = mock_llm

        LiveDraftingAdapter().draft(
            role=SECURITY_ROLE,
            domain="target.example",
            resume_context={},
            contact_name="Sam Rivera",
            operator_profile={"custom_instructions": "Mention my open-source work first."},
        )

    sent_prompt = mock_llm.invoke.call_args.args[0][0]["content"]
    assert SECTION_TITLE in sent_prompt
    assert "Mention my open-source work first." in sent_prompt


# ---------------------------------------------------------------------
# portfolio_url
# ---------------------------------------------------------------------

def test_profile_portfolio_replaces_resume_portfolio_in_prompt():
    prompt = build_prompt(
        resume_context={"personal": {"portfolio": RESUME_URL}},
        operator_profile={"portfolio_url": PROFILE_URL},
    )
    assert PROFILE_URL in prompt
    assert RESUME_URL not in prompt


@pytest.mark.parametrize("operator_profile", [None, {"portfolio_url": None}, {"portfolio_url": "  "}])
def test_resume_portfolio_used_when_profile_portfolio_unset(operator_profile):
    prompt = build_prompt(
        resume_context={"personal": {"portfolio": RESUME_URL}},
        operator_profile=operator_profile,
    )
    assert RESUME_URL in prompt


@pytest.mark.parametrize("resume_context", [
    {},
    {"personal": None},
    {"personal": {}},
    {"personal": {"portfolio": None}},
    {"personal": {"portfolio": ""}},
])
def test_prompt_forbids_a_link_when_no_portfolio_exists(resume_context):
    prompt = build_prompt(resume_context=resume_context)

    assert "raghavpathak.dev" not in prompt
    assert "Portfolio URL: None\n" not in prompt
    assert "code here: '" not in prompt
    assert "Always include the portfolio link" not in prompt
    assert "one portfolio link line" not in prompt
    assert "No portfolio URL is available" in prompt


# ---------------------------------------------------------------------
# Persona strings describe emphasis, never facts
# ---------------------------------------------------------------------

@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.parametrize("claim", [
    "grand finalist",
    "iit hyderabad",
    "lnmiit",
    "b.tech",
    "side-channel",
    "dss modular",
    "ckks",
    "gemini",
    "google ai studio",
])
def test_prompt_makes_no_candidate_claims_without_resume_highlights(role, claim):
    assert claim not in build_prompt(resume_context={}, role=role).lower()


# ---------------------------------------------------------------------
# Stub adapter and graph nodes
# ---------------------------------------------------------------------

def test_stub_adapter_accepts_operator_profile():
    draft = StubDraftingAdapter().draft(
        role=SECURITY_ROLE,
        domain="target.example",
        resume_context={},
        contact_name="Sam Rivera",
        operator_profile={"custom_instructions": "ignored by the stub"},
    )
    assert "target.example" in draft


def test_drafting_node_forwards_operator_profile():
    adapter = MagicMock()
    adapter.draft.return_value = "draft"
    profile = {"custom_instructions": "Be brief."}

    with patch("pipeline.drafting.AdapterFactory.get_drafting_adapter", return_value=adapter):
        drafting_node({
            "domain": "target.example",
            "resume_context": {"personal": {}},
            "operator_profile": profile,
        })

    assert adapter.draft.call_args.kwargs["operator_profile"] == profile


@pytest.mark.parametrize("state_extra,expected", [
    ({"operator_profile": {"portfolio_url": PROFILE_URL}, "resume_context": {"personal": {"portfolio": RESUME_URL}}}, PROFILE_URL),
    ({"resume_context": {"personal": {"portfolio": RESUME_URL}}}, RESUME_URL),
    ({}, ""),
])
def test_delivery_node_portfolio_variable(state_extra, expected):
    adapter = MagicMock()
    adapter.deliver.return_value = {"status": "staged"}

    with patch("pipeline.delivery.AdapterFactory.get_delivery_adapter", return_value=adapter), \
            patch("pipeline.delivery.record_contacted"):
        delivery_node({
            "domain": "target.example",
            "contact_email": "sam@target.example",
            "email_draft": "Subject: Hi\n\nBody",
            **state_extra,
        })

    payload = adapter.deliver.call_args.args[0]
    assert payload["custom_variables"]["candidate_portfolio"] == expected

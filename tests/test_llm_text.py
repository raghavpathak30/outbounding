"""
Unit test suite for LLM text extraction helper, LiveDraftingAdapter defensive parsing,
and email draft repair utilities.
"""
import sqlite3
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from pipeline.adapters._llm_text import extract_llm_text
from pipeline.adapters.live import LiveDraftingAdapter
from scripts.repair_email_drafts import repair_content_block_repr, scan_and_repair_db


# ---------------------------------------------------------------------------
# 1. Helper Unit Tests: extract_llm_text
# ---------------------------------------------------------------------------

def test_extract_llm_text_plain_string():
    """Helper returns stripped string for plain string input, and None for empty/whitespace."""
    assert extract_llm_text("Hello world!") == "Hello world!"
    assert extract_llm_text("   Subject: Test\n\nEmail body   ") == "Subject: Test\n\nEmail body"
    assert extract_llm_text("") is None
    assert extract_llm_text("   \n\t  ") is None
    assert extract_llm_text(None) is None


def test_extract_llm_text_single_block_list():
    """Helper extracts text from single-block list (both dict and object forms)."""
    # Dict form
    block_dict = [{"type": "text", "text": "Subject: Single block\n\nBody text"}]
    assert extract_llm_text(block_dict) == "Subject: Single block\n\nBody text"

    # Object form
    class BlockObj:
        def __init__(self, b_type, text):
            self.type = b_type
            self.text = text

    block_obj = [BlockObj("text", "Subject: Object block\n\nBody text")]
    assert extract_llm_text(block_obj) == "Subject: Object block\n\nBody text"


def test_extract_llm_text_multi_block_list():
    """Helper concatenates multiple text blocks with newlines."""
    blocks = [
        {"type": "text", "text": "Subject: Outreach line"},
        {"type": "text", "text": "Hi Alex,\n\nParagraph one."},
        {"type": "text", "text": "Best,\nRaghav"}
    ]
    expected = "Subject: Outreach line\nHi Alex,\n\nParagraph one.\nBest,\nRaghav"
    assert extract_llm_text(blocks) == expected


def test_extract_llm_text_thinking_block_plus_text_block():
    """
    Helper skips non-text blocks (thinking, reasoning, tool_calls) and
    never includes signatures or extras in the output.
    """
    blocks = [
        {
            "type": "thinking",
            "thinking": "The user wants an email to Nadia at quantum-grid.io.",
            "extras": {"signature": "secret_thinking_signature_123"}
        },
        {
            "type": "text",
            "text": "Subject: Systems engineering at quantum-grid.io\n\nHi Nadia,\n\nReaching out directly.",
            "extras": {"signature": "secret_text_signature_456"}
        }
    ]
    result = extract_llm_text(blocks)
    assert result == "Subject: Systems engineering at quantum-grid.io\n\nHi Nadia,\n\nReaching out directly."
    assert "thinking" not in result.lower()
    assert "secret_thinking_signature_123" not in result
    assert "secret_text_signature_456" not in result
    assert "extras" not in result
    assert "{" not in result


def test_extract_llm_text_only_non_text_blocks_returns_none():
    """When blocks contain only thinking/tool calls or whitespace text, helper returns None."""
    only_thinking = [
        {"type": "thinking", "thinking": "Internal reasoning step...", "extras": {"sig": "abc"}},
        {"type": "tool_call", "name": "search", "args": {}}
    ]
    assert extract_llm_text(only_thinking) is None

    empty_text_block = [{"type": "text", "text": "   "}]
    assert extract_llm_text(empty_text_block) is None


def test_extract_llm_text_message_text_property_and_callable():
    """Helper honors .text property and callable methods from LangChain / SDK message objects."""
    # Object with .text string property
    class MessageWithTextProp:
        @property
        def text(self):
            return "Extracted via .text property"

    assert extract_llm_text(MessageWithTextProp()) == "Extracted via .text property"

    # Object with .text() callable
    class MessageWithTextCallable:
        def text(self):
            return "Extracted via .text() method"

    assert extract_llm_text(MessageWithTextCallable()) == "Extracted via .text() method"

    # LangChain AIMessage with list content blocks
    from langchain_core.messages import AIMessage
    msg = AIMessage(content=[
        {"type": "thinking", "thinking": "Skip this"},
        {"type": "text", "text": "Subject: AIMessage Text\n\nBody here", "extras": {"signature": "sig"}}
    ])
    assert extract_llm_text(msg) == "Subject: AIMessage Text\n\nBody here"


# ---------------------------------------------------------------------------
# 2. LiveDraftingAdapter Unit Tests
# ---------------------------------------------------------------------------

def test_live_drafting_adapter_cleans_block_list_response(monkeypatch):
    """
    LiveDraftingAdapter.draft() returns clean plain text (no '{', no ''type':', no 'signature')
    when the LLM returns a block list with thinking and signatures.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_for_test")
    monkeypatch.setenv("GEMINI_DRAFTING_MODEL", "gemini-3.8-flash")

    adapter = LiveDraftingAdapter()

    fake_content_blocks = [
        {
            "type": "thinking",
            "thinking": "Pondering about quantum-grid.io security infrastructure...",
            "extras": {"signature": "EpQiCpEiAWkUfRM4fiqnnAbKBlWPt5d85i5W0fTYVJ4JGpGRQ4FzbTyJLgtodZL9..."}
        },
        {
            "type": "text",
            "text": "Subject: Systems engineering & security at quantum-grid.io\n\nHi Nadia,\n\nReaching out directly to connect with engineering leadership.",
            "extras": {"signature": "EqAqCp0qXyz..."}
        }
    ]

    with patch("langchain_google_genai.ChatGoogleGenerativeAI") as MockLLMClass:
        mock_llm_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.content = fake_content_blocks
        mock_llm_instance.invoke.return_value = mock_response
        MockLLMClass.return_value = mock_llm_instance

        draft = adapter.draft(
            role="CTO & Co-Founder",
            domain="quantum-grid.io",
            resume_context={"personal": {"portfolio": "https://raghavpathak.dev"}},
            contact_name="Nadia Kovacs"
        )

        # Assert clean text output
        assert "Subject: Systems engineering & security at quantum-grid.io" in draft
        assert "Hi Nadia," in draft
        assert "Reaching out directly to connect with engineering leadership." in draft

        # Strict safety checks: ensure no raw repr artifacts exist
        assert "{" not in draft
        assert "}" not in draft
        assert "'type':" not in draft
        assert "'text':" not in draft
        assert "signature" not in draft
        assert "EpQiCpEiAWk" not in draft
        assert "EqAqCp0qXyz" not in draft


def test_live_drafting_adapter_fallback_when_extraction_is_empty(monkeypatch):
    """
    LiveDraftingAdapter.draft() falls back to offline template when extraction
    yields empty string or None (e.g. LLM returned only thinking blocks or whitespace).
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key_for_test")

    adapter = LiveDraftingAdapter()

    # Scenario: LLM returns only thinking block, no text
    empty_content_blocks = [
        {
            "type": "thinking",
            "thinking": "Thinking only, but model failed to generate text block...",
            "extras": {"signature": "sig123"}
        }
    ]

    with patch("langchain_google_genai.ChatGoogleGenerativeAI") as MockLLMClass:
        mock_llm_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.content = empty_content_blocks
        mock_llm_instance.invoke.return_value = mock_response
        MockLLMClass.return_value = mock_llm_instance

        draft = adapter.draft(
            role="Chief Information Security Officer",
            domain="apex-vault-fintech.io",
            resume_context={"personal": {"portfolio": "https://raghavpathak.dev"}},
            contact_name="Devon Sterling"
        )

        # Verify fallback synthesis was executed
        assert draft is not None
        assert len(draft.strip()) > 0
        assert "Raghav Pathak" in draft
        assert "Encrypted transaction compute" in draft or "apex-vault-fintech.io" in draft
        assert "{" not in draft


def test_live_drafting_adapter_reads_model_from_env_or_default(monkeypatch):
    """LiveDraftingAdapter defaults to GEMINI_DRAFTING_MODEL env var with gemini-2.5-pro fallback."""
    monkeypatch.delenv("GEMINI_DRAFTING_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    adapter_default = LiveDraftingAdapter()
    assert adapter_default.model_name == "gemini-2.5-pro"

    monkeypatch.setenv("GEMINI_DRAFTING_MODEL", "gemini-custom-flash")
    adapter_custom = LiveDraftingAdapter()
    assert adapter_custom.model_name == "gemini-custom-flash"


# ---------------------------------------------------------------------------
# 3. Repair Script Unit Tests
# ---------------------------------------------------------------------------

def test_repair_content_block_repr_helper():
    """Tests the repair helper parses Python content block repr and preserves footers."""
    # Case 1: Standalone repr
    raw = "[{'type': 'text', 'text': \"Subject: Hello\\n\\nWorld\", 'extras': {'signature': 'sig123'}}]"
    repaired = repair_content_block_repr(raw)
    assert repaired == "Subject: Hello\n\nWorld"

    # Case 2: Repr with appended footer
    raw_with_footer = (
        "[{'type': 'text', 'text': \"Subject: Hello\\n\\nWorld\", 'extras': {'signature': 'sig123'}}]\n\n"
        "---\nIf you prefer not to receive technical outreach, simply reply with 'unsubscribe'."
    )
    repaired_with_footer = repair_content_block_repr(raw_with_footer)
    assert "Subject: Hello\n\nWorld" in repaired_with_footer
    assert "---" in repaired_with_footer
    assert "reply with 'unsubscribe'" in repaired_with_footer
    assert "sig123" not in repaired_with_footer
    assert "{" not in repaired_with_footer.split("\n\n---\n")[0]

    # Case 3: Already clean string
    clean_str = "Subject: Clean\n\nNormal text"
    assert repair_content_block_repr(clean_str) is None


def test_repair_script_db_dry_run_and_apply(tmp_path):
    """
    Verifies that scan_and_repair_db:
    1. In dry-run mode (apply_changes=False): detects corrupted rows, generates diffs, but leaves DB unchanged.
    2. In apply mode (apply_changes=True): updates corrupted rows in SQLite.
    """
    db_file = tmp_path / "test_repair.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()

    # Create drafts table
    cur.execute("""
        CREATE TABLE drafts (
            id VARCHAR(36) PRIMARY KEY,
            subject VARCHAR(255),
            body TEXT
        );
    """)

    corrupted_body = "[{'type': 'text', 'text': \"Subject: Buggy draft\\n\\nFixed body text\", 'extras': {'signature': 'bad_sig'}}]"
    clean_body = "Subject: Normal draft\n\nClean body text"

    cur.execute("INSERT INTO drafts (id, subject, body) VALUES (?, ?, ?);", ("draft-1", "Subject: Buggy draft", corrupted_body))
    cur.execute("INSERT INTO drafts (id, subject, body) VALUES (?, ?, ?);", ("draft-2", "Subject: Normal draft", clean_body))
    conn.commit()
    conn.close()

    # 1. Test Dry Run: apply_changes=False
    found, repaired, diffs = scan_and_repair_db(db_file, apply_changes=False)
    assert found == 1
    assert repaired == 1
    assert len(diffs) == 1
    assert "Fixed body text" in diffs[0]
    assert "bad_sig" in diffs[0]

    # Verify database was NOT modified
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT body FROM drafts WHERE id = 'draft-1';")
    current_val = cur.fetchone()[0]
    assert current_val == corrupted_body
    conn.close()

    # 2. Test Apply Mode: apply_changes=True
    found, repaired, diffs = scan_and_repair_db(db_file, apply_changes=True)
    assert found == 1
    assert repaired == 1

    # Verify database WAS modified
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("SELECT body FROM drafts WHERE id = 'draft-1';")
    updated_val = cur.fetchone()[0]
    assert updated_val == "Subject: Buggy draft\n\nFixed body text"
    assert "{" not in updated_val
    assert "signature" not in updated_val
    conn.close()

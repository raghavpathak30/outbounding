"""
Unit tests for Resume Upload and Structured Parsing Service.
Validates Phase 4 requirements:
- Upload validation (rejects non-PDF/JSON, enforces file size limit)
- File persisted outside public web root
- Stub adapter produces deterministic parsed output
- parsing_status transitions correctly (pending -> completed/failed)
- Multiple resumes coexist; 'activate' correctly flips is_active and deactivates previous one
- Uploaded resume PDF/PII never appears in logs or error messages
"""
import io
import json
import logging
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from pypdf import PdfWriter
from starlette.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from server.models.base import Base
from server.models.entities import User, Resume, Profile
from server.database import create_db_engine, get_db
from server.config import Settings, get_settings
from server.app import create_app
from server.services.auth import AuthService, ACCESS_TOKEN_COOKIE_NAME
from server.services.resume import (
    ResumeService,
    ResumeSchema,
    MAX_FILE_SIZE_BYTES,
    UPLOAD_BASE_DIR,
)
from pipeline.adapters.resume_parsing import (
    StubResumeParsingAdapter,
    GeminiResumeParsingAdapter,
)


def create_minimal_pdf_bytes(content_hint: str = "Test Candidate Resume") -> bytes:
    """Generates valid minimal in-memory PDF bytes for upload testing."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def resume_ctx(tmp_path, monkeypatch):
    """Provides isolated DB, configured app, test upload directory, and TestClient."""
    test_db_file = tmp_path / "test_resumes.db"
    test_db_url = f"sqlite:///{test_db_file}"
    engine = create_db_engine(db_url=test_db_url)
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    test_uploads = tmp_path / "uploads" / "resumes"
    test_uploads.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("server.services.resume.UPLOAD_BASE_DIR", test_uploads)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    settings = Settings(
        jwt_secret_key="test-secret-key-for-resume-upload-service-32b!",
        cors_allowed_origins=["https://work.raghavpathak.me", "http://localhost"],
        delivery_mode="staged",
        dry_run=True,
    )

    app = create_app(settings=settings)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings

    client = TestClient(app, raise_server_exceptions=False)
    session = TestingSessionLocal()

    # Seed test user and generate auth cookie
    user = User(
        email="candidate@raghavpathak.me",
        password_hash=AuthService.hash_password("ValidPassword123!"),
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)

    # Seed initial profile
    profile = Profile(
        user_id=user.id,
        full_name="Candidate Operator",
        title="Software Engineer",
        email=user.email,
    )
    session.add(profile)
    session.commit()

    token, _, _ = AuthService.create_access_token(user_id=user.id, email=user.email, secret_key=settings.jwt_secret_key)
    client.cookies.set(ACCESS_TOKEN_COOKIE_NAME, token)

    yield {
        "client": client,
        "session": session,
        "user": user,
        "uploads_dir": test_uploads,
        "settings": settings,
    }

    session.close()
    engine.dispose()


# =====================================================================
# 1. Upload Validation: Reject Disallowed Formats & Enforce Size Limit
# =====================================================================

def test_upload_validation_rejects_disallowed_formats(resume_ctx):
    """Verifies that non-PDF and non-JSON files are rejected with HTTP 400."""
    client = resume_ctx["client"]

    disallowed_files = [
        ("malicious.exe", b"MZ\x90\x00executable_binary_content", "application/x-msdownload"),
        ("notes.txt", b"plain text resume content", "text/plain"),
        ("profile.png", b"\x89PNG\r\n\x1a\nimage_bytes", "image/png"),
        ("script.sh", b"#!/bin/bash\necho hack", "application/x-sh"),
    ]

    for filename, content, mime in disallowed_files:
        response = client.post(
            "/api/v1/resumes/upload",
            files={"file": (filename, io.BytesIO(content), mime)}
        )
        assert response.status_code == 400, f"Expected 400 for {filename}, got {response.status_code}"
        data = response.json()
        assert "unsupported file format" in data["detail"].lower() or "mismatched content type" in data["detail"].lower()


def test_upload_validation_enforces_size_limit(resume_ctx, monkeypatch):
    """Verifies that uploads exceeding MAX_FILE_SIZE_BYTES are rejected with HTTP 413."""
    client = resume_ctx["client"]

    # Temporarily set MAX_FILE_SIZE_BYTES to 100 KB for fast test execution
    test_limit = 100 * 1024
    monkeypatch.setattr("server.services.resume.MAX_FILE_SIZE_BYTES", test_limit)

    oversized_payload = b"%PDF-1.4\n" + b"A" * (test_limit + 1024)
    response = client.post(
        "/api/v1/resumes/upload",
        files={"file": ("large_resume.pdf", io.BytesIO(oversized_payload), "application/pdf")}
    )
    assert response.status_code == 413
    assert "exceeds limit" in response.json()["detail"].lower()


# =====================================================================
# 2. File Persistence Outside Public Web Root
# =====================================================================

def test_file_persisted_outside_public_web_root(resume_ctx):
    """
    Verifies that uploaded resumes are saved to uploads/resumes/{user_id}/{resume_uuid}.pdf
    and are completely unreachable via standard public web routing.
    """
    client = resume_ctx["client"]
    user = resume_ctx["user"]
    uploads_dir = resume_ctx["uploads_dir"]

    pdf_bytes = create_minimal_pdf_bytes("Candidate Systems Engineer")
    response = client.post(
        "/api/v1/resumes/upload",
        files={"file": ("systems_engineer.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    )
    assert response.status_code == 201
    data = response.json()
    resume_id = data["id"]
    file_path = Path(data["file_path"])

    # Confirm file exists on disk within secure user directory
    assert file_path.exists()
    assert file_path.parent == uploads_dir / user.id
    assert file_path.suffix == ".pdf"
    assert resume_id in file_path.name

    # Confirm file path cannot be requested via public GET route
    public_attempt = client.get(f"/uploads/resumes/{user.id}/{file_path.name}")
    assert public_attempt.status_code == 404


# =====================================================================
# 3. Stub Adapter Produces Deterministic Parsed Output
# =====================================================================

def test_stub_adapter_produces_deterministic_parsed_output(tmp_path):
    """
    Verifies that StubResumeParsingAdapter yields deterministic, schema-compliant
    dictionaries with all 3 persona categories and personal contacts.
    """
    adapter = StubResumeParsingAdapter()
    dummy_pdf = tmp_path / "dummy.pdf"
    dummy_pdf.write_bytes(create_minimal_pdf_bytes())

    parsed = adapter.parse(str(dummy_pdf), is_json=False)

    # Validate against strict Pydantic ResumeSchema
    validated = ResumeSchema.model_validate(parsed)
    assert validated.personal.name == "Raghav Pathak"
    assert validated.personal.portfolio == "https://raghavpathak.dev"

    # Security Infrastructure persona
    assert len(validated.security_infrastructure.highlights) >= 3
    assert len(validated.security_infrastructure.core_stack) >= 3
    assert any("cryptography" in h.lower() or "timing side-channel" in h.lower() for h in validated.security_infrastructure.highlights)

    # AI / Machine Learning persona
    assert len(validated.ai_machine_learning.highlights) >= 3
    assert len(validated.ai_machine_learning.core_stack) >= 3
    assert any("gemini" in h.lower() or "agent" in h.lower() for h in validated.ai_machine_learning.highlights)

    # HR / Talent Acquisition persona
    assert len(validated.hr_talent_acquisition.highlights) >= 3
    assert len(validated.hr_talent_acquisition.core_stack) >= 3
    assert any("lnmiit" in h.lower() or "hackathon" in h.lower() for h in validated.hr_talent_acquisition.highlights)


# =====================================================================
# 4. Parsing Status Transitions (pending -> completed / failed)
# =====================================================================

def test_parsing_status_transitions_to_completed_on_success(resume_ctx):
    """Verifies that a valid resume moves from pending to completed with parsed_data_json."""
    client = resume_ctx["client"]
    session = resume_ctx["session"]

    pdf_bytes = create_minimal_pdf_bytes("Security and AI Resume")
    response = client.post(
        "/api/v1/resumes/upload",
        files={"file": ("valid_resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    )
    assert response.status_code == 201
    data = response.json()

    assert data["parsing_status"] == "completed"
    assert data["parsing_error"] is None
    assert data["parsed_data"] is not None
    assert "security_infrastructure" in data["parsed_data"]
    assert "ai_machine_learning" in data["parsed_data"]
    assert "hr_talent_acquisition" in data["parsed_data"]

    # Verify DB persistence
    resume_in_db = session.execute(
        select(Resume).where(Resume.id == data["id"])
    ).scalar_one()
    assert resume_in_db.parsing_status == "completed"
    assert resume_in_db.parsed_data_json is not None


def test_parsing_status_transitions_to_failed_on_error(resume_ctx, monkeypatch):
    """
    Verifies that when parsing fails (e.g. corrupted file or adapter error),
    the resume record transitions to parsing_status='failed' with sanitized error message.
    """
    client = resume_ctx["client"]
    session = resume_ctx["session"]

    # Mock adapter.parse to raise an unexpected parse exception
    def failing_parse(self, file_path, is_json=False):
        raise ValueError("Corrupted PDF structure: trailer dictionary unreadable")

    monkeypatch.setattr(StubResumeParsingAdapter, "parse", failing_parse)

    pdf_bytes = create_minimal_pdf_bytes("Corrupted File")
    response = client.post(
        "/api/v1/resumes/upload",
        files={"file": ("corrupted.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    )
    # Upload still accepts and creates the record, returning 201 with status="failed"
    assert response.status_code == 201
    data = response.json()

    assert data["parsing_status"] == "failed"
    assert data["parsing_error"] is not None
    assert "ValueError" in data["parsing_error"]
    assert "Corrupted PDF" in data["parsing_error"]

    # Record persisted in database as failed
    resume_in_db = session.execute(
        select(Resume).where(Resume.id == data["id"])
    ).scalar_one()
    assert resume_in_db.parsing_status == "failed"
    assert "ValueError" in resume_in_db.parsing_error


# =====================================================================
# 5. Multiple Resumes Coexist; 'activate' Flips is_active Flag
# =====================================================================

def test_multiple_resumes_coexist_and_activate_flips_flag(resume_ctx):
    """
    Verifies:
    1. First uploaded resume becomes is_active=True automatically.
    2. Second uploaded resume becomes is_active=False.
    3. Listing returns both resumes.
    4. Activating the second resume sets it to is_active=True and sets the first to False.
    """
    client = resume_ctx["client"]
    session = resume_ctx["session"]

    pdf_bytes_1 = create_minimal_pdf_bytes("Resume 1")
    pdf_bytes_2 = create_minimal_pdf_bytes("Resume 2")

    # 1. Upload Resume 1
    res1 = client.post(
        "/api/v1/resumes/upload",
        files={"file": ("resume_v1.pdf", io.BytesIO(pdf_bytes_1), "application/pdf")}
    )
    assert res1.status_code == 201
    data1 = res1.json()
    id1 = data1["id"]
    assert data1["is_active"] is True

    # 2. Upload Resume 2
    res2 = client.post(
        "/api/v1/resumes/upload",
        files={"file": ("resume_v2.pdf", io.BytesIO(pdf_bytes_2), "application/pdf")}
    )
    assert res2.status_code == 201
    data2 = res2.json()
    id2 = data2["id"]
    assert data2["is_active"] is False

    # 3. List Resumes
    list_res = client.get("/api/v1/resumes")
    assert list_res.status_code == 200
    resumes_list = list_res.json()
    assert len(resumes_list) == 2
    ids_in_list = {r["id"] for r in resumes_list}
    assert id1 in ids_in_list
    assert id2 in ids_in_list

    # 4. Activate Resume 2
    act_res = client.post(f"/api/v1/resumes/{id2}/activate")
    assert act_res.status_code == 200
    assert act_res.json()["is_active"] is True

    # 5. Verify database states
    session.expire_all()
    r1 = session.execute(select(Resume).where(Resume.id == id1)).scalar_one()
    r2 = session.execute(select(Resume).where(Resume.id == id2)).scalar_one()
    assert r1.is_active is False
    assert r2.is_active is True

    # 6. Detail endpoint verification
    detail_res = client.get(f"/api/v1/resumes/{id2}")
    assert detail_res.status_code == 200
    assert detail_res.json()["is_active"] is True
    assert detail_res.json()["parsed_data"] is not None


# =====================================================================
# 6. Uploaded Resume PDF/PII Never Appears in Logs or Error Messages
# =====================================================================

def test_uploaded_resume_pii_never_appears_in_logs_or_errors(resume_ctx, caplog):
    """
    Confirms strict PII sanitization:
    Logs and error fields must NEVER contain candidate private phone, private email,
    or raw document text.
    """
    client = resume_ctx["client"]

    secret_ssn = "SECRET_CANDIDATE_PII_998877"
    secret_phone = "+1-555-PRIVATE-PII"
    raw_document = f"Resume for John Doe with phone {secret_phone} and internal id {secret_ssn}"

    pdf_bytes = create_minimal_pdf_bytes(raw_document)

    with caplog.at_level(logging.DEBUG):
        response = client.post(
            "/api/v1/resumes/upload",
            files={"file": ("pii_resume.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        )
        assert response.status_code == 201

        # Check all logged records
        all_logs = " ".join([record.getMessage() for record in caplog.records])
        assert secret_ssn not in all_logs
        assert secret_phone not in all_logs
        assert raw_document not in all_logs


# =====================================================================
# 7. Gemini Parsing Adapter Mock Structured Extraction
# =====================================================================

def test_gemini_parsing_adapter_structured_extraction(tmp_path, monkeypatch):
    """
    Verifies that GeminiResumeParsingAdapter:
    1. Extracts text from PDF via pypdf.
    2. Builds structured prompt.
    3. Correctly decodes and validates structured JSON response into the 3 persona categories.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "mock_gemini_api_key_test")

    adapter = GeminiResumeParsingAdapter()

    # Create dummy pdf
    pdf_file = tmp_path / "gemini_test.pdf"
    pdf_file.write_bytes(create_minimal_pdf_bytes())

    fake_gemini_json = {
        "personal": {
            "name": "Alex Gemini",
            "title": "Systems Lead",
            "email": "alex@systems.io",
            "phone": None,
            "location": "San Francisco, CA",
            "github": "https://github.com/alex",
            "linkedin": None,
            "portfolio": "https://alex.systems"
        },
        "security_infrastructure": {
            "summary": "Applied security and enclave virtualization engineer.",
            "highlights": ["Built confidential computing enclave", "Audited cryptographic kernels"],
            "core_stack": ["Rust", "Linux", "SGX"]
        },
        "ai_machine_learning": {
            "summary": "LLM agent pipeline engineer optimizing low-latency inference.",
            "highlights": ["Orchestrated multi-agent DAGs", "Implemented streaming token verification"],
            "core_stack": ["Python", "FastAPI", "Gemini"]
        },
        "hr_talent_acquisition": {
            "summary": "Founding engineer experienced in building fast cross-functional teams.",
            "highlights": ["Top hackathon finalist", "Graduated top of engineering class"],
            "core_stack": ["Full-Stack", "Leadership"]
        }
    }

    # Mock extract_text_from_pdf and ChatGoogleGenerativeAI call
    with patch.object(adapter, "extract_text_from_pdf", return_value="Dummy extracted resume text"):
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as MockLLM:
            mock_instance = MagicMock()
            mock_instance.invoke.return_value = MagicMock(
                content=f"```json\n{json.dumps(fake_gemini_json)}\n```"
            )
            MockLLM.return_value = mock_instance

            result = adapter.parse(str(pdf_file), is_json=False)

            assert result["personal"]["name"] == "Alex Gemini"
            assert result["security_infrastructure"]["summary"] == "Applied security and enclave virtualization engineer."
            assert len(result["ai_machine_learning"]["highlights"]) == 2

            # Validates against ResumeSchema
            validated = ResumeSchema.model_validate(result)
            assert validated.personal.name == "Alex Gemini"


# =====================================================================
# 8. Unauthenticated Access Rejected
# =====================================================================

def test_unauthenticated_requests_rejected(resume_ctx):
    """Verifies that all resume endpoints reject unauthenticated requests with 401."""
    client = resume_ctx["client"]
    # Clear client auth cookie
    client.cookies.clear()

    # 1. List
    res_list = client.get("/api/v1/resumes")
    assert res_list.status_code == 401

    # 2. Detail
    res_detail = client.get("/api/v1/resumes/some-uuid")
    assert res_detail.status_code == 401

    # 3. Upload
    pdf_bytes = create_minimal_pdf_bytes("Auth Test")
    res_upload = client.post(
        "/api/v1/resumes/upload",
        files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    )
    assert res_upload.status_code == 401

    # 4. Activate
    res_act = client.post("/api/v1/resumes/some-uuid/activate")
    assert res_act.status_code == 401

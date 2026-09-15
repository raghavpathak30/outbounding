"""
Unit Tests for FastAPI Scaffold, Application Factory, Configuration, and Error Handling.
Validates Phase 2 requirements:
- /api/v1/health returns 200 with status payload
- CORS headers correctly scoped and disallowed origins rejected
- 404, 422, and 500 exception handlers return consistent JSON shape without leakage
- Configuration loads from environment and fails loudly on missing required secrets
"""
import pytest
from pydantic import BaseModel, ValidationError
from starlette.testclient import TestClient

from server.app import create_app
from server.config import Settings, get_settings


@pytest.fixture
def test_settings():
    """Provides isolated test settings with explicit valid keys."""
    return Settings(
        jwt_secret_key="test-secret-key-for-scaffold-verification-999",
        cors_allowed_origins=[
            "https://work.raghavpathak.me",
            "http://localhost",
            "http://localhost:3000",
        ],
        delivery_mode="staged",
        dry_run=True,
    )


@pytest.fixture
def test_client(test_settings):
    """Provides a TestClient initialized with test settings."""
    app = create_app(settings=test_settings)
    return TestClient(app, raise_server_exceptions=False)


# 1. Healthcheck Endpoint
def test_healthcheck_returns_200(test_client):
    """Verifies that /api/v1/health returns HTTP 200 with healthy status."""
    response = test_client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert data["delivery_mode"] == "staged"
    assert data["dry_run"] is True


# 2. CORS Middleware: Allowed and Disallowed Origins
def test_cors_headers_allowed_origin(test_client):
    """Verifies that requests from allowed origins receive Access-Control-Allow-Origin."""
    # Production dashboard origin
    res_prod = test_client.get(
        "/api/v1/health",
        headers={"Origin": "https://work.raghavpathak.me"}
    )
    assert res_prod.status_code == 200
    assert res_prod.headers.get("access-control-allow-origin") == "https://work.raghavpathak.me"
    assert res_prod.headers.get("access-control-allow-credentials") == "true"

    # Local development origin
    res_local = test_client.get(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000"}
    )
    assert res_local.status_code == 200
    assert res_local.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_headers_rejects_disallowed_origin(test_client):
    """Verifies that unauthorized origins do NOT receive CORS headers and preflight is rejected."""
    # Unauthorized GET request
    res_disallowed = test_client.get(
        "/api/v1/health",
        headers={"Origin": "https://malicious-phishing-attacker.com"}
    )
    assert res_disallowed.status_code == 200
    assert "access-control-allow-origin" not in res_disallowed.headers

    # Unauthorized OPTIONS preflight request
    res_opt = test_client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://malicious-phishing-attacker.com",
            "Access-Control-Request-Method": "GET",
        }
    )
    assert res_opt.status_code == 400
    assert "access-control-allow-origin" not in res_opt.headers


def test_cors_preflight_allowed_origin(test_client):
    """Verifies that preflight OPTIONS requests for allowed origins succeed with full headers."""
    response = test_client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://work.raghavpathak.me",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization, Content-Type",
        }
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "https://work.raghavpathak.me"
    assert "POST" in response.headers.get("access-control-allow-methods", "")


# 3. Centralized Exception Handlers (Consistent JSON Shape)
def test_404_error_handler_consistent_shape(test_client):
    """Verifies that nonexistent routes return consistent JSON shape."""
    response = test_client.get("/api/v1/non_existent_endpoint")
    assert response.status_code == 404

    data = response.json()
    assert data["status_code"] == 404
    assert data["error"] == "Not Found"
    assert "detail" in data


def test_422_validation_error_handler_consistent_shape(test_settings):
    """Verifies that validation failures return consistent JSON shape with field details."""
    app = create_app(settings=test_settings)

    class SamplePayload(BaseModel):
        target_count: int
        domain: str

    @app.post("/test-validation")
    def sample_endpoint(payload: SamplePayload):
        return payload

    client = TestClient(app, raise_server_exceptions=False)
    # Send invalid type for target_count
    response = client.post("/test-validation", json={"target_count": "not-an-int", "domain": "test.com"})
    assert response.status_code == 422

    data = response.json()
    assert data["status_code"] == 422
    assert data["error"] == "Validation Error"
    assert isinstance(data["detail"], list)
    assert len(data["detail"]) > 0
    assert "target_count" in str(data["detail"])


def test_500_error_handler_suppresses_internal_leakage(test_settings):
    """Verifies that unhandled internal exceptions return 500 without leaking stack trace or secrets."""
    app = create_app(settings=test_settings)

    @app.get("/test-unhandled-crash")
    def crash_route():
        raise RuntimeError("Internal DB connection failed: password=super_secret_db_pass_xyz123")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/test-unhandled-crash")
    assert response.status_code == 500

    data = response.json()
    assert data["status_code"] == 500
    assert data["error"] == "Internal Server Error"
    assert data["detail"] == "An unexpected error occurred."

    # Critical security assertion: internal detail must never leak to client
    assert "super_secret_db_pass_xyz123" not in response.text
    assert "RuntimeError" not in response.text
    assert "Traceback" not in response.text


# 4. Configuration Loading & Loud Failure on Missing Secrets
def test_config_loads_from_environment(monkeypatch):
    """Verifies that Settings correctly reads variables from the environment."""
    monkeypatch.setenv("JWT_SECRET_KEY", "env-provided-secure-secret-key-abcdef123")
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setenv("DELIVERY_MODE", "live")
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://custom1.com, http://custom2.com")

    settings = Settings(_env_file=None)
    assert settings.jwt_secret_key == "env-provided-secure-secret-key-abcdef123"
    assert settings.port == 9090
    assert settings.delivery_mode == "live"
    assert settings.dry_run is False
    assert settings.cors_allowed_origins == ["http://custom1.com", "http://custom2.com"]


def test_config_fails_loudly_when_jwt_secret_missing(monkeypatch):
    """Verifies that Settings raises ValidationError loudly if JWT_SECRET_KEY is missing."""
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        # Avoid loading from .env to test missing env var behavior
        Settings(_env_file=None)

    assert "jwt_secret_key" in str(exc_info.value).lower()


def test_config_fails_loudly_when_jwt_secret_is_empty_or_whitespace(monkeypatch):
    """Verifies that empty string or whitespace JWT_SECRET_KEY is rejected loudly."""
    for empty_val in ["", "   "]:
        monkeypatch.setenv("JWT_SECRET_KEY", empty_val)
        with pytest.raises(ValidationError) as exc_info:
            Settings(_env_file=None)

        assert "jwt_secret_key" in str(exc_info.value).lower()

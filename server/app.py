"""
FastAPI Application Factory for Outbound Lead Generation Pipeline.
Sets up routing, CORS middleware, centralized error handling, and health endpoints.
"""
import logging
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from server.config import Settings, get_settings
from server.routers.auth import router as auth_router
from server.routers.profile import router as profile_router
from server.routers.resumes import router as resumes_router
from server.routers.campaigns import router as campaigns_router
from server.routers.companies import router as companies_router
from server.routers.reviews import router as reviews_router
from server.routers.deliveries import router as deliveries_router
from server.routers.dashboard import router as dashboard_router
from server.views import (
    get_login_html,
    get_dashboard_html,
    get_campaigns_html,
    get_campaign_detail_html,
    get_review_html,
    get_deliveries_html,
    get_profile_html,
    get_settings_html,
)
from server.services.job_manager import JobManager

logger = logging.getLogger("server.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables & backward-compatible migrations exist, then recover stale runs
    try:
        from server.database import init_db
        init_db()
        JobManager.get_instance().recover_stale_runs()
    except Exception as e:
        logger.warning(f"Error during startup initialization/recovery: {e}")
    yield
    # Shutdown: clean up background workers
    try:
        JobManager.get_instance().shutdown(wait=False)
    except Exception as e:
        logger.warning(f"Error shutting down JobManager: {e}")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Creates and configures a new FastAPI application instance."""
    app_settings = settings or get_settings()

    app = FastAPI(
        title="Autonomous Outbound Lead Pipeline API",
        description="REST API for discovery, enrichment, drafting, review, and staged delivery.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan
    )
    app.state.settings = app_settings

    # 1. CORS Middleware Configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Security Headers Middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Prevent clickjacking / frame embedding
        response.headers["X-Frame-Options"] = "DENY"
        # Control referrer leakage
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Restrict dangerous browser features
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        # Content Security Policy (compatible with operator cockpit inline scripts/styles and Google Fonts)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "img-src 'self' data: https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        )
        # Strict Transport Security (enforce HTTPS for 1 year with subdomains and preload)
        is_https = (
            app_settings.app_env == "production"
            or request.headers.get("x-forwarded-proto") == "https"
            or request.url.scheme == "https"
        )
        if is_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        return response

    # 3. Centralized Exception Handlers (Consistent JSON shape across all errors)
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        try:
            status_phrase = HTTPStatus(exc.status_code).phrase
        except ValueError:
            status_phrase = "HTTP Error"

        error_title = status_phrase
        if exc.status_code == 404:
            error_title = "Not Found"

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": error_title,
                "detail": exc.detail,
                "status_code": exc.status_code
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": "Validation Error",
                "detail": exc.errors(),
                "status_code": 422
            }
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        # Log the full traceback internally while suppressing internal details in the response
        logger.exception("Unhandled internal exception during request processing: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "detail": "An unexpected error occurred.",
                "status_code": 500
            }
        )

    # 4. Core Healthcheck Endpoints (non-leaking, verifies database readiness)
    @app.get("/health", tags=["System"])
    @app.get("/api/v1/health", tags=["System"])
    async def health_check():
        db_status = "ok"
        try:
            from sqlalchemy import text
            from server.database import engine
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
            db_status = "unhealthy"

        overall_status = "healthy" if db_status == "ok" else "degraded"
        return {
            "status": overall_status,
            "version": "1.0.0",
            "delivery_mode": app_settings.delivery_mode,
            "dry_run": app_settings.dry_run,
            "database": db_status
        }

    # 5. Mount API Routers
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(resumes_router)
    app.include_router(campaigns_router)
    app.include_router(companies_router)
    app.include_router(reviews_router)
    app.include_router(deliveries_router)
    app.include_router(dashboard_router)

    # 6. Frontend Shell Routes
    @app.get("/login", response_class=HTMLResponse, tags=["Frontend"])
    async def login_page():
        return HTMLResponse(content=get_login_html())

    @app.get("/dashboard", response_class=HTMLResponse, tags=["Frontend"])
    async def dashboard_page():
        return HTMLResponse(content=get_dashboard_html())

    @app.get("/campaigns", response_class=HTMLResponse, tags=["Frontend"])
    async def campaigns_page():
        return HTMLResponse(content=get_campaigns_html())

    @app.get("/campaigns/{campaign_id}", response_class=HTMLResponse, tags=["Frontend"])
    async def campaign_detail_page(campaign_id: str):
        return HTMLResponse(content=get_campaign_detail_html())

    @app.get("/review", response_class=HTMLResponse, tags=["Frontend"])
    @app.get("/reviews", response_class=HTMLResponse, tags=["Frontend"])
    async def review_page():
        return HTMLResponse(content=get_review_html())

    @app.get("/deliveries", response_class=HTMLResponse, tags=["Frontend"])
    async def deliveries_page():
        return HTMLResponse(content=get_deliveries_html())

    @app.get("/profile", response_class=HTMLResponse, tags=["Frontend"])
    async def profile_page():
        return HTMLResponse(content=get_profile_html())

    @app.get("/settings", response_class=HTMLResponse, tags=["Frontend"])
    async def settings_page():
        return HTMLResponse(content=get_settings_html())

    @app.get("/", response_class=RedirectResponse, tags=["Frontend"])
    async def root_redirect():
        return RedirectResponse(url="/dashboard", status_code=302)

    return app


def get_app() -> FastAPI:
    """Factory helper for ASGI servers like Uvicorn."""
    return create_app()


# Module-level default ASGI application instance
try:
    app = create_app()
except Exception:
    # Deferred initialization if required environment variables (e.g. JWT_SECRET_KEY) are missing during import
    app = None


"""
FastAPI Application Factory for Outbound Lead Generation Pipeline.
Sets up routing, CORS middleware, centralized error handling, and health endpoints.
"""
import logging
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
from server.views import get_login_html, get_dashboard_html

logger = logging.getLogger("server.app")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Creates and configures a new FastAPI application instance."""
    app_settings = settings or get_settings()

    app = FastAPI(
        title="Autonomous Outbound Lead Pipeline API",
        description="REST API for discovery, enrichment, drafting, review, and staged delivery.",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc"
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

    # 2. Centralized Exception Handlers (Consistent JSON shape across all errors)
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

    # 3. Core Healthcheck Endpoint
    @app.get("/api/v1/health", tags=["System"])
    async def health_check():
        return {
            "status": "healthy",
            "version": "1.0.0",
            "delivery_mode": app_settings.delivery_mode,
            "dry_run": app_settings.dry_run
        }

    # 4. Mount API Routers
    app.include_router(auth_router)
    app.include_router(profile_router)
    app.include_router(resumes_router)
    app.include_router(campaigns_router)
    app.include_router(companies_router)

    # 5. Frontend Shell Routes
    @app.get("/login", response_class=HTMLResponse, tags=["Frontend"])
    async def login_page():
        return HTMLResponse(content=get_login_html())

    @app.get("/dashboard", response_class=HTMLResponse, tags=["Frontend"])
    async def dashboard_page():
        return HTMLResponse(content=get_dashboard_html())

    @app.get("/", response_class=RedirectResponse, tags=["Frontend"])
    async def root_redirect():
        return RedirectResponse(url="/dashboard", status_code=302)

    return app

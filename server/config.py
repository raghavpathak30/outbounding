"""
Server configuration management using Pydantic Settings.
Loads configuration from environment variables and validates critical settings.
"""
from typing import List, Union, Optional
from functools import lru_cache
from pydantic import Field, field_validator, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Environment
    app_env: str = Field(
        default="production",
        validation_alias=AliasChoices("app_env", "APP_ENV"),
        description="Application runtime environment: development, test, production"
    )

    # Security & Auth (Required, never hardcoded)
    jwt_secret_key: str = Field(
        ...,
        validation_alias=AliasChoices("jwt_secret_key", "JWT_SECRET_KEY"),
        description="Cryptographic secret key for signing JWT tokens. Required."
    )
    jwt_algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices("jwt_algorithm", "JWT_ALGORITHM"),
        description="JWT signing algorithm"
    )
    jwt_access_token_expire_minutes: int = Field(
        default=1440,
        validation_alias=AliasChoices("jwt_access_token_expire_minutes", "JWT_ACCESS_TOKEN_EXPIRE_MINUTES"),
        description="Access token expiration in minutes (default: 24h)"
    )
    secure_cookies: Optional[bool] = Field(
        default=None,
        validation_alias=AliasChoices("secure_cookies", "SECURE_COOKIES"),
        description="Enforce secure flag on auth cookies. If None, auto-detected from HTTPS / proxy header."
    )

    # Server Network
    host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("host", "HOST"),
        description="Server bind host (defaults to loopback for reverse proxy safety)"
    )
    port: int = Field(
        default=8000,
        validation_alias=AliasChoices("port", "PORT"),
        description="Server bind port"
    )

    # Database
    database_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("database_url", "DATABASE_URL"),
        description="Database connection URL"
    )

    # Pipeline Defaults
    delivery_mode: str = Field(
        default="staged",
        validation_alias=AliasChoices("delivery_mode", "DELIVERY_MODE"),
        description="Outbound delivery mode: stub, staged, live"
    )
    dry_run: bool = Field(
        default=True,
        validation_alias=AliasChoices("dry_run", "DRY_RUN"),
        description="Enforce dry run staging by default"
    )
    confirm_live: bool = Field(
        default=False,
        validation_alias=AliasChoices("confirm_live", "CONFIRM_LIVE"),
        description="Explicit environment gate for live outbound sending"
    )

    # CORS Allowed Origins
    cors_allowed_origins: Union[List[str], str] = Field(
        default=[
            "https://work.raghavpatak.me",
            "https://work.raghavpathak.me",
            "http://localhost",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
        validation_alias=AliasChoices("cors_allowed_origins", "CORS_ALLOWED_ORIGINS", "cors_origins", "CORS_ORIGINS"),
        description="Allowed origins for CORS requests"
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("JWT_SECRET_KEY is required and cannot be empty.")
        return v.strip()

    @field_validator("cors_allowed_origins")
    @classmethod
    def parse_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            clean_v = v.strip()
            if clean_v.startswith("[") and clean_v.endswith("]"):
                import json
                try:
                    parsed = json.loads(clean_v)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if str(x).strip()]
                except Exception:
                    pass
            return [origin.strip() for origin in clean_v.split(",") if origin.strip()]
        return [str(x).strip() for x in v if str(x).strip()]


@lru_cache
def get_settings() -> Settings:
    """Returns a cached instance of Settings loaded from the environment."""
    return Settings()


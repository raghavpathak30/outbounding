"""
Server configuration management using Pydantic Settings.
Loads configuration from environment variables and validates critical settings.
"""
from typing import List, Union
from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Security & Auth (Required, never hardcoded)
    jwt_secret_key: str = Field(
        ...,
        description="Cryptographic secret key for signing JWT tokens. Required."
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm"
    )
    jwt_access_token_expire_minutes: int = Field(
        default=1440,
        description="Access token expiration in minutes (default: 24h)"
    )

    # Server Network
    host: str = Field(
        default="0.0.0.0",
        description="Server bind host"
    )
    port: int = Field(
        default=8000,
        description="Server bind port"
    )

    # Pipeline Defaults
    delivery_mode: str = Field(
        default="staged",
        description="Outbound delivery mode: stub, staged, live"
    )
    dry_run: bool = Field(
        default=True,
        description="Enforce dry run staging by default"
    )

    # CORS Allowed Origins
    cors_allowed_origins: Union[List[str], str] = Field(
        default=[
            "https://work.raghavpathak.me",
            "http://localhost",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ],
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

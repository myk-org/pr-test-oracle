"""Configuration settings from environment variables."""

import os
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from simple_logger.logger import get_logger

logger = get_logger(name=__name__, level=os.environ.get("LOG_LEVEL", "INFO"))


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GitHub configuration
    github_token: SecretStr

    # AI configuration
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_cli_timeout: int = Field(default=10, gt=0)

    # Test discovery
    test_patterns: list[str] = Field(default_factory=lambda: ["tests/**/*.py", "test_*.py"])

    # PR comment posting
    post_comment: bool = True

    # Custom prompt file path
    prompt_file: str = "/app/PROMPT.md"


@lru_cache
def get_settings() -> Settings:
    """Get application settings instance."""
    return Settings()

"""
Application-wide configuration via pydantic-settings.
All values are sourced from environment variables or .env file.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = Field(default="AI Copilot Infra", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    debug: bool = Field(default=False, alias="DEBUG")

    # ── API ───────────────────────────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # ── MCP Server ────────────────────────────────────────────────────────────
    mcp_base_url: str = Field(default="http://localhost:8100", alias="MCP_BASE_URL")
    mcp_timeout_seconds: float = Field(default=30.0, alias="MCP_TIMEOUT_SECONDS")

    # ── Context7 ──────────────────────────────────────────────────────────────
    context7_base_url: str = Field(default="", alias="CONTEXT7_BASE_URL")
    context7_api_key: str = Field(default="", alias="CONTEXT7_API_KEY")
    context7_timeout_seconds: float = Field(default=10.0, alias="CONTEXT7_TIMEOUT_SECONDS")

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_temperature: float = Field(default=0.2, alias="OPENAI_TEMPERATURE")
    openai_max_tokens: int = Field(default=2048, alias="OPENAI_MAX_TOKENS")
    openai_timeout_seconds: float = Field(default=60.0, alias="OPENAI_TIMEOUT_SECONDS")

    # ── Langfuse (future) ─────────────────────────────────────────────────────
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", alias="LANGFUSE_HOST")

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")  # "json" | "text"


def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

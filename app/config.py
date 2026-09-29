from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # LLM Provider selection ("openrouter", "ollama", or "mock")
    LLM_PROVIDER: Literal["openrouter", "ollama", "mock"] = "openrouter"

    # Ollama settings (Local LLM)
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "llama3.2:latest"

    # OpenRouter API settings (Cloud LLM)
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: str = "anthropic/claude-3.5-sonnet"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # Optional GitHub PAT for higher rate limits
    GITHUB_TOKEN: Optional[str] = None

    # Session parameters
    MAX_SESSION_TURNS: int = 15
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

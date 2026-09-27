"""Provider-agnostic LLM client dispatcher and compatibility layer."""

from typing import Any, Dict, List, Literal, Optional

from app.config import settings
from app.llm.base import BaseLLMClient, extract_and_parse_json
from app.llm.mock_client import MockLLMClient
from app.llm.ollama_client import OllamaClient
from app.llm.openrouter_client import OpenRouterClient


class LLMClient(BaseLLMClient):
    """Dispatcher client selecting between OpenRouter (cloud), Ollama (local), or Mock (demo)."""

    def __init__(
        self,
        provider: Optional[Literal["openrouter", "ollama", "mock"]] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.provider = provider or settings.LLM_PROVIDER
        if self.provider == "mock":
            self._backend: BaseLLMClient = MockLLMClient()
        elif self.provider == "ollama":
            self._backend = OllamaClient(
                base_url=base_url or settings.OLLAMA_BASE_URL,
                model=model or settings.OLLAMA_MODEL,
            )
        else:
            self._backend = OpenRouterClient(
                api_key=api_key or settings.OPENROUTER_API_KEY,
                model=model or settings.OPENROUTER_MODEL,
                base_url=base_url or settings.OPENROUTER_BASE_URL,
            )

    async def _call_provider(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> str:
        return await self._backend._call_provider(messages, temperature)

    async def generate_turn(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.4,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        return await self._backend.generate_turn(
            messages=messages,
            temperature=temperature,
            max_retries=max_retries,
        )


__all__ = [
    "BaseLLMClient",
    "LLMClient",
    "OpenRouterClient",
    "OllamaClient",
    "MockLLMClient",
    "extract_and_parse_json",
]

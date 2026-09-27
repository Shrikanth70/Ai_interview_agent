"""OpenRouter API client implementation."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings
from app.llm.base import BaseLLMClient

logger = logging.getLogger(__name__)


class OpenRouterClient(BaseLLMClient):
    """OpenRouter hosted LLM client with structured JSON mode and backoff."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or settings.OPENROUTER_API_KEY
        self.model = model or settings.OPENROUTER_MODEL
        self.base_url = (base_url or settings.OPENROUTER_BASE_URL).rstrip("/")

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/interview-agent",
            "X-Title": "AI Interview Agent",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _call_provider(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> str:
        if not self.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is not set. Please provide it in .env or switch LLM_PROVIDER to 'ollama'."
            )

        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        max_retries = 3
        last_err = None

        async with httpx.AsyncClient() as client:
            for attempt in range(1, max_retries + 1):
                try:
                    resp = await client.post(
                        url,
                        headers=self._get_headers(),
                        json=payload,
                        timeout=45.0,
                    )

                    if resp.status_code in (429, 502, 503, 504):
                        logger.warning(
                            f"OpenRouter transient error {resp.status_code} on attempt {attempt}/{max_retries}. Retrying..."
                        )
                        await asyncio.sleep(1.5 * attempt)
                        continue

                    if resp.status_code != 200:
                        raise RuntimeError(
                            f"OpenRouter API returned error {resp.status_code}: {resp.text}"
                        )

                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise RuntimeError(f"OpenRouter response contained no choices: {data}")

                    content = choices[0].get("message", {}).get("content", "")
                    return content

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    last_err = net_err
                    logger.warning(
                        f"Network error calling OpenRouter on attempt {attempt}/{max_retries}: {net_err}"
                    )
                    await asyncio.sleep(1.5 * attempt)

            raise RuntimeError(
                f"Failed to communicate with OpenRouter after {max_retries} attempts: {last_err}"
            )

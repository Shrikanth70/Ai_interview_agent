"""Ollama local LLM client implementation."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.config import settings
from app.llm.base import BaseLLMClient

logger = logging.getLogger(__name__)


class OllamaClient(BaseLLMClient):
    """Local Ollama client supporting OpenAI-compatible and native chat endpoints."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        raw_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        # Ensure base_url does not double /v1 if already provided
        self.base_url = raw_url
        self.model = model or settings.OLLAMA_MODEL

    async def _call_provider(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> str:
        # Check endpoint style
        if self.base_url.endswith("/v1"):
            url = f"{self.base_url}/chat/completions"
        else:
            url = f"{self.base_url}/v1/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        max_retries = 2
        last_err = None

        async with httpx.AsyncClient() as client:
            for attempt in range(1, max_retries + 1):
                try:
                    resp = await client.post(
                        url,
                        headers={"Content-Type": "application/json"},
                        json=payload,
                        timeout=90.0,
                    )

                    # If /v1/chat/completions is not found, try native /api/chat
                    if resp.status_code == 404:
                        native_url = f"{self.base_url.removesuffix('/v1')}/api/chat"
                        native_payload = {
                            "model": self.model,
                            "messages": messages,
                            "format": "json",
                            "stream": False,
                            "options": {"temperature": temperature},
                        }
                        resp = await client.post(
                            native_url,
                            headers={"Content-Type": "application/json"},
                            json=native_payload,
                            timeout=90.0,
                        )

                    if resp.status_code == 401:
                        raise RuntimeError(
                            f"Ollama returned HTTP 401 Unauthorized for model '{self.model}'. "
                            f"This model is hosted on Ollama Cloud and requires authentication ('ollama login'). "
                            f"Please select a locally downloaded model such as 'llama3.2:latest' or 'gemma4:latest'."
                        )
                    if resp.status_code != 200:
                        raise RuntimeError(
                            f"Ollama returned HTTP {resp.status_code}: {resp.text}"
                        )

                    data = resp.json()
                    # Handle OpenAI format (choices[0].message.content)
                    if "choices" in data and len(data["choices"]) > 0:
                        return data["choices"][0].get("message", {}).get("content", "")
                    # Handle Ollama native format (message.content)
                    if "message" in data:
                        return data["message"].get("content", "")

                    raise RuntimeError(f"Unexpected Ollama response structure: {data}")

                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    last_err = net_err
                    logger.warning(
                        f"Network error calling Ollama ({self.base_url}) on attempt {attempt}/{max_retries}: {net_err}"
                    )
                    await asyncio.sleep(1.0 * attempt)

            raise RuntimeError(
                f"Failed to communicate with Ollama at {self.base_url} after {max_retries} attempts: {last_err}. "
                "Ensure Ollama is running ('ollama serve') and the model is pulled ('ollama pull <model>')."
            )

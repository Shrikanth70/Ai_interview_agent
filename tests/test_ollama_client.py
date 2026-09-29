"""Unit tests for OllamaClient URL normalization, retry behavior, and response formatting."""

import pytest
import httpx
from app.llm.ollama_client import OllamaClient, normalize_ollama_url


def test_normalize_ollama_url():
    """Verify that localhost URLs are normalized to 127.0.0.1 to avoid Windows IPv6 resolution issues."""
    assert normalize_ollama_url("http://localhost:11434") == "http://127.0.0.1:11434"
    assert normalize_ollama_url("http://localhost:11434/") == "http://127.0.0.1:11434"
    assert normalize_ollama_url("http://localhost:11434/v1") == "http://127.0.0.1:11434/v1"
    assert normalize_ollama_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
    assert normalize_ollama_url("http://custom-host:11434") == "http://custom-host:11434"


def test_ollama_client_init_normalization():
    """Verify OllamaClient normalizes base_url upon initialization."""
    client = OllamaClient(base_url="http://localhost:11434", model="llama3.2:latest")
    assert client.base_url == "http://127.0.0.1:11434"
    assert client.model == "llama3.2:latest"


@pytest.mark.asyncio
async def test_ollama_client_retry_and_clear_error(monkeypatch):
    """Verify that OllamaClient retries network failures and raises informative error."""
    attempts = 0

    def mock_post(self, *args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    client = OllamaClient(base_url="http://127.0.0.1:11434", model="llama3.2:latest")

    with pytest.raises(RuntimeError) as exc_info:
        await client._call_provider(
            [{"role": "user", "content": "hello"}],
            temperature=0.4,
        )

    assert "Failed to communicate with Ollama" in str(exc_info.value)
    assert "Ensure Ollama is running" in str(exc_info.value)
    assert "llama3.2:latest" in str(exc_info.value)
    assert attempts == 3  # Verified 3 retries

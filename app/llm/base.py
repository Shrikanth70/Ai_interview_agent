"""Base LLM interface with shared structured JSON repair and retry fallback."""

import asyncio
from abc import ABC, abstractmethod
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def extract_and_parse_json(text: str) -> Dict[str, Any]:
    """Extracts and parses JSON from raw LLM output.
    
    Handles markdown code fences (```json ... ```), surrounding conversational text,
    and regex fallback on outermost curly braces.
    """
    cleaned = text.strip()

    # 1. Strip markdown code fences if present
    if "```" in cleaned:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()

    # 2. Direct JSON decode
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 3. Fallback: Extract outermost curly braces
    brace_match = re.search(r"\{[\s\S]*\}", cleaned)
    if brace_match:
        try:
            parsed = json.loads(brace_match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Failed to parse valid JSON from text: {text[:200]}..."
    )


class BaseLLMClient(ABC):
    """Abstract base LLM client with shared structured JSON repair and retry logic."""

    @abstractmethod
    async def _call_provider(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> str:
        """Invokes the specific upstream API and returns the raw string content."""
        pass

    async def generate_turn(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.4,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Calls the model and returns structured JSON conforming to the interviewer contract.
        
        If the initial raw response fails JSON parsing, strips markdown fences, attempts
        brace extraction, and if still invalid, retries once with a stricter instruction.
        """
        raw_content = await self._call_provider(messages, temperature)

        try:
            return extract_and_parse_json(raw_content)
        except ValueError as parse_err:
            logger.warning(
                f"Initial JSON parse failed: {parse_err}. Attempting 1 strict repair retry..."
            )

        # Retry once with a stricter "return ONLY valid JSON" instruction
        repair_messages = list(messages) + [
            {
                "role": "user",
                "content": (
                    "CRITICAL: Your previous response was not valid JSON. "
                    "Return ONLY a single valid JSON object with the exact keys: "
                    "'question', 'turn_type', 'source', 'source_ref', 'reasoning_note'. "
                    "Do NOT include markdown formatting, backticks, preamble, or commentary."
                ),
            }
        ]

        try:
            repair_raw = await self._call_provider(repair_messages, temperature=0.1)
            return extract_and_parse_json(repair_raw)
        except Exception as retry_err:
            logger.error(f"JSON repair retry failed: {retry_err}")
            raise ValueError(
                f"LLM failed to produce valid structured JSON after repair retry: {retry_err}\n"
                f"Raw initial response: {raw_content}"
            ) from retry_err

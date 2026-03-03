"""
LLMService — thin async wrapper around the OpenAI Chat Completions API.

Responsibilities:
  - Own the AsyncOpenAI client lifecycle
  - Accept a plain prompt string, call the model, return a typed dict
  - Measure and surface latency + token usage via structured Loguru logs
  - Expose no business logic; callers (workflow steps, tools) own that layer

Configuration (via environment / .env):
  OPENAI_API_KEY          — required, no default
  OPENAI_MODEL            — default: gpt-4o-mini
  OPENAI_TEMPERATURE      — default: 0.2
  OPENAI_MAX_TOKENS       — default: 2048
  OPENAI_TIMEOUT_SECONDS  — default: 60.0
"""

from __future__ import annotations

import time
from typing import TypedDict

from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError

from ai_copilot_infra.core.config import settings
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)


# ── Return type ───────────────────────────────────────────────────────────────


class LLMResponse(TypedDict):
    content: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


# ── Service ───────────────────────────────────────────────────────────────────


class LLMService:
    """
    Pure async wrapper around the OpenAI Chat Completions API.

    One instance should be created at application startup and reused;
    AsyncOpenAI manages its own connection pool internally.

    Usage:
        service = LLMService()
        response = await service.generate("Explain Redis pipelining.")
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> None:
        resolved_key = api_key or settings.openai_api_key
        if not resolved_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. "
                "Add it to your .env file or pass api_key= explicitly."
            )

        self._model = model or settings.openai_model
        self._temperature = temperature if temperature is not None else settings.openai_temperature
        self._max_tokens = max_tokens or settings.openai_max_tokens
        self._timeout = timeout if timeout is not None else settings.openai_timeout_seconds

        self._client = AsyncOpenAI(
            api_key=resolved_key,
            timeout=self._timeout,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate(self, prompt: str) -> LLMResponse:
        """
        Send a prompt to the configured OpenAI model and return a structured
        response with content, token counts, and latency.

        Args:
            prompt: The fully-constructed prompt string. No system prompt is
                    added here — callers are responsible for prompt design.

        Returns:
            LLMResponse TypedDict with keys:
                content       — assistant reply text
                input_tokens  — tokens consumed by the prompt
                output_tokens — tokens in the completion
                latency_ms    — wall-clock time for the API round-trip

        Raises:
            LLMRateLimitError    — when OpenAI returns 429
            LLMConnectionError   — on network-level failures
            LLMAPIError          — on all other OpenAI API errors
        """
        logger.info(
            "llm_request_start",
            model=self._model,
            prompt_length=len(prompt),
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )

        start = time.perf_counter()

        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except RateLimitError as exc:
            self._log_error("llm_rate_limit", exc, start, prompt)
            raise LLMRateLimitError("OpenAI rate limit reached. Retry after back-off.") from exc
        except APIConnectionError as exc:
            self._log_error("llm_connection_error", exc, start, prompt)
            raise LLMConnectionError("Failed to connect to the OpenAI API.") from exc
        except APIStatusError as exc:
            self._log_error("llm_api_error", exc, start, prompt)
            raise LLMAPIError(f"OpenAI API error {exc.status_code}: {exc.message}") from exc

        latency_ms = round((time.perf_counter() - start) * 1000, 3)

        content = completion.choices[0].message.content or ""
        usage = completion.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        logger.info(
            "llm_request_complete",
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=(input_tokens + output_tokens),
            latency_ms=latency_ms,
            finish_reason=completion.choices[0].finish_reason,
        )

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _log_error(
        self,
        event: str,
        exc: Exception,
        start: float,
        prompt: str,
    ) -> None:
        latency_ms = round((time.perf_counter() - start) * 1000, 3)
        logger.error(
            event,
            model=self._model,
            prompt_length=len(prompt),
            error=str(exc),
            latency_ms=latency_ms,
            exc_info=True,
        )


# ── Domain exceptions ─────────────────────────────────────────────────────────


class LLMServiceError(Exception):
    """Base exception for all LLMService errors."""


class LLMRateLimitError(LLMServiceError):
    """Raised when the OpenAI API returns a 429 rate-limit response."""


class LLMConnectionError(LLMServiceError):
    """Raised on network-level failures reaching the OpenAI API."""


class LLMAPIError(LLMServiceError):
    """Raised on non-rate-limit HTTP error responses from the OpenAI API."""

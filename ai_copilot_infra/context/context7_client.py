"""
Context7Client — async HTTP client for the Context7 documentation API.

Responsibilities:
  - Own the httpx.AsyncClient lifecycle
  - Expose fetch_documentation(library_name) -> str
  - Handle all HTTP, timeout, and empty-response edge cases
  - Emit structured Loguru log events at every outcome

Configuration (via environment / .env):
  CONTEXT7_BASE_URL         — required; base URL of the Context7 service
  CONTEXT7_API_KEY          — bearer token (can be blank for open instances)
  CONTEXT7_TIMEOUT_SECONDS  — per-request timeout, default 10 s

Wire format expected from the service:
  GET {base_url}/docs/{library_name}
  200 → { "content": "<documentation text>" }
       or plain-text body (handled via _extract_text)
  4xx / 5xx → raises Context7Error
"""

from __future__ import annotations

import time

import httpx

from ai_copilot_infra.core.config import settings
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)


# ── Domain exceptions ─────────────────────────────────────────────────────────


class Context7Error(Exception):
    """Base exception for all Context7Client errors."""


class Context7ConfigError(Context7Error):
    """Raised when CONTEXT7_BASE_URL is not configured."""


class Context7TimeoutError(Context7Error):
    """Raised when the request exceeds the configured timeout."""


class Context7HTTPError(Context7Error):
    """Raised on non-2xx HTTP responses."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class Context7EmptyResponseError(Context7Error):
    """Raised when the API returns a 200 but no usable documentation text."""


# ── Client ────────────────────────────────────────────────────────────────────


class Context7Client:
    """
    Async HTTP client for the Context7 documentation API.

    One instance per application lifetime; the underlying httpx.AsyncClient
    is created fresh per request so no connection-pool state leaks between
    calls (suitable for low-to-medium traffic; switch to a persistent client
    with connection pooling if throughput demands it).

    Usage:
        client = Context7Client()
        doc_text = await client.fetch_documentation("fastapi")
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        resolved_url = (base_url or settings.context7_base_url).rstrip("/")
        if not resolved_url:
            raise Context7ConfigError(
                "CONTEXT7_BASE_URL is not set. "
                "Add it to your .env file or pass base_url= explicitly."
            )

        self._base_url = resolved_url
        self._timeout = timeout if timeout is not None else settings.context7_timeout_seconds

        api_key_value = api_key or settings.context7_api_key
        self._headers: dict[str, str] = {"Accept": "application/json"}
        if api_key_value:
            self._headers["Authorization"] = f"Bearer {api_key_value}"

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_documentation(self, library_name: str) -> str:
        """
        Retrieve documentation text for a named library from Context7.

        Args:
            library_name: Library identifier (e.g. "fastapi", "redis").
                          Used verbatim as the URL path segment.

        Returns:
            Documentation text as a plain string.

        Raises:
            Context7TimeoutError    — request exceeded timeout
            Context7HTTPError       — non-2xx response
            Context7EmptyResponseError — 200 but no documentation content
        """
        path = f"/docs/{library_name}"
        url = f"{self._base_url}{path}"

        logger.info(
            "context7_request_start",
            library=library_name,
            url=url,
        )

        start = time.perf_counter()

        try:
            async with httpx.AsyncClient(
                headers=self._headers,
                timeout=self._timeout,
                follow_redirects=True,
            ) as client:
                response = await client.get(url)

        except httpx.TimeoutException as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 3)
            logger.error(
                "context7_timeout",
                library=library_name,
                timeout_seconds=self._timeout,
                latency_ms=latency_ms,
            )
            raise Context7TimeoutError(
                f"Context7 timed out after {self._timeout}s for library '{library_name}'."
            ) from exc

        except httpx.RequestError as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 3)
            logger.error(
                "context7_connection_error",
                library=library_name,
                error=str(exc),
                latency_ms=latency_ms,
            )
            raise Context7Error(
                f"Context7 connection failed for library '{library_name}': {exc}"
            ) from exc

        latency_ms = round((time.perf_counter() - start) * 1000, 3)

        logger.info(
            "context7_response_received",
            library=library_name,
            status_code=response.status_code,
            latency_ms=latency_ms,
        )

        if response.status_code != 200:
            logger.warning(
                "context7_non_200",
                library=library_name,
                status_code=response.status_code,
                body_preview=response.text[:200],
            )
            raise Context7HTTPError(
                status_code=response.status_code,
                message=response.text[:200],
            )

        doc_text = self._extract_text(response)

        if not doc_text.strip():
            logger.warning(
                "context7_empty_response",
                library=library_name,
                status_code=response.status_code,
            )
            raise Context7EmptyResponseError(
                f"Context7 returned no documentation for library '{library_name}'."
            )

        logger.info(
            "context7_documentation_fetched",
            library=library_name,
            content_length=len(doc_text),
            latency_ms=latency_ms,
        )

        return doc_text

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_text(response: httpx.Response) -> str:
        """
        Extract documentation text from the response.

        Handles two formats:
          1. JSON body with a "content" key  → returns content value
          2. Plain-text body                 → returns raw text
        """
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            try:
                data = response.json()
                if isinstance(data, dict):
                    return str(data.get("content") or data.get("text") or "")
                if isinstance(data, str):
                    return data
            except Exception:
                pass

        return response.text

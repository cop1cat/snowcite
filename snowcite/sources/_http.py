"""HTTP helper with retry/backoff and per-source concurrency limits.

Uses a module-level `httpx.AsyncClient` with connection pooling — a fresh
client per request would pay TCP+TLS cost on every call, which is visible on
large snowball runs.

Respects Retry-After on 429, exponential backoff on 5xx and transport errors.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from snowcite.logging import log


# Per-source concurrency caps. Sized to stay well under published rate limits.
#   Semantic Scholar: 100 req / 5 min unauthenticated (~0.33 rps)
#   OpenAlex: 10 rps in polite pool
#   Crossref: generous (~50 rps polite)
#   PubMed: NCBI asks for ≤3 req/s unauthenticated
_SEMAPHORE_LIMITS: dict[str, int] = {
    "semantic_scholar": 3,
    "openalex": 8,
    "crossref": 8,
    "pubmed": 3,
}

# Lazy-initialised on first use so semaphore objects bind to the running
# event loop, not whichever loop happened to exist at import time.
_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


def _semaphore_for(source: str) -> asyncio.Semaphore | None:
    if source not in _SEMAPHORE_LIMITS:
        return None
    sem = _SEMAPHORES.get(source)
    if sem is None:
        sem = asyncio.Semaphore(_SEMAPHORE_LIMITS[source])
        _SEMAPHORES[source] = sem
    return sem


# Single shared client. httpx handles connection pooling per origin out of the
# box, so all five source clients get connection reuse on repeat calls.
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client  # noqa: PLW0603 — intentional lazy-singleton
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _client


async def close_client() -> None:
    """Close the shared client — intended for a clean server shutdown hook."""
    global _client  # noqa: PLW0603 — intentional lazy-singleton
    if _client is not None:
        await _client.aclose()
        _client = None


@asynccontextmanager
async def _limit(source: str) -> AsyncIterator[None]:
    sem = _semaphore_for(source)
    if sem is None:
        yield
        return
    async with sem:
        yield


def _retry_delay(resp: httpx.Response | None, attempt: int, base_delay: float) -> float:
    """Honor Retry-After if server provided one; otherwise exponential backoff."""
    if resp is not None:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return base_delay * (2**attempt)


async def http_get(
    source: str,
    url: str,
    *,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
    max_retries: int = 4,
    base_delay: float = 1.5,
) -> httpx.Response:
    """GET with per-source concurrency, retry on 429/5xx, Retry-After support.

    Raises on non-retriable errors (4xx other than 429) or after `max_retries`.
    The shared client's default timeout applies unless `timeout` overrides it.
    """
    client = get_client()
    request_timeout = httpx.Timeout(timeout) if timeout is not None else client.timeout
    async with _limit(source):
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                resp = await client.get(
                    url, params=params, headers=headers, timeout=request_timeout
                )
            except httpx.RequestError as e:
                last_exc = e
                if attempt == max_retries:
                    raise
                delay = _retry_delay(None, attempt, base_delay)
                log.warning(
                    "%s: %s, retrying in %.1fs (attempt %d/%d)",
                    source,
                    type(e).__name__,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(delay)
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt == max_retries:
                    resp.raise_for_status()
                delay = _retry_delay(resp, attempt, base_delay)
                log.warning(
                    "%s: HTTP %d, waiting %.1fs (attempt %d/%d)",
                    source,
                    resp.status_code,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(delay)
                continue
            return resp
        raise RuntimeError(f"{source}: exhausted retries") from last_exc

"""Small, read-only, politely rate-limited client for the two upstream rugby APIs.

* World Rugby's PulseLive backend (``api.wr-rims-prod.pulselive.com/rugby/v3``) is the
  governing body's own data service: official rankings and the cross-competition
  match feed with team stats, player stats, timelines and team sheets.
* ESPN's undocumented site APIs (``site.api.espn.com``) supply league tables,
  fixtures/results and per-player box scores for the major club and test
  competitions.

Every request goes through :func:`get_json`, which applies timeouts, bounded
retries with backoff for 429/5xx, redirects, an honest User-Agent, a per-source
request-rate ceiling, and an in-process TTL cache. Data is fetched on demand for
the querying user and never persisted or rehosted.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import random
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from vgi_rugby import __version__

USER_AGENT = f"vgi-rugby/{__version__} (+https://github.com/Query-farm/vgi-rugby)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
MAX_RETRY_DELAY = 30.0
QUERY_TIMEOUT = 120.0
MAX_CONCURRENT_REQUESTS = 4
CACHE_MAX_ENTRIES = 512

logger = logging.getLogger(__name__)
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)


@dataclass(frozen=True, slots=True)
class Source:
    """One upstream API root and the politeness policy applied to it."""

    name: str
    label: str
    env_var: str
    default_base_url: str
    max_requests: int
    per_seconds: float

    def base_url(self) -> str:
        """Return the API root, optionally overridden for hermetic testing."""
        return os.environ.get(self.env_var, self.default_base_url).rstrip("/")


# World Rugby advertises ``x-ratelimit-limit: 100;w=60``; stay well below it.
WORLD_RUGBY = Source(
    name="world_rugby",
    label="World Rugby API",
    env_var="WORLD_RUGBY_API_BASE_URL",
    default_base_url="https://api.wr-rims-prod.pulselive.com/rugby/v3",
    max_requests=50,
    per_seconds=60.0,
)
# ESPN publishes no limit; keep request volume low and steady.
ESPN_SITE = Source(
    name="espn_site",
    label="ESPN rugby API",
    env_var="ESPN_SITE_API_BASE_URL",
    default_base_url="https://site.api.espn.com/apis/site/v2/sports/rugby",
    max_requests=60,
    per_seconds=60.0,
)
ESPN_STANDINGS = Source(
    name="espn_standings",
    label="ESPN rugby standings API",
    env_var="ESPN_STANDINGS_API_BASE_URL",
    default_base_url="https://site.api.espn.com/apis/v2/sports/rugby",
    max_requests=60,
    per_seconds=60.0,
)


class RugbyApiError(RuntimeError):
    """A failed response from an upstream rugby API."""

    def __init__(self, source: Source, status: int, body: str) -> None:
        super().__init__(f"{source.label} returned HTTP {status}: {body[:400]}")
        self.status = status
        self.source = source.name


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """Decoded JSON plus the freshness lifetime applied to it."""

    payload: Any
    ttl: int


class _RateLimiter:
    """Sliding-window request ceiling, shared by every thread in the process."""

    def __init__(self, max_requests: int, per_seconds: float) -> None:
        self._max = max_requests
        self._window = per_seconds
        self._sent: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    def acquire(self, deadline: float) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._sent and now - self._sent[0] >= self._window:
                    self._sent.popleft()
                wait = max(0.0, self._blocked_until - now)
                if not wait and len(self._sent) < self._max:
                    self._sent.append(now)
                    return
                if not wait:
                    wait = self._window - (now - self._sent[0])
            if time.monotonic() + wait > deadline:
                raise TimeoutError(f"rugby API query exceeded {QUERY_TIMEOUT:g} seconds")
            time.sleep(wait)

    def block_for(self, seconds: float) -> None:
        """Pause this source after the origin reports an exhausted quota."""
        with self._lock:
            self._blocked_until = max(self._blocked_until, time.monotonic() + seconds)

    def reset(self) -> None:
        with self._lock:
            self._sent.clear()
            self._blocked_until = 0.0


class _TtlCache:
    """Bounded, thread-safe in-process response cache."""

    def __init__(self, max_entries: int) -> None:
        self._max = max_entries
        self._items: OrderedDict[str, tuple[float, ApiResponse]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> ApiResponse | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires, value = item
            if expires <= time.monotonic():
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def store(self, key: str, value: ApiResponse) -> None:
        if value.ttl <= 0:
            return
        with self._lock:
            self._items[key] = (time.monotonic() + value.ttl, value)
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_cache = _TtlCache(CACHE_MAX_ENTRIES)
_limiters = {
    source.name: _RateLimiter(source.max_requests, source.per_seconds)
    for source in (WORLD_RUGBY, ESPN_SITE, ESPN_STANDINGS)
}
_client_lock = threading.Lock()
_shared_client: httpx.Client | None = None


def reset_state() -> None:
    """Drop cached responses and rate-limit history (used by tests)."""
    _cache.clear()
    for limiter in _limiters.values():
        limiter.reset()


def _client() -> httpx.Client:
    """Return the process-wide connection pool, creating it on first use."""
    global _shared_client
    with _client_lock:
        if _shared_client is None:
            _shared_client = httpx.Client(timeout=TIMEOUT, follow_redirects=True)
        return _shared_client


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Return a bounded Retry-After delay or exponential backoff with jitter."""
    if response is not None:
        raw = response.headers.get("retry-after")
        if raw:
            try:
                delay = float(raw)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    delay = (retry_at - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = -1.0
            if delay >= 0:
                return min(delay, MAX_RETRY_DELAY)
    base = min(0.25 * 2**attempt, MAX_RETRY_DELAY)
    return min(base + random.uniform(0, base * 0.25), MAX_RETRY_DELAY)


def _body_bytes(response: httpx.Response) -> bytes:
    """Return the body, inflating gzip that ESPN sometimes sends undeclared."""
    content = response.content
    if content[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(content)
        except (OSError, EOFError):
            return content
    return content


def _observe_quota(source: Source, response: httpx.Response) -> None:
    """Honor World Rugby's advertised quota headers when it reports exhaustion."""
    remaining = response.headers.get("x-ratelimit-remaining")
    reset = response.headers.get("x-ratelimit-reset")
    if remaining is None or reset is None:
        return
    try:
        if int(remaining.split(",")[0].strip()) <= 0:
            _limiters[source.name].block_for(min(float(reset), MAX_RETRY_DELAY * 2))
    except ValueError:
        return


def _request(
    source: Source,
    path: str,
    params: Mapping[str, str | int],
    *,
    client: httpx.Client,
    deadline: float,
) -> httpx.Response:
    """Issue one GET, retrying transient failures within the query deadline."""
    url = f"{source.base_url()}/{path.lstrip('/')}"
    limiter = _limiters[source.name]
    for attempt in range(MAX_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"rugby API query exceeded {QUERY_TIMEOUT:g} seconds")
        limiter.acquire(deadline)
        started = time.monotonic()
        try:
            if not _request_slots.acquire(timeout=max(0.001, deadline - time.monotonic())):
                raise TimeoutError(f"rugby API query exceeded {QUERY_TIMEOUT:g} seconds")
            try:
                remaining = max(0.001, deadline - time.monotonic())
                response = client.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                    timeout=httpx.Timeout(min(30.0, remaining), connect=min(10.0, remaining)),
                )
            finally:
                _request_slots.release()
        except httpx.TransportError:
            logger.warning(
                "rugby_api_transport_error source=%s path=%s attempt=%d duration_ms=%d",
                source.name,
                path,
                attempt + 1,
                round((time.monotonic() - started) * 1_000),
            )
            if attempt + 1 == MAX_ATTEMPTS:
                raise
            time.sleep(min(_retry_delay(None, attempt), max(0.0, deadline - time.monotonic())))
            continue
        _observe_quota(source, response)
        logger.debug(
            "rugby_api_response source=%s path=%s status=%d attempt=%d duration_ms=%d",
            source.name,
            path,
            response.status_code,
            attempt + 1,
            round((time.monotonic() - started) * 1_000),
        )
        if response.status_code not in RETRYABLE_STATUSES or attempt + 1 == MAX_ATTEMPTS:
            return response
        delay = min(_retry_delay(response, attempt), max(0.0, deadline - time.monotonic()))
        logger.warning(
            "rugby_api_retry source=%s path=%s status=%d attempt=%d delay_seconds=%.3f",
            source.name,
            path,
            response.status_code,
            attempt + 1,
            delay,
        )
        time.sleep(delay)
    raise AssertionError("retry loop exited without a response")


def get_json(
    source: Source,
    path: str,
    params: Mapping[str, str | int] | None = None,
    *,
    ttl: int | Callable[[Any], int],
    client: httpx.Client | None = None,
    deadline: float | None = None,
) -> ApiResponse:
    """Fetch and decode one JSON document, serving repeats from the TTL cache.

    ``ttl`` is either a fixed lifetime in seconds or a function of the decoded
    payload, so finished matches can be kept longer than live ones.
    """
    query = dict(params or {})
    key = json.dumps([source.base_url(), path, sorted(query.items())], default=str)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    effective_deadline = deadline if deadline is not None else time.monotonic() + QUERY_TIMEOUT
    response = _request(source, path, query, client=client or _client(), deadline=effective_deadline)
    body = _body_bytes(response)
    if not response.is_success:
        raise RugbyApiError(source, response.status_code, body.decode("utf-8", errors="replace"))
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise ValueError(f"{source.label} returned a non-JSON response for {path}") from exc
    lifetime = ttl(payload) if callable(ttl) else ttl
    result = ApiResponse(payload=payload, ttl=max(0, int(lifetime)))
    _cache.store(key, result)
    return result

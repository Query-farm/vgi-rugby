"""Tests for the HTTP boundary: headers, retries, caching, rate limits, errors."""

from __future__ import annotations

import gzip
import json

import httpx
import pytest

from vgi_rugby import __version__, api


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr(api.time, "sleep", sleeps.append)
    return sleeps


def test_honest_user_agent_params_and_base_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORLD_RUGBY_API_BASE_URL", "https://example.test/rugby/v3/")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        result = api.get_json(api.WORLD_RUGBY, "rankings/mru", {"date": "2023-10-30"}, ttl=60, client=client)

    assert result.payload == {"ok": True}
    assert result.ttl == 60
    request = seen[0]
    assert str(request.url) == "https://example.test/rugby/v3/rankings/mru?date=2023-10-30"
    assert request.headers["User-Agent"] == (
        f"vgi-rugby/{__version__} (+https://github.com/Query-farm/vgi-rugby)"
    )
    assert request.headers["Accept"] == "application/json"


def test_responses_are_cached_within_ttl() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"n": calls})

    with _client(handler) as client:
        first = api.get_json(api.ESPN_SITE, "180659/teams", ttl=60, client=client)
        second = api.get_json(api.ESPN_SITE, "180659/teams", ttl=60, client=client)
        other = api.get_json(api.ESPN_SITE, "180659/teams", {"x": 1}, ttl=60, client=client)

    assert first.payload == second.payload == {"n": 1}
    assert other.payload == {"n": 2}
    assert calls == 2


def test_zero_ttl_and_payload_dependent_ttl() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"done": request.url.path.endswith("done")})

    with _client(handler) as client:
        api.get_json(api.ESPN_SITE, "live", ttl=0, client=client)
        api.get_json(api.ESPN_SITE, "live", ttl=0, client=client)
        done = api.get_json(api.ESPN_SITE, "done", ttl=lambda p: 3600 if p["done"] else 5, client=client)

    assert calls == 3
    assert done.ttl == 3600


def test_expired_entries_are_refetched(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1_000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    with _client(handler) as client:
        api.get_json(api.ESPN_SITE, "a", ttl=10, client=client)
        now[0] += 11
        api.get_json(api.ESPN_SITE, "a", ttl=10, client=client)
    assert calls == 2


def test_cache_is_bounded() -> None:
    cache = api._TtlCache(2)
    for key in ("a", "b", "c"):
        cache.store(key, api.ApiResponse({}, 60))
    assert cache.get("a") is None
    assert cache.get("c") is not None


def test_retries_transient_status_honoring_retry_after(_no_sleep: list[float]) -> None:
    statuses = iter([503, 429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        if status == 200:
            return httpx.Response(200, json={"ok": 1})
        return httpx.Response(status, headers={"Retry-After": "2"}, text="busy")

    with _client(handler) as client:
        result = api.get_json(api.ESPN_SITE, "x", ttl=0, client=client)
    assert result.payload == {"ok": 1}
    assert _no_sleep == [2.0, 2.0]


def test_retry_after_http_date_and_backoff() -> None:
    future = httpx.Response(503, headers={"Retry-After": "Fri, 01 Jan 2100 00:00:00 GMT"})
    assert api._retry_delay(future, 0) == api.MAX_RETRY_DELAY
    past = httpx.Response(503, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert 0.25 <= api._retry_delay(past, 0) <= 0.3125
    garbage = httpx.Response(503, headers={"Retry-After": "soon"})
    assert 0.25 <= api._retry_delay(garbage, 0) <= 0.3125
    assert api._retry_delay(None, 20) == api.MAX_RETRY_DELAY


def test_gives_up_after_max_attempts() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502, text="bad gateway")

    with _client(handler) as client, pytest.raises(api.RugbyApiError, match="HTTP 502.*bad gateway"):
        api.get_json(api.ESPN_SITE, "x", ttl=0, client=client)
    assert calls == api.MAX_ATTEMPTS


def test_transport_errors_are_retried_then_raised() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down", request=request)

    with _client(handler) as client, pytest.raises(httpx.ConnectError):
        api.get_json(api.WORLD_RUGBY, "x", ttl=0, client=client)
    assert calls == api.MAX_ATTEMPTS


def test_client_errors_are_descriptive_and_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"code": 400, "message": "Failed to get events endpoint."})

    with _client(handler) as client, pytest.raises(api.RugbyApiError) as caught:
        api.get_json(api.ESPN_SITE, "180659/scoreboard", ttl=0, client=client)
    assert calls == 1
    assert caught.value.status == 400
    assert caught.value.source == "espn_site"
    assert "ESPN rugby API returned HTTP 400" in str(caught.value)


def test_undeclared_gzip_bodies_are_inflated() -> None:
    body = gzip.compress(json.dumps({"code": 404, "message": "gone"}).encode())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("ok"):
            return httpx.Response(200, content=gzip.compress(b'{"fine": true}'))
        return httpx.Response(404, content=body)

    with _client(handler) as client:
        assert api.get_json(api.ESPN_SITE, "ok", ttl=0, client=client).payload == {"fine": True}
        with pytest.raises(api.RugbyApiError, match="gone"):
            api.get_json(api.ESPN_SITE, "missing", ttl=0, client=client)


def test_corrupt_gzip_and_non_json_bodies() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x1f\x8bnot really gzip")

    with _client(handler) as client, pytest.raises(ValueError, match="non-JSON"):
        api.get_json(api.ESPN_SITE, "x", ttl=0, client=client)


def test_rate_limiter_waits_when_window_is_full(
    monkeypatch: pytest.MonkeyPatch, _no_sleep: list[float]
) -> None:
    now = [0.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])

    def fake_sleep(seconds: float) -> None:
        _no_sleep.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(api.time, "sleep", fake_sleep)
    limiter = api._RateLimiter(2, 10.0)
    limiter.acquire(deadline=100)
    limiter.acquire(deadline=100)
    limiter.acquire(deadline=100)
    assert _no_sleep == [10.0]
    with pytest.raises(TimeoutError):
        limiter.acquire(deadline=now[0] + 1)
        limiter.acquire(deadline=now[0] + 1)


def test_exhausted_quota_header_pauses_the_source(monkeypatch: pytest.MonkeyPatch) -> None:
    blocked: list[float] = []
    monkeypatch.setattr(api._limiters["world_rugby"], "block_for", blocked.append)
    response = httpx.Response(200, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "41"})
    api._observe_quota(api.WORLD_RUGBY, response)
    api._observe_quota(api.WORLD_RUGBY, httpx.Response(200, headers={"x-ratelimit-remaining": "9"}))
    api._observe_quota(
        api.WORLD_RUGBY,
        httpx.Response(200, headers={"x-ratelimit-remaining": "n/a", "x-ratelimit-reset": "1"}),
    )
    assert blocked == [41.0]


def test_blocked_limiter_delays_next_request(monkeypatch: pytest.MonkeyPatch, _no_sleep: list[float]) -> None:
    now = [0.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: now[0])

    def fake_sleep(seconds: float) -> None:
        _no_sleep.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(api.time, "sleep", fake_sleep)
    limiter = api._RateLimiter(10, 60.0)
    limiter.block_for(5)
    limiter.acquire(deadline=100)
    assert _no_sleep == [5.0]


def test_expired_deadline_raises_timeout() -> None:
    with _client(lambda request: httpx.Response(200, json={})) as client, pytest.raises(TimeoutError):
        api.get_json(api.ESPN_SITE, "x", ttl=0, client=client, deadline=api.time.monotonic() - 1)


def test_shared_client_is_reused_and_follows_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_shared_client", None)
    first = api._client()
    try:
        assert api._client() is first
        assert first.follow_redirects is True
    finally:
        first.close()
        monkeypatch.setattr(api, "_shared_client", None)

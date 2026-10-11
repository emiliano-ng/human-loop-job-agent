import time

import httpx
import pytest

from app import github_source, net


def test_sends_user_agent_and_honors_retry_after(mock_http, sleeps):
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, text="ok")

    mock_http(handler)
    assert net.get("https://example.test/a").text == "ok"
    assert len(seen) == 2
    assert seen[0] == net.DEFAULT_USER_AGENT
    assert 2.0 in sleeps


def test_gives_up_after_max_retries_with_backoff(mock_http, sleeps):
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(500)

    mock_http(handler)
    with pytest.raises(httpx.HTTPStatusError):
        net.get("https://example.test/b")
    assert len(attempts) == net.MAX_RETRIES + 1
    assert [s for s in sleeps if s in (1, 2, 4)] == [1, 2, 4]


def test_retries_network_errors(mock_http, sleeps):
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, text="hello")

    mock_http(handler)
    assert net.get("https://example.test/c").text == "hello"
    assert len(attempts) == 2


def test_does_not_retry_client_errors(mock_http, sleeps):
    attempts = []

    def handler(request):
        attempts.append(1)
        return httpx.Response(404)

    mock_http(handler)
    with pytest.raises(httpx.HTTPStatusError):
        net.get("https://example.test/d")
    assert len(attempts) == 1


def test_spaces_consecutive_requests(mock_http, sleeps, monkeypatch):
    mock_http(lambda request: httpx.Response(200, text="x"))
    monkeypatch.setattr(net, "_last_request", time.monotonic())
    net.get("https://example.test/e")
    assert sleeps
    assert 0 < sleeps[0] <= net.DEFAULT_DELAY


def test_delay_is_configurable(mock_http, sleeps, monkeypatch):
    mock_http(lambda request: httpx.Response(200, text="x"))
    monkeypatch.setenv("JOB_AGENT_REQUEST_DELAY", "0")
    net.get("https://example.test/f")
    net.get("https://example.test/f")
    assert sleeps == []


def test_user_agent_can_be_overridden(monkeypatch):
    monkeypatch.setattr(net, "_client", None)
    monkeypatch.setenv("JOB_AGENT_USER_AGENT", "custom-agent/1.0")
    client = net._get_client()
    try:
        assert client.headers["user-agent"] == "custom-agent/1.0"
    finally:
        client.close()


def test_github_list_reuses_local_copy_on_304(mock_http, sleeps, tmp_path, monkeypatch):
    monkeypatch.setattr(github_source, "_HTTP_CACHE", tmp_path / "http_cache")
    sent = []

    def handler(request):
        sent.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"abc"':
            return httpx.Response(304)
        return httpx.Response(200, text="CONTENT", headers={"ETag": '"abc"'})

    mock_http(handler)
    first = github_source._fetch_text_cached("https://raw.example.test/list.md")
    second = github_source._fetch_text_cached("https://raw.example.test/list.md")
    assert first == second == "CONTENT"
    assert sent == [None, '"abc"']

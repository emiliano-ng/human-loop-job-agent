"""Shared HTTP client with User-Agent, request spacing and retries."""

import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_USER_AGENT = "job-agent/0.1 (open-source job search assistant)"
DEFAULT_DELAY = 0.5
MAX_RETRIES = 3
RETRY_STATUS = {429, 500, 502, 503, 504}

_client: httpx.Client | None = None
_last_request = 0.0


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        ua = os.getenv("JOB_AGENT_USER_AGENT", DEFAULT_USER_AGENT)
        _client = httpx.Client(headers={"User-Agent": ua}, follow_redirects=True)
    return _client


def _throttle() -> None:
    global _last_request
    delay = float(os.getenv("JOB_AGENT_REQUEST_DELAY", DEFAULT_DELAY))
    wait = delay - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def _backoff(attempt: int) -> float:
    return min(2**attempt, 30)


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    try:
        return min(float(resp.headers["Retry-After"]), 60)
    except (KeyError, ValueError):
        return _backoff(attempt)


def get(url: str, *, headers: dict | None = None, timeout: float = 20) -> httpx.Response:
    """GET with spacing between requests and retries on 429, 5xx and network errors."""
    client = _get_client()
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        try:
            resp = client.get(url, headers=headers, timeout=timeout)
        except httpx.TransportError:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(_backoff(attempt))
            continue
        if resp.status_code in RETRY_STATUS and attempt < MAX_RETRIES:
            time.sleep(_retry_delay(resp, attempt))
            continue
        if resp.status_code == 304:
            return resp
        resp.raise_for_status()
        return resp
    raise RuntimeError("unreachable")

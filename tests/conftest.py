import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import cache, net

ROOT = Path(__file__).parent.parent


@pytest.fixture
def profile():
    return json.loads((ROOT / "data" / "profile.example.json").read_text(encoding="utf-8"))


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(net, "time", SimpleNamespace(sleep=calls.append, monotonic=time.monotonic))
    monkeypatch.setattr(net, "_last_request", 0.0)
    monkeypatch.delenv("JOB_AGENT_REQUEST_DELAY", raising=False)
    return calls


@pytest.fixture
def mock_http(monkeypatch):
    def install(handler):
        client = httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={"User-Agent": net.DEFAULT_USER_AGENT},
        )
        monkeypatch.setattr(net, "_client", client)

    return install


@pytest.fixture
def temp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "DB_PATH", tmp_path / "test.db")
    cache.init_db()

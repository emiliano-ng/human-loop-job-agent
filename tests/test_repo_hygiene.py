import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

PRIVATE_PATH = re.compile(
    r"^(data/profile\.json|data/companies\.json|\.env|\.env\.(?!example$).+"
    r"|job_agent_cache\.db.*|drafts/.*|\.http_cache/.*|\.?venv/.*)$"
)
SECRET = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16})"
)
REQUIRED_IGNORES = (
    "data/profile.json", "data/companies.json", ".env", "job_agent_cache.db", "drafts/", ".http_cache/", "venv/",
)


def tracked_files():
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [line for line in out.splitlines() if line]


def test_no_private_files_are_tracked():
    leaked = [f for f in tracked_files() if PRIVATE_PATH.match(f)]
    assert leaked == []


def test_no_secrets_in_tracked_files():
    hits = []
    for name in tracked_files():
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if SECRET.search(text):
            hits.append(name)
    assert hits == []


def test_gitignore_covers_private_paths():
    lines = {line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    missing = [p for p in REQUIRED_IGNORES if p not in lines]
    assert missing == []

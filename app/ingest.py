"""Pulls job postings from PUBLIC, documented ATS APIs."""

import json
import sys
from pathlib import Path

import httpx
from dataclasses import dataclass

from . import net

_COMPANIES_PATH = Path(__file__).parent.parent / "data" / "companies.json"


@dataclass
class JobPosting:
    source: str
    company: str
    title: str
    location: str
    url: str
    description: str
    posting_id: str


def fetch_greenhouse(board_token: str) -> list[JobPosting]:
    """Fetches postings from a Greenhouse board by its slug."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    resp = net.get(url, timeout=20)
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        jobs.append(
            JobPosting(
                source="greenhouse",
                company=board_token,
                title=j["title"],
                location=(j.get("location") or {}).get("name", ""),
                url=j["absolute_url"],
                description=j.get("content", ""),
                posting_id=str(j["id"]),
            )
        )
    return jobs


def fetch_lever(company_slug: str) -> list[JobPosting]:
    """company_slug is the company's slug in jobs.lever.co/<slug>."""
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    resp = net.get(url, timeout=20)
    resp.raise_for_status()
    jobs = []
    for j in resp.json():
        jobs.append(
            JobPosting(
                source="lever",
                company=company_slug,
                title=j["text"],
                location=(j.get("categories") or {}).get("location", ""),
                url=j["hostedUrl"],
                description=j.get("descriptionPlain", j.get("description", "")),
                posting_id=j["id"],
            )
        )
    return jobs


def fetch_ashby(board_name: str) -> list[JobPosting]:
    """board_name is the slug in jobs.ashbyhq.com/<board_name>."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true"
    resp = net.get(url, timeout=20)
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        jobs.append(
            JobPosting(
                source="ashby",
                company=board_name,
                title=j.get("title", ""),
                location=j.get("location", ""),
                url=j.get("jobUrl") or j.get("applyUrl", ""),
                description=j.get("descriptionPlain", ""),
                posting_id=j.get("jobUrl", j.get("title", "")),
            )
        )
    return jobs


def _load_companies_config() -> dict:
    """Loads scan targets from data/companies.json."""
    if not _COMPANIES_PATH.exists():
        sys.exit(
            f"\n[setup needed] {_COMPANIES_PATH} not found.\n\n"
            "This file tells the scanner which companies/job-boards to check. "
            "Copy the example and edit it:\n\n"
            "    cp data/companies.example.json data/companies.json\n\n"
            "(on Windows: copy data\\companies.example.json data\\companies.json)\n\n"
            "Then open data/companies.json and add the Greenhouse/Lever/Ashby "
            "slugs or GitHub job-list repos you want to scan, the _readme "
            "field inside the example explains each format.\n"
        )
    with open(_COMPANIES_PATH, encoding="utf-8") as f:
        return json.load(f)


def fetch_all() -> list[JobPosting]:
    config = _load_companies_config()
    postings: list[JobPosting] = []

    for entry in config.get("greenhouse", []):
        if not entry.get("active", True):
            continue
        slug = entry["slug"]
        try:
            postings.extend(fetch_greenhouse(slug))
        except httpx.HTTPError as e:
            print(f"[warn] Greenhouse fetch failed for {slug}: {e}")

    for entry in config.get("lever", []):
        if not entry.get("active", True):
            continue
        slug = entry["slug"]
        try:
            postings.extend(fetch_lever(slug))
        except httpx.HTTPError as e:
            print(f"[warn] Lever fetch failed for {slug}: {e}")

    for entry in config.get("ashby", []):
        if not entry.get("active", True):
            continue
        slug = entry["slug"]
        try:
            postings.extend(fetch_ashby(slug))
        except httpx.HTTPError as e:
            print(f"[warn] Ashby fetch failed for {slug}: {e}")

    for entry in config.get("github_job_lists", []):
        if not entry.get("active", True):
            continue
        owner, repo = entry["owner"], entry["repo"]
        branch = entry.get("branch", "dev")
        path = entry.get("path", "README.md")
        try:
            from .github_source import fetch_github_job_list
            postings.extend(fetch_github_job_list(owner, repo, branch, path))
        except httpx.HTTPError as e:
            print(f"[warn] GitHub list fetch failed for {owner}/{repo}: {e}")

    return postings


if __name__ == "__main__":
    results = fetch_all()
    print(f"Fetched {len(results)} postings.")
    for p in results[:10]:
        print(f"- [{p.company}] {p.title} ({p.location})")

"""Connector for GitHub-hosted job-tracker repos like SimplifyJobs' Summer-Internships and New-Grad-Positions lists."""

import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from . import net
from .ingest import JobPosting

_HTTP_CACHE = Path(__file__).parent.parent / ".http_cache"

LEGEND = {
    "🛂": "Does NOT offer immigration sponsorship.",
    "🇺🇸": "Requires U.S. Citizenship.",
    "🔒": "CLOSED",
    "🎓": "Requires an advanced degree (Master's, PhD, or MBA).",
}

HARD_EXCLUDE_FLAGS = {"🇺🇸", "🛂"}


def _fetch_text_cached(url: str) -> str:
    """Downloads a text file, reusing the local copy when the server reports it unchanged."""
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    body_path = _HTTP_CACHE / f"{key}.txt"
    meta_path = _HTTP_CACHE / f"{key}.json"
    headers = {}
    if body_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("etag"):
            headers["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            headers["If-Modified-Since"] = meta["last_modified"]
    resp = net.get(url, headers=headers, timeout=30)
    if resp.status_code == 304:
        return body_path.read_text(encoding="utf-8")
    _HTTP_CACHE.mkdir(exist_ok=True)
    body_path.write_text(resp.text, encoding="utf-8")
    meta_path.write_text(
        json.dumps({"etag": resp.headers.get("etag"), "last_modified": resp.headers.get("last-modified")}),
        encoding="utf-8",
    )
    return resp.text


def fetch_github_job_list(owner: str, repo: str, branch: str = "dev", path: str = "README.md") -> list[JobPosting]:
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    return _parse_html_tables(_fetch_text_cached(url), source=f"github:{owner}/{repo}")


def _clean_text(el) -> str:
    return el.get_text(strip=True) if el else ""


def _parse_html_tables(markdown_text: str, source: str) -> list[JobPosting]:
    soup = BeautifulSoup(markdown_text, "html.parser")
    postings = []
    last_company = None

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            company_cell, role_cell, location_cell, application_cell = cells[0], cells[1], cells[2], cells[3]

            company_raw = _clean_text(company_cell)
            if company_raw in ("↳", "") or company_raw is None:
                company = last_company or "Unknown"
            else:
                company = re.sub(r"[^\w\s&.,'-]", "", company_raw).strip() or company_raw
                last_company = company

            role_raw = _clean_text(role_cell)
            location = _clean_text(location_cell)

            flags_text = role_raw + " " + company_raw
            matched_emojis = [emoji for emoji in LEGEND if emoji in flags_text]
            matched_flags = [LEGEND[e] for e in matched_emojis]

            if "🔒" in matched_emojis:
                continue
            if any(e in HARD_EXCLUDE_FLAGS for e in matched_emojis):
                continue
            if re.search(r"u\.?s\.?\s*citizen(ship)?\s*required|citizenship\s*required", flags_text, re.IGNORECASE):
                continue

            link_tag = application_cell.find("a")
            job_url = link_tag["href"] if link_tag and link_tag.has_attr("href") else ""

            role_clean = re.sub(r"[^\w\s()/+#.,'-]", "", role_raw).strip()

            synthetic_description = (
                f"[This posting was sourced from a GitHub job-tracker list, not the "
                f"original job page, no full description is available here.]\n"
                f"Company: {company}\nRole: {role_clean}\nLocation: {location}\n"
            )
            if matched_flags:
                synthetic_description += "Flags noted by the tracker: " + "; ".join(matched_flags) + "\n"

            posting_id = hashlib.sha256(f"{company}|{role_clean}|{location}|{job_url}".encode("utf-8")).hexdigest()[:16]

            postings.append(
                JobPosting(
                    source=source,
                    company=company,
                    title=role_clean,
                    location=location,
                    url=job_url or "(no direct link found, check the repo)",
                    description=synthetic_description,
                    posting_id=posting_id,
                )
            )

    return postings

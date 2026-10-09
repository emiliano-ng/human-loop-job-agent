"""CLI entry point: scan, draft <url>, manual."""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from .ingest import fetch_all, JobPosting
from .scoring import (
    score_posting, is_obviously_irrelevant, looks_technical, is_excluded_location,
    ScoredPosting, classify_level, parse_level_filter, matches_level, LEVEL_PRESETS,
)
from .docx_export import build_resume_docx, convert_docx_to_pdf
from .validate import load_profile
from . import cache

DRAFTS_DIR = Path(__file__).parent.parent / "drafts"


def _safe_dirname(company: str, title: str) -> str:
    safe_company = "".join(c if c.isalnum() else "_" for c in company)
    safe_title = "".join(c if c.isalnum() else "_" for c in title)[:60]
    return f"{safe_company}_{safe_title}"


def _cv_basename(profile: dict, company: str, title: str) -> str:
    """Filename stub for the .docx/.pdf themselves."""
    stub = profile.get("candidate", {}).get("file_name_stub")
    if not stub:
        full_name = profile.get("candidate", {}).get("name", "Candidate")
        stub = "_".join(full_name.split()[:2]) or "Candidate"
    return f"{stub}_CV_{_safe_dirname(company, title)}"


def _write_sidecar_info(info_path: Path, scored):
    """Writes an info.txt next to each resume with the job URL, score and rationale."""
    lines = [
        f"Company: {scored.posting.company}",
        f"Title: {scored.posting.title}",
        f"Location: {scored.posting.location}",
        f"Level (auto-classified from title): {classify_level(scored.posting.title)}",
        f"Fit score: {scored.fit_score}",
        "",
        f"APPLY / VERIFY HERE: {scored.posting.url}",
        "",
        f"Rationale: {scored.rationale}",
    ]
    if scored.hard_flags:
        lines.append("")
        lines.append("Flags to double-check manually before applying:")
        lines.extend(f"  - {f}" for f in scored.hard_flags)
    info_path.write_text("\n".join(lines), encoding="utf-8")


def cmd_scan(min_score: int = 50, limit: int | None = None, level: str = "entry"):
    try:
        allowed_levels = parse_level_filter(level)
    except ValueError as e:
        print(f"[error] {e}")
        return

    cache.init_db()
    profile = load_profile()
    print("Fetching postings from configured companies...")
    all_postings = fetch_all()
    if not all_postings:
        print(
            "No postings fetched. Add company slugs to data/companies.json first "
            "-- copy data/companies.example.json to data/companies.json and edit "
            "it (see the _readme field inside for the format)."
        )
        return

    postings = [
        p for p in all_postings
        if not is_obviously_irrelevant(p.title)
        and looks_technical(p.title)
        and not is_excluded_location(p.location)
        and matches_level(p.title, allowed_levels)
    ]
    skipped = len(all_postings) - len(postings)
    print(
        f"Fetched {len(all_postings)} postings. Filtered out {skipped} "
        f"non-technical, obviously irrelevant, Asia/India-based, or "
        f"wrong-career-level ({level}) postings (see IRRELEVANT_TITLE_KEYWORDS / "
        f"RELEVANT_TITLE_KEYWORDS / EXCLUDED_LOCATION_KEYWORDS / classify_level "
        f"in scoring.py to adjust). {len(postings)} remain."
    )

    to_score = []
    cached_hits = 0
    for p in postings:
        if cache.get_cached(p.source, p.company, p.posting_id, p.description):
            cached_hits += 1
        else:
            to_score.append(p)

    print(f"{cached_hits} already scored in a previous run (skipped, using cached result). {len(to_score)} are new or changed.")

    if limit is not None and len(to_score) > limit:
        print(f"--limit {limit} set: only scoring the first {limit} new postings this run.")
        to_score = to_score[:limit]

    print(f"Scoring {len(to_score)} postings with the LLM...\n")

    DRAFTS_DIR.mkdir(exist_ok=True)
    new_matches = []

    for i, posting in enumerate(to_score, start=1):
        print(f"[{i}/{len(to_score)}] Scoring: {posting.company} - {posting.title} ...", flush=True)
        try:
            scored = score_posting(posting, profile)
        except Exception as e:
            print(f"    -> FAILED: {e}")
            continue
        print(f"    -> fit_score={scored.fit_score}")
        cache.save_scored(posting, scored)

        if scored.fit_score >= min_score:
            out_dir = DRAFTS_DIR / _safe_dirname(posting.company, posting.title)
            out_dir.mkdir(parents=True, exist_ok=True)
            base = _cv_basename(profile, posting.company, posting.title)
            docx_path = out_dir / f"{base}.docx"
            info_path = out_dir / "info.txt"
            try:
                build_resume_docx(scored, docx_path, profile)
                _write_sidecar_info(info_path, scored)
                pdf_path = convert_docx_to_pdf(docx_path)
                if pdf_path is None:
                    print(
                        "    -> .docx saved, but PDF conversion failed (no LibreOffice found). "
                        "Install it free from libreoffice.org, or open the .docx in Word and "
                        "use File > Save As > PDF."
                    )
                new_matches.append((scored, out_dir))
                print(f"    -> MATCH: draft saved to {out_dir}")
            except Exception as e:
                print(f"    -> Scored above threshold but .docx generation FAILED: {e}")

    print(
        f"\n\nDone. Showing everything cached with fit_score >= {min_score} and "
        f"level={level} (including past runs, even ones scored under a "
        f"different --level):\n"
    )
    for row in cache.all_cached(min_score):
        if not matches_level(row["title"], allowed_levels):
            continue
        hard_flags = json.loads(row["hard_flags_json"] or "[]")
        flag_str = f"  [!] {' | '.join(hard_flags)}" if hard_flags else ""
        draft_dir = DRAFTS_DIR / _safe_dirname(row["company"], row["title"])
        has_draft = " (draft ready)" if (draft_dir / f"{_cv_basename(profile, row['company'], row['title'])}.docx").exists() else " (run again to generate a draft)"
        print(f"[{row['fit_score']:3d}] {row['company']} - {row['title']}{flag_str}")
        print(f"       {row['rationale']}")
        print(f"       Job posting: {row['url']}")
        print(f"       Resume draft:{has_draft} {draft_dir}\n")


def cmd_manual():
    """Scores and drafts a resume for a pasted posting found outside the configured sources."""
    cache.init_db()
    profile = load_profile()

    company = input("Company name: ").strip()
    title = input("Job title: ").strip()
    location = input("Location (e.g. 'Austin, TX' or 'Remote'): ").strip()
    url = input("Job posting URL (paste the link so it ends up in info.txt): ").strip()

    print(
        "\nPaste the full job description below. When you're done, type "
        "END on its own line and press Enter:\n"
    )
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    description = "\n".join(lines).strip()

    if not description:
        print("No description entered, aborting.")
        return

    import hashlib
    posting_id = hashlib.sha256(description.encode("utf-8")).hexdigest()[:16]

    posting = JobPosting(
        source="manual", company=company, title=title, location=location,
        url=url or "(no URL provided)", description=description, posting_id=posting_id,
    )

    print("\nScoring with the LLM...")
    try:
        scored = score_posting(posting, profile)
    except Exception as e:
        print(f"Scoring FAILED: {e}")
        return

    cache.save_scored(posting, scored)

    print(f"\nFit score: {scored.fit_score}")
    print(f"Rationale: {scored.rationale}")
    if scored.hard_flags:
        print("Flags to double-check manually:")
        for f in scored.hard_flags:
            print(f"  - {f}")

    out_dir = DRAFTS_DIR / _safe_dirname(company, title)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _cv_basename(profile, company, title)
    docx_path = out_dir / f"{base}.docx"
    info_path = out_dir / "info.txt"
    build_resume_docx(scored, docx_path, profile)
    _write_sidecar_info(info_path, scored)
    pdf_path = convert_docx_to_pdf(docx_path)
    if pdf_path is None:
        print(
            "Note: .docx saved, but PDF conversion failed (no LibreOffice found). "
            "Install it free from libreoffice.org, or open the .docx in Word and "
            "use File > Save As > PDF."
        )

    print(f"\nDraft folder: {out_dir}")


def cmd_draft(url: str):
    row = cache.get_cached_by_url(url)
    if row is None:
        print(
            "No cached posting found for that URL. Run `python -m app.main scan` "
            "first (this posting needs to have been scored at least once)."
        )
        return

    profile = load_profile()

    posting = JobPosting(
        source=row["source"],
        company=row["company"],
        title=row["title"],
        location=row["location"] or "",
        url=row["url"],
        description="",
        posting_id=row["posting_id"],
    )
    scored = ScoredPosting(
        posting=posting,
        hard_flags=json.loads(row["hard_flags_json"] or "[]"),
        fit_score=row["fit_score"],
        rationale=row["rationale"] or "",
        skill_ids=json.loads(row["skill_ids_json"] or "[]"),
        project_ids=json.loads(row["project_ids_json"] or "[]"),
        rejected_by_validator=[],
    )

    out_dir = DRAFTS_DIR / _safe_dirname(row["company"], row["title"])
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _cv_basename(profile, row["company"], row["title"])
    docx_path = out_dir / f"{base}.docx"
    info_path = out_dir / "info.txt"
    build_resume_docx(scored, docx_path, profile)
    _write_sidecar_info(info_path, scored)
    pdf_path = convert_docx_to_pdf(docx_path)
    if pdf_path is None:
        print(
            "Note: .docx saved, but PDF conversion failed (no LibreOffice found). "
            "Install it free from libreoffice.org, or open the .docx in Word and "
            "use File > Save As > PDF."
        )

    print(f"Fit score: {scored.fit_score}")
    if scored.hard_flags:
        print("Flags to double-check manually:")
        for f in scored.hard_flags:
            print(f"  - {f}")
    print(f"\nDraft folder: {out_dir}")
    print(f"Job posting: {row['url']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    scan_p = sub.add_parser("scan")
    scan_p.add_argument("--min-score", type=int, default=50)
    scan_p.add_argument("--limit", type=int, default=None, help="Cap how many postings get scored, for quick test runs.")
    scan_p.add_argument(
        "--level", default="entry",
        help=(
            "Which career level(s) to include, by title. A preset "
            f"({', '.join(sorted(LEVEL_PRESETS))}) or a comma-separated list "
            "of internship,new_grad,senior,unspecified. Default: entry "
            "(internship + new_grad + unspecified, i.e. everything except "
            "explicitly senior-leveled titles, same as this tool's original "
            "behavior). Example: --level internship to see only internships, "
            "--level new_grad to see only new-grad roles, --level all to turn "
            "level filtering off (including senior roles, for the future)."
        ),
    )
    draft_p = sub.add_parser("draft")
    draft_p.add_argument("url")
    sub.add_parser("manual", help="Paste in a job posting found outside the configured companies (e.g. Workday-based ones) and generate a draft for it.")
    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args.min_score, args.limit, args.level)
    elif args.command == "draft":
        cmd_draft(args.url)
    elif args.command == "manual":
        cmd_manual()

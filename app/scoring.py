"""Posting evaluation: cheap deterministic pre-filters, then LLM scoring."""

import re
from dataclasses import dataclass

from .validate import load_profile, validate_selection
from .llm_client import json_completion
from .ingest import JobPosting


IRRELEVANT_TITLE_KEYWORDS = [
    "recruiter", "recruiting", "talent acquisition",
    "sales", "account executive", "business development",
    "marketing", "brand", "communications", "pr manager",
    "legal", "counsel", "compliance officer",
    "finance", "accounting", "financial controller", "payroll",
    "human resources", " hr ", "people operations", "people partner",
    "office coordinator", "executive assistant", "administrative assistant",
    "product designer", "visual designer", "brand designer", "ux ", "ui/ux", "graphic design",
    "customer success", "customer support agent",
    "operator", "technician",
    "chief ", "vp ", "vice president", "director of",
]


def is_obviously_irrelevant(title: str) -> bool:
    t = f" {title.lower()} "
    return any(kw in t for kw in IRRELEVANT_TITLE_KEYWORDS)


RELEVANT_TITLE_KEYWORDS = [
    "engineer", "engineering", "developer", "software", "firmware",
    "embedded", "robotics", "robot", "hardware", "electrical",
    "machine learning", "ml ", " ai ", "deep learning", "data scientist",
    "data engineer", "computer vision", "perception", "controls",
    "autonomy", "autonomous", "full stack", "full-stack", "backend",
    "infrastructure", "platform engineer", "research engineer",
]


def looks_technical(title: str) -> bool:
    t = f" {title.lower()} "
    return any(kw in t for kw in RELEVANT_TITLE_KEYWORDS)


EXCLUDED_LOCATION_KEYWORDS = [
    "india", "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi", "gurgaon", "gurugram", "chennai", "noida",
    "china", "shanghai", "beijing", "shenzhen", "hangzhou", "hong kong",
    "japan", "tokyo", "osaka",
    "south korea", "seoul",
    "singapore",
    "taiwan", "taipei",
    "vietnam", "hanoi", "ho chi minh",
    "philippines", "manila",
    "indonesia", "jakarta",
    "malaysia", "kuala lumpur",
    "thailand", "bangkok",
]


_EXCLUDED_LOCATION_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in EXCLUDED_LOCATION_KEYWORDS) + r")\b")


def is_excluded_location(location: str) -> bool:
    return bool(_EXCLUDED_LOCATION_RE.search((location or "").lower()))


INTERNSHIP_PATTERN = re.compile(r"\b(interns?|internships?|co-?ops?|co op)\b")

NEW_GRAD_KEYWORDS = [
    "new grad", "new graduate", "university grad", "university graduate",
    "recent graduate", "early career", "entry level", "entry-level",
    "early in career", "rotational", "rotation program", "graduate program",
    "associate engineer", "class of 20",
]

SENIOR_KEYWORDS = [
    "senior ", "sr.", "sr ", "principal ", "staff ", "lead ",
    "head of", "manager", "director",
]


def classify_level(title: str) -> str:
    """Buckets a posting title into internship, new_grad, senior or unspecified."""
    t = f" {title.lower()} "
    if INTERNSHIP_PATTERN.search(t):
        return "internship"
    if any(kw in t for kw in SENIOR_KEYWORDS):
        return "senior"
    if any(kw in t for kw in NEW_GRAD_KEYWORDS):
        return "new_grad"
    return "unspecified"


LEVEL_PRESETS: dict[str, set[str]] = {
    "entry": {"internship", "new_grad", "unspecified"},
    "internship": {"internship"},
    "new_grad": {"new_grad"},
    "senior": {"senior"},
    "all": {"internship", "new_grad", "senior", "unspecified"},
}

VALID_LEVEL_BUCKETS = {"internship", "new_grad", "senior", "unspecified"}


def parse_level_filter(level_arg: str) -> set[str]:
    """Turns the --level CLI value into a set of classify_level() bucket names to keep."""
    level_arg = (level_arg or "entry").strip().lower()
    if level_arg in LEVEL_PRESETS:
        return LEVEL_PRESETS[level_arg]
    buckets = {b.strip() for b in level_arg.split(",") if b.strip()}
    unknown = buckets - VALID_LEVEL_BUCKETS
    if unknown or not buckets:
        raise ValueError(
            f"Unknown --level value '{level_arg}'. Use a preset "
            f"({', '.join(sorted(LEVEL_PRESETS))}) or a comma-separated list "
            f"of: {', '.join(sorted(VALID_LEVEL_BUCKETS))}."
        )
    return buckets


def matches_level(title: str, allowed_levels: set[str]) -> bool:
    return classify_level(title) in allowed_levels


@dataclass
class ScoredPosting:
    posting: JobPosting
    hard_flags: list[str]
    fit_score: int
    rationale: str
    skill_ids: list[str]
    project_ids: list[str]
    rejected_by_validator: list[str]


def check_hard_disqualifiers(profile: dict, description: str) -> list[str]:
    flags = []
    for rule in profile["hard_disqualifier_rules"]:
        if re.search(rule["pattern"], description, re.IGNORECASE):
            flags.append(rule["flag"])
    return flags


SCORING_SYSTEM_PROMPT = """You are a careful, honest technical recruiter assistant.
You will be given a candidate's real, verified profile (skills and projects
with IDs) and a job posting. Score how well the candidate genuinely fits,
being skeptical rather than encouraging, the candidate would rather skip
a bad-fit application than waste time on one.

In your rationale, refer to skills and projects by their human-readable
NAME (e.g. "the Example Webapp project" or "PyTorch"), never by their internal
ID (e.g. never write "proj_example" or "skill_pytorch"), the IDs exist
only for the skill_ids/project_ids fields below, not for prose.

You MUST respond with ONLY valid JSON in this exact shape, nothing else:
{
  "fit_score": <integer 0-100>,
  "rationale": "<2-3 sentences, plain language, using real names not IDs, mention at least one real gap if any exists>",
  "skill_ids": ["<only IDs from the provided skill list that are genuinely relevant>"],
  "project_ids": ["<only IDs from the provided project list, ordered most to least relevant, max 4>"]
}

Never invent a skill or project ID that wasn't given to you. If nothing fits well, say so honestly with a low score.
"""


def score_posting(posting: JobPosting, profile: dict | None = None) -> ScoredPosting:
    profile = profile or load_profile()

    hard_flags = check_hard_disqualifiers(profile, posting.description)

    skills_list = "\n".join(f"- {s['id']}: {s['name']}" for s in profile["skills"])
    projects_list = "\n".join(f"- {p['id']}: {p['title']}" for p in profile["projects"])

    user_prompt = f"""CANDIDATE SKILLS:
{skills_list}

CANDIDATE PROJECTS:
{projects_list}

CANDIDATE DOES NOT HAVE: {", ".join(profile["not_skills"])}

JOB POSTING:
Company: {posting.company}
Title: {posting.title}
Location: {posting.location}
Description:
{posting.description[:6000]}

Pre-flagged concerns from automated screening (already detected, factor into your rationale/score, don't repeat them verbatim):
{chr(10).join(hard_flags) if hard_flags else "(none)"}
"""

    result = json_completion(SCORING_SYSTEM_PROMPT, user_prompt)

    validated = validate_selection(
        profile,
        result.get("skill_ids", []),
        result.get("project_ids", []),
    )

    rationale = _replace_ids_with_names(result.get("rationale", ""), profile)

    return ScoredPosting(
        posting=posting,
        hard_flags=hard_flags,
        fit_score=int(result.get("fit_score", 0)),
        rationale=rationale,
        skill_ids=validated["skill_ids"],
        project_ids=validated["project_ids"],
        rejected_by_validator=validated["rejected"],
    )


def _replace_ids_with_names(text: str, profile: dict) -> str:
    """Replaces raw skill and project IDs leaked into the rationale with display names."""
    id_to_name = {s["id"]: s["name"] for s in profile["skills"]}
    id_to_name.update({p["id"]: p["title"] for p in profile["projects"]})
    id_to_name.update({e["id"]: e["title"] for e in profile["experience"]})

    for raw_id in sorted(id_to_name, key=len, reverse=True):
        text = text.replace(raw_id, id_to_name[raw_id])
    return text

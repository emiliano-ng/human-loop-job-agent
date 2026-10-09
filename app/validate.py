"""Only place allowed to decide a skill or project claim is real: drops any ID missing from profile.json."""

import json
import sys
from pathlib import Path

PROFILE_PATH = Path(__file__).parent.parent / "data" / "profile.json"


def load_profile() -> dict:
    if not PROFILE_PATH.exists():
        sys.exit(
            f"\n[setup needed] {PROFILE_PATH} not found.\n\n"
            "This file is your ground-truth resume data, the only source "
            "the scorer/generator is allowed to pull skills, projects, and "
            "experience from. Copy the example and fill in your own info:\n\n"
            "    cp data/profile.example.json data/profile.json\n\n"
            "(on Windows: copy data\\profile.example.json data\\profile.json)\n\n"
            "Then edit data/profile.json with your real name, skills, "
            "projects, and experience before running scan/draft/manual.\n"
        )
    with open(PROFILE_PATH, encoding="utf-8") as f:
        return json.load(f)


def valid_skill_ids(profile: dict) -> set[str]:
    return {s["id"] for s in profile["skills"]}


def valid_project_ids(profile: dict) -> set[str]:
    return {p["id"] for p in profile["projects"]}


def valid_experience_ids(profile: dict) -> set[str]:
    return {e["id"] for e in profile["experience"]}


def validate_selection(profile: dict, skill_ids: list[str], project_ids: list[str]) -> dict:
    """Filters model-proposed skill_ids/project_ids down to only what actually exists in the ground-truth profile."""
    ok_skills = valid_skill_ids(profile)
    ok_projects = valid_project_ids(profile)

    clean_skills = [s for s in skill_ids if s in ok_skills]
    rejected_skills = [s for s in skill_ids if s not in ok_skills]

    clean_projects = [p for p in project_ids if p in ok_projects]
    rejected_projects = [p for p in project_ids if p not in ok_projects]

    return {
        "skill_ids": clean_skills,
        "project_ids": clean_projects,
        "rejected": rejected_skills + rejected_projects,
    }


if __name__ == "__main__":
    profile = load_profile()
    real_skill = profile["skills"][0]["id"]
    real_project = profile["projects"][0]["id"]
    result = validate_selection(
        profile,
        [real_skill, "skill_KUBERNETES_MASTER_FAKE"],
        [real_project, "proj_FAKE_PROJECT"],
    )
    print(result)
    assert "skill_KUBERNETES_MASTER_FAKE" in result["rejected"]
    assert "proj_FAKE_PROJECT" in result["rejected"]
    assert real_skill in result["skill_ids"]
    assert real_project in result["project_ids"]
    print("Validator self-test passed.")

import pytest

from app import scoring
from app.ingest import JobPosting
from app.scoring import (
    _replace_ids_with_names,
    check_hard_disqualifiers,
    classify_level,
    is_excluded_location,
    is_obviously_irrelevant,
    looks_technical,
    parse_level_filter,
    score_posting,
)


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Software Engineering Intern", "internship"),
        ("Robotics Co-op Summer 2027", "internship"),
        ("Embedded Firmware Internship", "internship"),
        ("Internal Tools Engineer", "unspecified"),
        ("International Software Engineer", "unspecified"),
        ("Senior Internal Tools Engineer", "senior"),
        ("Software Engineer, New Grad", "new_grad"),
        ("Staff Robotics Engineer", "senior"),
        ("Engineering Manager", "senior"),
        ("Embedded Engineer", "unspecified"),
    ],
)
def test_classify_level(title, expected):
    assert classify_level(title) == expected


def test_level_filter_presets_and_custom_lists():
    assert parse_level_filter("entry") == {"internship", "new_grad", "unspecified"}
    assert parse_level_filter("") == parse_level_filter("entry")
    assert parse_level_filter("all") == {"internship", "new_grad", "senior", "unspecified"}
    assert parse_level_filter("internship, unspecified") == {"internship", "unspecified"}


@pytest.mark.parametrize("value", ["bogus", "internship,bogus", ","])
def test_level_filter_rejects_unknown_values(value):
    with pytest.raises(ValueError):
        parse_level_filter(value)


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Technical Recruiter", True),
        ("Sales Engineer", True),
        ("Product Designer", True),
        ("Financial Controller", True),
        ("Motor Controller Firmware Engineer", False),
        ("ASIC Designer", False),
        ("Software Engineer Intern", False),
    ],
)
def test_obviously_irrelevant_titles(title, expected):
    assert is_obviously_irrelevant(title) is expected


@pytest.mark.parametrize(
    "title, expected",
    [("Embedded Software Engineer", True), ("Robotics Intern", True), ("Account Executive", False)],
)
def test_looks_technical(title, expected):
    assert looks_technical(title) is expected


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Bengaluru, India", True),
        ("Tokyo, Japan", True),
        ("Singapore", True),
        ("Austin, TX", False),
        ("Remote", False),
        ("Indianapolis, IN", False),
        ("Bloomington, Indiana", False),
        (None, False),
        ("", False),
    ],
)
def test_excluded_locations(location, expected):
    assert is_excluded_location(location) is expected


@pytest.mark.parametrize(
    "description, should_flag",
    [
        ("This role is subject to ITAR and export control rules.", True),
        ("Active security clearance required.", True),
        ("Must be a U.S. citizen.", True),
        ("We want 5+ years of experience shipping products.", True),
        ("A PhD is required for this position.", True),
        ("Great fit for students who love building robots.", False),
        ("Looking for 2+ years of hands-on experience.", False),
    ],
)
def test_hard_disqualifiers(profile, description, should_flag):
    assert bool(check_hard_disqualifiers(profile, description)) is should_flag


def test_replace_ids_handles_ids_that_contain_other_ids():
    profile = {
        "skills": [{"id": "skill_git", "name": "Git"}, {"id": "skill_github", "name": "GitHub"}],
        "projects": [],
        "experience": [],
    }
    assert _replace_ids_with_names("skill_github and skill_git", profile) == "GitHub and Git"


def test_score_posting_strips_invented_ids_and_raw_ids_from_prose(profile, monkeypatch):
    skill = profile["skills"][0]
    project = profile["projects"][0]

    def fake_completion(system_prompt, user_prompt):
        return {
            "fit_score": "85",
            "rationale": f"Good match through {skill['id']} and {project['id']}.",
            "skill_ids": [skill["id"], "skill_INVENTED"],
            "project_ids": [project["id"], "proj_INVENTED"],
        }

    monkeypatch.setattr(scoring, "json_completion", fake_completion)
    posting = JobPosting(
        source="greenhouse", company="Acme", title="Software Intern", location="Remote",
        url="https://example.test/1", description="Subject to ITAR restrictions.", posting_id="1",
    )
    scored = score_posting(posting, profile)
    assert scored.fit_score == 85
    assert scored.skill_ids == [skill["id"]]
    assert scored.project_ids == [project["id"]]
    assert set(scored.rejected_by_validator) == {"skill_INVENTED", "proj_INVENTED"}
    assert skill["id"] not in scored.rationale and project["id"] not in scored.rationale
    assert skill["name"] in scored.rationale and project["title"] in scored.rationale
    assert scored.hard_flags

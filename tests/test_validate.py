import re

import pytest

from app import validate
from app.validate import validate_selection


def test_rejects_fabricated_ids_and_keeps_real_ones(profile):
    skill = profile["skills"][0]["id"]
    project = profile["projects"][0]["id"]
    result = validate_selection(profile, [skill, "skill_FAKE"], [project, "proj_FAKE"])
    assert result["skill_ids"] == [skill]
    assert result["project_ids"] == [project]
    assert set(result["rejected"]) == {"skill_FAKE", "proj_FAKE"}


def test_empty_selection(profile):
    assert validate_selection(profile, [], []) == {"skill_ids": [], "project_ids": [], "rejected": []}


def test_a_project_id_is_not_accepted_as_a_skill(profile):
    project = profile["projects"][0]["id"]
    result = validate_selection(profile, [project], [])
    assert result["skill_ids"] == []
    assert result["rejected"] == [project]


def test_missing_profile_exits_with_setup_message(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "PROFILE_PATH", tmp_path / "profile.json")
    with pytest.raises(SystemExit) as exc:
        validate.load_profile()
    assert "setup needed" in str(exc.value)


def test_example_profile_is_consistent(profile):
    for key in ("candidate", "skills", "projects", "experience", "not_skills", "hard_disqualifier_rules"):
        assert key in profile
    ids = [x["id"] for group in ("skills", "projects", "experience") for x in profile[group]]
    assert len(ids) == len(set(ids))
    for rule in profile["hard_disqualifier_rules"]:
        re.compile(rule["pattern"])
        assert rule["flag"]

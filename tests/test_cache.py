import json

from app import cache
from app.ingest import JobPosting
from app.scoring import ScoredPosting


def make_posting(description="desc", posting_id="1", url="https://example.test/1"):
    return JobPosting(
        source="greenhouse", company="Acme", title="Robotics Intern", location="Remote",
        url=url, description=description, posting_id=posting_id,
    )


def make_scored(posting, score=80):
    return ScoredPosting(
        posting=posting, hard_flags=["flag"], fit_score=score, rationale="because",
        skill_ids=["skill_python"], project_ids=[], rejected_by_validator=[],
    )


def test_miss_before_save_and_hit_after(temp_cache):
    posting = make_posting()
    assert cache.get_cached(posting.source, posting.company, posting.posting_id, posting.description) is None
    cache.save_scored(posting, make_scored(posting))
    row = cache.get_cached(posting.source, posting.company, posting.posting_id, posting.description)
    assert row["fit_score"] == 80
    assert json.loads(row["hard_flags_json"]) == ["flag"]


def test_changed_description_is_a_cache_miss(temp_cache):
    posting = make_posting()
    cache.save_scored(posting, make_scored(posting))
    assert cache.get_cached(posting.source, posting.company, posting.posting_id, "new text") is None


def test_saving_again_updates_instead_of_duplicating(temp_cache):
    posting = make_posting()
    cache.save_scored(posting, make_scored(posting, 50))
    cache.save_scored(posting, make_scored(posting, 90))
    rows = cache.all_cached()
    assert len(rows) == 1
    assert rows[0]["fit_score"] == 90


def test_lookup_by_url(temp_cache):
    posting = make_posting(url="https://example.test/job")
    cache.save_scored(posting, make_scored(posting))
    assert cache.get_cached_by_url("https://example.test/job")["company"] == "Acme"
    assert cache.get_cached_by_url("https://example.test/other") is None


def test_all_cached_orders_by_score_and_filters(temp_cache):
    for i, score in enumerate((40, 90, 70)):
        posting = make_posting(posting_id=str(i), url=f"https://example.test/{i}")
        cache.save_scored(posting, make_scored(posting, score))
    assert [r["fit_score"] for r in cache.all_cached()] == [90, 70, 40]
    assert [r["fit_score"] for r in cache.all_cached(min_score=60)] == [90, 70]

import pytest

from tools.sources import (
    MAX_NOTE_CHARS, new_source, normalize_url, plan_source_update, sort_sources, source_counts,
    source_id, sources_from_evidence,
)


@pytest.mark.parametrize("raw,clean", [
    ("https://Example.COM/Path/", "https://example.com/Path"),
    ("https://example.com/a?utm_source=x&id=7&fbclid=abc#section", "https://example.com/a?id=7"),
    ("  http://example.com  ", "http://example.com"),
    ("https://example.com:8443/x", "https://example.com:8443/x"),
])
def test_normalize_url_tidies_without_changing_the_page(raw, clean):
    assert normalize_url(raw) == clean


@pytest.mark.parametrize("bad", [
    "javascript:alert(1)", "data:text/html,<script>1</script>", "ftp://example.com/x",
    "file:///etc/passwd", "example.com/no-scheme", "", "https://", "https://user:pw@example.com/",
])
def test_only_plain_web_links_are_accepted(bad):
    with pytest.raises(ValueError):
        normalize_url(bad)


def test_the_same_page_spelled_differently_gets_the_same_id_per_idea():
    a = source_id("idea_1", "https://Example.com/post/?utm_campaign=x")
    assert a == source_id("idea_1", "https://example.com/post#top")
    assert a != source_id("idea_2", "https://example.com/post")
    assert a.startswith("src_")


def test_new_source_has_expected_defaults():
    s = new_source("idea_1", "https://www.example.com/post", title="", found_by="scout", run_id="r1")
    assert (s["domain"], s["title"], s["important"], s["note"], s["found_by"]) == (
        "example.com", "example.com", False, "", "scout")
    assert s["idea_id"] == "idea_1" and s["run_id"] == "r1"


def test_new_source_validates_found_by_and_note_length():
    with pytest.raises(ValueError, match="found_by"):
        new_source("i", "https://a.com", found_by="robot")
    with pytest.raises(ValueError, match="characters"):
        new_source("i", "https://a.com", note="x" * (MAX_NOTE_CHARS + 1))


def test_plan_source_update_only_touches_the_owners_marks():
    s = new_source("i", "https://a.com")
    out = plan_source_update(s, {"important": True, "note": "  read section 3  "})
    assert out["important"] is True and out["note"] == "read section 3" and out["updated_at"]
    with pytest.raises(ValueError, match="cannot be edited"):
        plan_source_update(s, {"url": "https://evil.com"})
    with pytest.raises(ValueError, match="true or false"):
        plan_source_update(s, {"important": "yes"})
    with pytest.raises(ValueError, match="characters"):
        plan_source_update(s, {"note": "x" * 600})


def test_sources_from_evidence_registers_good_urls_and_skips_junk():
    idea = {"id": "idea_1", "run_id": "r9", "evidence": [
        {"url": "https://a.com/x", "title": "A", "published_date": "Wed, 07 Oct 2026 10:00:00 GMT"},
        {"url": "javascript:alert(1)", "title": "bad"},
        "not a dict",
        {"title": "no url"},
        {"url": "https://a.com/x?utm_source=feed"},     # same page again
    ]}
    found = sources_from_evidence(idea)
    assert [s["url"] for s in found] == ["https://a.com/x", "https://a.com/x"]
    assert found[0]["found_by"] == "scout" and found[0]["run_id"] == "r9" and found[0]["title"] == "A"
    assert found[0]["id"] == found[1]["id"]      # inserting both is harmless: the second is a no-op


def test_sources_from_evidence_handles_an_idea_with_no_evidence():
    assert sources_from_evidence({"id": "i"}) == []
    assert sources_from_evidence({"id": "i", "evidence": None}) == []


def test_source_counts_and_sorting():
    a = new_source("i1", "https://a.com"); b = new_source("i1", "https://b.com", important=True)
    c = new_source("i2", "https://c.com")
    a["created_at"], b["created_at"], c["created_at"] = "1", "2", "3"
    assert source_counts([a, b, c]) == {"i1": {"total": 2, "important": 1}, "i2": {"total": 1, "important": 0}}
    assert [s["url"] for s in sort_sources([a, b])] == ["https://b.com", "https://a.com"]   # important first

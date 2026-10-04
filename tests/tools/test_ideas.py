import pytest

from tools import ideas as ideas_mod
from tools.ideas import (
    MAX_TOPIC_CHARS, coverage_from, validate_experiment, edit_idea, new_idea, plan_edit, plan_status_change, topic_key,
)


def test_topic_key_ignores_case_punctuation_and_spacing():
    assert topic_key("  KV  Cache! ") == topic_key("kv cache") == "kv cach"


@pytest.mark.parametrize("paraphrase", [
    "KV cache",
    "How does KV caching work?",
    "KV cache explained",
    "kv caches",
    "Understanding the KV-cache",
])
def test_paraphrases_share_a_key(paraphrase):
    assert topic_key(paraphrase) == topic_key("KV cache")


@pytest.mark.parametrize("different", [
    "Prefix caching in LLM serving",
    "KV cache quantization",
    "Kalman filters",
])
def test_different_topics_get_different_keys(different):
    assert topic_key(different) != topic_key("KV cache")


def test_topic_made_only_of_stopwords_still_gets_a_key():
    assert topic_key("How does it work?") != ""


def test_new_idea_has_expected_defaults():
    idea = new_idea("Kalman filters", "niche", "refresher", "autonomous-driving", "needs a refresh")
    assert idea["status"] == "pending"
    assert idea["topic_key"] == "kalman filter"
    assert idea["skip_count"] == 0
    assert idea["id"].startswith("idea_")


@pytest.mark.parametrize("field,bad", [("angle", "huge"), ("kind", "news"), ("source", "bot")])
def test_new_idea_rejects_bad_enum_values(field, bad):
    args = dict(topic="t", angle="broad", kind="trending", profile_topic="p", rationale="r")
    args[field] = bad
    with pytest.raises(ValueError):
        new_idea(**args)


def test_new_idea_rejects_empty_topic():
    with pytest.raises(ValueError):
        new_idea("   ", "broad", "trending", "p", "r")


def test_coverage_counts_and_tracks_latest():
    ideas = [
        {"profile_topic": "vla", "created_at": "2026-10-01T00:00:00", "updated_at": "2026-10-09T00:00:00"},
        {"profile_topic": "vla", "created_at": "2026-10-05T00:00:00", "updated_at": "2026-10-05T00:00:00"},
        {"profile_topic": "caching", "created_at": "2026-10-02T00:00:00", "updated_at": "2026-10-02T00:00:00"},
        {"profile_topic": "not-in-profile", "created_at": "2026-10-03T00:00:00", "updated_at": "2026-10-03T00:00:00"},
    ]
    cov = coverage_from(ideas, ["vla", "caching", "slam"])
    assert cov["vla"] == {
        "count": 2,
        "last_created": "2026-10-05T00:00:00",
        "last_updated": "2026-10-09T00:00:00",  # the older idea was edited later
    }
    assert cov["caching"]["count"] == 1
    assert cov["slam"] == {"count": 0, "last_created": None, "last_updated": None}
    assert "not-in-profile" not in cov


# ---- edit_idea: Cosmos calls are replaced with fakes, so no network ----------

@pytest.fixture
def fake_store(monkeypatch):
    """One stored idea; captures what edit_idea writes back."""
    stored = {"id": "idea_1", "topic": "Old topic", "topic_key": "old topic",
              "status": "rejected", "_etag": "x", "updated_at": "2026-10-01T00:00:00"}
    written = {}
    monkeypatch.setattr(ideas_mod, "get_document", lambda container, doc_id: dict(stored))
    monkeypatch.setattr(ideas_mod, "find_by_topic_key", lambda key: None)
    monkeypatch.setattr(ideas_mod, "upsert_document", lambda container, doc: written.update(doc))
    return written


def test_edit_idea_recomputes_topic_key(fake_store):
    edit_idea("idea_1", topic="  New  Topic! ")
    assert fake_store["topic"] == "New  Topic!"
    assert fake_store["topic_key"] == "new topic"


def test_edit_idea_does_not_change_status_and_strips_system_fields(fake_store):
    edit_idea("idea_1", rationale="sharper angle")
    assert fake_store["status"] == "rejected"
    assert fake_store["rationale"] == "sharper angle"
    assert "_etag" not in fake_store
    assert fake_store["updated_at"] > "2026-10-01T00:00:00"


def test_edit_idea_rejects_topic_that_clashes_with_another_idea(fake_store, monkeypatch):
    monkeypatch.setattr(ideas_mod, "find_by_topic_key", lambda key: {"id": "idea_2"})
    with pytest.raises(ValueError, match="idea_2"):
        edit_idea("idea_1", topic="Taken topic")
    assert fake_store == {}  # nothing was written


def test_edit_idea_allows_keeping_its_own_topic(fake_store, monkeypatch):
    monkeypatch.setattr(ideas_mod, "find_by_topic_key", lambda key: {"id": "idea_1"})
    edit_idea("idea_1", topic="Old topic")  # matches itself, not a clash
    assert fake_store["topic_key"] == "old topic"


def test_edit_idea_unknown_id_raises(monkeypatch):
    monkeypatch.setattr(ideas_mod, "get_document", lambda container, doc_id: None)
    with pytest.raises(KeyError):
        edit_idea("nope", rationale="x")


# ---- topic length ---------------------------------------------------------------------

def test_new_idea_rejects_an_over_long_topic():
    with pytest.raises(ValueError, match="characters"):
        new_idea("x" * (MAX_TOPIC_CHARS + 1), "broad", "trending", "p", "r")


# ---- status changes: free among the owner's statuses, blocked once the pipeline owns it ----

@pytest.mark.parametrize("old", ["pending", "approved", "rejected"])
@pytest.mark.parametrize("new", ["pending", "approved", "rejected"])
def test_owner_can_move_an_idea_freely_among_pending_approved_rejected(old, new):
    plan = plan_status_change({"status": old}, new)
    assert plan["status"] == new


def test_reject_reason_is_kept_when_rejecting_and_cleared_when_reviving():
    assert plan_status_change({"status": "pending"}, "rejected", "  too shallow ")["reject_reason"] == "too shallow"
    assert plan_status_change({"status": "pending"}, "rejected", "   ")["reject_reason"] is None
    assert plan_status_change({"status": "rejected", "reject_reason": "old"}, "approved", "ignored")["reject_reason"] is None


@pytest.mark.parametrize("owned", ["researched", "held", "drafted", "published"])
def test_pipeline_owned_ideas_cannot_be_changed_from_outside(owned):
    with pytest.raises(ValueError, match="pipeline owns"):
        plan_status_change({"status": owned}, "pending")


@pytest.mark.parametrize("bad", ["researched", "published", "banana"])
def test_owner_cannot_set_pipeline_statuses(bad):
    with pytest.raises(ValueError, match="only set"):
        plan_status_change({"status": "pending"}, bad)


# ---- plan_edit --------------------------------------------------------------------------

def test_plan_edit_validates_fields_and_recomputes_the_key():
    idea = {"id": "i1"}
    out = plan_edit(idea, {"topic": "  KV caching explained ", "angle": "niche"}, lambda key: None)
    assert out == {"topic": "KV caching explained", "topic_key": "kv cach", "angle": "niche"}


@pytest.mark.parametrize("changes,message", [
    ({"status": "approved"}, "cannot be edited"),
    ({"angle": "huge"}, "angle"),
    ({"kind": "news"}, "kind"),
    ({"topic": ""}, "empty"),
    ({"topic": "x" * 200}, "characters"),
    ({"rationale": "x" * 600}, "too long"),
])
def test_plan_edit_rejects_bad_changes(changes, message):
    with pytest.raises(ValueError, match=message):
        plan_edit({"id": "i1"}, changes, lambda key: None)


# ---- experiments ------------------------------------------------------------------------------------------

PLAN = {"question": "How much faster is generation with a KV cache?", "setup": "Run 20 prompts on a 125M model with and without the cache.",
        "measure": "Tokens per second for each.", "effort": "hours", "needs": ["cpu"]}


def test_a_complete_plan_is_accepted_and_cleaned():
    out = validate_experiment({**PLAN, "question": "  Why?  ", "needs": ["cpu", "cpu"]})
    assert out["question"] == "Why?" and out["needs"] == ["cpu"]


@pytest.mark.parametrize("change,message", [
    ({"question": ""}, "experiment.question is required"),
    ({"setup": "  "}, "experiment.setup is required"),
    ({"measure": "x" * 300}, "experiment.measure is 300 characters"),
    ({"effort": "week"}, "nothing bigger than a weekend"),
    ({"effort": None}, "experiment.effort"),
    ({"needs": []}, "experiment.needs"),
    ({"needs": ["tpu-pod"]}, "experiment.needs"),
    ({"bonus": "x"}, "unknown experiment fields"),
])
def test_an_incomplete_or_oversized_plan_is_rejected(change, message):
    with pytest.raises(ValueError, match=message):
        validate_experiment({**PLAN, **change})


def test_missing_plan_or_wrong_type_is_rejected():
    for bad in (None, "just do it", ["x"]):
        with pytest.raises(ValueError, match="needs an experiment plan"):
            validate_experiment(bad)


def test_a_plan_cannot_need_hardware_the_owner_does_not_have():
    with pytest.raises(ValueError, match="only has"):
        validate_experiment({**PLAN, "needs": ["small-gpu"]}, allowed_needs=("cpu",))
    assert validate_experiment({**PLAN, "needs": ["cpu", "small-gpu"]}, allowed_needs=("cpu", "small-gpu"))["needs"] == ["cpu", "small-gpu"]


def test_new_idea_requires_a_plan_for_experiments_and_forbids_one_otherwise():
    exp = new_idea("Measure KV caching on CPU", "niche", "experiment", "p", "r", experiment=PLAN, builds_on="idea_parent")
    assert exp["experiment"]["effort"] == "hours" and exp["builds_on"] == "idea_parent"
    with pytest.raises(ValueError, match="needs an experiment plan"):
        new_idea("Measure KV caching on CPU", "niche", "experiment", "p", "r")
    with pytest.raises(ValueError, match="only ideas of kind"):
        new_idea("Explain KV caching", "broad", "deep-dive", "p", "r", experiment=PLAN)
    plain = new_idea("Explain KV caching", "broad", "deep-dive", "p", "r")
    assert plain["experiment"] is None and plain["builds_on"] is None


def test_editing_keeps_kind_and_plan_consistent():
    exp = {"id": "i1", "kind": "experiment", "experiment": validate_experiment(PLAN)}
    plain = {"id": "i2", "kind": "deep-dive", "experiment": None}
    # editing an experiment's plan validates it
    out = plan_edit(exp, {"experiment": {**PLAN, "effort": "weekend"}}, lambda k: None)
    assert out["experiment"]["effort"] == "weekend"
    with pytest.raises(ValueError, match="experiment.effort"):
        plan_edit(exp, {"experiment": {**PLAN, "effort": "week"}}, lambda k: None)
    # turning an idea INTO an experiment needs a plan; turning one away from it drops the plan
    with pytest.raises(ValueError, match="needs an experiment plan"):
        plan_edit(plain, {"kind": "experiment"}, lambda k: None)
    assert plan_edit(plain, {"kind": "experiment", "experiment": PLAN}, lambda k: None)["experiment"]["needs"] == ["cpu"]
    assert plan_edit(exp, {"kind": "deep-dive"}, lambda k: None)["experiment"] is None
    # a plan on a non-experiment is refused
    with pytest.raises(ValueError, match="only ideas of kind"):
        plan_edit(plain, {"experiment": PLAN}, lambda k: None)
    # an unrelated edit does not disturb a valid plan
    assert "experiment" not in plan_edit(plain, {"rationale": "r"}, lambda k: None)
    assert plan_edit(exp, {"rationale": "r"}, lambda k: None)["experiment"]["question"]


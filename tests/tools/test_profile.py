import pytest

from tools.profile import (
    allowed_resources, area_of, area_topics, changed_topics, profile_with_topic, topic_levels, validate_profile,
)


def make(*pairs):
    """make(('vla','learning'), ('rag','know')) -> a tiny profile."""
    return {"areas": [{"name": "x", "topics": [{"key": k, "level": l} for k, l in pairs]}]}


def test_no_old_profile_means_everything_is_new():
    assert changed_topics(None, make(("vla", "learning"), ("rag", "know"))) == ["rag", "vla"]


def test_unchanged_profile_has_no_changes():
    p = make(("vla", "learning"))
    assert changed_topics(p, p) == []


def test_level_change_is_detected():
    old, new = make(("agents", "curious")), make(("agents", "know"))
    assert changed_topics(old, new) == ["agents"]


def test_new_topic_is_detected():
    old, new = make(("vla", "learning")), make(("vla", "learning"), ("slam", "curious"))
    assert changed_topics(old, new) == ["slam"]


def test_removed_topic_is_ignored():
    old, new = make(("vla", "learning"), ("slam", "curious")), make(("vla", "learning"))
    assert changed_topics(old, new) == []


def test_topic_levels_flattens_areas():
    p = {"areas": [{"name": "a", "topics": [{"key": "x", "level": "know"}]},
                   {"name": "b", "topics": [{"key": "y", "level": "curious"}]}]}
    assert topic_levels(p) == {"x": "know", "y": "curious"}

def test_area_topics_groups_keys_by_area_in_order():
    p = {"areas": [{"name": "a", "topics": [{"key": "x", "level": "know"}, {"key": "z", "level": "know"}]},
                   {"name": "b", "topics": [{"key": "y", "level": "curious"}]}]}
    assert area_topics(p) == {"a": ["x", "z"], "b": ["y"]}


GOOD = {"areas": [{"name": "agents", "topics": [{"key": "multi-agent", "level": "curious"}]},
                  {"name": "cv", "topics": [{"key": "3d-estimation", "level": "learning"}]}],
        "avoid": ["what is a transformer"], "mix": {"trending": 1}}


def test_a_good_profile_has_no_errors():
    assert validate_profile(GOOD) == []


def edited(**changes):
    import copy
    p = copy.deepcopy(GOOD)
    p.update(changes)
    return p


@pytest.mark.parametrize("profile,needle", [
    ({"areas": []}, "at least one area"),
    ({"areas": [{"name": "Bad Name", "topics": [{"key": "x", "level": "know"}]}]}, "lowercase"),
    ({"areas": [{"name": "a", "topics": []}]}, "at least one topic"),
    ({"areas": [{"name": "a", "topics": [{"key": "Bad Key", "level": "know"}]}]}, "lowercase"),
    ({"areas": [{"name": "a", "topics": [{"key": "x", "level": "expert"}]}]}, "level"),
    ({"areas": [{"name": "a", "topics": [{"key": "x", "level": "know"}]},
                {"name": "a", "topics": [{"key": "y", "level": "know"}]}]}, "duplicate area"),
    ({"areas": [{"name": "a", "topics": [{"key": "x", "level": "know"}]},
                {"name": "b", "topics": [{"key": "x", "level": "know"}]}]}, "unique across all areas"),
])
def test_validate_profile_reports_each_kind_of_problem(profile, needle):
    assert any(needle in e for e in validate_profile(profile))


def test_validate_profile_checks_avoid_and_mix():
    assert any("avoid" in e for e in validate_profile(edited(avoid=["ok", ""])))
    assert any("mix" in e for e in validate_profile(edited(mix={"trending": -1})))
    assert any("mix" in e for e in validate_profile(edited(mix={"trending": "one"})))


def test_area_of_finds_the_current_area_or_none():
    assert area_of(GOOD, "3d-estimation") == "cv"
    assert area_of(GOOD, "gone") is None


def test_profile_with_topic_adds_to_an_existing_area_without_touching_the_original():
    new = profile_with_topic(GOOD, "agents", "agentic-evals", "curious")
    assert area_topics(new)["agents"] == ["multi-agent", "agentic-evals"]
    assert area_topics(GOOD)["agents"] == ["multi-agent"]


def test_profile_with_topic_creates_a_new_area():
    new = profile_with_topic(GOOD, "quantum", "qubits", "curious")
    assert area_topics(new)["quantum"] == ["qubits"]


def test_profile_with_topic_rejects_existing_keys_and_bad_levels():
    with pytest.raises(ValueError, match="already in the profile"):
        profile_with_topic(GOOD, "cv", "multi-agent", "curious")
    with pytest.raises(ValueError, match="level"):
        profile_with_topic(GOOD, "cv", "new-thing", "expert")


def test_resources_default_to_a_laptop_and_must_come_from_the_known_choices():
    assert allowed_resources({}) == ["cpu"] and allowed_resources(None) == ["cpu"]
    assert allowed_resources({"resources": ["cpu", "small-gpu"]}) == ["cpu", "small-gpu"]
    assert validate_profile(edited(resources=["cpu", "small-gpu"])) == []
    for bad in ([], ["quantum"], "cpu"):
        assert any("resources" in e for e in validate_profile(edited(resources=bad)))


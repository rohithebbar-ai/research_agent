import pytest

from tools.suggestions import MAX_NAME_CHARS, new_suggestion, plan_suggestion_status, slugify


def test_slugify_produces_profile_style_keys():
    assert slugify("KV cache eviction!") == "kv-cache-eviction"
    assert slugify("  3D  estimation ") == "3d-estimation"


def test_new_suggestion_has_expected_fields():
    s = new_suggestion("World Models", "Robotics", "why", "subtopic", run_id="r1")
    assert (s["key"], s["area"], s["status"], s["level"], s["run_id"]) == (
        "world-models", "robotics", "pending", "curious", "r1")
    assert s["id"].startswith("sug_") and s["decided_at"] is None


@pytest.mark.parametrize("kwargs,message", [
    (dict(name="  ", area="a", kind="subtopic"), "empty"),
    (dict(name="x" * (MAX_NAME_CHARS + 1), area="a", kind="subtopic"), "characters"),
    (dict(name="ok", area="!!!", kind="subtopic"), "area is empty"),
    (dict(name="ok", area="a", kind="galaxy"), "kind"),
    (dict(name="ok", area="a", kind="subtopic", level="expert"), "level"),
])
def test_new_suggestion_rejects_bad_input(kwargs, message):
    with pytest.raises(ValueError, match=message):
        new_suggestion(why="w", **kwargs)


def test_every_status_move_is_allowed_so_the_owner_can_change_their_mind():
    for old in ("pending", "accepted", "dismissed"):
        for new in ("pending", "accepted", "dismissed"):
            assert plan_suggestion_status({"status": old}, new)["status"] == new


def test_decided_at_is_set_when_deciding_and_cleared_when_back_to_pending():
    assert plan_suggestion_status({"status": "pending"}, "dismissed")["decided_at"]
    assert plan_suggestion_status({"status": "dismissed"}, "pending")["decided_at"] is None


def test_unknown_suggestion_status_rejected():
    with pytest.raises(ValueError):
        plan_suggestion_status({"status": "pending"}, "maybe")


def test_a_suggestion_records_who_made_it_and_defaults_to_scout():
    assert new_suggestion("Jev", "ai-engineering", "w", "subtopic")["source"] == "scout"
    assert new_suggestion("Jev", "ai-engineering", "w", "subtopic", source="you")["source"] == "you"
    with pytest.raises(ValueError, match="source"):
        new_suggestion("Jev", "ai-engineering", "w", "subtopic", source="robot")


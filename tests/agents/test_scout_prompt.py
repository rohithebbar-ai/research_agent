import inspect

import pytest

from agents.scout_prompt import (
    EXPLORE_SYSTEM_PROMPT, MAX_EXISTING_LINES, MAX_FOCUS_TOPICS, SYSTEM_PROMPT, build_explore_briefing,
    pick_area, TOOL_SCHEMAS, build_briefing, resources_text, schemas_for, select_topics, target_mix_line,
)
from agents.scout_tools import ScoutConfig, ScoutTools
from tools.ideas import ANGLES, KINDS, MAX_TOPIC_CHARS, STATUSES, coverage_from, new_idea
from tools.profile import topic_levels

PROFILE = {
    "areas": [
        {"name": "robotics", "topics": [{"key": "vla", "level": "learning"}]},
        {"name": "llm", "topics": [{"key": "rag", "level": "know"}, {"key": "agents", "level": "curious"}]},
    ],
    "avoid": ["what is a transformer"],
    "mix": {"trending": 1, "refresher_or_deep_dive": 2},
}


def idea(topic, status="pending", profile_topic="agents", created_at="2026-10-01T00:00:00+00:00", **extra):
    i = new_idea(topic, "broad", "deep-dive", profile_topic, "r")
    i.update(status=status, created_at=created_at, **extra)
    return i


def brief(ideas=(), trends=(), mode="weekly", topics=None, **cfg):
    config = ScoutConfig(mode=mode, **cfg)
    keys = list(topic_levels(PROFILE))
    cov = coverage_from(list(ideas), keys)
    return build_briefing(PROFILE, topics or keys, list(ideas), list(trends), cov, config, "2026-10-04")


# ---- schemas stay in sync with the tool functions --------------------------------

@pytest.mark.parametrize("schema", TOOL_SCHEMAS, ids=lambda s: s["function"]["name"])
def test_schema_matches_the_handler_signature(schema):
    fn = schema["function"]
    handler = ScoutTools(None, None, ScoutConfig())._handlers[fn["name"]]
    params = inspect.signature(handler).parameters
    assert set(fn["parameters"]["properties"]) == set(params)
    required = {name for name, p in params.items() if p.default is inspect.Parameter.empty}
    assert set(fn["parameters"]["required"]) == required


def test_every_tool_has_a_schema():
    handlers = set(ScoutTools(None, None, ScoutConfig())._handlers)
    assert {s["function"]["name"] for s in TOOL_SCHEMAS} == handlers


def test_enums_come_from_the_idea_rules():
    props = {s["function"]["name"]: s["function"]["parameters"]["properties"] for s in TOOL_SCHEMAS}
    assert set(props["propose_idea"]["angle"]["enum"]) == ANGLES
    assert set(props["propose_idea"]["kind"]["enum"]) == KINDS
    assert set(props["read_backlog"]["status"]["enum"]) == STATUSES


def test_hold_only_mode_hides_propose_idea():
    names = lambda mode: {s["function"]["name"] for s in schemas_for(mode)}
    assert "propose_idea" in names("weekly") and "propose_idea" in names("profile_changed")
    assert "propose_idea" not in names("hold_only") and "hold_trend" in names("hold_only")


# ---- select_topics ----------------------------------------------------------------

def test_weekly_orders_least_covered_first():
    ideas = [idea("a one", profile_topic="vla"), idea("b two", profile_topic="vla"),
             idea("c three", profile_topic="rag")]
    cov = coverage_from(ideas, ["vla", "rag", "agents"])
    assert select_topics(PROFILE, "weekly", None, cov) == ["agents", "rag", "vla"]


def big_profile(n):
    return {"areas": [{"name": "x", "topics": [{"key": f"t{i:02d}", "level": "curious"} for i in range(n)]}]}


def test_weekly_is_capped_to_the_least_covered_topics():
    profile = big_profile(MAX_FOCUS_TOPICS + 5)
    covered = [idea(f"idea {i}", profile_topic="t00") for i in range(3)]   # t00 is the most covered
    cov = coverage_from(covered, list(topic_levels(profile)))
    picked = select_topics(profile, "weekly", None, cov)
    assert len(picked) == MAX_FOCUS_TOPICS and "t00" not in picked
    assert len(select_topics(profile, "hold_only", None, cov)) == MAX_FOCUS_TOPICS


def test_profile_changed_is_not_capped():
    profile = big_profile(MAX_FOCUS_TOPICS + 5)
    assert len(select_topics(profile, "profile_changed", None, {})) == MAX_FOCUS_TOPICS + 5


def test_profile_changed_only_returns_changed_topics():
    old = {"areas": [{"name": "x", "topics": [{"key": "vla", "level": "learning"},
                                              {"key": "rag", "level": "know"},
                                              {"key": "agents", "level": "know"}]}]}
    # PROFILE differs from old only in: agents know -> curious
    assert select_topics(PROFILE, "profile_changed", old, {}) == ["agents"]


def test_profile_changed_with_no_previous_profile_means_everything():
    assert sorted(select_topics(PROFILE, "profile_changed", None, {})) == ["agents", "rag", "vla"]


# ---- build_briefing ----------------------------------------------------------------

def test_briefing_contains_profile_levels_avoid_list_and_mix():
    text = brief()
    for needle in ("vla (learning)", "rag (know)", "agents (curious)", "what is a transformer",
                   "1 trending, 1 experiment, 1 refresher/deep-dive", "Today: 2026-10-04"):
        assert needle in text


def test_briefing_shows_coverage_for_focus_topics():
    text = brief([idea("KV cache", profile_topic="vla", created_at="2026-09-20T10:00:00+00:00")],
                 topics=["vla", "agents"])
    assert "- vla (learning): 1 ideas so far, last proposed 2026-09-20" in text
    assert "- agents (curious): 0 ideas so far, last proposed never" in text


def test_briefing_lists_existing_ideas_trends_and_rejections_with_reasons():
    text = brief([idea("KV cache", "approved"),
                  idea("Old news roundup", "rejected", reject_reason="too shallow")],
                 trends=[{"topic": "Flux 3 release"}])
    assert "[approved] KV cache" in text
    assert "Reading list: Flux 3 release" in text
    assert '"Old news roundup": too shallow' in text


def test_briefing_truncates_a_huge_backlog_but_says_so():
    many = [idea(f"topic number {n}", created_at=f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}+00:00")
            for n in range(MAX_EXISTING_LINES + 30)]
    text = brief(many)
    assert text.count("- [pending]") == MAX_EXISTING_LINES
    assert "+30 older ideas not shown" in text


def test_briefing_reports_backlog_room_and_limits():
    text = brief([idea("A one"), idea("B two", "approved"), idea("C three", "rejected")],
                 backlog_cap=8, max_proposals=3)
    assert "1 of 8 undecided (pending) ideas" in text and "3 proposals" in text


@pytest.mark.parametrize("mode,needle", [
    ("hold_only", "Do NOT propose ideas"),
    ("profile_changed", "profile was just edited"),
    ("weekly", "Weekly run"),
])
def test_briefing_explains_the_mode(mode, needle):
    assert needle in brief(mode=mode)


def test_system_prompt_names_the_key_rules():
    for needle in ("finish", "published_date", "news=true", "ERROR", "'know'", "'curious'"):
        assert needle in SYSTEM_PROMPT


# ---- focusing a run on one area ------------------------------------------------------

def test_select_topics_with_area_only_returns_that_areas_topics():
    cov = coverage_from([], list(topic_levels(PROFILE)))
    assert sorted(select_topics(PROFILE, "weekly", None, cov, area="llm")) == ["agents", "rag"]
    assert select_topics(PROFILE, "weekly", None, cov, area="robotics") == ["vla"]


def test_select_topics_unknown_area_raises():
    with pytest.raises(ValueError, match="nope"):
        select_topics(PROFILE, "weekly", None, {}, area="nope")


def test_area_focus_still_caps_and_orders_by_coverage():
    profile = big_profile(MAX_FOCUS_TOPICS + 4)
    profile["areas"][0]["name"] = "big"
    covered = [idea(f"idea {i}", profile_topic="t00") for i in range(2)]
    cov = coverage_from(covered, list(topic_levels(profile)))
    picked = select_topics(profile, "weekly", None, cov, area="big")
    assert len(picked) == MAX_FOCUS_TOPICS and "t00" not in picked


def test_profile_changed_with_area_only_returns_changed_topics_inside_the_area():
    old = {"areas": [{"name": "x", "topics": [{"key": "vla", "level": "learning"},
                                              {"key": "rag", "level": "know"},
                                              {"key": "agents", "level": "know"}]}]}
    # agents changed (know -> curious) and lives in 'llm'; vla did not change
    assert select_topics(PROFILE, "profile_changed", old, {}, area="llm") == ["agents"]
    assert select_topics(PROFILE, "profile_changed", old, {}, area="robotics") == []


def test_pick_area_chooses_the_least_covered_area():
    keys = list(topic_levels(PROFILE))
    # tie on count (1 each): the area proposed for longest ago wins
    tied = [idea("a one", profile_topic="vla", created_at="2026-10-09T00:00:00+00:00"),
            idea("b two", profile_topic="rag", created_at="2026-10-01T00:00:00+00:00")]
    assert pick_area(PROFILE, coverage_from(tied, keys)) == "llm"
    # fewest ideas wins: llm has 2, robotics has 0
    uneven = [idea("c", profile_topic="rag"), idea("d", profile_topic="agents")]
    assert pick_area(PROFILE, coverage_from(uneven, keys)) == "robotics"


def test_briefing_with_area_shows_only_that_area_and_says_so():
    text = build_briefing(PROFILE, ["vla"], [], [], coverage_from([], list(topic_levels(PROFILE))),
                          ScoutConfig(), "2026-10-04", area="robotics")
    assert "FOCUS AREA: robotics" in text and "vla (learning)" in text
    assert "rag (know)" not in text and "agents (curious)" not in text
    assert "what is a transformer" in text   # the avoid list still applies


def test_briefing_without_area_has_no_focus_section():
    assert "FOCUS AREA" not in brief()


# ---- explore mode, suggestions, tightened prompt -----------------------------------------------

def names(mode):
    return {s["function"]["name"] for s in schemas_for(mode)}


def test_explore_mode_offers_only_search_suggest_and_finish():
    assert names("explore") == {"search_web", "suggest_topic", "finish"}


def test_hold_only_still_offers_suggestions_and_the_reading_list():
    assert {"suggest_topic", "hold_trend"} <= names("hold_only") and "propose_idea" not in names("hold_only")


def test_normal_modes_offer_every_tool():
    assert names("weekly") == names("profile_changed") == {s["function"]["name"] for s in TOOL_SCHEMAS}


def test_suggest_topic_schema_requires_name_area_and_why():
    schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "suggest_topic")
    assert set(schema["function"]["parameters"]["required"]) == {"name", "area", "why"}


def test_explore_briefing_lists_the_profile_prior_suggestions_and_limits():
    cfg = ScoutConfig(mode="explore", max_suggestions=3, max_searches=6)
    sugs = [{"status": "dismissed", "name": "Quantum robotics", "area": "robotics"}]
    text = build_explore_briefing(PROFILE, sugs, cfg, "2026-10-04")
    for needle in ("explore", "vla (learning)", "rag (know)", "[dismissed] Quantum robotics",
                   "3 suggestions", "6 searches", "across all areas"):
        assert needle in text


def test_explore_briefing_can_focus_on_one_area():
    text = build_explore_briefing(PROFILE, [], ScoutConfig(mode="explore"), "2026-10-04", area="llm")
    assert "'llm' area" in text and "ALREADY SUGGESTED" not in text


def test_system_prompt_sets_the_title_cap_and_bans_generic_titles():
    assert f"at most {MAX_TOPIC_CHARS} characters" in SYSTEM_PROMPT
    assert "suggest_topic" in SYSTEM_PROMPT and "overview" in SYSTEM_PROMPT


def test_explore_prompt_says_it_does_not_propose_posts():
    assert "EXPLORE" in EXPLORE_SYSTEM_PROMPT and "suggest_topic" in EXPLORE_SYSTEM_PROMPT


# ---- focusing a run on ONE sub-topic -------------------------------------------------------------

def test_select_topics_with_a_topic_returns_exactly_that_topic():
    assert select_topics(PROFILE, "weekly", None, {}, topic="agents") == ["agents"]
    assert select_topics(PROFILE, "weekly", None, {}, area="llm", topic="rag") == ["rag"]


@pytest.mark.parametrize("kwargs,message", [
    (dict(topic="nope"), "unknown sub-topic"),
    (dict(area="robotics", topic="rag"), "not in area"),
    (dict(area="nope", topic="rag"), "unknown area"),
])
def test_select_topics_rejects_bad_topic_requests(kwargs, message):
    with pytest.raises(ValueError, match=message):
        select_topics(PROFILE, "weekly", None, {}, **kwargs)


def test_profile_changed_with_a_topic_only_returns_it_if_it_changed():
    old = {"areas": [{"name": "x", "topics": [{"key": "vla", "level": "learning"},
                                              {"key": "rag", "level": "know"},
                                              {"key": "agents", "level": "know"}]}]}
    assert select_topics(PROFILE, "profile_changed", old, {}, topic="agents") == ["agents"]   # know -> curious
    assert select_topics(PROFILE, "profile_changed", old, {}, topic="vla") == []              # unchanged


def test_briefing_for_a_sub_topic_names_it_and_forbids_wandering():
    text = build_briefing(PROFILE, ["agents"], [], [], coverage_from([], list(topic_levels(PROFILE))),
                          ScoutConfig(), "2026-10-04", area="llm", topic="agents")
    assert "FOCUS SUB-TOPIC: agents (level: curious, area: llm)" in text
    assert "ONE sub-topic" in text and "FOCUS AREA" not in text


def test_explore_briefing_can_focus_on_one_sub_topic():
    text = build_explore_briefing(PROFILE, [], ScoutConfig(mode="explore"), "2026-10-04", area="llm", topic="agents")
    assert "around 'agents'" in text


# ---- experiments ----------------------------------------------------------------------------------------

def test_the_default_mix_adds_one_experiment_and_keeps_the_total_at_three():
    line = target_mix_line({"mix": {"trending": 1, "refresher_or_deep_dive": 2}}, 3)
    assert "1 trending, 1 experiment, 1 refresher/deep-dive" in line and "at most 3" in line


def test_an_explicit_experiment_count_is_used_as_given_and_zero_removes_it():
    assert "2 experiment" in target_mix_line({"mix": {"trending": 0, "experiment": 2, "refresher_or_deep_dive": 1}}, 3)
    assert "experiment" not in target_mix_line({"mix": {"trending": 1, "experiment": 0, "refresher_or_deep_dive": 2}}, 3)


def test_an_empty_mix_still_gives_a_sensible_line():
    assert "1 trending, 1 experiment, 1 refresher/deep-dive" in target_mix_line({}, 3)


def test_resources_text_defaults_to_a_laptop_and_mentions_a_sometimes_gpu():
    assert "laptop CPU" in resources_text({}) and "no cloud spend" in resources_text({})
    both = resources_text({"resources": ["cpu", "small-gpu"]})
    assert "laptop CPU" in both and "only sometimes available" in both


def test_briefing_states_the_resources_and_lists_idea_ids_so_experiments_can_build_on_them():
    i = idea("KV cache", "approved")
    text = brief([i])
    assert f"(id: {i['id']})" in text and "RESOURCES for experiments: a laptop CPU" in text


def test_briefing_marks_existing_experiments():
    e = idea("Measure KV caching on CPU", "approved", kind="experiment",
             experiment={"question": "q", "setup": "s", "measure": "m", "effort": "hours", "needs": ["cpu"]})
    assert ", experiment)" in brief([e])


def test_the_prompt_teaches_what_a_good_small_experiment_is():
    for needle in ("kind 'experiment'", "at most a weekend", "builds_on", "No cloud spend", "hash lookup", "returns its id"):
        assert needle in SYSTEM_PROMPT


def test_the_experiment_schema_requires_the_whole_plan_and_limits_effort_and_needs():
    props = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "propose_idea")["function"]["parameters"]["properties"]
    plan = props["experiment"]
    assert set(plan["required"]) == {"question", "setup", "measure", "effort", "needs"}
    assert plan["properties"]["effort"]["enum"] == ["hours", "weekend"]
    assert plan["properties"]["needs"]["items"]["enum"] == ["cpu", "small-gpu"]
    assert "experiment" in props["kind"]["enum"] and "builds_on" in props


# ---- only one kind ----------------------------------------------------------------------------------------

def kind_enum(schemas):
    schema = next(s for s in schemas if s["function"]["name"] == "propose_idea")
    return schema["function"]["parameters"]["properties"]["kind"]["enum"]


def test_only_kind_limits_the_kind_the_model_can_even_choose():
    assert kind_enum(schemas_for("weekly", "experiment")) == ["experiment"]
    assert set(kind_enum(schemas_for("weekly"))) == {"trending", "refresher", "deep-dive", "experiment"}


def test_limiting_the_kind_never_changes_the_shared_schema():
    schemas_for("weekly", "experiment")
    assert set(kind_enum(TOOL_SCHEMAS)) == {"trending", "refresher", "deep-dive", "experiment"}


def test_only_kind_does_not_bring_propose_idea_back_in_hold_only_mode():
    names = {s["function"]["name"] for s in schemas_for("hold_only", "experiment")}
    assert "propose_idea" not in names and "hold_trend" in names


def test_briefing_says_to_propose_only_that_kind_instead_of_the_normal_mix():
    cfg = ScoutConfig(max_proposals=3)
    text = build_briefing(PROFILE, ["agents"], [], [], coverage_from([], list(topic_levels(PROFILE))),
                          cfg, "2026-10-04", only_kind="experiment")
    assert "propose ONLY ideas of kind 'experiment'" in text and "TARGET MIX" not in text
    assert "TARGET MIX" in brief()


import json
from datetime import datetime, timezone

import pytest

from agents.scout_tools import (
    ScoutConfig, ScoutTools, throttle_mode, trending_evidence_ok,
)
from tools.ideas import new_idea, topic_key

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


class FakeStore:
    """Same methods as the real store, all in memory."""

    def __init__(self, ideas=None, trends=None, suggestions=None):
        self.ideas = list(ideas or [])
        self.trends = list(trends or [])
        self.suggestions = list(suggestions or [])
        self.sources = []

    def get_idea(self, idea_id):
        return next((i for i in self.ideas if i["id"] == idea_id), None)

    def add_source(self, source):
        self.sources.append(source)
        return True

    def find_suggestion_by_key(self, key):
        return next((x for x in self.suggestions if x["topic_key"] == key), None)

    def add_suggestion(self, suggestion):
        self.suggestions.append(suggestion)

    def list_ideas(self, status=None):
        return [i for i in self.ideas if status is None or i["status"] == status]

    def add_idea(self, idea):
        self.ideas.append(idea)

    def find_by_topic_key(self, key):
        return next((i for i in self.ideas if i["topic_key"] == key), None)

    def find_trend_by_key(self, key):
        return next((t for t in self.trends if t["topic_key"] == key), None)

    def add_trend(self, item):
        self.trends.append(item)


def existing(topic, status="pending", created_at="2026-10-01T00:00:00+00:00"):
    idea = new_idea(topic, "broad", "deep-dive", "agents", "r")
    idea["status"], idea["created_at"] = status, created_at
    return idea


def make(store=None, search=None, **cfg):
    cfg.setdefault("profile_topics", {"agents", "vla", "caching"})
    return ScoutTools(store or FakeStore(), search or (lambda *a: []), ScoutConfig(**cfg), now=NOW)


def propose(tools, topic="Agent memory patterns", **kw):
    args = dict(topic=topic, angle="niche", kind="deep-dive", profile_topic="agents", rationale="r")
    args.update(kw)
    return tools.call("propose_idea", args)


GOOD_EVIDENCE = [
    {"url": "https://a.com/x", "published_date": "Wed, 07 Oct 2026 10:00:00 GMT"},
    {"url": "https://www.b.org/y", "published_date": "2026-10-02"},
]


# ---- propose_idea ------------------------------------------------------------

def test_propose_stores_a_pending_idea_with_run_info():
    store = FakeStore()
    tools = make(store, run_id="run1", profile_version=3)
    assert propose(tools).startswith("OK")
    idea = store.ideas[0]
    assert (idea["status"], idea["run_id"], idea["profile_version"]) == ("pending", "run1", 3)
    assert tools.proposed == [idea["id"]]


def test_proposal_limit_per_run():
    tools = make(max_proposals=2)
    assert propose(tools, "Topic one").startswith("OK")
    assert propose(tools, "Topic two").startswith("OK")
    assert "limit" in propose(tools, "Topic three")


def test_the_backlog_cap_counts_only_ideas_still_waiting_for_a_decision():
    store = FakeStore([existing("A one", "pending"), existing("B two", "pending"),
                       existing("C three", "approved"), existing("D four", "rejected"),
                       existing("E five", "researched"), existing("F six", "drafted"), existing("G seven", "published")])
    assert "full" in propose(make(store, backlog_cap=2))               # 2 pending = full
    assert propose(make(store, backlog_cap=3)).startswith("OK")        # approved/rejected/drafted/... never count


def test_deciding_on_an_idea_frees_a_slot_for_a_new_one():
    a, b = existing("A one", "pending"), existing("B two", "pending")
    store = FakeStore([a, b])
    assert "full" in propose(make(store, backlog_cap=2))
    a["status"] = "approved"                                           # you approve one...
    assert propose(make(store, backlog_cap=2), "Fresh topic").startswith("OK")
    b["status"] = "rejected"                                           # ...and reject another
    store2 = FakeStore([a, b])
    assert propose(make(store2, backlog_cap=1), "Another fresh topic").startswith("OK")


def test_hold_only_mode_blocks_proposals():
    assert "switched off" in propose(make(mode="hold_only"))


def test_unknown_profile_topic_rejected():
    assert "profile_topic" in propose(make(), profile_topic="cooking")


def test_avoid_list_blocks_basics_but_not_advanced_angles():
    tools = make(avoid=["what is a transformer"])
    assert "avoid" in propose(tools, "Transformers explained")
    assert propose(tools, "Transformer attention variants").startswith("OK")


def test_duplicate_of_rejected_idea_and_of_reading_list_item():
    store = FakeStore([existing("KV cache", "rejected")],
                      [{"id": "trend_1", "topic_key": topic_key("Speculative decoding")}])
    tools = make(store)
    assert "duplicate of idea" in propose(tools, "How does KV caching work?")
    assert "reading-list item trend_1" in propose(tools, "Speculative decoding")


def test_bad_enum_value_comes_back_as_error_text():
    assert propose(make(), angle="huge").startswith("ERROR")


# ---- trending evidence -------------------------------------------------------

def test_trending_with_two_recent_distinct_sites_is_accepted():
    store = FakeStore()
    out = propose(make(store), kind="trending", evidence=GOOD_EVIDENCE)
    assert out.startswith("OK") and store.ideas[0]["source"] == "trending"


@pytest.mark.parametrize("evidence", [
    None,
    GOOD_EVIDENCE[:1],                                                          # only one site
    [GOOD_EVIDENCE[0], {"url": "https://a.com/z", "published_date": "2026-10-05"}],  # same domain
    [{"url": "https://a.com", "published_date": "Mon, 01 Jun 2026 00:00:00 GMT"},
     {"url": "https://b.com", "published_date": "Mon, 01 Jun 2026 00:00:00 GMT"}],   # too old
    [{"url": "https://a.com", "published_date": ""},
     {"url": "https://b.com", "published_date": ""}],                           # no dates
])
def test_trending_without_enough_evidence_is_rejected(evidence):
    assert "evidence" in propose(make(), kind="trending", evidence=evidence)


def test_non_trending_kinds_need_no_evidence():
    assert propose(make(), kind="refresher").startswith("OK")


def test_future_dated_evidence_does_not_count():
    future = [{"url": "https://a.com", "published_date": "2026-12-01"},
              {"url": "https://b.com", "published_date": "2026-12-02"}]
    assert not trending_evidence_ok(future, NOW, 30)


# ---- hold_trend ---------------------------------------------------------------

def test_hold_trend_stores_item_and_blocks_duplicates_and_limit():
    store = FakeStore()
    tools = make(store, max_holds=2)
    assert tools.call("hold_trend", {"topic": "Flux 3 release", "why": "w"}).startswith("OK")
    assert "duplicate" in tools.call("hold_trend", {"topic": "flux 3 releases", "why": "w"})
    assert tools.call("hold_trend", {"topic": "Another", "why": "w"}).startswith("OK")
    assert "limit" in tools.call("hold_trend", {"topic": "Third", "why": "w"})
    assert len(store.trends) == 2


# ---- search_web / read_backlog / finish ----------------------------------------

def test_search_passes_options_trims_content_and_enforces_limit():
    calls = []

    def fake_search(query, max_results, news, time_range):
        calls.append((query, news, time_range))
        return [{"title": "T", "url": "http://u", "content": "x" * 1000, "published_date": "d"}]

    tools = make(search=fake_search, max_searches=2)
    out = json.loads(tools.call("search_web", {"query": "q", "recency": "week", "news": True}))
    assert len(out[0]["content"]) == 300
    tools.call("search_web", {"query": "q2"})
    assert calls == [("q", True, "week"), ("q2", False, None)]
    assert "limit" in tools.call("search_web", {"query": "q3"})


def test_search_rejects_bad_recency():
    assert "recency" in make().call("search_web", {"query": "q", "recency": "decade"})


def test_read_backlog_filters_by_status_and_profile_topic():
    a, b = existing("A one", "pending"), existing("B two", "approved")
    b["profile_topic"] = "vla"
    tools = make(FakeStore([a, b]))
    assert [r["topic"] for r in json.loads(tools.call("read_backlog", {"status": "approved"}))] == ["B two"]
    assert [r["topic"] for r in json.loads(tools.call("read_backlog", {"profile_topic": "agents"}))] == ["A one"]


def test_finish_sets_flag_and_summary():
    tools = make()
    tools.call("finish", {"summary": "done"})
    assert tools.finished and tools.summary == "done"


# ---- call(): bad input never raises ---------------------------------------------

def test_unknown_tool_non_dict_args_and_missing_args_return_errors():
    tools = make()
    assert "unknown tool" in tools.call("make_coffee", {})
    assert "JSON object" in tools.call("propose_idea", ["not", "a", "dict"])
    assert "bad arguments" in tools.call("propose_idea", {"topic": "only a topic"})
    assert "bad arguments" in tools.call("propose_idea", {"nonsense": 1})


def test_tool_exception_becomes_error_text():
    def boom(*a):
        raise RuntimeError("tavily down")
    assert "tavily down" in make(search=boom).call("search_web", {"query": "q"})


# ---- throttle_mode ----------------------------------------------------------------

def test_throttle_normal_when_below_cap():
    assert throttle_mode([existing("A one")], cap=2, last_run_started_at=None) == "normal"


def test_throttle_skip_when_full_and_pending_is_fresh():
    ideas = [existing("A one", created_at="2026-10-05T00:00:00+00:00"),
             existing("B two", created_at="2026-10-05T00:00:00+00:00")]
    assert throttle_mode(ideas, cap=2, last_run_started_at="2026-10-04T00:00:00+00:00") == "skip"


def test_throttle_hold_only_when_full_and_pending_older_than_last_run():
    ideas = [existing("A one", created_at="2026-10-01T00:00:00+00:00"),
             existing("B two", created_at="2026-10-05T00:00:00+00:00")]
    assert throttle_mode(ideas, cap=2, last_run_started_at="2026-10-04T00:00:00+00:00") == "hold_only"


def test_throttle_first_ever_run_with_full_backlog_skips():
    ideas = [existing("A one"), existing("B two")]
    assert throttle_mode(ideas, cap=2, last_run_started_at=None) == "skip"


# ---- topic length, area on ideas ------------------------------------------------------

def test_over_long_topic_comes_back_as_an_error_the_model_can_read():
    out = propose(make(), topic="A" * 130)
    assert out.startswith("ERROR") and "characters" in out


def test_proposed_idea_records_the_area_of_its_profile_topic():
    store = FakeStore()
    tools = make(store, topic_areas={"agents": "ai-engineering"})
    assert propose(tools).startswith("OK")
    assert store.ideas[0]["area"] == "ai-engineering"


def test_explore_mode_blocks_proposals():
    assert "explore" in propose(make(mode="explore"))


# ---- suggest_topic ----------------------------------------------------------------------

def suggest(tools, name="World models", area="robotics", **kw):
    args = dict(name=name, area=area, why="a concrete reason")
    args.update(kw)
    return tools.call("suggest_topic", args)


def sug_tools(store=None, **cfg):
    cfg.setdefault("area_names", {"robotics", "agents-area"})
    cfg.setdefault("known_topics", {topic_key("vla"), topic_key("robotics")})
    return make(store, **cfg)


def test_suggest_subtopic_of_an_existing_area_is_stored():
    store = FakeStore()
    assert suggest(sug_tools(store)).startswith("OK")
    assert (store.suggestions[0]["kind"], store.suggestions[0]["area"]) == ("subtopic", "robotics")
    assert store.suggestions[0]["status"] == "pending"


def test_suggest_with_an_unknown_area_name_proposes_a_new_area():
    store = FakeStore()
    suggest(sug_tools(store), area="Quantum Computing")
    assert (store.suggestions[0]["kind"], store.suggestions[0]["area"]) == ("new_area", "quantum-computing")


def test_suggesting_something_already_in_the_profile_is_rejected():
    assert "already in the profile" in suggest(sug_tools(), name="VLA")
    assert "already in the profile" in suggest(sug_tools(), name="Robotics")


@pytest.mark.parametrize("status", ["pending", "accepted", "dismissed"])
def test_previously_suggested_topics_are_never_suggested_again(status):
    store = FakeStore(suggestions=[{"topic_key": topic_key("World models"), "status": status}])
    assert f"status {status}" in suggest(sug_tools(store), name="how do world models work")


def test_suggestion_limit_per_run():
    tools = sug_tools(max_suggestions=2)
    assert suggest(tools, "Topic alpha").startswith("OK")
    assert suggest(tools, "Topic beta").startswith("OK")
    assert "limit" in suggest(tools, "Topic gamma")


# ---- citation URLs are registered as sources; brief is stored ------------------------------------

def test_a_proposed_ideas_evidence_urls_become_sources_and_junk_urls_are_dropped():
    store = FakeStore()
    evidence = GOOD_EVIDENCE + [{"url": "javascript:alert(1)", "title": "bad"}]
    assert propose(make(store), kind="trending", evidence=evidence).startswith("OK")
    assert sorted(x["url"] for x in store.sources) == ["https://a.com/x", "https://www.b.org/y"]
    assert sorted(x["domain"] for x in store.sources) == ["a.com", "b.org"]   # display domain drops www
    assert all(x["idea_id"] == store.ideas[0]["id"] and x["found_by"] == "scout" for x in store.sources)


def test_brief_is_stored_and_an_over_long_brief_is_an_error():
    store = FakeStore()
    assert propose(make(store), brief="  What the post would walk through.  ").startswith("OK")
    assert store.ideas[0]["brief"] == "What the post would walk through."
    assert "brief" in propose(make(), topic="Another topic", brief="x" * 700)


# ---- experiments -------------------------------------------------------------------------------------------

PLAN = {"question": "How much does KV caching speed up a 125M model?", "setup": "Run 20 prompts with and without the cache.",
        "measure": "Tokens per second.", "effort": "hours", "needs": ["cpu"]}


def experiment(tools, topic="Measure KV caching on CPU", **kw):
    args = dict(topic=topic, angle="niche", kind="experiment", profile_topic="agents",
                rationale="r", experiment=PLAN)
    args.update(kw)
    return tools.call("propose_idea", args)


def test_an_experiment_with_a_complete_plan_is_stored_with_its_plan():
    store = FakeStore()
    assert experiment(make(store)).startswith("OK")
    stored = store.ideas[0]
    assert stored["kind"] == "experiment" and stored["experiment"]["needs"] == ["cpu"] and stored["source"] == "scout"


@pytest.mark.parametrize("plan,message", [
    (None, "needs an experiment plan"),
    ({**PLAN, "effort": "week"}, "nothing bigger than a weekend"),
    ({**PLAN, "needs": ["small-gpu"]}, "only has"),                      # the default config has a laptop only
    ({k: v for k, v in PLAN.items() if k != "measure"}, "experiment.measure is required"),
])
def test_a_bad_experiment_plan_comes_back_as_an_error_the_model_can_fix(plan, message):
    store = FakeStore()
    out = experiment(make(store, allowed_needs=("cpu",)), experiment=plan)      # a laptop-only owner
    assert out.startswith("ERROR") and message in out and store.ideas == []


def test_a_small_gpu_experiment_is_allowed_once_the_profile_says_the_owner_has_one():
    out = experiment(make(allowed_needs=("cpu", "small-gpu")), experiment={**PLAN, "needs": ["small-gpu"]})
    assert out.startswith("OK")


def test_a_plan_on_a_non_experiment_idea_is_refused():
    assert "only ideas of kind" in propose(make(), experiment=PLAN)


def test_an_experiment_can_build_on_an_earlier_idea():
    parent = existing("Explaining KV caching", "approved")
    store = FakeStore([parent])
    assert experiment(make(store), builds_on=parent["id"]).startswith("OK")
    assert store.ideas[-1]["builds_on"] == parent["id"]


@pytest.mark.parametrize("make_parent", [
    lambda: None,                                              # no such idea
    lambda: existing("Rejected concept", "rejected"),          # rejected ideas are not a base to build on
])
def test_building_on_a_missing_or_rejected_idea_is_an_error(make_parent):
    parent = make_parent()
    store = FakeStore([parent] if parent else [])
    out = experiment(make(store), builds_on=parent["id"] if parent else "idea_nope")
    assert out.startswith("ERROR") and "builds_on" in out and len(store.ideas) == (1 if parent else 0)


def test_experiments_do_not_need_evidence_but_trending_ideas_still_do():
    assert experiment(make()).startswith("OK")                       # no evidence given
    assert "evidence" in propose(make(), kind="trending", evidence=None)


def test_approved_and_rejected_ideas_never_fill_the_throttle():
    ideas = [existing("A one", "approved"), existing("B two", "rejected"), existing("C three", "drafted"),
             existing("D four", "pending")]
    assert throttle_mode(ideas, cap=2, last_run_started_at=None) == "normal"      # only 1 pending


def test_only_kind_makes_the_run_refuse_every_other_kind_but_accept_the_one_asked_for():
    store = FakeStore()
    tools = make(store, only_kind="experiment")
    out = propose(tools)                                                  # a deep-dive
    assert out.startswith("ERROR") and "only accepts 'experiment'" in out and store.ideas == []
    assert experiment(tools).startswith("OK") and store.ideas[0]["kind"] == "experiment"


def test_without_only_kind_every_kind_is_accepted():
    assert propose(make()).startswith("OK") and experiment(make()).startswith("OK")


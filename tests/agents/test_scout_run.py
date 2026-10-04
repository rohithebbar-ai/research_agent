"""run_scout end to end with a scripted fake LLM, fake search and in-memory persistence."""
import copy

import pytest

from agents import scout
from agents.shared.llm_client import ChatResult, ToolCall
from tests.fakes import FakeStore
from tools.ideas import new_idea

PROFILE = {
    "version": 2,
    "areas": [
        {"name": "robotics", "topics": [{"key": "vla", "level": "learning"}]},
        {"name": "llm", "topics": [{"key": "rag", "level": "know"}, {"key": "agents", "level": "curious"}]},
    ],
    "avoid": ["what is a transformer"],
    "mix": {"trending": 1, "refresher_or_deep_dive": 2},
}
OLD_PROFILE = {"version": 1, "areas": [{"name": "llm", "topics": [{"key": "rag", "level": "know"}]}]}


def call(tool, **args):
    tc = ToolCall(id=f"c_{tool}", name=tool, arguments=args)
    return ChatResult(content=None, tool_calls=[tc], message={"role": "assistant", "content": None})


def text(content):
    return ChatResult(content=content, tool_calls=[], message={"role": "assistant", "content": content})


class ScriptedChat:
    """Returns the scripted replies in order and remembers what it was shown."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages, schemas, **kwargs):
        self.calls.append({"messages": copy.deepcopy(messages), "schemas": schemas, "kwargs": kwargs})
        if not self.replies:
            raise AssertionError("the loop called the LLM more often than the test scripted")
        return self.replies.pop(0)


@pytest.fixture
def env(monkeypatch):
    """Patch every outside dependency of run_scout; returns a bag the tests can inspect."""
    class Env:
        saved = []                # a deep copy of the record at every save_run call
        last_run_calls = []
        last_run_result = None
        baseline_result = None
        snapshots = {1: OLD_PROFILE}
        profile = PROFILE
        busy = None
    e = Env()
    e.saved, e.last_run_calls = [], []

    def fake_last_run(agent, modes=None, baseline_only=False, exclude_id=None):
        e.last_run_calls.append({"modes": modes, "baseline_only": baseline_only, "exclude_id": exclude_id})
        return e.baseline_result if baseline_only else e.last_run_result

    monkeypatch.setattr(scout, "load_profile", lambda: e.profile)
    monkeypatch.setattr(scout, "save_run", lambda record: e.saved.append(copy.deepcopy(record)))
    monkeypatch.setattr(scout, "last_run", fake_last_run)
    monkeypatch.setattr(scout, "active_run", lambda agent, max_age: e.busy)
    monkeypatch.setattr(scout, "get_snapshot", lambda v: e.snapshots.get(v))
    monkeypatch.setattr(scout, "_search", lambda q, n, news, tr: [
        {"title": "T", "url": "https://a.com/x", "content": "c", "published_date": ""}])
    return e


GOOD_IDEA = dict(topic="Why agent traces hide retries", angle="niche", kind="deep-dive",
                 profile_topic="agents", rationale="Retries vanish from most trace UIs.")


def run(env, chat, store=None, **kwargs):
    kwargs.setdefault("area", "llm")
    return scout.run_scout(store=store or FakeStore(), chat=chat, **kwargs), kwargs


# ---- the happy path and the trace -------------------------------------------------------

def test_happy_path_saves_ideas_a_step_trace_and_a_final_record(env):
    store = FakeStore()
    chat = ScriptedChat(call("search_web", query="agent tracing"),
                        call("propose_idea", **GOOD_IDEA),
                        call("finish", summary="done"))
    record, _ = run(env, chat, store)

    assert record["status"] == "done" and record["stopped_reason"] == "finished"
    assert record["iterations"] == 3 and record["summary"] == "done"
    assert record["queries"] == ["agent tracing"]
    assert len(record["proposed_ids"]) == 1 and len(store.ideas) == 1
    assert [s["tool"] for s in record["steps"]] == ["search_web", "propose_idea", "finish"]
    assert {s["type"] for s in record["steps"]} == {"tool"}
    assert record["steps"][1]["result"].startswith("OK")
    assert record["ended_at"] and record["area"] == "llm"


def test_the_record_is_saved_as_running_first_and_updated_as_it_goes(env):
    chat = ScriptedChat(call("propose_idea", **GOOD_IDEA), call("finish", summary="s"))
    run(env, chat)
    assert env.saved[0]["status"] == "running" and env.saved[0]["steps"] == []
    mid = [r for r in env.saved if r["status"] == "running" and r["steps"]]
    assert mid, "progress should be saved after each iteration"
    assert env.saved[-1]["status"] == "done"
    assert len({r["id"] for r in env.saved}) == 1   # always the same document


def test_a_running_record_exists_before_any_slow_work_starts(env, monkeypatch):
    seen = {}

    def load_profile_and_look():
        seen["saved_so_far"] = [(r["status"], r["steps"]) for r in env.saved]
        return PROFILE

    monkeypatch.setattr(scout, "load_profile", load_profile_and_look)
    run(env, ScriptedChat(call("finish")))
    assert seen["saved_so_far"] == [("running", [])]


def test_long_tool_results_are_truncated_in_the_trace_but_not_for_the_model(env):
    store = FakeStore([{**new_idea(f"a fairly long idea topic number {i}", "broad", "deep-dive", "agents", "r"),
                        "status": "rejected"} for i in range(30)])   # rejected: not counted against the cap
    chat = ScriptedChat(call("read_backlog"), call("finish"))
    record, _ = run(env, chat, store)
    traced = record["steps"][0]["result"]
    full = chat.calls[1]["messages"][-1]["content"]          # what the model was actually sent back
    assert len(traced) == scout.STEP_RESULT_CHARS and len(full) > scout.STEP_RESULT_CHARS


def test_the_model_is_offered_the_right_tools_for_the_mode(env):
    chat = ScriptedChat(call("finish"))
    run(env, chat)
    assert "propose_idea" in [s["function"]["name"] for s in chat.calls[0]["schemas"]]
    assert chat.calls[0]["messages"][0]["role"] == "system"


# ---- nudge and stop reasons ----------------------------------------------------------------

def test_a_text_only_reply_gets_one_nudge_and_the_run_recovers(env):
    chat = ScriptedChat(text("Here are some thoughts..."),
                        call("propose_idea", **GOOD_IDEA), call("finish", summary="ok"))
    record, _ = run(env, chat)
    assert record["stopped_reason"] == "finished"
    kinds = [s["type"] for s in record["steps"]]
    assert kinds[:2] == ["text", "nudge"]
    assert chat.calls[1]["messages"][-1] == {"role": "user", "content": scout.NUDGE}


def test_two_text_only_replies_end_the_run_and_the_text_is_kept(env):
    chat = ScriptedChat(text("first prose"), text("second prose"))
    record, _ = run(env, chat)
    assert record["stopped_reason"] == "no_tool_call" and record["status"] == "done"
    assert [s["content"] for s in record["steps"] if s["type"] == "text"] == ["first prose", "second prose"]


def test_iteration_cap(env):
    chat = ScriptedChat(*[call("read_backlog") for _ in range(3)])
    record, _ = run(env, chat, max_iterations=3)
    assert record["stopped_reason"] == "max_iterations" and record["iterations"] == 3


def test_time_budget(env):
    chat = ScriptedChat(call("read_backlog"))
    record, _ = run(env, chat, time_budget=-1)   # already past the deadline before the first call
    assert record["stopped_reason"] == "time_budget" and chat.calls == []


def test_llm_failure_is_recorded_as_an_error_run_without_raising(env):
    def broken(messages, schemas, **kw):
        raise TimeoutError("request timed out")
    record, _ = run(env, broken)
    assert record["stopped_reason"] == "llm_error" and record["status"] == "error"
    assert "request timed out" in record["error"] and record["steps"][-1]["type"] == "error"


def test_bad_tool_calls_are_errors_in_the_trace_not_crashes(env):
    chat = ScriptedChat(call("make_coffee"), call("propose_idea", topic="only a topic"), call("finish"))
    record, _ = run(env, chat)
    assert record["stopped_reason"] == "finished"
    assert all(s["result"].startswith("ERROR") for s in record["steps"][:2])


def test_a_crash_inside_the_run_leaves_an_error_record_and_still_raises(env):
    env.profile = None   # run_scout needs a profile
    with pytest.raises(RuntimeError, match="No profile"):
        run(env, ScriptedChat())
    assert env.saved[-1]["status"] == "error" and "No profile" in env.saved[-1]["error"]


def test_unknown_area_is_an_error(env):
    with pytest.raises(ValueError, match="unknown area"):
        run(env, ScriptedChat(), area="cooking")


def test_a_run_already_in_progress_blocks_a_new_one(env):
    env.busy = {"id": "run_other"}
    with pytest.raises(scout.RunInProgress, match="run_other"):
        run(env, ScriptedChat())
    assert env.saved == []   # nothing was written


# ---- throttle ------------------------------------------------------------------------------------

def full_backlog(n=8):
    return FakeStore([new_idea(f"topic number {i}", "broad", "deep-dive", "agents", "r") for i in range(n)])  # all pending


def test_a_full_backlog_skips_the_run_with_zero_llm_calls(env):
    chat = ScriptedChat()
    record, _ = run(env, chat, full_backlog())
    assert record["stopped_reason"] == "skipped_full" and record["status"] == "done"
    assert chat.calls == []


def test_the_throttle_clock_ignores_explore_runs_and_the_current_run(env):
    run(env, ScriptedChat(call("finish")))
    first = env.last_run_calls[0]
    assert first["modes"] == scout.PROPOSING_MODES and first["exclude_id"] == env.saved[0]["id"]


def test_explore_runs_are_never_throttled_and_never_ask_for_run_history(env):
    chat = ScriptedChat(call("suggest_topic", name="World models", area="robotics", why="a reason"),
                        call("finish", summary="explored"))
    store = full_backlog()
    record, _ = run(env, chat, store, mode="explore", area=None)
    assert record["stopped_reason"] == "finished" and len(record["suggested_ids"]) == 1
    assert env.last_run_calls == []
    assert [s["function"]["name"] for s in chat.calls[0]["schemas"]] == ["search_web", "suggest_topic", "finish"]
    assert store.ideas[0]["status"] == "pending" and len(store.ideas) == 8   # no ideas created


# ---- profile baseline --------------------------------------------------------------------------

def finished_chat():
    return ScriptedChat(call("finish", summary="done"))


def test_a_clean_full_profile_changed_run_advances_the_baseline(env):
    record, _ = run(env, finished_chat(), mode="profile_changed", area=None)
    assert record["baseline_version"] == 2
    assert record["topics_scouted"] == ["agents", "vla"]   # new since version 1; rag is unchanged


@pytest.mark.parametrize("kwargs", [
    dict(mode="profile_changed", area="robotics"),   # only one area handled
    dict(mode="weekly", area="llm"),                  # weekly never handles profile changes
    dict(mode="explore", area=None),                  # explore never does either
])
def test_other_runs_do_not_move_the_baseline(env, kwargs):
    record, _ = run(env, finished_chat(), **kwargs)
    assert record["baseline_version"] is None


def test_a_profile_changed_run_that_does_not_finish_does_not_advance_the_baseline(env):
    record, _ = run(env, ScriptedChat(call("read_backlog"), call("read_backlog")),
                    mode="profile_changed", area=None, max_iterations=2)
    assert record["stopped_reason"] == "max_iterations" and record["baseline_version"] is None


def test_the_diff_uses_the_last_baseline_runs_snapshot(env):
    env.baseline_result = {"baseline_version": 1}
    env.snapshots = {1: PROFILE}   # nothing changed since the baseline
    record, _ = run(env, finished_chat(), mode="profile_changed", area=None)
    assert record["stopped_reason"] == "no_changes" and record["topics_scouted"] == []
    assert env.last_run_calls[-1]["baseline_only"] is True


def test_no_changes_does_not_call_the_llm(env):
    env.baseline_result = {"baseline_version": 2}
    env.snapshots = {2: PROFILE}
    chat = ScriptedChat()
    run(env, chat, mode="profile_changed", area=None)
    assert chat.calls == []


# ---- weekly picks an area ---------------------------------------------------------------------------

def test_weekly_without_an_area_picks_the_least_covered_one(env):
    ideas = [new_idea("covered topic one", "broad", "deep-dive", "agents", "r"),
             new_idea("covered topic two", "broad", "deep-dive", "rag", "r")]
    record, _ = run(env, finished_chat(), FakeStore(ideas), mode="weekly", area=None)
    assert record["area"] == "robotics"   # llm already has 2 ideas, robotics has none


# ---- one sub-topic ---------------------------------------------------------------------------------------

def test_a_sub_topic_run_fills_in_its_area_and_scouts_only_that_topic(env):
    chat = ScriptedChat(call("finish", summary="done"))
    record, _ = run(env, chat, mode="weekly", area=None, topic="agents")
    assert (record["area"], record["topic"], record["topics_scouted"]) == ("llm", "agents", ["agents"])
    assert "FOCUS SUB-TOPIC: agents" in chat.calls[0]["messages"][1]["content"]


def test_a_sub_topic_run_cannot_propose_for_any_other_topic(env):
    store = FakeStore()
    chat = ScriptedChat(call("propose_idea", **{**GOOD_IDEA, "profile_topic": "rag"}),   # same area, other topic
                        call("propose_idea", **GOOD_IDEA),                               # the focused topic
                        call("finish"))
    record, _ = run(env, chat, store, area=None, topic="agents")
    results = [s["result"] for s in record["steps"] if s.get("tool") == "propose_idea"]
    assert results[0].startswith("ERROR") and "not allowed in this run" in results[0] and "['agents']" in results[0]
    assert results[1].startswith("OK") and [i["profile_topic"] for i in store.ideas] == ["agents"]


def test_a_sub_topic_run_does_not_pick_an_area_at_random(env):
    record, _ = run(env, finished_chat(), mode="weekly", area=None, topic="vla")
    assert record["area"] == "robotics"   # derived from the topic, not from coverage


@pytest.mark.parametrize("kwargs,message", [
    (dict(topic="nope"), "unknown sub-topic"),
    (dict(area="robotics", topic="agents"), "not in area"),
])
def test_bad_sub_topic_requests_fail_cleanly_and_leave_an_error_record(env, kwargs, message):
    with pytest.raises(ValueError, match=message):
        run(env, ScriptedChat(), **kwargs)
    assert env.saved[-1]["status"] == "error"


def test_a_sub_topic_profile_changed_run_never_advances_the_baseline(env):
    record, _ = run(env, finished_chat(), mode="profile_changed", area=None, topic="agents")
    assert record["stopped_reason"] == "finished" and record["baseline_version"] is None


def test_explore_can_focus_on_a_sub_topic(env):
    chat = ScriptedChat(call("finish"))
    record, _ = run(env, chat, mode="explore", area=None, topic="agents")
    assert (record["area"], record["topics_scouted"]) == ("llm", ["agents"])
    assert "around 'agents'" in chat.calls[0]["messages"][1]["content"]


# ---- experiments -----------------------------------------------------------------------------------------------

EXPERIMENT_IDEA = dict(topic="Measure how much a KV cache speeds up a small model", angle="niche", kind="experiment",
                       profile_topic="agents", rationale="Seeing the speed-up teaches why caching matters.",
                       experiment={"question": "How much faster is generation with a KV cache?",
                                   "setup": "Run 20 prompts on a 125M model with and without the cache.",
                                   "measure": "Tokens per second for each.", "effort": "hours", "needs": ["cpu"]})


def test_a_run_can_propose_an_experiment_that_builds_on_the_concept_idea(env):
    concept = {**new_idea("Explaining KV caching in depth", "broad", "deep-dive", "agents", "r"), "status": "approved"}
    store = FakeStore([concept])
    chat = ScriptedChat(call("propose_idea", **EXPERIMENT_IDEA, builds_on=concept["id"]), call("finish", summary="ok"))
    record, _ = run(env, chat, store)
    exp = store.ideas[-1]
    assert exp["kind"] == "experiment" and exp["builds_on"] == concept["id"] and exp["experiment"]["effort"] == "hours"
    assert record["steps"][0]["result"].startswith("OK")
    assert concept["id"] in chat.calls[0]["messages"][1]["content"]       # the model was shown the id to build on


def test_a_run_rejects_an_experiment_that_needs_hardware_the_profile_does_not_list(env):
    chat = ScriptedChat(call("propose_idea", **{**EXPERIMENT_IDEA, "experiment": {**EXPERIMENT_IDEA["experiment"], "needs": ["small-gpu"]}}),
                        call("finish"))
    store = FakeStore()
    record, _ = run(env, chat, store)
    assert "only has" in record["steps"][0]["result"] and store.ideas == []
    assert "a laptop CPU" in chat.calls[0]["messages"][1]["content"]


def test_a_profile_with_a_small_gpu_lets_gpu_experiments_through(env):
    env.profile = {**PROFILE, "resources": ["cpu", "small-gpu"]}
    plan = {**EXPERIMENT_IDEA["experiment"], "needs": ["small-gpu"]}
    store = FakeStore()
    record, _ = run(env, ScriptedChat(call("propose_idea", **{**EXPERIMENT_IDEA, "experiment": plan}), call("finish")), store)
    assert len(store.ideas) == 1 and store.ideas[0]["experiment"]["needs"] == ["small-gpu"]


def test_approving_ideas_lets_the_next_run_go_ahead(env):
    store = full_backlog()
    first, _ = run(env, ScriptedChat(), store)
    assert first["stopped_reason"] == "skipped_full"
    for i in store.ideas[:3]:
        i["status"] = "approved"                                  # you decide on three of them
    chat = ScriptedChat(call("propose_idea", **GOOD_IDEA), call("finish", summary="ok"))
    second, _ = run(env, chat, store)
    assert second["stopped_reason"] == "finished" and len(second["proposed_ids"]) == 1


# ---- experiments only -----------------------------------------------------------------------------------------

def test_an_experiments_only_run_gets_only_experiments_even_if_the_model_tries_other_kinds(env):
    store = FakeStore()
    chat = ScriptedChat(call("propose_idea", **GOOD_IDEA),               # a deep-dive: refused
                        call("propose_idea", **EXPERIMENT_IDEA),         # an experiment: accepted
                        call("finish", summary="done"))
    record, _ = run(env, chat, store, only_kind="experiment")
    results = [s["result"] for s in record["steps"] if s.get("tool") == "propose_idea"]
    assert "only accepts 'experiment'" in results[0] and results[1].startswith("OK")
    assert [i["kind"] for i in store.ideas] == ["experiment"] and record["only_kind"] == "experiment"
    assert "propose ONLY ideas of kind 'experiment'" in chat.calls[0]["messages"][1]["content"]
    schema = next(s for s in chat.calls[0]["schemas"] if s["function"]["name"] == "propose_idea")
    assert schema["function"]["parameters"]["properties"]["kind"]["enum"] == ["experiment"]


@pytest.mark.parametrize("kwargs,message", [
    (dict(only_kind="poem"), "only_kind must be one of"),
    (dict(mode="explore", only_kind="experiment", area=None), "not explore runs"),
])
def test_bad_only_kind_requests_fail_cleanly(env, kwargs, message):
    with pytest.raises(ValueError, match=message):
        run(env, ScriptedChat(), **kwargs)


def test_a_normal_run_records_no_kind_limit(env):
    record, _ = run(env, finished_chat())
    assert record["only_kind"] is None


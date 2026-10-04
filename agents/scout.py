"""Scout: the loop that proposes blog ideas (and, in explore mode, suggests new topics).

Run it:  python -m agents.scout --mode weekly            # least-covered area, proposes ideas
         python -m agents.scout --mode weekly --area agents
         python -m agents.scout --mode weekly --topic multi-agent     # one sub-topic only
         python -m agents.scout --mode weekly --only-kind experiment  # only experiment ideas
         python -m agents.scout --mode profile_changed   # only topics added/changed since last time
         python -m agents.scout --mode explore           # suggests new sub-topics / areas, no ideas
"""
import argparse
import json
import logging
import os
import time
import uuid
from datetime import date, datetime, timezone

from agents.scout_prompt import (
    EXPLORE_SYSTEM_PROMPT, SYSTEM_PROMPT, build_briefing, build_explore_briefing,
    pick_area, schemas_for, select_topics,
)
from agents.scout_tools import ScoutConfig, ScoutTools, backlog_cap_from_env, throttle_mode
from agents.shared.llm_client import chat_with_tools, tool_result_message
from tools.ideas import KINDS, coverage_from, topic_key
from tools.profile import allowed_resources, area_of, area_topics, get_snapshot, load_profile, topic_levels
from tools.runs import active_run, last_run, save_run
from tools.store import CosmosStore
from tools.web_search import web_search

log = logging.getLogger("scout")

MAX_ITERATIONS = 8
TIME_BUDGET_SECONDS = 300
STEP_RESULT_CHARS = 500
RUN_MODES = ("weekly", "profile_changed", "explore")
# Modes that create ideas. Only these count for the backlog throttle's "last run" clock.
PROPOSING_MODES = ("weekly", "profile_changed")
NUDGE = ("You answered without calling a tool. Call propose_idea (or suggest_topic / hold_trend "
         "if they are offered) with what you found, or call finish if you are done.")


class RunInProgress(RuntimeError):
    """Another Scout run is still going; two at once would double-spend credits and fight over ideas."""


def _llm_timeout() -> int:
    """NVIDIA's free tier is sometimes slow (one call took 33s), so give it longer."""
    return 90 if os.getenv("LLM_PROVIDER", "azure") == "nvidia" else 60


def _search(query, max_results, news, time_range):
    return web_search(query, max_results, news=news, time_range=time_range)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip_args(args, limit: int = 1500):
    """Keep step traces small: oversized tool arguments are stored as clipped text."""
    text = json.dumps(args, default=str)
    return args if len(text) <= limit else text[:limit] + "..."


def _new_record(run_id: str, mode: str, area: str | None, topic: str | None = None,
                only_kind: str | None = None) -> dict:
    """The agent_runs document. It is saved as 'running' at the start and updated as the run goes."""
    return {
        "id": run_id, "agent": "scout", "type": "run",
        "status": "running",
        "mode": mode, "run_mode": mode, "area": area, "topic": topic, "only_kind": only_kind,
        "started_at": _now(), "updated_at": _now(), "ended_at": None,
        "llm_provider": os.getenv("LLM_PROVIDER", "azure"),
        "profile_version": None,    # the profile version this run used
        "baseline_version": None,   # set only when this run handled all profile changes up to that version
        "topics_scouted": [], "queries": [],
        "proposed_ids": [], "held_ids": [], "suggested_ids": [],
        "iterations": 0, "stopped_reason": None, "summary": "", "error": None,
        "steps": [],                # what the model did, in order
    }


def _save(record: dict, **fields) -> dict:
    record.update(fields)
    record["updated_at"] = _now()
    save_run(record)
    return record


def _finish(record: dict, **fields) -> dict:
    return _save(record, status="error" if fields.get("error") else "done", ended_at=_now(), **fields)


def run_scout(mode: str = "weekly", area: str | None = None,
              max_iterations: int = MAX_ITERATIONS, time_budget: int = TIME_BUDGET_SECONDS,
              store=None, chat=chat_with_tools, run_id: str | None = None,
              topic: str | None = None, only_kind: str | None = None) -> dict:
    """only_kind: propose ONLY this kind of idea (e.g. 'experiment'); the tool refuses anything else.
    area: focus the whole run on one profile area (e.g. 'agents').
    topic: focus on ONE sub-topic (e.g. 'multi-agent'); its area is filled in automatically.
    A weekly run with neither picks the least-covered area automatically.
    run_id: lets a caller (the web page) know the id before the run finishes."""
    if mode not in RUN_MODES:
        raise ValueError(f"mode must be one of {RUN_MODES}, got {mode!r}")
    if only_kind is not None:
        if only_kind not in KINDS:
            raise ValueError(f"only_kind must be one of {sorted(KINDS)}, got {only_kind!r}")
        if mode == "explore":
            raise ValueError("only_kind applies to runs that propose ideas, not explore runs")

    store = store or CosmosStore()
    busy = active_run("scout", time_budget + 60)
    if busy:
        raise RunInProgress(f"run {busy['id']} is still in progress")

    record = _new_record(run_id or f"run_{uuid.uuid4().hex[:10]}", mode, area, topic, only_kind)
    _save(record)   # visible in the Runs list straight away, as 'running'
    log.info("run %s starting, mode=%s", record["id"], mode)
    try:
        _execute(record, store, chat, max_iterations, time_budget)
    except Exception as e:   # a crash must not leave the record saying 'running' forever
        _finish(record, error=f"{type(e).__name__}: {e}")
        raise
    return record


def _execute(record: dict, store, chat, max_iterations: int, time_budget: int) -> None:
    mode, run_id = record["mode"], record["id"]
    area, topic, only_kind = record["area"], record["topic"], record["only_kind"]

    profile = load_profile()
    if profile is None:
        raise RuntimeError("No profile saved yet. Run: python -m scripts.seed_profile")

    keys = list(topic_levels(profile))
    areas = area_topics(profile)
    if area is not None and area not in areas:
        raise ValueError(f"unknown area {area!r}; choose from {sorted(areas)}")
    if topic is not None:
        if topic not in keys:
            raise ValueError(f"unknown sub-topic {topic!r}")
        if area is not None and topic not in areas[area]:
            raise ValueError(f"sub-topic {topic!r} is not in area {area!r}")
        area = area_of(profile, topic)   # a sub-topic belongs to exactly one area
    ideas = store.list_ideas()
    trends = store.list_trends()
    coverage = coverage_from(ideas, keys)
    backlog_cap = backlog_cap_from_env()

    if area is None and topic is None and mode == "weekly":
        area = pick_area(profile, coverage)   # rotate: the least-covered area gets this run
        log.info("no --area given, picked the least-covered area: %s", area)

    def make_config(run_mode: str, allowed_topics: set) -> ScoutConfig:
        return ScoutConfig(
            mode=run_mode, profile_topics=allowed_topics, avoid=profile.get("avoid", []),
            topic_areas={k: name for name, topic_keys in areas.items() for k in topic_keys},
            area_names=set(areas),
            known_topics={topic_key(k) for k in keys} | {topic_key(name) for name in areas},
            profile_version=profile["version"], run_id=run_id, backlog_cap=backlog_cap,
            allowed_needs=tuple(allowed_resources(profile)), only_kind=only_kind,
        )

    if mode == "explore":
        # Explore only suggests; it is not throttled and never moves the profile baseline.
        run_mode = "explore"
        topics = [topic] if topic else (list(areas[area]) if area else [])
        config = make_config(run_mode, set(topics) if topics else set(keys))
        briefing = build_explore_briefing(profile, store.list_suggestions(), config,
                                          date.today().isoformat(), area=area, topic=topic)
        system_prompt = EXPLORE_SYSTEM_PROMPT
    else:
        # 1. Throttle: decided in plain code, before any LLM tokens are spent
        previous = last_run("scout", modes=PROPOSING_MODES, exclude_id=run_id)
        throttle = throttle_mode(ideas, backlog_cap, previous["started_at"] if previous else None)
        if throttle == "skip":
            log.info("backlog is full, skipping this run")
            _finish(record, area=area, topic=topic, stopped_reason="skipped_full")
            return
        run_mode = "hold_only" if throttle == "hold_only" else mode

        # 2. Pick the topics to focus on
        previous_profile = None
        if mode == "profile_changed":
            # The baseline is the profile version whose changes a previous run fully handled.
            base = last_run("scout", baseline_only=True, exclude_id=run_id)
            if base:
                previous_profile = get_snapshot(base["baseline_version"])
            elif profile["version"] > 1:
                previous_profile = get_snapshot(1)
        topics = select_topics(profile, run_mode, previous_profile, coverage, area=area, topic=topic)
        if not topics:
            log.info("no new or changed topics in the profile, nothing to do")
            _finish(record, area=area, topic=topic, stopped_reason="no_changes")
            return

        allowed = {topic} if topic else (set(areas[area]) if area else set(keys))   # a focused run cannot wander
        config = make_config(run_mode, allowed)
        briefing = build_briefing(profile, topics, ideas, trends, coverage, config,
                                  date.today().isoformat(), area=area, topic=topic, only_kind=only_kind)
        system_prompt = SYSTEM_PROMPT
    log.info("focus area: %s | focus topics: %s", area or "(all)", ", ".join(topics) or "-")
    _save(record, area=area, topic=topic, run_mode=run_mode, topics_scouted=topics, profile_version=profile["version"])

    tools = ScoutTools(store, _search, config)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": briefing},
    ]
    stopped, error, iterations = _loop(record, tools, messages, schemas_for(run_mode, only_kind),
                                       chat, max_iterations, time_budget)

    # The baseline only advances when a profile_changed run covered every change and finished cleanly;
    # otherwise changed topics would silently never be scouted.
    handled_everything = (mode == "profile_changed" and area is None and topic is None
                          and run_mode == "profile_changed" and stopped == "finished")
    log.info("run %s done: %s, %d proposed, %d held, %d suggested", run_id, stopped,
             len(tools.proposed), len(tools.held), len(tools.suggested))
    _finish(
        record,
        queries=list(tools.queries), proposed_ids=list(tools.proposed), held_ids=list(tools.held),
        suggested_ids=list(tools.suggested), iterations=iterations, stopped_reason=stopped,
        summary=tools.summary, error=error,
        baseline_version=profile["version"] if handled_everything else None,
    )


def _loop(record: dict, tools: ScoutTools, messages: list, schemas: list, chat,
          max_iterations: int, time_budget: int) -> tuple[str, str | None, int]:
    """Model picks tool calls, code runs them, results go back to the model.
    Returns (stopped_reason, error, iterations). Every step is also written to record['steps']."""
    steps = record["steps"]
    stopped, error, iterations, nudged = "max_iterations", None, 0, False
    deadline = time.monotonic() + time_budget
    timeout = _llm_timeout()

    while iterations < max_iterations:
        if time.monotonic() > deadline:
            stopped = "time_budget"
            break
        iterations += 1

        try:
            result = chat(messages, schemas, max_tokens=2000, timeout=timeout)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            log.error("LLM call failed: %s", error)
            steps.append({"iteration": iterations, "type": "error", "content": error})
            stopped = "llm_error"
            break

        messages.append(result.message)
        if result.content:
            steps.append({"iteration": iterations, "type": "text", "content": result.content[:1000]})

        if not result.tool_calls:
            log.info("iteration %d: model answered without a tool call: %s",
                     iterations, (result.content or "")[:200])
            if not nudged:   # give it exactly one reminder before giving up
                nudged = True
                messages.append({"role": "user", "content": NUDGE})
                steps.append({"iteration": iterations, "type": "nudge", "content": NUDGE})
                _save(record, iterations=iterations)
                continue
            stopped = "no_tool_call"
            break

        for call in result.tool_calls:   # the model may ask for several tools in one turn
            output = tools.call(call.name, call.arguments)
            log.info("iteration %d: %s(%s) -> %s", iterations, call.name,
                     json.dumps(call.arguments)[:200], output[:300])
            steps.append({"iteration": iterations, "type": "tool", "tool": call.name,
                          "args": _clip_args(call.arguments), "result": output[:STEP_RESULT_CHARS]})
            messages.append(tool_result_message(call.id, output))

        _save(record, iterations=iterations, queries=list(tools.queries),
              proposed_ids=list(tools.proposed), held_ids=list(tools.held),
              suggested_ids=list(tools.suggested))   # progress is visible while the run is going
        if tools.finished:
            stopped = "finished"
            break

    return stopped, error, iterations


def main():
    parser = argparse.ArgumentParser(description="Run the blog Scout once.")
    parser.add_argument("--mode", choices=list(RUN_MODES), default="weekly")
    parser.add_argument("--area", help="focus the run on one profile area, e.g. agents")
    parser.add_argument("--topic", help="focus the run on ONE sub-topic, e.g. multi-agent")
    parser.add_argument("--only-kind", choices=sorted(KINDS), help="propose only this kind of idea, e.g. experiment")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

    try:
        record = run_scout(mode=args.mode, area=args.area, topic=args.topic, only_kind=args.only_kind)
    except RunInProgress as e:
        raise SystemExit(f"Not started: {e}")
    print("\n--- run summary ---")
    for key in ("area", "topic", "only_kind", "stopped_reason", "iterations", "proposed_ids", "held_ids",
                "suggested_ids", "summary", "error"):
        print(f"{key}: {record[key]}")


if __name__ == "__main__":
    main()

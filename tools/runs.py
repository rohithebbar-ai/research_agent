"""Run records: one document per agent run, in the agent_runs container."""
from datetime import datetime, timezone

from tools.cosmos_client import _get_container, get_document, upsert_document

# Fields shown in the Runs list. The (large) `steps` trace is only fetched for one run at a time.
LIST_FIELDS = ("id", "agent", "mode", "run_mode", "area", "topic", "only_kind", "status", "started_at", "ended_at",
               "updated_at", "iterations", "stopped_reason", "proposed_ids", "held_ids",
               "suggested_ids", "topics_scouted", "summary", "error", "llm_provider",
               "profile_version", "baseline_version")


def save_run(record: dict) -> None:
    upsert_document("agent_runs", {k: v for k, v in record.items() if not k.startswith("_")})


def get_run(run_id: str, agent: str = "scout") -> dict | None:
    return get_document("agent_runs", run_id, partition_key_value=agent)


def list_runs(agent: str = "scout", limit: int = 50) -> list[dict]:
    """Newest first, without the step trace."""
    fields = ", ".join(f"c.{f}" for f in LIST_FIELDS)
    return list(_get_container("agent_runs").query_items(
        query=f"SELECT TOP @n {fields} FROM c WHERE c.agent = @agent AND c.type = 'run' "
              "ORDER BY c.started_at DESC",
        parameters=[{"name": "@n", "value": limit}, {"name": "@agent", "value": agent}],
        partition_key=agent,
    ))


def last_run(agent: str, modes: tuple | None = None, baseline_only: bool = False,
             exclude_id: str | None = None) -> dict | None:
    """Most recent run record for an agent.

    modes: only runs in these modes (explore runs, for example, must not move the
        "when did the last proposing run start" clock used by the backlog throttle).
    baseline_only: only runs that advanced the profile baseline (see agents/scout.py).
    exclude_id: skip this run (the one currently starting).
    """
    query = "SELECT TOP 1 * FROM c WHERE c.agent = @agent AND c.type = 'run'"
    params = [{"name": "@agent", "value": agent}]
    if modes:
        query += " AND ARRAY_CONTAINS(@modes, c.mode)"
        params.append({"name": "@modes", "value": list(modes)})
    if baseline_only:
        query += " AND IS_NUMBER(c.baseline_version)"
    if exclude_id:
        query += " AND c.id != @exclude"
        params.append({"name": "@exclude", "value": exclude_id})
    query += " ORDER BY c.started_at DESC"
    rows = list(_get_container("agent_runs").query_items(
        query=query, parameters=params,
        partition_key=agent,  # agent_runs is partitioned by /agent, so this stays in one partition
    ))
    return rows[0] if rows else None


def is_stale(run: dict, max_age_seconds: float, now: datetime | None = None) -> bool:
    """A 'running' record nobody has touched for longer than a run can possibly take = crashed."""
    now = now or datetime.now(timezone.utc)
    touched = run.get("updated_at") or run.get("started_at")
    if not touched:
        return True
    return (now - datetime.fromisoformat(touched)).total_seconds() > max_age_seconds


def run_state(run: dict, max_age_seconds: float, now: datetime | None = None) -> str:
    """running | crashed | error | done  (records from before the status field count as done)."""
    status = run.get("status") or "done"
    if status == "running":
        return "crashed" if is_stale(run, max_age_seconds, now) else "running"
    return status


def active_run(agent: str, max_age_seconds: float) -> dict | None:
    """A run that is genuinely still going (not a stale record left by a crash)."""
    rows = list(_get_container("agent_runs").query_items(
        query="SELECT TOP 1 * FROM c WHERE c.agent = @agent AND c.type = 'run' "
              "AND c.status = 'running' ORDER BY c.started_at DESC",
        parameters=[{"name": "@agent", "value": agent}],
        partition_key=agent,
    ))
    if rows and not is_stale(rows[0], max_age_seconds):
        return rows[0]
    return None

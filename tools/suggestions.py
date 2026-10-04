"""Topic suggestions: sub-topics, or whole new areas, that Scout thinks you should look at.

Scout only ever *suggests*. You accept (it joins your profile) or dismiss, and you can change
your mind later in either direction.
"""
import re
import uuid
from datetime import datetime, timezone

from tools.cosmos_client import _get_container, get_document, upsert_document
from tools.ideas import topic_key
from tools.profile import LEVELS

STATUSES = ("pending", "accepted", "dismissed")
KINDS = ("subtopic", "new_area")
SOURCES = ("scout", "you")           # who suggested it
MAX_NAME_CHARS = 60
MAX_WHY_CHARS = 500


def slugify(name: str) -> str:
    """'KV cache eviction' -> 'kv-cache-eviction' (the form profile keys use)."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def new_suggestion(name: str, area: str, why: str, kind: str, evidence: list | None = None,
                   run_id: str | None = None, level: str = "curious", source: str = "scout") -> dict:
    name, area = name.strip(), area.strip()
    if not name or not slugify(name):
        raise ValueError("name is empty")
    if len(name) > MAX_NAME_CHARS:
        raise ValueError(f"name is {len(name)} characters; keep it under {MAX_NAME_CHARS}")
    if not slugify(area):
        raise ValueError("area is empty")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}, got {kind!r}")
    if level not in LEVELS:
        raise ValueError(f"level must be one of {list(LEVELS)}, got {level!r}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {list(SOURCES)}, got {source!r}")
    if len(why) > MAX_WHY_CHARS:
        raise ValueError(f"why is {len(why)} characters; keep it under {MAX_WHY_CHARS}")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"sug_{uuid.uuid4().hex[:12]}",
        "name": name, "key": slugify(name), "topic_key": topic_key(name),
        "area": slugify(area), "kind": kind, "level": level,
        "why": why.strip(), "evidence": evidence or [], "source": source,
        "status": "pending", "run_id": run_id,
        "created_at": now, "updated_at": now, "decided_at": None,
    }


def plan_suggestion_status(suggestion: dict, new_status: str) -> dict:
    """Field changes for a status change. Any move among the three is allowed (changing your mind)."""
    if new_status not in STATUSES:
        raise ValueError(f"status must be one of {list(STATUSES)}, got {new_status!r}")
    decided = None if new_status == "pending" else datetime.now(timezone.utc).isoformat()
    return {"status": new_status, "decided_at": decided,
            "updated_at": datetime.now(timezone.utc).isoformat()}


# ---- Cosmos-backed functions -------------------------------------------------

def list_suggestions(status: str | None = None) -> list[dict]:
    query, params = "SELECT * FROM c", []
    if status:
        query += " WHERE c.status = @s"
        params = [{"name": "@s", "value": status}]
    return list(_get_container("topic_suggestions").query_items(
        query=query, parameters=params, enable_cross_partition_query=True))


def get_suggestion(suggestion_id: str) -> dict | None:
    return get_document("topic_suggestions", suggestion_id)


def find_suggestion_by_key(key: str) -> dict | None:
    rows = list(_get_container("topic_suggestions").query_items(
        query="SELECT * FROM c WHERE c.topic_key = @k",
        parameters=[{"name": "@k", "value": key}],
        enable_cross_partition_query=True))
    return rows[0] if rows else None


def save_suggestion(doc: dict) -> None:
    upsert_document("topic_suggestions", {k: v for k, v in doc.items() if not k.startswith("_")})

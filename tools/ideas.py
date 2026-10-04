"""Post ideas: build, validate, store and measure coverage"""
import re
import uuid
from datetime import datetime, timezone

from tools.cosmos_client import _get_container, get_document, upsert_document

STATUSES = {"pending", "approved", "rejected", "researched", "held", "drafted", "published"}
ANGLES = {"broad", "niche"}
KINDS = {"trending", "refresher", "deep-dive", "experiment"}
SOURCES = {"you", "scout", "trending"}

MAX_TOPIC_CHARS = 100        # a topic is one specific line, not a paragraph
MAX_RATIONALE_CHARS = 500
MAX_BRIEF_CHARS = 600         # the short paragraph shown when you open an idea
USER_STATUSES = ("pending", "approved", "rejected")            # the owner moves ideas freely among these
AGENT_OWNED = ("researched", "held", "drafted", "published")   # set by the pipeline, not by hand
EDITABLE_FIELDS = ("topic", "angle", "kind", "rationale", "brief", "profile_topic", "experiment")

# A small learning experiment: one question, doable locally in up to a weekend.
EXPERIMENT_TEXT_LIMITS = {"question": 200, "setup": 400, "measure": 200}
EFFORTS = ("hours", "weekend")
NEEDS = ("cpu", "small-gpu")      # what the experiment needs to run; the profile says which are available


def validate_experiment(plan, allowed_needs=NEEDS) -> dict:
    """A clean experiment plan, or ValueError saying what is missing or not allowed."""
    if not isinstance(plan, dict):
        raise ValueError("an experiment idea needs an experiment plan: question, setup, measure, effort, needs")
    unknown = set(plan) - set(EXPERIMENT_TEXT_LIMITS) - {"effort", "needs"}
    if unknown:
        raise ValueError(f"unknown experiment fields: {sorted(unknown)}")
    clean = {}
    for field, limit in EXPERIMENT_TEXT_LIMITS.items():
        text = str(plan.get(field) or "").strip()
        if not text:
            raise ValueError(f"experiment.{field} is required")
        if len(text) > limit:
            raise ValueError(f"experiment.{field} is {len(text)} characters; keep it under {limit}")
        clean[field] = text
    if plan.get("effort") not in EFFORTS:
        raise ValueError(f"experiment.effort must be one of {list(EFFORTS)} (nothing bigger than a weekend)")
    clean["effort"] = plan["effort"]
    needs = plan.get("needs")
    if not isinstance(needs, list) or not needs or any(n not in NEEDS for n in needs):
        raise ValueError(f"experiment.needs must be a non-empty list drawn from {list(NEEDS)}")
    unavailable = sorted(set(needs) - set(allowed_needs))
    if unavailable:
        raise ValueError(f"this experiment needs {unavailable}, but the owner only has {sorted(allowed_needs)}")
    clean["needs"] = sorted(set(needs))
    return clean


# Words that carry no topic information ("how does X work" is the same topic as "X")
STOPWORDS = {
    "a", "an", "the", "how", "does", "do", "did", "what", "whats", "is", "are",
    "why", "to", "of", "in", "on", "for", "and", "with", "vs",
    "explained", "explain", "work", "works", "working",
    "guide", "intro", "introduction", "understanding",
}


def _stem(word: str) -> str:
    """Very naive stemmer: caching/caches/cached/cache all become 'cach'."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix == "s" and word.endswith("ss"):  # 'process' must not lose its s
                continue
            word = word[: -len(suffix)]
            break
    if word.endswith("e") and len(word) > 3:  # 'make' and 'making' both -> 'mak'
        word = word[:-1]
    return word


def topic_key(topic: str) -> str:
    """Normalize so paraphrases made of the same core words get the same key."""
    words = re.sub(r"[^a-z0-9]+", " ", topic.lower()).split()
    kept = [_stem(w) for w in words if w not in STOPWORDS]
    return " ".join(kept or words)  # if everything was a stopword, keep the plain words

def new_idea(
    topic: str,
    angle: str,
    kind: str,
    profile_topic: str,
    rationale: str,
    source: str = "scout",
    area: str | None = None,
    evidence: list[dict] | None = None,
    run_id: str | None = None,
    profile_version: int | None = None,
    brief: str = "",
    experiment: dict | None = None,
    builds_on: str | None = None,
    allowed_needs=NEEDS,
) -> dict:
    """Build a valid `pending` idea document. Raises ValueError on bad input."""
    if not topic.strip():
        raise ValueError("topic is empty")
    if len(topic.strip()) > MAX_TOPIC_CHARS:
        raise ValueError(f"topic is {len(topic.strip())} characters; keep it to one specific line "
                         f"under {MAX_TOPIC_CHARS}")
    if len(rationale) > MAX_RATIONALE_CHARS:
        raise ValueError(f"rationale is {len(rationale)} characters; keep it under {MAX_RATIONALE_CHARS}")
    if len(brief) > MAX_BRIEF_CHARS:
        raise ValueError(f"brief is {len(brief)} characters; keep it under {MAX_BRIEF_CHARS}")
    if angle not in ANGLES:
        raise ValueError(f"angle must be one of {sorted(ANGLES)}, got {angle!r}")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}, got {kind!r}")
    if source not in SOURCES:
        raise ValueError(f"source must be one of {sorted(SOURCES)}, got {source!r}")

    if kind == "experiment":
        experiment = validate_experiment(experiment, allowed_needs)
    elif experiment:
        raise ValueError("only ideas of kind 'experiment' have an experiment plan")
    else:
        experiment = None

    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"idea_{uuid.uuid4().hex[:12]}",
        "topic": topic.strip(),
        "topic_key": topic_key(topic),
        "angle": angle,
        "kind": kind,
        "area": area,
        "profile_topic": profile_topic,
        "status": "pending",
        "source": source,
        "rationale": rationale,
        "brief": brief.strip(),
        "experiment": experiment,
        "builds_on": builds_on,       # id of the earlier idea (e.g. the concept post) this follows up
        "evidence": evidence or [],
        "reject_reason": None,
        "skip_count": 0,
        "run_id": run_id,
        "profile_version": profile_version,
        "created_at": now,
        "updated_at": now,
    }

def coverage_from(ideas: list[dict], topic_keys: list[str]) -> dict[str, dict]:
    """For each profile topic: idea count, newest created, and newest activity."""
    result = {
        key: {"count": 0, "last_created": None, "last_updated": None}
        for key in topic_keys
    }
    for idea in ideas:
        entry = result.get(idea.get("profile_topic"))
        if entry is None:
            continue
        entry["count"] += 1
        for field, source in (("last_created", "created_at"), ("last_updated", "updated_at")):
            ts = idea.get(source)
            if ts and (entry[field] is None or ts > entry[field]):
                entry[field] = ts
    return result

def plan_status_change(idea: dict, new_status: str, reason: str | None = None) -> dict:
    """Field changes for an owner-made status change, or ValueError if it is not allowed.

    The owner can move an idea freely among pending / approved / rejected (so a rejected idea
    can be revived). Once the pipeline has taken over (researched, held, drafted, published)
    the status is not changed from outside.
    """
    if new_status not in USER_STATUSES:
        raise ValueError(f"you can only set pending, approved or rejected, not {new_status!r}")
    if idea["status"] in AGENT_OWNED:
        raise ValueError(f"this idea is '{idea['status']}': the pipeline owns it now, "
                         "so its status cannot be changed here")
    reason = (reason or "").strip() or None
    return {"status": new_status, "reject_reason": reason if new_status == "rejected" else None}


def plan_edit(idea: dict, changes: dict, lookup, allowed_needs=NEEDS) -> dict:
    """Validated field changes for an edit. lookup(topic_key) -> an existing idea or None."""
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"these fields cannot be edited: {sorted(unknown)}")
    out = dict(changes)
    if "topic" in out:
        topic = out["topic"].strip()
        if not topic:
            raise ValueError("topic is empty")
        if len(topic) > MAX_TOPIC_CHARS:
            raise ValueError(f"topic is {len(topic)} characters; keep it under {MAX_TOPIC_CHARS}")
        key = topic_key(topic)
        clash = lookup(key)
        if clash and clash["id"] != idea["id"]:
            raise ValueError(f"topic clashes with existing idea {clash['id']}")
        out["topic"], out["topic_key"] = topic, key
    if "angle" in out and out["angle"] not in ANGLES:
        raise ValueError(f"angle must be one of {sorted(ANGLES)}, got {out['angle']!r}")
    if "kind" in out and out["kind"] not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}, got {out['kind']!r}")
    if "rationale" in out and len(out["rationale"]) > MAX_RATIONALE_CHARS:
        raise ValueError(f"rationale is too long (max {MAX_RATIONALE_CHARS})")
    if "brief" in out and len(out["brief"]) > MAX_BRIEF_CHARS:
        raise ValueError(f"brief is too long (max {MAX_BRIEF_CHARS})")
    # an idea is an experiment exactly when it has a valid plan
    kind = out.get("kind", idea.get("kind"))
    if kind == "experiment":
        out["experiment"] = validate_experiment(out.get("experiment", idea.get("experiment")), allowed_needs)
    elif out.get("experiment"):
        raise ValueError("only ideas of kind 'experiment' have an experiment plan")
    elif idea.get("experiment"):
        out["experiment"] = None      # changed away from 'experiment': the plan goes too
    return out


def with_changes(idea: dict, changes: dict) -> dict:
    """A cleaned copy of the idea (no Cosmos system fields) with changes applied and updated_at bumped."""
    merged = {k: v for k, v in idea.items() if not k.startswith("_")}
    merged.update(changes)
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    return merged


def edit_idea(idea_id: str, **changes) -> dict:
    """Edit fields of an idea in Cosmos. Recomputes topic_key if the topic changes."""
    idea = get_document("post_ideas", idea_id)
    if idea is None:
        raise KeyError(f"no idea with id {idea_id}")
    clean = with_changes(idea, plan_edit(idea, changes, find_by_topic_key))
    upsert_document("post_ideas", clean)
    return clean

# ---- Cosmos-backed functions ------------------------------------------------

def add_idea(idea: dict) -> None:
    upsert_document("post_ideas", idea)


def list_ideas(status: str | None = None) -> list[dict]:
    """All ideas, optionally only one status. Cross-partition, fine at this volume."""
    query, params = "SELECT * FROM c", []
    if status:
        query += " WHERE c.status = @status"
        params = [{"name": "@status", "value": status}]
    return list(_get_container("post_ideas").query_items(
        query=query, parameters=params, enable_cross_partition_query=True
    ))


def find_by_topic_key(key: str) -> dict | None:
    """The existing idea with this normalized topic, or None. Used for duplicate checks."""
    rows = list(_get_container("post_ideas").query_items(
        query="SELECT * FROM c WHERE c.topic_key = @k",
        parameters=[{"name": "@k", "value": key}],
        enable_cross_partition_query=True,
    ))
    return rows[0] if rows else None

def set_status(idea_id: str, status: str, **fields) -> dict:
    """Change an idea's status (and optionally other fields, e.g. reject_reason)."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}, got {status!r}")
    idea = get_document("post_ideas", idea_id)
    if idea is None:
        raise KeyError(f"no idea with id {idea_id}")
    idea.update(fields)
    idea["status"] = status
    idea["updated_at"] = datetime.now(timezone.utc).isoformat()
    clean = {k: v for k, v in idea.items() if not k.startswith("_")}
    upsert_document("post_ideas", clean)
    return clean
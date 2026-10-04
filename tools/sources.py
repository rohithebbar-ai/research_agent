"""Sources: the citation URLs behind an idea, in one registry shared by Scout, Researcher and you.

A source belongs to one idea. Your marks (important, note) live on the source itself, so they
survive re-runs and re-research, and the Writer can read the sources you flagged first.
"""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError

from tools.cosmos_client import _get_container, get_document, upsert_document

MAX_NOTE_CHARS = 500
MAX_TITLE_CHARS = 200
FOUND_BY = ("scout", "researcher", "you")
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_)", re.IGNORECASE)


def normalize_url(url: str) -> str:
    """http(s) only, lowercase host, no fragment, no tracking parameters, no trailing slash.

    Two spellings of the same page get the same id, so a URL is never registered twice.
    Raises ValueError for anything that is not a plain web link.
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"not an http(s) URL: {url!r}")
    if parsed.username or parsed.password:
        raise ValueError("URLs with a username or password are not allowed")
    host = parsed.hostname.lower() + (f":{parsed.port}" if parsed.port else "")
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                       if not _TRACKING.match(k)])
    return urlunparse((parsed.scheme, host, parsed.path.rstrip("/"), "", query, ""))


def source_id(idea_id: str, url: str) -> str:
    """Deterministic: the same URL on the same idea always has the same id."""
    return "src_" + hashlib.sha1(f"{idea_id}|{normalize_url(url)}".encode()).hexdigest()[:14]


def new_source(idea_id: str, url: str, title: str = "", published_date: str = "",
               found_by: str = "you", run_id: str | None = None, note: str = "",
               important: bool = False) -> dict:
    if found_by not in FOUND_BY:
        raise ValueError(f"found_by must be one of {list(FOUND_BY)}, got {found_by!r}")
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError(f"note is {len(note)} characters; keep it under {MAX_NOTE_CHARS}")
    clean = normalize_url(url)
    domain = urlparse(clean).hostname.removeprefix("www.")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": source_id(idea_id, clean), "idea_id": idea_id,
        "url": clean, "domain": domain,
        "title": ((title or "").strip() or domain)[:MAX_TITLE_CHARS],
        "published_date": published_date or "",
        "found_by": found_by, "run_id": run_id,
        "important": bool(important), "note": note.strip(),
        "created_at": now, "updated_at": now,
    }


def plan_source_update(source: dict, changes: dict) -> dict:
    """Validated changes to the owner's marks. Only 'important' and 'note' can be changed."""
    unknown = set(changes) - {"important", "note"}
    if unknown:
        raise ValueError(f"these fields cannot be edited: {sorted(unknown)}")
    out = {}
    if "important" in changes:
        if not isinstance(changes["important"], bool):
            raise ValueError("important must be true or false")
        out["important"] = changes["important"]
    if "note" in changes:
        note = (changes["note"] or "").strip()
        if len(note) > MAX_NOTE_CHARS:
            raise ValueError(f"note is {len(note)} characters; keep it under {MAX_NOTE_CHARS}")
        out["note"] = note
    out["updated_at"] = datetime.now(timezone.utc).isoformat()
    return out


def sources_from_evidence(idea: dict) -> list[dict]:
    """Source records for an idea's evidence list. Entries without a usable web URL are skipped."""
    found = []
    for item in idea.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        try:
            found.append(new_source(idea["id"], item.get("url", ""), title=item.get("title", ""),
                                    published_date=item.get("published_date", ""),
                                    found_by="scout", run_id=idea.get("run_id")))
        except ValueError:
            continue
    return found


def source_counts(sources: list[dict]) -> dict[str, dict]:
    """{idea_id: {'total': n, 'important': m}} for the idea list."""
    counts: dict[str, dict] = {}
    for s in sources:
        entry = counts.setdefault(s["idea_id"], {"total": 0, "important": 0})
        entry["total"] += 1
        entry["important"] += 1 if s.get("important") else 0
    return counts


def sort_sources(sources: list[dict]) -> list[dict]:
    """Important first, then oldest first (the order they were found)."""
    return sorted(sources, key=lambda s: (not s.get("important"), s.get("created_at", "")))


# ---- Cosmos-backed functions -------------------------------------------------

def list_sources(idea_id: str) -> list[dict]:
    return list(_get_container("idea_sources").query_items(
        query="SELECT * FROM c WHERE c.idea_id = @i",
        parameters=[{"name": "@i", "value": idea_id}], partition_key=idea_id))


def list_all_sources() -> list[dict]:
    return list(_get_container("idea_sources").query_items(
        query="SELECT * FROM c", enable_cross_partition_query=True))


def get_source(idea_id: str, sid: str) -> dict | None:
    return get_document("idea_sources", sid, partition_key_value=idea_id)


def save_source(doc: dict) -> None:
    upsert_document("idea_sources", {k: v for k, v in doc.items() if not k.startswith("_")})


def add_source(doc: dict) -> bool:
    """Insert only if new. Returns False (and changes nothing) if the URL is already registered,
    so Scout re-finding a source never wipes your star or note."""
    try:
        _get_container("idea_sources").create_item(doc)
        return True
    except CosmosResourceExistsError:
        return False


def delete_source(idea_id: str, sid: str) -> None:
    try:
        _get_container("idea_sources").delete_item(item=sid, partition_key=idea_id)
    except CosmosResourceNotFoundError:
        pass

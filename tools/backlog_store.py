"""Idea backlog storage for the blog-pipeline Scout.

Doc shape (post_ideas), design section 05:
    id, topic, angle ("broad"|"niche"), status
    (approved|pending|skipped|held|drafted|published),
    source ("you"|"scout"|"trending"), rationale, created_at,
    optional shape ("experiment"|"conceptual").

trend_holding items: id, topic, rationale, url (optional), created_at.

`BacklogStore` is the interface agents depend on; `CosmosBacklogStore` is the
real backend and `InMemoryBacklogStore` is for tests / local runs.
Published-post history is simply ideas with status "published".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

ANGLES = ("broad", "niche")
STATUSES = ("approved", "pending", "skipped", "held", "drafted", "published")
SOURCES = ("you", "scout", "trending")
SHAPES = ("experiment", "conceptual")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "idea") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def normalize_idea(idea: dict) -> dict:
    """Fill defaults and validate enum fields. Returns a new dict."""
    doc = dict(idea)
    if not str(doc.get("topic", "")).strip():
        raise ValueError("idea requires a non-empty 'topic'")
    doc.setdefault("id", new_id("idea"))
    doc.setdefault("angle", "broad")
    doc.setdefault("status", "pending")
    doc.setdefault("source", "scout")
    doc.setdefault("rationale", "")
    doc.setdefault("created_at", _now())
    for field, allowed in (
        ("angle", ANGLES), ("status", STATUSES), ("source", SOURCES),
    ):
        if doc[field] not in allowed:
            raise ValueError(f"invalid {field} {doc[field]!r}; expected one of {allowed}")
    if doc.get("shape") is not None and doc["shape"] not in SHAPES:
        raise ValueError(f"invalid shape {doc['shape']!r}; expected one of {SHAPES}")
    return doc


def normalize_trend(item: dict) -> dict:
    doc = dict(item)
    if not str(doc.get("topic", "")).strip():
        raise ValueError("trend item requires a non-empty 'topic'")
    doc.setdefault("id", new_id("trend"))
    doc.setdefault("rationale", "")
    doc.setdefault("created_at", _now())
    return doc


@runtime_checkable
class BacklogStore(Protocol):
    def list_ideas(self, status: str | None = None) -> list[dict]: ...
    def add_idea(self, idea: dict) -> dict: ...
    def update_idea(self, idea_id: str, fields: dict) -> dict: ...
    def list_published_posts(self) -> list[dict]: ...
    def add_trend_holding(self, item: dict) -> dict: ...
    def list_trend_holding(self) -> list[dict]: ...


class InMemoryBacklogStore:
    """Dict-backed store for tests and local runs."""

    def __init__(self, ideas: list[dict] | None = None, trends: list[dict] | None = None):
        self._ideas: dict[str, dict] = {}
        self._trends: dict[str, dict] = {}
        for i in ideas or []:
            self.add_idea(i)
        for t in trends or []:
            self.add_trend_holding(t)

    def list_ideas(self, status: str | None = None) -> list[dict]:
        docs = [dict(d) for d in self._ideas.values()]
        if status is not None:
            docs = [d for d in docs if d["status"] == status]
        return sorted(docs, key=lambda d: d["created_at"])

    def add_idea(self, idea: dict) -> dict:
        doc = normalize_idea(idea)
        self._ideas[doc["id"]] = doc
        return dict(doc)

    def update_idea(self, idea_id: str, fields: dict) -> dict:
        if idea_id not in self._ideas:
            raise KeyError(f"idea not found: {idea_id}")
        merged = {**self._ideas[idea_id], **fields, "id": idea_id}
        self._ideas[idea_id] = normalize_idea(merged)
        return dict(self._ideas[idea_id])

    def list_published_posts(self) -> list[dict]:
        return self.list_ideas(status="published")

    def add_trend_holding(self, item: dict) -> dict:
        doc = normalize_trend(item)
        self._trends[doc["id"]] = doc
        return dict(doc)

    def list_trend_holding(self) -> list[dict]:
        return sorted((dict(d) for d in self._trends.values()), key=lambda d: d["created_at"])


class CosmosBacklogStore:
    """Cosmos-backed store: `post_ideas` and `trend_holding` containers."""

    IDEAS = "post_ideas"
    TRENDS = "trend_holding"

    @staticmethod
    def _container(name: str):
        # Imported lazily: tools.cosmos_client needs real env/config at import.
        from tools.cosmos_client import _get_container
        return _get_container(name)

    def _query(self, name: str, query: str, parameters: list | None = None) -> list[dict]:
        return list(self._container(name).query_items(
            query=query,
            parameters=parameters or [],
            enable_cross_partition_query=True,
        ))

    def list_ideas(self, status: str | None = None) -> list[dict]:
        if status is None:
            return self._query(self.IDEAS, "SELECT * FROM c ORDER BY c.created_at")
        return self._query(
            self.IDEAS,
            "SELECT * FROM c WHERE c.status = @status ORDER BY c.created_at",
            [{"name": "@status", "value": status}],
        )

    def add_idea(self, idea: dict) -> dict:
        doc = normalize_idea(idea)
        self._container(self.IDEAS).upsert_item(body=doc)
        return doc

    def update_idea(self, idea_id: str, fields: dict) -> dict:
        from tools.cosmos_client import get_document
        current = get_document(self.IDEAS, idea_id)
        if current is None:
            raise KeyError(f"idea not found: {idea_id}")
        # Strip Cosmos system fields (_rid, _etag, ...) before re-validating.
        clean = {k: v for k, v in current.items() if not k.startswith("_")}
        doc = normalize_idea({**clean, **fields, "id": idea_id})
        self._container(self.IDEAS).upsert_item(body=doc)
        return doc

    def list_published_posts(self) -> list[dict]:
        return self.list_ideas(status="published")

    def add_trend_holding(self, item: dict) -> dict:
        doc = normalize_trend(item)
        self._container(self.TRENDS).upsert_item(body=doc)
        return doc

    def list_trend_holding(self) -> list[dict]:
        return self._query(self.TRENDS, "SELECT * FROM c ORDER BY c.created_at")

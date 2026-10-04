"""Cosmos DB (NoSQL) — single store for all data.

Containers: documents, concepts, conversations, authorized_users, post_ideas,
trend_holding (the last two back the blog-pipeline Scout; see tools/backlog_store.py).

Reads:
- get_document_metadata(doc_id) -> dict
- get_image(image_url) -> bytes  (Blob Storage)
- get_conversation(session_id) -> dict
- get_authorized_user(phone) -> dict | None

Writes:
- write_document(record) -> None
- upsert_conversation(session_id, messages) -> None
"""

from __future__ import annotations
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from config import settings

# Each container's partition key field — needed because read_item()
# requires both the document id AND its partition key value
CONTAINER_PARTITION_KEYS: dict[str, str] = {
    "documents": "id",
    "concepts": "id",
    "conversations": "session_id",
    "authorized_users": "id",
    "post_ideas": "id",
    "trend_holding": "id",
    "scout_profile": "id",
    "research_notes": "idea_id",
    "your_notes": "idea_id",
    "drafts": "idea_id",
    "agent_runs": "agent",
    "topic_suggestions": "id",
    "idea_sources": "idea_id",
}

_client : CosmosClient | None = None
_containers : dict = {}

def _get_container(name: str):
    """Lazily create and cache client/database/container so we don't
    reconnect on every call."""
    global _client
    if name in _containers:
        return _containers[name]

    if _client is None:
        _client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)

    database = _client.get_database_client(settings.cosmos_database)
    container = database.get_container_client(name)
    _containers[name] = container
    return container

def upsert_document(container: str, doc: dict) -> None:
    """Insert or replace a document by its `id`. Cosmos handles the
    insert-vs-replace decision itself — no need to check existence first."""
    _get_container(container).upsert_item(body=doc)

def get_document(
    container : str,
    doc_id : str,
    partition_key_value: str | None = None,
) -> dict | None:
    """Fetch one document by id. `partition_key_value` is required unless
    this container's partition key IS `id` (then it defaults to doc_id)."""
    key_field = CONTAINER_PARTITION_KEYS[container]

    if partition_key_value is None:
        if key_field != "id":
            raise ValueError(
                f"Container '{container}' is partitioned by '{key_field}', "
                f"not 'id' — pass partition_key_value explicitly."
            )
        partition_key_value = doc_id
    try:
        return _get_container(container).read_item(
            item=doc_id, partition_key = partition_key_value
        )
    except CosmosResourceNotFoundError:
        return None

def get_document_metadata(doc_id: str) -> dict:
    raise NotImplementedError


def get_image(image_url: str) -> bytes:
    raise NotImplementedError


def get_conversation(session_id: str) -> dict:
    raise NotImplementedError


def get_authorized_user(phone: str) -> dict | None:
    raise NotImplementedError


def write_document(record: dict) -> None:
    raise NotImplementedError


def upsert_conversation(session_id: str, messages: list[dict]) -> None:
    raise NotImplementedError

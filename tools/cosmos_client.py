"""Cosmos DB (NoSQL, native vector search) — single store for all data.

Containers: documents, chunks (vector search on content_vector, 512-dim),
concepts, conversations, authorized_users.

Reads:
- vector_search(query_vector, concept_ids=None, top_k=5) -> list[dict]:
    Native Cosmos DB vector search over the chunks container.
- get_document_metadata(doc_id) -> dict
- get_image(image_url) -> bytes  (Blob Storage)
- get_conversation(session_id) -> dict
- get_authorized_user(phone) -> dict | None

Writes:
- write_document(record) -> None
- write_chunks(chunks) -> None
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
    "chunks": "parent_id",
    "concepts": "id",
    "conversations": "session_id",
    "authorized_users": "id",
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

def vector_search(
        query_vector: list[float],
        concept_ids: list[str] | None = None,
        top_k: int = 5
    ) -> list[dict]:
    """
    Search the `chunks` container by embedding similarity.

    `query_vector` must already be embedded (512-dim, per our schema) —
    embedding the raw query text happens one layer up, in whichever
    agent calls this, not here.

    Cross-partition is required: `chunks` is partitioned by `parent_id`
    (one partition per paper/article), but a topic search needs to look
    across every paper, not just one. 
    """
    container = _get_container("chunks")
    query = (
        "SELECT TOP @top_k "
        "c.id, c.parent_id, c.content, c.content_type, c.image_url, "
        "VectorDistance(c.content_vector, @query_vector) AS similarity "
        "FROM c "
    )
    parameters = [
        {"name": "@top_k", "value": top_k},
        {"name": "@query_vector", "value": query_vector},
    ]

    if concept_ids:
        # "any of c.concept_ids appears in the requested list" —
        # array-intersection isn't a single built-in function in Cosmos
        # SQL, so this is the standard pattern: iterate the chunk's own
        # concept_ids array and check membership against the parameter list.
        query += (
            "WHERE EXISTS(SELECT VALUE t FROM t IN c.concept_ids "
            "WHERE ARRAY_CONTAINS(@concept_ids, t)) "
        )
        parameters.append({"name": "@concept_ids", "value": concept_ids})

    query += "ORDER BY VectorDistance(c.content_vector, @query_vector)"

    results = container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
    )
    return list(results)


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


def write_chunks(chunks: list[dict]) -> None:
    raise NotImplementedError


def upsert_conversation(session_id: str, messages: list[dict]) -> None:
    raise NotImplementedError

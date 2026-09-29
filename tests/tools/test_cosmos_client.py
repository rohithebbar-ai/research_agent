from tools.cosmos_client import upsert_document, get_document, vector_search

# 1. Basic CRUD — concepts container (partition key = id)
upsert_document("concepts", {
    "id": "concept_test",
    "name": "Test Concept",
    "status": "active",
})
doc = get_document("concepts", "concept_test")
print("Read back:", doc)
assert doc is not None and doc["name"] == "Test Concept"

# 2. Vector search — chunks container (partition key = parent_id)
fake_vector = [0.1] * 512  # dummy 512-dim vector, matches our schema

upsert_document("chunks", {
    "id": "doc_test_chunk1",
    "parent_id": "doc_test",
    "content": "This is a test chunk about 6D pose estimation.",
    "content_vector": fake_vector,
    "content_type": "text",
    "concept_ids": ["concept_test"],
})

results = vector_search(query_vector=fake_vector, top_k=3)
print("Vector search results:", results)
assert len(results) > 0
assert results[0]["id"] == "doc_test_chunk1"  # identical vector → top match

print("\nAll checks passed — Cosmos DB connection, CRUD, and vector search all work.")
from tools.cosmos_client import upsert_document, get_document

# 1. Basic CRUD — concepts container (partition key = id)
upsert_document("concepts", {
    "id": "concept_test",
    "name": "Test Concept",
    "status": "active",
})
doc = get_document("concepts", "concept_test")
print("Read back:", doc)
assert doc is not None and doc["name"] == "Test Concept"

print("\nAll checks passed — Cosmos DB connection and CRUD work.")

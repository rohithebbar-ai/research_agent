import os
from azure.cosmos import CosmosClient, PartitionKey
from dotenv import load_dotenv

load_dotenv()

# container name - partition key path
CONTAINERS = {
    "scout_profile": "/id",
    "post_ideas": "/id",
    "trend_holding": "/id",
    "research_notes": "/idea_id",
    "your_notes": "/idea_id",
    "drafts": "/idea_id",
    "agent_runs": "/agent",
    "topic_suggestions": "/id",
    "idea_sources": "/idea_id",
}

client = CosmosClient(os.environ["COSMOS_ENDPOINT"], os.environ["COSMOS_KEY"])
db = client.get_database_client(os.environ["COSMOS_DATABASE"])

for name, pk_path in CONTAINERS.items():
    db.create_container_if_not_exists(id=name, partition_key=PartitionKey(path=pk_path))
    print(f"ok {name} (partition key {pk_path})")

print("\nContainers in database: ", sorted(c["id"] for c in db.list_containers()))


from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from config import settings

client = CosmosClient(settings.cosmos_endpoint, credentials=settings.cosmos_key)
database = client.get_database_client(settings.cosmos_database)

try:
    database.delete_container("documents")
except CosmosResourceNotFoundError:
    pass

database.create_container(
    id="documents",
    partition_key = PartitionKey(path="/id"),
)

print("Documents container created.")
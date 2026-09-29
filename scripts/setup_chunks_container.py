import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from azure.cosmos import CosmosClient, PartitionKey
from config import settings

client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
database = client.get_database_client(settings.cosmos_database)

vector_embedding_policy = {
    "vectorEmbeddings": [
        {
            "path": "/content_vector",
            "dataType": "float32",
            "distanceFunction": "cosine",
            "dimensions": settings.embedding_dimensions,  # 512
        }
    ]
}

indexing_policy = {
    "indexingMode": "consistent",
    "automatic": True,
    "includedPaths": [{"path": "/*"}],
    "excludedPaths": [{"path": '/"_etag"/?'}],
    "vectorIndexes": [{"path": "/content_vector", "type": "quantizedFlat"}],
}

database.create_container(
    id="chunks",
    partition_key=PartitionKey(path="/parent_id"),
    vector_embedding_policy=vector_embedding_policy,
    indexing_policy=indexing_policy,
    offer_throughput=400,  # minimum for dedicated container throughput
)

print("chunks container created with vector policy.")
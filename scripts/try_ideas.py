from tools.cosmos_client import _get_container
from tools.ideas import add_idea, find_by_topic_key, list_ideas, new_idea, set_status, topic_key

idea = new_idea("Test: how KV caching works", "niche", "deep-dive",
                "llm-inference", "smoke test, safe to delete")
add_idea(idea)
print("added:", idea["id"])

print("duplicate found:", find_by_topic_key(topic_key("test: HOW kv caching works!"))["id"])
print("pending count:", len(list_ideas("pending")))

updated = set_status(idea["id"], "rejected", reject_reason="just a test")
print("now:", updated["status"], "|", updated["reject_reason"])

_get_container("post_ideas").delete_item(item=idea["id"], partition_key=idea["id"])
print("cleaned up, remaining:", len(list_ideas()))
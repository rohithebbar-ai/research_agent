import pytest

from tools import backlog_store
from tools.backlog_store import BacklogStore, CosmosBacklogStore, InMemoryBacklogStore


def test_defaults_and_validation():
    s = InMemoryBacklogStore()
    d = s.add_idea({"topic": "t"})
    assert d["status"] == "pending" and d["source"] == "scout" and d["angle"] == "broad"
    assert d["id"] and d["created_at"]
    with pytest.raises(ValueError):
        s.add_idea({"topic": "t", "status": "nope"})
    with pytest.raises(ValueError):
        s.add_idea({"topic": " "})
    with pytest.raises(ValueError):
        s.add_idea({"topic": "t", "shape": "weird"})


def test_list_update_published_and_holding():
    s = InMemoryBacklogStore()
    a = s.add_idea({"topic": "a"})
    s.add_idea({"topic": "b", "status": "approved"})
    assert len(s.list_ideas()) == 2 and len(s.list_ideas("approved")) == 1
    s.update_idea(a["id"], {"status": "published"})
    assert [i["topic"] for i in s.list_published_posts()] == ["a"]
    with pytest.raises(KeyError):
        s.update_idea("missing", {})
    s.add_trend_holding({"topic": "trend"})
    assert [t["topic"] for t in s.list_trend_holding()] == ["trend"]
    assert isinstance(s, BacklogStore) and isinstance(CosmosBacklogStore(), BacklogStore)


class FakeContainer:
    def __init__(self):
        self.items = {}
    def upsert_item(self, body):
        self.items[body["id"]] = body
    def query_items(self, query, parameters=None, enable_cross_partition_query=False):
        vals = list(self.items.values())
        if parameters:
            vals = [v for v in vals if v["status"] == parameters[0]["value"]]
        return iter(vals)


def test_cosmos_store_uses_containers(monkeypatch):
    from tools import cosmos_client
    containers = {"post_ideas": FakeContainer(), "trend_holding": FakeContainer()}
    monkeypatch.setattr(cosmos_client, "_get_container", lambda n: containers[n])
    monkeypatch.setattr(cosmos_client, "get_document",
                        lambda c, i, p=None: containers[c].items.get(i))
    s = CosmosBacklogStore()
    d = s.add_idea({"topic": "x"})
    s.update_idea(d["id"], {"status": "published"})
    assert [i["topic"] for i in s.list_published_posts()] == ["x"]
    s.add_trend_holding({"topic": "t"})
    assert len(containers["trend_holding"].items) == 1
    assert cosmos_client.CONTAINER_PARTITION_KEYS["post_ideas"] == "id"
    assert cosmos_client.CONTAINER_PARTITION_KEYS["trend_holding"] == "id"

from unittest.mock import MagicMock

import pytest
import requests

from tools import web_search as ws


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)


def _ok(payload):
    r = MagicMock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


def test_missing_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        ws.web_search("q")


def test_success(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    post = MagicMock(return_value=_ok({"results": [
        {"title": "T", "url": "http://u", "content": "C", "score": 1}]}))
    monkeypatch.setattr(ws.requests, "post", post)
    assert ws.web_search("q", 3) == [
        {"title": "T", "url": "http://u", "content": "C", "published_date": ""}]
    kw = post.call_args.kwargs
    assert kw["json"] == {"query": "q", "max_results": 3, "include_published_date": True}
    assert kw["headers"]["Authorization"] == "Bearer k" and kw["timeout"]


def test_retry_then_success(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    post = MagicMock(side_effect=[requests.ConnectionError("x"), _ok({"results": []})])
    monkeypatch.setattr(ws.requests, "post", post)
    assert ws.web_search("q") == []
    assert post.call_count == 2


def test_fails_after_retry(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    post = MagicMock(side_effect=requests.Timeout("x"))
    monkeypatch.setattr(ws.requests, "post", post)
    with pytest.raises(RuntimeError, match="failed after retry"):
        ws.web_search("q")
    assert post.call_count == 2


def test_schema():
    f = ws.WEB_SEARCH_TOOL_SCHEMA["function"]
    assert f["name"] == "web_search" and f["parameters"]["required"] == ["query"]


def test_news_and_time_range_are_sent_and_date_is_returned(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    post = MagicMock(return_value=_ok({"results": [
        {"title": "T", "url": "http://u", "content": "C", "published_date": "2026-10-05"}]}))
    monkeypatch.setattr(ws.requests, "post", post)
    out = ws.web_search("q", news=True, time_range="week")
    assert out[0]["published_date"] == "2026-10-05"
    sent = post.call_args.kwargs["json"]
    assert sent["topic"] == "news" and sent["time_range"] == "week"

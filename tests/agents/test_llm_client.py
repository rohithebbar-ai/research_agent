import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.shared import llm_client


def _resp(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _tc(id_, name, args):
    return SimpleNamespace(id=id_, function=SimpleNamespace(name=name, arguments=args))


@pytest.fixture
def client(monkeypatch):
    c = MagicMock()
    monkeypatch.setattr(llm_client, "_client", c)
    return c


def test_chat_with_tools_plain_answer(client):
    client.chat.completions.create.return_value = _resp("done")
    r = llm_client.chat_with_tools([], [{"type": "function"}])
    assert r.content == "done" and r.tool_calls == []
    assert r.message == {"role": "assistant", "content": "done"}


def test_chat_with_tools_parses_calls(client):
    args = json.dumps({"query": "x"})
    client.chat.completions.create.return_value = _resp(None, [_tc("c1", "web_search", args)])
    r = llm_client.chat_with_tools([], [])
    assert r.tool_calls == [llm_client.ToolCall("c1", "web_search", {"query": "x"})]
    assert r.message["tool_calls"] == [
        {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": args}}
    ]
    assert r.message["role"] == "assistant"


@pytest.mark.parametrize("bad", ["{not json", "", None, "[1,2]"])
def test_malformed_arguments_give_empty_dict(client, bad):
    client.chat.completions.create.return_value = _resp(None, [_tc("c1", "f", bad)])
    r = llm_client.chat_with_tools([], [])
    assert r.tool_calls[0].arguments == {}
    assert r.message["tool_calls"][0]["function"]["arguments"]  # still valid-ish string


def test_tool_result_message():
    assert llm_client.tool_result_message("c1", "ok") == {
        "role": "tool", "tool_call_id": "c1", "content": "ok"
    }


def test_passes_model_and_kwargs(client, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "my-deploy")
    client.chat.completions.create.return_value = _resp("ok")
    llm_client.chat_with_tools([{"role": "user", "content": "hi"}], [], max_tokens=50)
    kw = client.chat.completions.create.call_args.kwargs
    assert kw["model"] == "my-deploy" and kw["max_tokens"] == 50


def test_model_name_follows_provider(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "az-model")
    monkeypatch.setenv("NVIDIA_MODEL", "nv-model")
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    assert llm_client._model_name() == "az-model"
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    assert llm_client._model_name() == "nv-model"


def test_lazy_singleton_azure(monkeypatch):
    monkeypatch.setattr(llm_client, "_client", None)
    monkeypatch.setenv("LLM_PROVIDER", "azure")
    fake = MagicMock()
    monkeypatch.setattr(llm_client, "AzureOpenAI", fake)
    a = llm_client._get_client()
    b = llm_client._get_client()
    assert a is b and fake.call_count == 1


def test_nvidia_provider_uses_openai_with_base_url(monkeypatch):
    monkeypatch.setattr(llm_client, "_client", None)
    monkeypatch.setenv("LLM_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    fake = MagicMock()
    monkeypatch.setattr(llm_client, "OpenAI", fake)
    llm_client._get_client()
    fake.assert_called_once_with(base_url="https://example.test/v1", api_key="nvapi-test")

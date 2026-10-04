"""One place that talks to the LLM. Every agent imports from here."""
import json
import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

load_dotenv()
log = logging.getLogger(__name__)

@dataclass
class ToolCall:
    id:str
    name:str
    arguments:dict  # already parsed from JSON

@dataclass
class ChatResult:
    content: str | None
    tool_calls: list[ToolCall]
    message: dict  # assistant message, ready to append to conversation


_client = None


def _get_client():
    """Client build once LLM provider picks azure or NVIDIA backup"""
    global _client
    if _client is None:
        if os.getenv("LLM_PROVIDER", "azure") == "nvidia":
            _client = OpenAI(
                base_url = os.environ["NVIDIA_BASE_URL"],
                api_key = os.environ["NVIDIA_API_KEY"],
            )
        else:
            _client = AzureOpenAI(
                azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
                api_key=os.environ["AZURE_OPENAI_KEY"],
                api_version=os.environ["AZURE_OPENAI_API_VERSION"],
            )
    return _client

def _model_name() -> str:
    if os.getenv("LLM_PROVIDER", "azure") == "nvidia":
        return os.environ["NVIDIA_MODEL"]
    return os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"]

def chat_with_tools(messages: list[dict], tools: list[dict], **kwargs) -> ChatResult:
    resp = _get_client().chat.completions.create(
        model=_model_name(),
        messages=messages,
        tools=tools,
        **kwargs,
    )
    msg = resp.choices[0].message

    calls = []
    for tc in msg.tool_calls or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
            if not isinstance(args, dict):
                args = {}
        except json.JSONDecodeError:
            log.warning("bad tool arguments from model: %r", tc.function.arguments)
            args = {}
        calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

    message = {"role": "assistant", "content": msg.content}
    if msg.tool_calls:
        message["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
            }
            for tc in msg.tool_calls
        ]
    return ChatResult(content=msg.content, tool_calls=calls, message=message)


def tool_result_message(tool_call_id: str, content: str) -> dict:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


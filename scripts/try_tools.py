import json
import time

from agents.shared.llm_client import _get_client, _model_name, tool_result_message

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]


def raw_call(label, messages):
    """Call the API directly so we can see everything the model returned."""
    start = time.time()
    resp = _get_client().chat.completions.create(
        model=_model_name(), messages=messages, tools=TOOLS, max_tokens=4000
    )
    print(f"\n===== {label}: {time.time() - start:.1f}s, model={_model_name()} =====")
    print("usage:", resp.usage)
    msg = resp.choices[0].message
    print("full message:")
    print(json.dumps(msg.model_dump(exclude_none=True), indent=2, default=str))
    return msg


messages = [{"role": "user", "content": "What's the weather in Bengaluru?"}]

# Call 1: model should ask for the tool
msg = raw_call("call 1 (expects tool call)", messages)

messages.append({
    "role": "assistant",
    "content": msg.content,
    "tool_calls": [
        {"id": tc.id, "type": "function",
         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
        for tc in msg.tool_calls
    ],
})
for tc in msg.tool_calls:
    messages.append(tool_result_message(tc.id, "31°C, sunny"))

# Call 2: model reads the tool result and answers
raw_call("call 2 (expects final answer)", messages)

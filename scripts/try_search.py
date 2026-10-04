"""Step 3 check: the model decides to call web_search, we run it, the model answers."""
import json

from agents.shared.llm_client import chat_with_tools, tool_result_message
from tools.web_search import WEB_SEARCH_TOOL_SCHEMA, web_search

TOOLS = [WEB_SEARCH_TOOL_SCHEMA]
messages = [{
    "role": "user",
    "content": "What are people writing about agentic RAG lately? Search, then give 3 bullet points with URLs.",
}]

result = chat_with_tools(messages, TOOLS, max_tokens=2000)
print("model asked for:", [(c.name, c.arguments) for c in result.tool_calls])

messages.append(result.message)
for call in result.tool_calls:
    if call.name == "web_search":
        hits = web_search(**call.arguments)
        print(f"  got {len(hits)} results, first: {hits[0]['title'] if hits else None}")
        messages.append(tool_result_message(call.id, json.dumps(hits)))
    else:
        messages.append(tool_result_message(call.id, f"ERROR: unknown tool {call.name}"))

final = chat_with_tools(messages, TOOLS, max_tokens=2000)
print("\nanswer:\n", final.content)

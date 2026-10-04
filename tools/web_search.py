"""Web search tool for agents, backed by Tavily (REST, no extra dependency).

Two parts live together so they stay in sync:
- web_search(): the Python function that does the work.
- WEB_SEARCH_TOOL_SCHEMA: tells the model the function exists and how to call it.
"""
import logging
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"

WEB_SEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web. Returns results with title, url and a content snippet.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (default 5).",
                },
            },
            "required": ["query"],
        },
    },
}


def web_search(
    query: str,
    max_results: int = 5,
    news: bool = False,
    time_range: str | None = None,
) -> list[dict]:
    """Return [{title, url, content, published_date}] for a query. One retry on failure.

    news=True searches Tavily's news index; time_range is day|week|month|year.
    published_date is "" when Tavily does not provide one.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")

    payload = {"query": query, "max_results": max_results, "include_published_date": True}
    if news:
        payload["topic"] = "news"
    if time_range:
        payload["time_range"] = time_range

    last_error = None
    for attempt in range(2):  # first try + one retry
        try:
            resp = requests.post(
                TAVILY_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()  # turns 401/429/500 into an exception
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "published_date": r.get("published_date") or "",
                }
                for r in resp.json().get("results", [])
            ]
        except (requests.RequestException, ValueError) as e:
            last_error = e
            log.warning("tavily attempt %d failed: %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(1)

    raise RuntimeError(f"Tavily search failed after retry: {last_error}")

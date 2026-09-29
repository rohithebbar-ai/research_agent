"""Summarizer agent — ReAct loop per chat message.

Loop (per message):
1. Understand: what is being asked (specific paper? topic? comparison ->
   "not yet, Phase 2" reply).
2. Plan retrieval: named paper_id or open topic search.
3. Call vector_search (Cosmos DB native).
4. Inspect evidence: enough context? If not, broaden query and retry (max 2).
   If evidence is thin for a concept -> call fetch_more (A2A handoff to Scout).
5. Generate answer with inline citations to paper/doc IDs.
6. Validate every claim against retrieved chunks; if unsupported, regenerate
   once with a stricter prompt.
7. Return answer to the calling channel (same API for WhatsApp and web).

Tools used: tools/cosmos_client.py (vector_search, get_document_metadata,
get_image), fetch_more (HTTP call to /scout/on-demand).
"""


def answer(message: str, user_id: str, session_id: str, channel: str) -> dict:
    """Run the full ReAct loop for one user message.

    Returns {"reply": str, "cited_docs": list[str]}.
    Persists the exchange to the conversations container.
    """
    raise NotImplementedError

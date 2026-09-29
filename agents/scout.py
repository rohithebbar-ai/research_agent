"""Scout agent (Paper agent) — daily timer + on-demand call from Summarizer.

Pipeline per paper:
1. arxiv_search / semantic_scholar_search for candidates (category- or concept-based).
2. Relevance decision (LLM reasoning against stated interests; borderline ->
   check citations via semantic_scholar_citations).
3. If relevant: fetch_arxiv_html (primary) or fetch_and_extract_pdf (PyMuPDF fallback).
4. Parse: text sections + <img> tags with surrounding context (BeautifulSoup).
5. Chunk text (~500 tokens, ~50 overlap).
6. Caption each extracted image (vision LLM) — image verbalization.
7. Embed text chunks + captions (512-dim).
8. Store raw images in Blob Storage; write document record + chunks to Cosmos DB.

Tools used: tools/arxiv.py, tools/semantic_scholar.py, tools/pdf_fallback.py,
tools/chunking.py, tools/cosmos_client.py, agents/shared/llm_client.py.
"""


def run_daily(categories: list[str], since_date: str) -> dict:
    """Category-based daily run. Returns run summary (papers seen, indexed)."""
    raise NotImplementedError


def run_on_demand(concept: str, reason: str) -> dict:
    """Concept-based on-demand run (called via /scout/on-demand by Summarizer).

    Returns count of newly indexed chunks for the concept.
    """
    raise NotImplementedError

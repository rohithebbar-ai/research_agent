"""Tests for the Scout agent loop.

Cover:
- Relevance decision (relevant / not / borderline -> citation check).
- arXiv HTML primary path vs PyMuPDF fallback path.
- Chunking + embedding + write to Cosmos (mock cosmos_client).
- run_on_demand returns correct new-chunk count.
"""


def test_relevance_decision():
    raise NotImplementedError


def test_html_primary_path():
    raise NotImplementedError


def test_pdf_fallback_path():
    raise NotImplementedError


def test_run_on_demand_returns_chunk_count():
    raise NotImplementedError

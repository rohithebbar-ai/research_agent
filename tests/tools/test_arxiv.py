"""Tests for arXiv tools.

Cover:
- arxiv_search returns expected shape (id, title, abstract, categories, date).
- fetch_arxiv_html returns HTML for a recent paper, None on 404 (older paper).
"""


def test_arxiv_search_shape():
    raise NotImplementedError


def test_fetch_arxiv_html_recent_paper():
    raise NotImplementedError


def test_fetch_arxiv_html_404_returns_none():
    raise NotImplementedError

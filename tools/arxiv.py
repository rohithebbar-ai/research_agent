"""arXiv tools — primary ingestion path (no OCR needed).

- arxiv_search(query_or_categories, since_date) -> list[dict]:
    arXiv API search; returns candidate papers (id, title, abstract, categories,
    published_date).
- fetch_arxiv_html(paper_id) -> str | None:
    Fetch arxiv.org/html/<id>. Returns HTML string, or None on 404 (caller
    falls back to tools/pdf_fallback.py).
"""


def arxiv_search(query_or_categories: list[str], since_date: str) -> list[dict]:
    raise NotImplementedError


def fetch_arxiv_html(paper_id: str) -> str | None:
    raise NotImplementedError

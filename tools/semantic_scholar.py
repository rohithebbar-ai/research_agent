"""Semantic Scholar tools — broader concept coverage + citation checks.

- semantic_scholar_search(concept) -> list[dict]:
    Search by concept name (not just citations) for wider coverage.
- semantic_scholar_citations(paper_id) -> list[dict]:
    Cited-by list; Scout uses this to check if a borderline paper connects to
    work already being followed.
"""


def semantic_scholar_search(concept: str) -> list[dict]:
    raise NotImplementedError


def semantic_scholar_citations(paper_id: str) -> list[dict]:
    raise NotImplementedError

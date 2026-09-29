"""PyMuPDF fallback — used only when arXiv HTML is unavailable (older papers).

- fetch_and_extract_pdf(paper_id) -> tuple[str, list[bytes]]:
    Download the PDF, extract text and embedded images with PyMuPDF.
    Returns (full_text, image_bytes_list). Free (compute only).
"""


def fetch_and_extract_pdf(paper_id: str) -> tuple[str, list[bytes]]:
    raise NotImplementedError

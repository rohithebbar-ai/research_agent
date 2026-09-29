"""Text chunking — ~500 tokens per chunk, ~50 token overlap.

- chunk_text(text, chunk_tokens=500, overlap_tokens=50) -> list[str]:
    Split parsed paper/article text into overlapping chunks.
"""


def chunk_text(text: str, chunk_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
    raise NotImplementedError

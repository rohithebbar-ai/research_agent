"""Azure OpenAI wrapper — single client for chat, embeddings, and vision.

- chat(messages, ...) -> str: GPT-4o-mini (or GPT-4.1-mini) for agent reasoning,
  relevance scoring, claim validation, and LLM quality filtering.
- embed(texts, dimensions=512) -> list[list[float]]: text-embedding-3-small with
  reduced dimension (512) — fits Cosmos DB flat index cap, ~3x storage savings.
- caption_image(image_url_or_bytes) -> str: vision LLM call for diagram
  verbalization (e.g. "Five-stage 6D pose estimation pipeline: ...").
"""


def chat(messages: list[dict], **kwargs) -> str:
    """Single chat completion. Returns assistant text."""
    raise NotImplementedError


def embed(texts: list[str], dimensions: int = 512) -> list[list[float]]:
    """Embed a batch of texts at reduced dimension (default 512)."""
    raise NotImplementedError


def caption_image(image: bytes, context: str = "") -> str:
    """Vision LLM: produce a citable text caption for an extracted diagram.

    context: surrounding paragraph text from the paper, to ground the caption.
    """
    raise NotImplementedError

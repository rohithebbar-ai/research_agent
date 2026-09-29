"""Tests for text chunking.

Cover:
- Chunk size ~500 tokens, overlap ~50 tokens.
- Short text (under one chunk) returns a single chunk.
- No content lost across chunks (overlap preserves boundaries).
"""


def test_chunk_size_and_overlap():
    raise NotImplementedError


def test_short_text_single_chunk():
    raise NotImplementedError


def test_no_content_lost():
    raise NotImplementedError

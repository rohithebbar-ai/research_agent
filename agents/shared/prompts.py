"""Prompt templates for both agents.

Templates needed:
- SCOUT_RELEVANCE: judge paper relevance against stated interests
  (pose estimation, bin picking, embodied AI, VLA, JEPA).
- SCOUT_IMAGE_CAPTION: image verbalization for extracted diagrams.
- SUMMARIZER_SYSTEM: ReAct system prompt — retrieve, inspect, cite, validate.
- SUMMARIZER_GENERATE: answer generation with inline citations to doc IDs.
- SUMMARIZER_VALIDATE: claim-by-claim check against retrieved chunks.
- SUMMARIZER_STRICT_REGENERATE: stricter prompt for the one retry after
  validation failure.
"""

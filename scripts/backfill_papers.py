"""One-off script: seed ~2 weeks of papers manually so Summarizer has
something to answer against on day one.

Run locally:  uv run python scripts/backfill_papers.py

Reuses the Scout pipeline (agents.scout) over a fixed date range instead of
the daily timer.
"""


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()

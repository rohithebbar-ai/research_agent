"""Registers the citation URLs already stored on ideas (idea.evidence) as sources.

Safe to run any number of times: a URL that is already registered is left untouched,
so your stars and notes are never overwritten.

    python -m scripts.backfill_sources
"""
from tools.ideas import list_ideas
from tools.sources import add_source, sources_from_evidence

added = skipped = 0
for idea in list_ideas():
    for source in sources_from_evidence(idea):
        if add_source(source):
            added += 1
        else:
            skipped += 1
print(f"registered {added} new source(s); {skipped} were already there")

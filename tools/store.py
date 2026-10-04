"""The store Scout and the web API talk to: ideas, reading list, runs, profile, suggestions.

Tests hand Scout and the API a fake with the same methods instead of this class.
"""
from tools import ideas, profile, runs, sources, suggestions
from tools.cosmos_client import _get_container, get_document, upsert_document


class CosmosStore:
    # ---- ideas ----
    def list_ideas(self, status: str | None = None) -> list[dict]:
        return ideas.list_ideas(status)

    def get_idea(self, idea_id: str) -> dict | None:
        return get_document("post_ideas", idea_id)

    def add_idea(self, idea: dict) -> None:
        ideas.add_idea(idea)

    def save_idea(self, idea: dict) -> None:
        upsert_document("post_ideas", {k: v for k, v in idea.items() if not k.startswith("_")})

    def find_by_topic_key(self, key: str) -> dict | None:
        return ideas.find_by_topic_key(key)

    # ---- sources (citation URLs) ----
    def add_source(self, source: dict) -> bool:
        return sources.add_source(source)

    def list_sources(self, idea_id: str) -> list[dict]:
        return sources.list_sources(idea_id)

    def list_all_sources(self) -> list[dict]:
        return sources.list_all_sources()

    def get_source(self, idea_id: str, source_id: str) -> dict | None:
        return sources.get_source(idea_id, source_id)

    def save_source(self, source: dict) -> None:
        sources.save_source(source)

    def delete_source(self, idea_id: str, source_id: str) -> None:
        sources.delete_source(idea_id, source_id)

    # ---- reading list ----
    def add_trend(self, item: dict) -> None:
        upsert_document("trend_holding", item)

    def find_trend_by_key(self, key: str) -> dict | None:
        rows = list(_get_container("trend_holding").query_items(
            query="SELECT * FROM c WHERE c.topic_key = @k",
            parameters=[{"name": "@k", "value": key}],
            enable_cross_partition_query=True,
        ))
        return rows[0] if rows else None

    def list_trends(self) -> list[dict]:
        return list(_get_container("trend_holding").query_items(
            query="SELECT * FROM c", enable_cross_partition_query=True))

    # ---- suggestions ----
    def list_suggestions(self, status: str | None = None) -> list[dict]:
        return suggestions.list_suggestions(status)

    def get_suggestion(self, suggestion_id: str) -> dict | None:
        return suggestions.get_suggestion(suggestion_id)

    def find_suggestion_by_key(self, key: str) -> dict | None:
        return suggestions.find_suggestion_by_key(key)

    def add_suggestion(self, suggestion: dict) -> None:
        suggestions.save_suggestion(suggestion)

    def save_suggestion(self, suggestion: dict) -> None:
        suggestions.save_suggestion(suggestion)

    # ---- runs ----
    def list_runs(self, limit: int = 50) -> list[dict]:
        return runs.list_runs("scout", limit)

    def get_run(self, run_id: str) -> dict | None:
        return runs.get_run(run_id, "scout")

    def active_run(self, max_age_seconds: float) -> dict | None:
        return runs.active_run("scout", max_age_seconds)

    # ---- profile ----
    def load_profile(self) -> dict | None:
        return profile.load_profile()

    def save_profile(self, new_profile: dict) -> dict:
        return profile.save_profile(new_profile)

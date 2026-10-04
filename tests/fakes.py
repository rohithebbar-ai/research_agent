"""One in-memory store with every method the CosmosStore has, for tests of the loop and the web API."""


class FakeStore:
    def __init__(self, ideas=None, trends=None, suggestions=None, runs=None, profile=None):
        self.ideas = list(ideas or [])
        self.trends = list(trends or [])
        self.suggestions = list(suggestions or [])
        self.runs = list(runs or [])
        self.sources = []
        self.profile = profile
        self.active = None            # set to a run dict to simulate one in progress
        self.profile_saves = []

    # ideas
    def list_ideas(self, status=None):
        return [dict(i) for i in self.ideas if status is None or i["status"] == status]

    def get_idea(self, idea_id):
        return next((dict(i) for i in self.ideas if i["id"] == idea_id), None)

    def add_idea(self, idea):
        self.ideas.append(idea)

    def save_idea(self, idea):
        self.ideas = [idea if i["id"] == idea["id"] else i for i in self.ideas]

    def find_by_topic_key(self, key):
        return next((i for i in self.ideas if i["topic_key"] == key), None)

    # sources
    def add_source(self, source):
        if any(s["id"] == source["id"] for s in self.sources):
            return False
        self.sources.append(source)
        return True

    def list_sources(self, idea_id):
        return [dict(s) for s in self.sources if s["idea_id"] == idea_id]

    def list_all_sources(self):
        return [dict(s) for s in self.sources]

    def get_source(self, idea_id, source_id):
        return next((dict(s) for s in self.sources if s["id"] == source_id and s["idea_id"] == idea_id), None)

    def save_source(self, source):
        self.sources = [source if s["id"] == source["id"] else s for s in self.sources]

    def delete_source(self, idea_id, source_id):
        self.sources = [s for s in self.sources if not (s["id"] == source_id and s["idea_id"] == idea_id)]

    # reading list
    def add_trend(self, item):
        self.trends.append(item)

    def find_trend_by_key(self, key):
        return next((t for t in self.trends if t["topic_key"] == key), None)

    def list_trends(self):
        return list(self.trends)

    # suggestions
    def list_suggestions(self, status=None):
        return [dict(s) for s in self.suggestions if status is None or s["status"] == status]

    def get_suggestion(self, suggestion_id):
        return next((dict(s) for s in self.suggestions if s["id"] == suggestion_id), None)

    def find_suggestion_by_key(self, key):
        return next((s for s in self.suggestions if s["topic_key"] == key), None)

    def add_suggestion(self, suggestion):
        self.suggestions.append(suggestion)

    def save_suggestion(self, suggestion):
        self.suggestions = [suggestion if s["id"] == suggestion["id"] else s for s in self.suggestions]

    # runs
    def list_runs(self, limit=50):
        return [{k: v for k, v in r.items() if k != "steps"} for r in self.runs][:limit]

    def get_run(self, run_id):
        return next((r for r in self.runs if r["id"] == run_id), None)

    def active_run(self, max_age_seconds):
        return self.active

    # profile
    def load_profile(self):
        return self.profile

    def save_profile(self, new_profile):
        saved = {**new_profile, "version": (self.profile or {}).get("version", 0) + 1}
        self.profile = saved
        self.profile_saves.append(saved)
        return saved

"""Scout's tools and the rules they enforce. No LLM in this file."""
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from tools.ideas import NEEDS, new_idea, topic_key
from tools.sources import sources_from_evidence
from tools.suggestions import new_suggestion

# The backlog cap counts only ideas still WAITING FOR YOUR DECISION. Approving or rejecting an idea
# (or the pipeline moving it on to researched / drafted) frees a slot for a new one.
ACTIVE_STATUSES = ("pending",)


def backlog_cap_from_env() -> int:
    """How many undecided ideas are allowed before runs pause (SCOUT_BACKLOG_CAP, default 8)."""
    return int(os.getenv("SCOUT_BACKLOG_CAP", "8"))


@dataclass
class ScoutConfig:
    mode: str = "weekly"                      # weekly | profile_changed | hold_only | explore
    profile_topics: set = field(default_factory=set)
    topic_areas: dict = field(default_factory=dict)   # profile topic key -> its area name
    area_names: set = field(default_factory=set)      # every area currently in the profile
    known_topics: set = field(default_factory=set)    # topic_key() of every profile topic + area
    avoid: list = field(default_factory=list)
    profile_version: int | None = None
    run_id: str = ""
    backlog_cap: int = 8
    max_proposals: int = 3
    max_holds: int = 5
    max_searches: int = 6
    max_suggestions: int = 3
    allowed_needs: tuple = NEEDS        # what the owner can run experiments on (from the profile)
    only_kind: str | None = None        # e.g. 'experiment': this run may only propose that kind
    trend_window_days: int = 30


def throttle_mode(ideas: list[dict], cap: int, last_run_started_at: str | None) -> str:
    """normal | skip | hold_only, decided before any LLM call.

    "Full" means `cap` ideas are still pending (undecided). Full -> skip once. If it is still full
    next run and some pending ideas were created before the last run started (undecided for a
    full cycle) -> hold_only.
    """
    active = [i for i in ideas if i["status"] in ACTIVE_STATUSES]
    if len(active) < cap:
        return "normal"
    stale = [
        i for i in ideas
        if i["status"] == "pending" and last_run_started_at and i["created_at"] < last_run_started_at
    ]
    return "hold_only" if stale else "skip"


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _parse_date(value) -> datetime | None:
    """Tavily gives RFC 2822 ('Thu, 10 Sep 2026 18:22:35 GMT'); also accept ISO."""
    if not value or not isinstance(value, str):
        return None
    try:
        d = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(value[:10])
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def trending_evidence_ok(evidence: list[dict], now: datetime, window_days: int) -> bool:
    """>= 2 distinct domains, each with a published_date inside the window."""
    domains = set()
    for item in evidence or []:
        date = _parse_date(item.get("published_date"))
        if date and timedelta(0) <= now - date <= timedelta(days=window_days):
            domains.add(_domain(item.get("url", "")))
    domains.discard("")
    return len(domains) >= 2


class ScoutTools:
    """The tool functions the model can call. Every method returns a string."""

    def __init__(self, store, search, config: ScoutConfig, now: datetime | None = None):
        self.store = store      # needs list_ideas, add_idea, find_by_topic_key,
                                # find_trend_by_key, add_trend
        self.search = search    # search(query, max_results, news, time_range) -> list[dict]
        self.config = config
        self.now = now or datetime.now(timezone.utc)
        self.proposed: list[str] = []
        self.held: list[str] = []
        self.suggested: list[str] = []
        self.searches = 0
        self.queries: list[str] = []
        self.finished = False
        self.summary = ""
        self._avoid_keys = {topic_key(a) for a in config.avoid}
        self._handlers = {
            "read_backlog": self.read_backlog,
            "search_web": self.search_web,
            "propose_idea": self.propose_idea,
            "hold_trend": self.hold_trend,
            "suggest_topic": self.suggest_topic,
            "finish": self.finish,
        }

    def call(self, name: str, args) -> str:
        """Run a tool by name. Never raises: problems come back as 'ERROR: ...' text."""
        handler = self._handlers.get(name)
        if handler is None:
            return f"ERROR: unknown tool {name!r}"
        if not isinstance(args, dict):
            return "ERROR: tool arguments must be a JSON object"
        try:
            return handler(**args)
        except TypeError as e:
            return f"ERROR: bad arguments: {e}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

    # ---- read-only tools ----------------------------------------------------

    def read_backlog(self, status: str | None = None, profile_topic: str | None = None) -> str:
        ideas = self.store.list_ideas(status)
        if profile_topic:
            ideas = [i for i in ideas if i.get("profile_topic") == profile_topic]
        rows = [
            {"id": i["id"], "topic": i["topic"], "status": i["status"],
             "kind": i.get("kind"), "profile_topic": i.get("profile_topic")}
            for i in ideas
        ]
        return json.dumps(rows)

    def search_web(self, query: str, recency: str = "any", news: bool = False) -> str:
        if self.searches >= self.config.max_searches:
            return f"ERROR: search limit reached ({self.config.max_searches} per run)"
        if recency not in ("any", "week", "month"):
            return "ERROR: recency must be one of any, week, month"
        self.searches += 1
        self.queries.append(query)
        results = self.search(query, 5, news, None if recency == "any" else recency)
        return json.dumps([
            {"title": r["title"], "url": r["url"],
             "published_date": r.get("published_date", ""), "content": r["content"][:300]}
            for r in results
        ])

    # ---- tools that write ---------------------------------------------------

    def _duplicate_of(self, key: str) -> str | None:
        hit = self.store.find_by_topic_key(key)
        if hit:
            return f"idea {hit['id']} (status {hit['status']})"
        hit = self.store.find_trend_by_key(key)
        if hit:
            return f"reading-list item {hit['id']}"
        return None

    def propose_idea(self, topic: str, angle: str, kind: str, profile_topic: str,
                     rationale: str, evidence: list | None = None, brief: str = "",
                     experiment: dict | None = None, builds_on: str | None = None) -> str:
        cfg = self.config
        if cfg.mode == "explore":
            return "ERROR: proposing ideas is switched off in explore runs; use suggest_topic"
        if cfg.mode == "hold_only":
            return "ERROR: proposing is switched off this run (backlog full); use hold_trend"
        if cfg.only_kind and kind != cfg.only_kind:
            return f"ERROR: this run only accepts '{cfg.only_kind}' ideas, not '{kind}'"
        if len(self.proposed) >= cfg.max_proposals:
            return f"ERROR: proposal limit reached ({cfg.max_proposals} per run)"
        active = sum(1 for i in self.store.list_ideas() if i["status"] in ACTIVE_STATUSES)
        if active >= cfg.backlog_cap:
            return f"ERROR: backlog is full ({active}/{cfg.backlog_cap} ideas are still waiting for the owner's decision)"
        if cfg.profile_topics and profile_topic not in cfg.profile_topics:
            return (f"ERROR: profile_topic {profile_topic!r} is not allowed in this run; "
                    f"use one of {sorted(cfg.profile_topics)}")
        key = topic_key(topic)
        if key in self._avoid_keys:
            return f"ERROR: {topic!r} is on the avoid list (you already know the basics)"
        dup = self._duplicate_of(key)
        if dup:
            return f"ERROR: duplicate of {dup}"
        if kind == "trending" and not trending_evidence_ok(
                evidence or [], self.now, cfg.trend_window_days):
            return (f"ERROR: kind=trending needs evidence from at least 2 different sites, "
                    f"each with a published_date in the last {cfg.trend_window_days} days")
        if builds_on:
            parent = self.store.get_idea(builds_on)
            if parent is None or parent["status"] == "rejected":
                return f"ERROR: builds_on {builds_on!r} is not an existing, non-rejected idea (see the ids in the briefing)"
        idea = new_idea(topic, angle, kind, profile_topic, rationale,
                        source="trending" if kind == "trending" else "scout",
                        area=cfg.topic_areas.get(profile_topic),
                        evidence=evidence, run_id=cfg.run_id,
                        profile_version=cfg.profile_version, brief=brief,
                        experiment=experiment, builds_on=builds_on or None,
                        allowed_needs=cfg.allowed_needs)
        self.store.add_idea(idea)
        for source in sources_from_evidence(idea):   # the citation URLs, kept so the owner can open and mark them
            self.store.add_source(source)
        self.proposed.append(idea["id"])
        return f"OK: proposed {idea['id']}"

    def hold_trend(self, topic: str, why: str, evidence: list | None = None) -> str:
        cfg = self.config
        if len(self.held) >= cfg.max_holds:
            return f"ERROR: reading-list limit reached ({cfg.max_holds} per run)"
        key = topic_key(topic)
        if key in self._avoid_keys:
            return f"ERROR: {topic!r} is on the avoid list"
        dup = self._duplicate_of(key)
        if dup:
            return f"ERROR: duplicate of {dup}"
        item = {
            "id": f"trend_{uuid.uuid4().hex[:12]}", "topic": topic.strip(), "topic_key": key,
            "why": why, "evidence": evidence or [],
            "created_at": datetime.now(timezone.utc).isoformat(), "run_id": cfg.run_id,
        }
        self.store.add_trend(item)
        self.held.append(item["id"])
        return f"OK: added to reading list {item['id']}"

    def suggest_topic(self, name: str, area: str, why: str, evidence: list | None = None) -> str:
        """Suggest a new sub-topic (area = an existing area) or a whole new area (a new area name)."""
        cfg = self.config
        if len(self.suggested) >= cfg.max_suggestions:
            return f"ERROR: suggestion limit reached ({cfg.max_suggestions} per run)"
        key = topic_key(name)
        if key in cfg.known_topics:
            return f"ERROR: {name!r} is already in the profile"
        before = self.store.find_suggestion_by_key(key)
        if before:
            return f"ERROR: already suggested before (status {before['status']}); do not repeat it"
        kind = "subtopic" if area in cfg.area_names else "new_area"
        suggestion = new_suggestion(name, area, why, kind, evidence=evidence, run_id=cfg.run_id)
        self.store.add_suggestion(suggestion)
        self.suggested.append(suggestion["id"])
        return f"OK: suggested {suggestion['id']} ({kind})"

    def finish(self, summary: str = "") -> str:
        self.finished = True
        self.summary = summary
        return "OK: run finished"

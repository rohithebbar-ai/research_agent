"""Local web API + page for reviewing Scout's work.

    uvicorn app.api:app --host 127.0.0.1 --port 8000

Local only: it binds to 127.0.0.1, rejects other Host headers, sends a strict
Content-Security-Policy, and every write needs a JSON body (browsers cannot send one
cross-site without a CORS preflight, which this app never answers).
"""
import logging
import threading
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agents.scout import RUN_MODES, TIME_BUDGET_SECONDS, run_scout
from agents.scout_tools import ACTIVE_STATUSES, backlog_cap_from_env
from tools.ideas import AGENT_OWNED, KINDS, USER_STATUSES, plan_edit, plan_status_change, with_changes
from tools.profile import allowed_resources, area_of, area_topics, changed_topics, profile_with_topic, topic_levels, validate_profile
from tools.runs import run_state
from tools.sources import new_source, plan_source_update, sort_sources, source_counts
from tools.store import CosmosStore
from tools.ideas import topic_key
from tools.suggestions import new_suggestion, plan_suggestion_status, slugify

log = logging.getLogger("app")
STATIC = Path(__file__).parent / "static"
RUN_MAX_AGE = TIME_BUDGET_SECONDS + 60     # a 'running' record older than this = crashed
LAUNCH_COOLDOWN_SECONDS = 8                # blocks a double-click before the run's record exists

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


# ---- dependencies (tests replace these with fakes) ------------------------------------------------

_store = None


def get_store():
    global _store
    if _store is None:
        _store = CosmosStore()
    return _store


def launch_run(mode: str, area: str | None, run_id: str, store, topic: str | None = None,
               only_kind: str | None = None) -> None:
    """Start Scout in a background thread so the request returns immediately."""
    def work():
        try:
            run_scout(mode=mode, area=area, run_id=run_id, store=store, topic=topic, only_kind=only_kind)
        except Exception:
            log.exception("run %s failed", run_id)   # the run record already says 'error'
    threading.Thread(target=work, daemon=True).start()


def get_launcher():
    return launch_run


# ---- request bodies -------------------------------------------------------------------------------

class StatusBody(BaseModel):
    status: str
    reason: str | None = None


class EditBody(BaseModel):
    topic: str | None = None
    angle: str | None = None
    kind: str | None = None
    rationale: str | None = None
    brief: str | None = None
    profile_topic: str | None = None
    experiment: dict | None = None


class SourceBody(BaseModel):
    url: str
    title: str = ""
    note: str = ""
    important: bool = False


class SourceUpdateBody(BaseModel):
    important: bool | None = None
    note: str | None = None


class RunBody(BaseModel):
    mode: str = "weekly"
    area: str | None = None
    topic: str | None = None      # one sub-topic; its area is filled in automatically
    only_kind: str | None = None  # propose only this kind of idea, e.g. 'experiment'


class ProfileBody(BaseModel):
    areas: list[dict]
    avoid: list[str] = []
    mix: dict[str, int] = {}
    resources: list[str] | None = None   # what experiments may need; omitted = keep what is saved


class SuggestionBody(BaseModel):
    status: str
    level: str | None = None


class NewSuggestionBody(BaseModel):
    name: str
    area: str                # an existing field to add a sub-topic to, or a new field's name
    why: str = ""


# ---- helpers ----------------------------------------------------------------------------------------

def _clean(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _idea_row(idea: dict, profile: dict | None, counts: dict | None = None,
              topics_by_id: dict | None = None) -> dict:
    """An idea as the page shows it: the field (area) is looked up in the CURRENT profile."""
    row = _clean(idea)
    row["area"] = (area_of(profile, idea.get("profile_topic")) if profile else None) or "unlisted"
    row["owner_editable"] = idea["status"] in USER_STATUSES
    mine = (counts or {}).get(idea["id"], {})
    row["sources_total"], row["sources_important"] = mine.get("total", 0), mine.get("important", 0)
    row["builds_on_topic"] = (topics_by_id or {}).get(idea.get("builds_on"))   # the idea this follows up, by name
    return row


def _parent_topics(store, idea: dict) -> dict:
    parent = store.get_idea(idea["builds_on"]) if idea.get("builds_on") else None
    return {parent["id"]: parent["topic"]} if parent else {}


def _bad_request(message) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


# ---- the app ---------------------------------------------------------------------------------------

def create_app(allowed_hosts=("127.0.0.1", "localhost")) -> FastAPI:
    app = FastAPI(title="Scout review", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))
    launch_lock = threading.Lock()
    launched_at = {"t": -1e9}

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    # ---- ideas ----
    @app.get("/api/ideas")
    def list_ideas(status: str | None = None, store=Depends(get_store)):
        profile = store.load_profile()
        ideas = sorted(store.list_ideas(status), key=lambda i: i.get("created_at", ""), reverse=True)
        counts = source_counts(store.list_all_sources())
        topics_by_id = {i["id"]: i["topic"] for i in store.list_ideas()}
        return [_idea_row(i, profile, counts, topics_by_id) for i in ideas]

    @app.post("/api/ideas/{idea_id}/status")
    def set_idea_status(idea_id: str, body: StatusBody, store=Depends(get_store)):
        idea = store.get_idea(idea_id)
        if idea is None:
            raise HTTPException(404, "no such idea")
        try:
            changes = plan_status_change(idea, body.status, body.reason)
        except ValueError as e:
            raise _bad_request(str(e))
        updated = with_changes(idea, changes)
        store.save_idea(updated)
        return _idea_row(updated, store.load_profile(), source_counts(store.list_sources(idea_id)),
                         _parent_topics(store, updated))

    @app.patch("/api/ideas/{idea_id}")
    def edit_idea(idea_id: str, body: EditBody, store=Depends(get_store)):
        idea = store.get_idea(idea_id)
        if idea is None:
            raise HTTPException(404, "no such idea")
        if idea["status"] in AGENT_OWNED:
            raise _bad_request(f"this idea is '{idea['status']}': the pipeline owns it now")
        try:
            changes = plan_edit(idea, body.model_dump(exclude_none=True), store.find_by_topic_key,
                                allowed_needs=allowed_resources(store.load_profile()))
        except ValueError as e:
            raise _bad_request(str(e))
        updated = with_changes(idea, changes)
        store.save_idea(updated)
        return _idea_row(updated, store.load_profile(), source_counts(store.list_sources(idea_id)),
                         _parent_topics(store, updated))

    @app.get("/api/limits")
    def limits(store=Depends(get_store)):
        """How full the backlog is. A run pauses when `pending` reaches `backlog_cap`."""
        pending = sum(1 for i in store.list_ideas() if i["status"] in ACTIVE_STATUSES)
        cap = backlog_cap_from_env()
        return {"backlog_cap": cap, "pending": pending, "full": pending >= cap}

    # ---- sources (citation URLs) ----
    # Marks live on the source, and are allowed at any idea status: you will want to star
    # sources for an idea the pipeline has already researched or drafted.
    @app.get("/api/ideas/{idea_id}/sources")
    def list_sources(idea_id: str, store=Depends(get_store)):
        if store.get_idea(idea_id) is None:
            raise HTTPException(404, "no such idea")
        return [_clean(x) for x in sort_sources(store.list_sources(idea_id))]

    @app.post("/api/ideas/{idea_id}/sources")
    def add_source(idea_id: str, body: SourceBody, store=Depends(get_store)):
        if store.get_idea(idea_id) is None:
            raise HTTPException(404, "no such idea")
        try:
            source = new_source(idea_id, body.url, title=body.title, found_by="you",
                                note=body.note, important=body.important)
        except ValueError as e:
            raise _bad_request(str(e))
        if not store.add_source(source):   # already registered (maybe found by Scout): keep it, apply your marks
            source = store.get_source(idea_id, source["id"])
            changes = {k: v for k, v in (("note", body.note), ("important", body.important or None)) if v}
            if changes:
                source = {**source, **plan_source_update(source, changes)}
                store.save_source(source)
        return _clean(source)

    @app.patch("/api/ideas/{idea_id}/sources/{source_id}")
    def update_source(idea_id: str, source_id: str, body: SourceUpdateBody, store=Depends(get_store)):
        source = store.get_source(idea_id, source_id)
        if source is None:
            raise HTTPException(404, "no such source")
        try:
            changes = plan_source_update(source, body.model_dump(exclude_none=True))
        except ValueError as e:
            raise _bad_request(str(e))
        updated = {**source, **changes}
        store.save_source(updated)
        return _clean(updated)

    @app.delete("/api/ideas/{idea_id}/sources/{source_id}")
    def delete_source(idea_id: str, source_id: str, store=Depends(get_store)):
        source = store.get_source(idea_id, source_id)
        if source is None:
            raise HTTPException(404, "no such source")
        if source["found_by"] != "you":
            raise _bad_request("only URLs you added can be removed; for the others, un-star them instead")
        store.delete_source(idea_id, source_id)
        return {"deleted": source_id}

    # ---- runs ----
    @app.get("/api/runs")
    def list_runs(store=Depends(get_store)):
        return [{**_clean(r), "state": run_state(r, RUN_MAX_AGE)} for r in store.list_runs(50)]

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, store=Depends(get_store)):
        run = store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "no such run")
        return {**_clean(run), "state": run_state(run, RUN_MAX_AGE)}

    @app.post("/api/runs", status_code=202)
    def start_run(body: RunBody, store=Depends(get_store), launcher=Depends(get_launcher)):
        if body.mode not in RUN_MODES:
            raise _bad_request(f"mode must be one of {list(RUN_MODES)}")
        profile = store.load_profile()
        if profile is None:
            raise _bad_request("there is no profile yet")
        if body.only_kind is not None:
            if body.only_kind not in KINDS:
                raise _bad_request(f"only_kind must be one of {sorted(KINDS)}")
            if body.mode == "explore":
                raise _bad_request("an explore run does not propose ideas, so it cannot be limited to one kind")
        areas = area_topics(profile)
        if body.area is not None and body.area not in areas:
            raise _bad_request(f"unknown area {body.area!r}")
        if body.topic is not None:
            if body.topic not in topic_levels(profile):
                raise _bad_request(f"unknown sub-topic {body.topic!r}")
            if body.area is not None and body.topic not in areas[body.area]:
                raise _bad_request(f"sub-topic {body.topic!r} is not in area {body.area!r}")
        with launch_lock:
            if time.monotonic() - launched_at["t"] < LAUNCH_COOLDOWN_SECONDS or store.active_run(RUN_MAX_AGE):
                raise HTTPException(409, "a run is already in progress")
            run_id = f"run_{uuid.uuid4().hex[:10]}"
            launcher(body.mode, body.area, run_id, store, body.topic, body.only_kind)
            launched_at["t"] = time.monotonic()
        return {"run_id": run_id}

    # ---- profile ----
    @app.get("/api/profile")
    def get_profile(store=Depends(get_store)):
        profile = store.load_profile()
        return _clean(profile) if profile else {"areas": [], "avoid": [], "mix": {}, "version": 0}

    @app.put("/api/profile")
    def put_profile(body: ProfileBody, store=Depends(get_store)):
        current = store.load_profile()
        new = {"areas": body.areas, "avoid": body.avoid, "mix": body.mix}
        resources = body.resources if body.resources is not None else (current or {}).get("resources")
        if resources is not None:
            new["resources"] = resources
        errors = validate_profile(new)
        if errors:
            raise HTTPException(400, {"errors": errors})
        saved = store.save_profile(new)
        # Saving never starts a run (that spends credits); the page offers a button for it.
        return {"profile": _clean(saved), "changed_topics": changed_topics(current, saved)}

    # ---- suggestions ----
    @app.get("/api/suggestions")
    def list_suggestions(status: str | None = None, store=Depends(get_store)):
        rows = sorted(store.list_suggestions(status), key=lambda s: s.get("created_at", ""), reverse=True)
        return [_clean(s) for s in rows]

    @app.post("/api/suggestions")
    def add_suggestion(body: NewSuggestionBody, store=Depends(get_store)):
        """Suggest a topic yourself (for example something new you heard about). It joins the same
        list as Scout's suggestions: accept it to add it to your profile, then run Scout on it."""
        profile = store.load_profile() or {"areas": []}
        areas = set(area_topics(profile)) if profile["areas"] else set()
        kind = "subtopic" if slugify(body.area) in areas else "new_area"
        try:
            suggestion = new_suggestion(body.name, body.area, body.why, kind, source="you")
        except ValueError as e:
            raise _bad_request(str(e))
        known = {topic_key(k) for k in topic_levels(profile)} | {topic_key(a) for a in areas} if profile["areas"] else set()
        if suggestion["topic_key"] in known:
            raise _bad_request(f"{body.name!r} is already in your profile")
        before = store.find_suggestion_by_key(suggestion["topic_key"])
        if before:
            raise HTTPException(409, f"already suggested (status {before['status']}); change its status in the list instead")
        store.add_suggestion(suggestion)
        return _clean(suggestion)

    @app.post("/api/suggestions/{suggestion_id}/status")
    def set_suggestion_status(suggestion_id: str, body: SuggestionBody, store=Depends(get_store)):
        suggestion = store.get_suggestion(suggestion_id)
        if suggestion is None:
            raise HTTPException(404, "no such suggestion")
        try:
            changes = plan_suggestion_status(suggestion, body.status)
        except ValueError as e:
            raise _bad_request(str(e))

        note = None
        if body.status == "accepted":
            profile = store.load_profile()
            if profile is None:
                raise _bad_request("there is no profile to add the topic to")
            if suggestion["key"] in topic_levels(profile):
                note = "already in the profile"
            else:
                level = body.level or suggestion.get("level", "curious")
                try:
                    store.save_profile(profile_with_topic(profile, suggestion["area"], suggestion["key"], level))
                except ValueError as e:
                    raise _bad_request(str(e))
                changes["level"] = level
                note = "added to the profile"
        elif suggestion["status"] == "accepted":
            note = ("the profile was NOT changed: remove the topic in the Profile tab "
                    "if you no longer want it there")

        updated = {**suggestion, **changes}
        store.save_suggestion(updated)
        return {"suggestion": _clean(updated), "note": note}

    return app


app = create_app()

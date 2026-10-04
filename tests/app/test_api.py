from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import api
from tests.fakes import FakeStore
from tools.ideas import new_idea
from tools.suggestions import new_suggestion

PROFILE = {
    "id": "profile", "version": 3,
    "areas": [
        {"name": "agents", "topics": [{"key": "multi-agent", "level": "curious"}]},
        {"name": "cv", "topics": [{"key": "3d-estimation", "level": "learning"}]},
    ],
    "avoid": ["what is a transformer"], "mix": {"trending": 1},
}


def idea(topic, profile_topic="multi-agent", status="pending", created_at="2026-10-01T00:00:00+00:00",
         kind=None, experiment=None, **kw):
    i = new_idea(topic, "niche", "deep-dive", profile_topic, "because", **kw)
    i.update(status=status, created_at=created_at)
    if kind:
        i["kind"] = kind                # set directly: these tests are about the API, not new_idea's checks
    if experiment:
        i["experiment"] = experiment
    return i


def minutes_ago(n):
    return (datetime.now(timezone.utc) - timedelta(minutes=n)).isoformat()


class Harness:
    def __init__(self, **store_kwargs):
        import copy
        self.store = FakeStore(profile=copy.deepcopy(PROFILE), **store_kwargs)
        self.launched = []
        app = api.create_app(allowed_hosts=("testserver",))
        app.dependency_overrides[api.get_store] = lambda: self.store
        app.dependency_overrides[api.get_launcher] = lambda: (lambda *args: self.launched.append(args))
        self.client = TestClient(app)


@pytest.fixture
def h():
    return Harness()


# ---- ideas ---------------------------------------------------------------------------------------

def test_ideas_come_back_newest_first_with_the_field_from_the_current_profile():
    h = Harness(ideas=[idea("Older", created_at="2026-10-01T00:00:00+00:00"),
                       idea("Newer", "3d-estimation", created_at="2026-10-05T00:00:00+00:00")])
    rows = h.client.get("/api/ideas").json()
    assert [r["topic"] for r in rows] == ["Newer", "Older"]
    assert [r["area"] for r in rows] == ["cv", "agents"]


def test_an_idea_whose_topic_left_the_profile_shows_as_unlisted():
    h = Harness(ideas=[idea("Orphan", profile_topic="removed-topic")])
    assert h.client.get("/api/ideas").json()[0]["area"] == "unlisted"


def test_status_filter_and_system_fields_are_hidden():
    i = idea("Has system field")
    i["_etag"] = "secret"
    h = Harness(ideas=[i, idea("Approved one", status="approved")])
    rows = h.client.get("/api/ideas", params={"status": "pending"}).json()
    assert [r["topic"] for r in rows] == ["Has system field"] and "_etag" not in rows[0]


def test_owner_can_reject_then_change_their_mind_and_approve():
    i = idea("Maybe later")
    h = Harness(ideas=[i])
    r = h.client.post(f"/api/ideas/{i['id']}/status", json={"status": "rejected", "reason": "not now"}).json()
    assert (r["status"], r["reject_reason"]) == ("rejected", "not now")
    r = h.client.post(f"/api/ideas/{i['id']}/status", json={"status": "approved"}).json()
    assert (r["status"], r["reject_reason"]) == ("approved", None)
    assert h.store.get_idea(i["id"])["status"] == "approved"   # persisted, not just returned


@pytest.mark.parametrize("owned", ["researched", "held", "drafted", "published"])
def test_the_page_cannot_change_a_pipeline_owned_idea(owned):
    i = idea("Owned", status=owned)
    h = Harness(ideas=[i])
    r = h.client.post(f"/api/ideas/{i['id']}/status", json={"status": "pending"})
    assert r.status_code == 400 and "pipeline owns" in r.json()["detail"]
    assert h.store.get_idea(i["id"])["status"] == owned
    assert h.client.get("/api/ideas").json()[0]["owner_editable"] is False


def test_setting_a_pipeline_status_by_hand_is_refused(h):
    h.store.ideas = [idea("X")]
    r = h.client.post(f"/api/ideas/{h.store.ideas[0]['id']}/status", json={"status": "published"})
    assert r.status_code == 400


def test_unknown_idea_is_404(h):
    assert h.client.post("/api/ideas/nope/status", json={"status": "approved"}).status_code == 404
    assert h.client.patch("/api/ideas/nope", json={"topic": "x"}).status_code == 404


def test_editing_an_idea_validates_and_recomputes_the_key():
    i, other = idea("Original"), idea("Taken topic")
    h = Harness(ideas=[i, other])
    ok = h.client.patch(f"/api/ideas/{i['id']}", json={"topic": "  KV caching explained ", "angle": "broad"})
    assert ok.status_code == 200 and ok.json()["topic_key"] == "kv cach" and ok.json()["angle"] == "broad"
    assert h.client.patch(f"/api/ideas/{i['id']}", json={"topic": "Taken topic"}).status_code == 400
    assert h.client.patch(f"/api/ideas/{i['id']}", json={"angle": "huge"}).status_code == 400
    assert h.client.patch(f"/api/ideas/{i['id']}", json={"topic": "x" * 300}).status_code == 400


def test_a_pipeline_owned_idea_cannot_be_edited():
    i = idea("Owned", status="drafted")
    h = Harness(ideas=[i])
    assert h.client.patch(f"/api/ideas/{i['id']}", json={"rationale": "new"}).status_code == 400


# ---- runs ----------------------------------------------------------------------------------------

def test_runs_list_omits_steps_and_marks_fresh_and_stale_running_records():
    runs = [
        {"id": "r_fresh", "status": "running", "updated_at": minutes_ago(1), "started_at": minutes_ago(2), "steps": [1]},
        {"id": "r_crash", "status": "running", "updated_at": minutes_ago(60), "started_at": minutes_ago(61), "steps": [1]},
        {"id": "r_old", "stopped_reason": "finished", "started_at": minutes_ago(500), "steps": [1]},
        {"id": "r_err", "status": "error", "started_at": minutes_ago(600), "steps": [1]},
    ]
    h = Harness(runs=runs)
    rows = {r["id"]: r for r in h.client.get("/api/runs").json()}
    assert {k: v["state"] for k, v in rows.items()} == {
        "r_fresh": "running", "r_crash": "crashed", "r_old": "done", "r_err": "error"}
    assert all("steps" not in r for r in rows.values())


def test_run_detail_includes_the_step_trace():
    h = Harness(runs=[{"id": "r1", "status": "done", "steps": [{"type": "tool", "tool": "finish"}]}])
    detail = h.client.get("/api/runs/r1").json()
    assert detail["steps"][0]["tool"] == "finish" and detail["state"] == "done"
    assert h.client.get("/api/runs/missing").status_code == 404


def test_starting_a_run_returns_202_immediately_and_launches_once(h):
    r = h.client.post("/api/runs", json={"mode": "weekly", "area": "agents"})
    assert r.status_code == 202
    mode, area, run_id, store, topic, only_kind = h.launched[0]
    assert (mode, area, run_id, topic, only_kind) == ("weekly", "agents", r.json()["run_id"], None, None) and store is h.store


def test_a_double_click_does_not_start_two_runs(h):
    assert h.client.post("/api/runs", json={"mode": "weekly"}).status_code == 202
    assert h.client.post("/api/runs", json={"mode": "weekly"}).status_code == 409
    assert len(h.launched) == 1


def test_a_run_already_in_progress_blocks_a_new_one(h):
    h.store.active = {"id": "run_other"}
    assert h.client.post("/api/runs", json={"mode": "weekly"}).status_code == 409
    assert h.launched == []


def test_a_run_can_target_one_sub_topic_and_the_launcher_receives_it(h):
    r = h.client.post("/api/runs", json={"mode": "weekly", "topic": "multi-agent"})
    assert r.status_code == 202
    mode, area, run_id, store, topic, only_kind = h.launched[0]
    assert (mode, area, topic) == ("weekly", None, "multi-agent")     # the area is filled in by the run itself


def test_a_sub_topic_inside_the_chosen_area_is_accepted(h):
    assert h.client.post("/api/runs", json={"mode": "weekly", "area": "cv", "topic": "3d-estimation"}).status_code == 202


@pytest.mark.parametrize("body,message", [
    ({"mode": "weekly", "topic": "no-such-topic"}, "unknown sub-topic"),
    ({"mode": "weekly", "area": "agents", "topic": "3d-estimation"}, "not in area"),   # real topic, wrong area
])
def test_a_bad_sub_topic_is_refused_and_launches_nothing(h, body, message):
    r = h.client.post("/api/runs", json=body)
    assert r.status_code == 400 and message in r.json()["detail"] and h.launched == []


@pytest.mark.parametrize("body", [{"mode": "banana"}, {"mode": "weekly", "area": "cooking"}])
def test_bad_run_requests_are_rejected_and_launch_nothing(h, body):
    assert h.client.post("/api/runs", json=body).status_code == 400
    assert h.launched == []


# ---- profile --------------------------------------------------------------------------------------

def test_profile_round_trip_and_save_reports_changed_topics_without_starting_a_run(h):
    new = {"areas": [{"name": "agents", "topics": [{"key": "multi-agent", "level": "know"},
                                                   {"key": "agentic-evals", "level": "curious"}]}],
           "avoid": [], "mix": {"trending": 2}}
    r = h.client.put("/api/profile", json=new).json()
    assert r["changed_topics"] == ["agentic-evals", "multi-agent"]   # one new, one level change
    assert h.store.profile["version"] == 4 and h.launched == []
    assert [a["name"] for a in h.client.get("/api/profile").json()["areas"]] == ["agents"]


def test_an_invalid_profile_is_rejected_with_readable_errors_and_nothing_is_saved(h):
    bad = {"areas": [{"name": "Bad Name", "topics": [{"key": "x", "level": "expert"}]}]}
    r = h.client.put("/api/profile", json=bad)
    assert r.status_code == 400 and len(r.json()["detail"]["errors"]) == 2
    assert h.store.profile_saves == []


# ---- suggestions -----------------------------------------------------------------------------------

def sug(name="World models", area="cv", **kw):
    return new_suggestion(name, area, "why", "subtopic", **kw)


def test_accepting_a_suggestion_adds_the_topic_to_the_profile_at_the_chosen_level():
    s = sug()
    h = Harness(suggestions=[s])
    r = h.client.post(f"/api/suggestions/{s['id']}/status", json={"status": "accepted", "level": "learning"}).json()
    assert r["note"] == "added to the profile" and r["suggestion"]["status"] == "accepted"
    topics = {t["key"]: t["level"] for a in h.store.profile["areas"] for t in a["topics"]}
    assert topics["world-models"] == "learning"


def test_accepting_a_new_area_suggestion_creates_the_area():
    s = new_suggestion("Qubits", "Quantum Computing", "why", "new_area")
    h = Harness(suggestions=[s])
    h.client.post(f"/api/suggestions/{s['id']}/status", json={"status": "accepted"})
    assert "quantum-computing" in [a["name"] for a in h.store.profile["areas"]]


def test_dismiss_then_accept_works_so_the_owner_can_change_their_mind():
    s = sug()
    h = Harness(suggestions=[s])
    path = f"/api/suggestions/{s['id']}/status"
    assert h.client.post(path, json={"status": "dismissed"}).json()["suggestion"]["status"] == "dismissed"
    assert h.store.profile_saves == []                      # dismissing never touches the profile
    assert h.client.post(path, json={"status": "accepted"}).json()["note"] == "added to the profile"
    assert h.store.get_suggestion(s["id"])["status"] == "accepted"


def test_un_accepting_leaves_the_profile_alone_and_says_so():
    s = sug()
    h = Harness(suggestions=[s])
    path = f"/api/suggestions/{s['id']}/status"
    h.client.post(path, json={"status": "accepted"})
    saves = len(h.store.profile_saves)
    r = h.client.post(path, json={"status": "dismissed"}).json()
    assert "NOT changed" in r["note"] and len(h.store.profile_saves) == saves


def test_re_accepting_does_not_add_the_topic_twice():
    s = sug()
    h = Harness(suggestions=[s])
    path = f"/api/suggestions/{s['id']}/status"
    h.client.post(path, json={"status": "accepted"})
    h.client.post(path, json={"status": "pending"})
    r = h.client.post(path, json={"status": "accepted"}).json()
    assert r["note"] == "already in the profile"
    assert sum(t["key"] == "world-models" for a in h.store.profile["areas"] for t in a["topics"]) == 1


def test_a_bad_suggestion_status_or_unknown_id_is_refused(h):
    s = sug()
    h.store.suggestions = [s]
    assert h.client.post(f"/api/suggestions/{s['id']}/status", json={"status": "maybe"}).status_code == 400
    assert h.client.post("/api/suggestions/nope/status", json={"status": "accepted"}).status_code == 404


def test_suggestions_list_newest_first_with_optional_status_filter():
    old, new = sug("Old one"), sug("New one")
    old["created_at"], new["created_at"] = "2026-10-01", "2026-10-05"
    new["status"] = "dismissed"
    h = Harness(suggestions=[old, new])
    assert [s["name"] for s in h.client.get("/api/suggestions").json()] == ["New one", "Old one"]
    assert [s["name"] for s in h.client.get("/api/suggestions", params={"status": "dismissed"}).json()] == ["New one"]


# ---- local-only protections ---------------------------------------------------------------------------

def test_security_headers_are_sent(h):
    r = h.client.get("/api/ideas")
    assert "script-src 'self'" in r.headers["content-security-policy"] and "unsafe-inline" not in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"


def test_a_foreign_host_header_is_refused(h):
    assert h.client.get("/api/ideas", headers={"host": "evil.example"}).status_code == 400


def test_writes_need_a_json_body_so_a_cross_site_form_post_cannot_trigger_them(h):
    h.store.ideas = [idea("X")]
    path = f"/api/ideas/{h.store.ideas[0]['id']}/status"
    plain = h.client.post(path, content='{"status": "approved"}', headers={"content-type": "text/plain"})
    form = h.client.post(path, data={"status": "approved"})
    assert plain.status_code == 422 and form.status_code == 422
    assert h.store.ideas[0]["status"] == "pending"


def test_the_page_and_its_assets_are_served(h):
    page = h.client.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert h.client.get("/static/app.js").status_code == 200 and h.client.get("/static/app.css").status_code == 200


# ---- sources: citation URLs you can open, star and annotate ----------------------------------------

from tools.sources import new_source


def idea_with_sources(**kw):
    i = idea("Has sources", **kw)
    a = new_source(i["id"], "https://a.com/one", title="First", found_by="scout")
    b = new_source(i["id"], "https://b.com/two", title="Second", found_by="scout")
    a["created_at"], b["created_at"] = "2026-10-01", "2026-10-02"
    return i, a, b


def harness_with_sources(**idea_kw):
    i, a, b = idea_with_sources(**idea_kw)
    h = Harness(ideas=[i])
    h.store.sources = [a, b]
    return h, i, a, b


def test_the_idea_list_carries_source_counts():
    h, i, a, b = harness_with_sources()
    b["important"] = True
    h.store.ideas.append(idea("No sources"))
    rows = {r["topic"]: r for r in h.client.get("/api/ideas").json()}
    assert (rows["Has sources"]["sources_total"], rows["Has sources"]["sources_important"]) == (2, 1)
    assert rows["No sources"]["sources_total"] == 0


def test_sources_list_puts_important_first_and_hides_system_fields():
    h, i, a, b = harness_with_sources()
    b["important"] = True
    b["_etag"] = "secret"
    got = h.client.get(f"/api/ideas/{i['id']}/sources").json()
    assert [s["title"] for s in got] == ["Second", "First"] and "_etag" not in got[0]
    assert h.client.get("/api/ideas/nope/sources").status_code == 404


def test_you_can_star_a_source_and_attach_a_note():
    h, i, a, b = harness_with_sources()
    r = h.client.patch(f"/api/ideas/{i['id']}/sources/{a['id']}", json={"important": True, "note": "read section 3"})
    assert r.status_code == 200 and r.json()["important"] is True and r.json()["note"] == "read section 3"
    saved = h.store.get_source(i["id"], a["id"])
    assert saved["important"] and saved["note"] == "read section 3"
    assert h.client.patch(f"/api/ideas/{i['id']}/sources/{a['id']}", json={"important": False}).json()["important"] is False


@pytest.mark.parametrize("owned", ["researched", "drafted", "published"])
def test_sources_can_be_starred_even_after_the_pipeline_owns_the_idea(owned):
    h, i, a, b = harness_with_sources(status=owned)
    assert h.client.patch(f"/api/ideas/{i['id']}/sources/{a['id']}", json={"important": True}).status_code == 200


def test_bad_source_updates_are_refused():
    h, i, a, b = harness_with_sources()
    path = f"/api/ideas/{i['id']}/sources/{a['id']}"
    assert h.client.patch(path, json={"note": "x" * 600}).status_code == 400
    assert h.client.patch(f"/api/ideas/{i['id']}/sources/nope", json={"important": True}).status_code == 404
    assert h.store.get_source(i["id"], a["id"])["note"] == ""


def test_you_can_add_your_own_url_and_it_is_tidied():
    h, i, a, b = harness_with_sources()
    r = h.client.post(f"/api/ideas/{i['id']}/sources",
                      json={"url": "https://Example.com/Great-Post/?utm_source=x#frag", "title": "Great", "note": "key idea", "important": True})
    body = r.json()
    assert r.status_code == 200 and body["url"] == "https://example.com/Great-Post"
    assert (body["found_by"], body["important"], body["note"]) == ("you", True, "key idea")
    assert len(h.store.list_sources(i["id"])) == 3


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "data:text/html,x", "not a url", "https://u:p@a.com/"])
def test_only_web_links_can_be_added(bad):
    h, i, a, b = harness_with_sources()
    assert h.client.post(f"/api/ideas/{i['id']}/sources", json={"url": bad}).status_code == 400
    assert len(h.store.list_sources(i["id"])) == 2


def test_adding_a_url_scout_already_found_keeps_one_record_and_applies_your_marks():
    h, i, a, b = harness_with_sources()
    r = h.client.post(f"/api/ideas/{i['id']}/sources", json={"url": "https://a.com/one/", "note": "mine", "important": True}).json()
    assert r["id"] == a["id"] and r["found_by"] == "scout"           # still Scout's record
    assert (r["important"], r["note"]) == (True, "mine")
    assert len(h.store.list_sources(i["id"])) == 2


def test_only_urls_you_added_can_be_removed():
    h, i, a, b = harness_with_sources()
    mine = h.client.post(f"/api/ideas/{i['id']}/sources", json={"url": "https://c.com/mine"}).json()
    assert h.client.delete(f"/api/ideas/{i['id']}/sources/{mine['id']}").json() == {"deleted": mine["id"]}
    scouts = h.client.delete(f"/api/ideas/{i['id']}/sources/{a['id']}")
    assert scouts.status_code == 400 and "un-star" in scouts.json()["detail"]
    assert {s["id"] for s in h.store.list_sources(i["id"])} == {a["id"], b["id"]}


def test_editing_the_brief_works_and_is_length_limited():
    h, i, a, b = harness_with_sources()
    ok = h.client.patch(f"/api/ideas/{i['id']}", json={"brief": "The post walks through X."})
    assert ok.status_code == 200 and ok.json()["brief"] == "The post walks through X."
    assert h.client.patch(f"/api/ideas/{i['id']}", json={"brief": "x" * 700}).status_code == 400


# ---- experiments -----------------------------------------------------------------------------------------------

PLAN = {"question": "How much faster?", "setup": "Run it twice.", "measure": "Tokens per second.",
        "effort": "hours", "needs": ["cpu"]}


def test_an_experiment_row_names_the_idea_it_builds_on():
    parent = idea("Explaining KV caching")
    child = idea("Measure KV caching", builds_on=parent["id"], kind="experiment", experiment=PLAN)
    h = Harness(ideas=[parent, child])
    rows = {r["topic"]: r for r in h.client.get("/api/ideas").json()}
    assert rows["Measure KV caching"]["builds_on_topic"] == "Explaining KV caching"
    assert rows["Measure KV caching"]["experiment"]["effort"] == "hours"
    assert rows["Explaining KV caching"]["builds_on_topic"] is None


def test_editing_an_experiment_plan_is_validated_against_the_profile_resources():
    e = idea("Measure it", kind="experiment", experiment=PLAN)
    h = Harness(ideas=[e])
    path = f"/api/ideas/{e['id']}"
    ok = h.client.patch(path, json={"experiment": {**PLAN, "effort": "weekend"}})
    assert ok.status_code == 200 and ok.json()["experiment"]["effort"] == "weekend"
    assert h.client.patch(path, json={"experiment": {**PLAN, "effort": "week"}}).status_code == 400
    gpu = h.client.patch(path, json={"experiment": {**PLAN, "needs": ["small-gpu"]}})
    assert gpu.status_code == 400 and "only has" in gpu.json()["detail"]      # the test profile has no resources: a laptop
    h.store.profile["resources"] = ["cpu", "small-gpu"]
    assert h.client.patch(path, json={"experiment": {**PLAN, "needs": ["small-gpu"]}}).status_code == 200


def test_the_kind_experiment_cannot_be_set_without_a_plan(h):
    i = idea("A plain idea")
    h.store.ideas = [i]
    assert h.client.patch(f"/api/ideas/{i['id']}", json={"kind": "experiment"}).status_code == 400
    assert h.client.patch(f"/api/ideas/{i['id']}", json={"kind": "experiment", "experiment": PLAN}).status_code == 200


def test_profile_resources_are_saved_validated_and_kept_when_omitted():
    h = Harness()
    base = {"areas": [{"name": "agents", "topics": [{"key": "multi-agent", "level": "curious"}]}]}
    bad = h.client.put("/api/profile", json={**base, "resources": ["quantum"]})
    assert bad.status_code == 400 and "resources" in bad.json()["detail"]["errors"][0]
    assert h.store.profile_saves == []
    good = h.client.put("/api/profile", json={**base, "resources": ["cpu", "small-gpu"]}).json()
    assert good["profile"]["resources"] == ["cpu", "small-gpu"]
    again = h.client.put("/api/profile", json=base).json()          # resources omitted this time
    assert again["profile"]["resources"] == ["cpu", "small-gpu"]    # ...so the saved value is kept


def test_the_experiment_mix_count_is_saved_with_the_profile():
    h = Harness()
    base = {"areas": [{"name": "agents", "topics": [{"key": "multi-agent", "level": "curious"}]}],
            "mix": {"trending": 1, "experiment": 2, "refresher_or_deep_dive": 0}}
    assert h.client.put("/api/profile", json=base).json()["profile"]["mix"]["experiment"] == 2


def test_limits_report_how_full_the_backlog_is_counting_only_undecided_ideas(monkeypatch):
    monkeypatch.setenv("SCOUT_BACKLOG_CAP", "3")
    h = Harness(ideas=[idea("A one"), idea("B two"), idea("C three", status="approved"),
                       idea("D four", status="rejected"), idea("E five", status="drafted")])
    assert h.client.get("/api/limits").json() == {"backlog_cap": 3, "pending": 2, "full": False}
    h.store.ideas.append(idea("F six"))
    assert h.client.get("/api/limits").json() == {"backlog_cap": 3, "pending": 3, "full": True}


def test_a_run_can_be_limited_to_one_kind_of_idea_and_the_launcher_receives_it(h):
    r = h.client.post("/api/runs", json={"mode": "weekly", "only_kind": "experiment", "topic": "multi-agent"})
    assert r.status_code == 202
    assert h.launched[0][4:] == ("multi-agent", "experiment")


@pytest.mark.parametrize("body,message", [
    ({"mode": "weekly", "only_kind": "poem"}, "only_kind must be one of"),
    ({"mode": "explore", "only_kind": "experiment"}, "explore run does not propose ideas"),
])
def test_a_bad_only_kind_is_refused_and_launches_nothing(h, body, message):
    r = h.client.post("/api/runs", json=body)
    assert r.status_code == 400 and message in r.json()["detail"] and h.launched == []


# ---- suggesting a topic yourself -----------------------------------------------------------------------------

def test_you_can_suggest_a_sub_topic_for_an_existing_field():
    h = Harness()
    r = h.client.post("/api/suggestions", json={"name": "Jev decision models", "area": "agents", "why": "typed probabilistic decisions"})
    body = r.json()
    assert r.status_code == 200 and (body["source"], body["kind"], body["area"], body["status"]) == ("you", "subtopic", "agents", "pending")
    assert h.store.suggestions[0]["name"] == "Jev decision models"


def test_a_new_field_name_makes_a_new_area_suggestion():
    h = Harness()
    body = h.client.post("/api/suggestions", json={"name": "Jev", "area": "Decision Models", "why": ""}).json()
    assert (body["kind"], body["area"]) == ("new_area", "decision-models")


def test_the_whole_flow_suggest_accept_then_run_scout_on_it():
    h = Harness()
    s = h.client.post("/api/suggestions", json={"name": "Jev", "area": "agents", "why": "new"}).json()
    done = h.client.post(f"/api/suggestions/{s['id']}/status", json={"status": "accepted", "level": "curious"}).json()
    assert done["note"] == "added to the profile"
    r = h.client.post("/api/runs", json={"mode": "weekly", "topic": "jev"})      # the new sub-topic is now a valid focus
    assert r.status_code == 202 and h.launched[0][4] == "jev"


@pytest.mark.parametrize("body,message", [
    ({"name": "multi-agent", "area": "agents"}, "already in your profile"),       # a topic that is already tracked
    ({"name": "Agents", "area": "agents"}, "already in your profile"),            # a field name counts too
    ({"name": "", "area": "agents"}, "empty"),
    ({"name": "x" * 100, "area": "agents"}, "characters"),
    ({"name": "Okay", "area": "!!!"}, "area is empty"),
])
def test_a_bad_self_suggestion_is_refused_and_nothing_is_stored(body, message):
    h = Harness()
    r = h.client.post("/api/suggestions", json=body)
    assert r.status_code == 400 and message in r.json()["detail"] and h.store.suggestions == []


def test_suggesting_something_already_suggested_points_you_to_the_existing_one():
    h = Harness(suggestions=[{**new_suggestion("Jev", "agents", "w", "subtopic"), "status": "dismissed"}])
    r = h.client.post("/api/suggestions", json={"name": "How does Jev work", "area": "agents"})
    assert r.status_code == 409 and "dismissed" in r.json()["detail"] and len(h.store.suggestions) == 1


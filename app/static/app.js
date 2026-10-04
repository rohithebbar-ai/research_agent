"use strict";
/* Scout review page. No innerHTML anywhere: everything is built from text nodes, because idea titles,
   rationales and source titles come from a model and from the open web. Links are only created for
   http(s) URLs. */

// ---------------------------------------------------------------- helpers
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false || k === "value") continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  if (attrs && attrs.value !== undefined && attrs.value !== null) el.value = attrs.value; // after <option>s exist
  return el;
}

function safeLink(url, label) {
  try {
    const u = new URL(url);
    if (u.protocol === "http:" || u.protocol === "https:") {
      return h("a", { href: u.href, target: "_blank", rel: "noopener noreferrer" }, label || u.hostname);
    }
  } catch (e) { /* not a URL */ }
  return h("span", { class: "muted" }, label || String(url));
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) {
    const d = data && data.detail;
    let msg = res.statusText;
    if (typeof d === "string") msg = d;
    else if (d && d.errors) msg = d.errors.join("; ");
    else if (Array.isArray(d)) msg = d.map((x) => x.msg).join("; ");
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return data;
}

let messageTimer = null;
function say(text, ok = true) {
  const el = document.getElementById("message");
  el.textContent = text;
  el.className = ok ? "ok" : "err";
  clearTimeout(messageTimer);
  messageTimer = setTimeout(() => { el.textContent = ""; el.className = ""; }, ok ? 6000 : 12000);
}

const guard = (fn) => async (...args) => {
  try { await fn(...args); } catch (e) { say(e.message, false); }
};

const badge = (text, cls) => h("span", { class: "badge " + (cls || text) }, text);

// ---------------------------------------------------------------- state
const S = {
  tab: "ideas",
  ideas: [], runs: [], suggestions: [], profile: null,
  filters: { status: "all", area: "all", kind: "all", q: "", run: "", group: true },
  editing: null, rejecting: null,
  expanded: new Set(), sources: {},          // sources: idea id -> list (loaded when a row is opened)
  suggestionFilter: "all",
  runForm: { mode: "weekly", area: "", topic: "", onlyKind: "" },
  limits: null,                                       // {backlog_cap, pending, full} from the server   // survives re-renders while a run is polled
  selectedRun: null, runDetail: null, pollTimer: null,
  profileDraft: null, profileErrors: [], profileBanner: null,
};

const TABS = [["ideas", "Ideas"], ["runs", "Runs"], ["suggestions", "Suggestions"], ["profile", "Profile"]];

// ---------------------------------------------------------------- loading
async function loadIdeas() { S.ideas = await api("/api/ideas"); }
async function loadRuns() { S.runs = await api("/api/runs"); }
async function loadSuggestions() { S.suggestions = await api("/api/suggestions"); }
async function loadProfile() { S.profile = await api("/api/profile"); }
async function loadLimits() { S.limits = await api("/api/limits"); }

async function showTab(tab) {
  S.tab = tab;
  stopPolling();
  try {
    if (tab === "ideas") { await Promise.all([loadIdeas(), loadProfile(), loadLimits()]); }
    if (tab === "runs") { await Promise.all([loadRuns(), loadProfile(), loadLimits()]); startPollingIfRunning(); }
    if (tab === "suggestions") { await Promise.all([loadSuggestions(), loadProfile()]); }
    if (tab === "profile") { await loadProfile(); S.profileDraft = draftFrom(S.profile); S.profileErrors = []; }
  } catch (e) { say(e.message, false); }
  render();
}

// A profile saved before experiments existed has no experiment count; the server then gives one
// slot to experiments and takes it from refresher/deep-dive. Show the page the same numbers.
function draftFrom(profile) {
  const d = JSON.parse(JSON.stringify(profile));
  d.mix = d.mix || {};
  if (d.mix.experiment === undefined) {
    d.mix.experiment = 1;
    d.mix.refresher_or_deep_dive = Math.max(0, (d.mix.refresher_or_deep_dive ?? 2) - 1);
  }
  d.resources = d.resources || ["cpu"];
  return d;
}

function render() {
  const tabs = document.getElementById("tabs");
  tabs.replaceChildren(...TABS.map(([id, label]) =>
    h("button", { class: id === S.tab ? "active" : "", onclick: () => showTab(id) }, label)));
  const view = document.getElementById("view");
  const views = { ideas: ideasView, runs: runsView, suggestions: suggestionsView, profile: profileView };
  view.replaceChildren(views[S.tab]());
}

// ---------------------------------------------------------------- ideas
const IDEA_STATUSES = ["pending", "approved", "rejected", "researched", "held", "drafted", "published"];
const IDEA_KINDS = ["trending", "refresher", "deep-dive", "experiment"];
const NEEDS_LABELS = { "cpu": "laptop CPU", "small-gpu": "small GPU" };

function ideasView() {
  const host = h("div");
  const banner = h("div");
  const stats = h("span", { class: "muted" });
  const areas = [...new Set(S.ideas.map((i) => i.area))].sort();
  const bar = h("div", { class: "bar" },
    h("label", {}, "Status ", h("select", { value: S.filters.status, onchange: (e) => { S.filters.status = e.target.value; draw(); } },
      h("option", { value: "all" }, "all"), IDEA_STATUSES.map((s) => h("option", { value: s }, s)))),
    h("label", {}, "Field ", h("select", { value: S.filters.area, onchange: (e) => { S.filters.area = e.target.value; draw(); } },
      h("option", { value: "all" }, "all"), areas.map((a) => h("option", { value: a }, a)))),
    h("label", {}, "Kind ", h("select", { value: S.filters.kind, onchange: (e) => { S.filters.kind = e.target.value; draw(); } },
      h("option", { value: "all" }, "all"), IDEA_KINDS.map((k) => h("option", { value: k }, k)))),
    h("input", { type: "search", placeholder: "Search ideas...", value: S.filters.q, oninput: (e) => { S.filters.q = e.target.value; draw(); } }),
    h("label", {}, h("input", { type: "checkbox", checked: S.filters.group, onchange: (e) => { S.filters.group = e.target.checked; draw(); } }), " group by field"),
    S.filters.run ? h("button", { class: "btn", onclick: () => { S.filters.run = ""; draw(); } }, "Only run " + S.filters.run + "  ✕") : null,
    h("span", { class: "grow" }), stats,
    h("button", { class: "btn", onclick: guard(async () => { await loadIdeas(); render(); }) }, "Refresh"));

  function visible() {
    const f = S.filters, q = f.q.trim().toLowerCase();
    return S.ideas.filter((i) =>
      (f.status === "all" || i.status === f.status) &&
      (f.area === "all" || i.area === f.area) &&
      (f.kind === "all" || i.kind === f.kind) &&
      (!f.run || i.run_id === f.run) &&
      (!q || (i.topic + " " + (i.rationale || "") + " " + (i.brief || "") + " " + i.profile_topic + " " + i.area).toLowerCase().includes(q)));
  }

  function draw() {
    const rows = visible();
    const count = (s) => S.ideas.filter((i) => i.status === s).length;
    const cap = S.limits ? S.limits.backlog_cap : null;
    stats.textContent = `${rows.length} shown · ${count("pending")} pending${cap ? " of " + cap + " allowed" : ""} · ${count("approved")} approved · ${count("rejected")} rejected`;
    banner.replaceChildren(...(cap && count("pending") >= cap ? [h("div", { class: "panel warn" },
      `Your backlog is full: ${count("pending")} ideas are waiting for a decision (the limit is ${cap}). New runs will skip until you approve or reject some. Only pending ideas count; approved, rejected and drafted ones never do.`)] : []));
    if (!rows.length) { host.replaceChildren(h("div", { class: "empty" }, S.ideas.length ? "No ideas match these filters." : "No ideas yet. Run Scout from the Runs tab.")); return; }
    if (S.filters.group) rows.sort((a, b) => a.area.localeCompare(b.area) || (b.created_at || "").localeCompare(a.created_at || ""));
    const body = [];
    let lastArea = null;
    for (const idea of rows) {
      if (S.filters.group && idea.area !== lastArea) {
        lastArea = idea.area;
        body.push(h("tr", { class: "group" }, h("td", { colspan: 8 }, `${idea.area}  (${rows.filter((r) => r.area === idea.area).length})`)));
      }
      body.push(ideaRow(idea));
      if (S.expanded.has(idea.id)) body.push(detailRow(idea));
    }
    host.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, ["Field", "Sub-topic", "Idea", "Kind", "Angle", "Status", "Created", "Actions"].map((t) => h("th", {}, t)))),
      h("tbody", {}, body)));
  }

  function ideaRow(idea) {
    const editing = S.editing === idea.id;
    const open = S.expanded.has(idea.id);
    return h("tr", { class: "idea-row" + (open ? " open" : ""), "aria-expanded": String(open),
        onclick: (e) => { if (!e.target.closest("button, a, input, select, textarea, label")) toggle(idea); } },
      h("td", {}, h("span", { class: "chev" }, open ? "▾" : "▸"), badge(idea.area, idea.area === "unlisted" ? "unlisted" : "field")),
      h("td", {}, idea.profile_topic),
      h("td", {}, editing ? editForm(idea) : ideaCell(idea)),
      h("td", {}, idea.kind === "experiment" ? badge("experiment") : idea.kind),
      h("td", {}, idea.angle),
      h("td", {}, badge(idea.status)),
      h("td", { class: "small muted" }, fmtDate(idea.created_at)),
      h("td", {}, actionsCell(idea)));
  }

  async function toggle(idea) {
    if (S.expanded.has(idea.id)) { S.expanded.delete(idea.id); draw(); return; }
    S.expanded.add(idea.id);
    draw();
    if (!S.sources[idea.id]) {
      try { S.sources[idea.id] = await api(`/api/ideas/${idea.id}/sources`); }
      catch (e) { say(e.message, false); S.sources[idea.id] = []; }
      draw();
    }
  }

  function detailRow(idea) {
    return h("tr", { class: "detail" }, h("td", { colspan: 8 },
      h("div", { class: "detail-grid" }, aboutBlock(idea), sourcesBlock(idea))));
  }

  function aboutBlock(idea) {
    return h("div", {},
      h("h2", {}, "About this idea"),
      idea.brief
        ? [h("p", { class: "brief" }, idea.brief), h("p", { class: "why" }, h("strong", {}, "Why now: "), idea.rationale)]
        : [h("p", { class: "brief" }, idea.rationale), h("p", { class: "small muted" }, "(This idea has no separate brief; new ideas from Scout include one.)")],
      idea.builds_on_topic ? h("p", { class: "small" }, "Follows up on: ", h("strong", {}, idea.builds_on_topic)) : null,
      idea.experiment ? planBlock(idea.experiment) : null,
      idea.status === "rejected" && idea.reject_reason ? h("p", { class: "why" }, "Rejected: " + idea.reject_reason) : null,
      h("p", { class: "small muted" },
        `${idea.area} › ${idea.profile_topic} · ${idea.kind} · ${idea.angle} · from ${idea.source}`,
        idea.run_id ? [" · run ", h("a", { href: "#", onclick: (e) => { e.preventDefault(); S.filters.run = idea.run_id; draw(); window.scrollTo(0, 0); } }, idea.run_id)] : null));
  }

  function planBlock(plan) {
    const row = (label, value) => [h("dt", {}, label), h("dd", {}, value)];
    return h("div", { class: "plan" }, h("h2", {}, "Experiment plan"),
      h("dl", {},
        row("Question", plan.question), row("Setup", plan.setup), row("Measure", plan.measure),
        row("Effort", badge(plan.effort, "field")),
        row("Needs", (plan.needs || []).map((n) => [badge(NEEDS_LABELS[n] || n, "field"), " "]))));
  }

  function sourcesBlock(idea) {
    const list = S.sources[idea.id];
    const path = (id) => `/api/ideas/${idea.id}/sources/${id}`;
    const items = list === undefined ? [h("div", { class: "muted" }, "Loading…")]
      : list.length ? list.map((src) => sourceItem(idea, src, path))
      : [h("div", { class: "muted" }, "No sources yet. Add one below.")];

    const url = h("input", { placeholder: "https://… a page worth citing", style: "flex:2;min-width:220px" });
    const title = h("input", { placeholder: "title (optional)", style: "flex:1;min-width:140px" });
    const note = h("input", { placeholder: "why it matters (optional)", style: "flex:2;min-width:180px", maxlength: 500 });
    const add = h("button", { class: "btn primary", onclick: guard(async () => {
      const src = await api(`/api/ideas/${idea.id}/sources`, "POST", { url: url.value, title: title.value, note: note.value });
      putSource(idea, src); say("Source added"); draw();
    }) }, "Add source");
    return h("div", {},
      h("h2", {}, `Sources (${(list || []).length})`,
        h("span", { class: "muted small" }, "  ☆ mark the ones that matter; the Writer will use them first")),
      items,
      h("div", { class: "source-add" }, url, title, note, add));
  }

  function sourceItem(idea, src, path) {
    const note = h("input", { value: src.note || "", maxlength: 500, class: "source-note",
      placeholder: "why does this matter? (saved when you click away)",
      onchange: guard(async () => { putSource(idea, await api(path(src.id), "PATCH", { note: note.value })); say("Note saved"); }) });
    const star = h("button", { class: "btn star" + (src.important ? " on" : ""), "aria-pressed": String(!!src.important),
      title: src.important ? "Important: click to un-star" : "Mark as important",
      onclick: guard(async () => { putSource(idea, await api(path(src.id), "PATCH", { important: !src.important })); draw(); }) },
      src.important ? "★" : "☆");
    return h("div", { class: "source" + (src.important ? " important" : "") },
      star,
      h("div", { class: "source-main" },
        h("div", {}, safeLink(src.url, src.title), " ", badge(src.found_by, "field")),
        h("div", { class: "small muted" }, src.domain + (src.published_date ? " · " + (fmtDate(src.published_date) || src.published_date) : "")),
        note),
      src.found_by === "you" ? h("button", { class: "btn bad", title: "Remove this source", onclick: guard(async () => {
        await api(path(src.id), "DELETE"); S.sources[idea.id] = S.sources[idea.id].filter((x) => x.id !== src.id);
        syncCounts(idea); say("Source removed"); draw();
      }) }, "✕") : null);
  }

  // keep the local list sorted like the server (important first) and the counts on the idea row current
  function putSource(idea, src) {
    const list = (S.sources[idea.id] || []).filter((x) => x.id !== src.id);
    list.push(src);
    list.sort((a, b) => (b.important === true) - (a.important === true) || (a.created_at || "").localeCompare(b.created_at || ""));
    S.sources[idea.id] = list;
    syncCounts(idea);
  }
  function syncCounts(idea) {
    const list = S.sources[idea.id] || [];
    idea.sources_total = list.length;
    idea.sources_important = list.filter((x) => x.important).length;
  }

  function ideaCell(idea) {
    return h("div", {},
      h("div", { class: "topic" }, idea.topic),
      h("div", { class: "why" }, idea.rationale),
      idea.builds_on_topic ? h("div", { class: "small muted" }, "↳ follows up: " + idea.builds_on_topic) : null,
      idea.status === "rejected" && idea.reject_reason ? h("div", { class: "why" }, "Rejected: " + idea.reject_reason) : null,
      h("div", { class: "small muted" },
        idea.sources_total ? `${idea.sources_total} source${idea.sources_total === 1 ? "" : "s"}` + (idea.sources_important ? ` · ★ ${idea.sources_important} important` : "") : "no sources yet",
        S.expanded.has(idea.id) ? "" : "  ·  click to open"));
  }

  function editForm(idea) {
    const topic = h("input", { value: idea.topic, maxlength: 100, style: "width:100%" });
    const why = h("textarea", { maxlength: 500, value: idea.rationale, placeholder: "why now (rationale)" });
    const brief = h("textarea", { maxlength: 600, value: idea.brief || "", placeholder: "brief: what the post would cover" });
    const angle = h("select", { value: idea.angle }, ["broad", "niche"].map((a) => h("option", { value: a }, a)));
    const kind = h("select", { value: idea.kind, onchange: () => { planBox.hidden = kind.value !== "experiment"; } },
      IDEA_KINDS.map((k) => h("option", { value: k }, k)));

    // the experiment plan: shown only while the kind is 'experiment'
    const plan = idea.experiment || { question: "", setup: "", measure: "", effort: "hours", needs: ["cpu"] };
    const q = h("textarea", { maxlength: 200, value: plan.question, placeholder: "question: what does it find out?" });
    const setup = h("textarea", { maxlength: 400, value: plan.setup, placeholder: "setup: what to build or run" });
    const measure = h("textarea", { maxlength: 200, value: plan.measure, placeholder: "measure: what to observe, and what a clear result looks like" });
    const effort = h("select", { value: plan.effort }, ["hours", "weekend"].map((e) => h("option", { value: e }, e)));
    const resources = ((S.profile && S.profile.resources) || ["cpu"]);
    const needBoxes = [...new Set([...resources, ...(plan.needs || [])])].map((n) => {
      const box = h("input", { type: "checkbox", "data-need": n });
      box.checked = (plan.needs || []).includes(n);
      return h("label", { class: "small" }, box, " " + (NEEDS_LABELS[n] || n));
    });
    const planBox = h("div", { class: "plan-edit" }, q, setup, measure,
      h("div", { class: "actions" }, h("span", { class: "muted small" }, "effort"), effort, needBoxes));
    planBox.hidden = idea.kind !== "experiment";

    return h("div", { "data-editing": idea.id },
      topic, brief, why, planBox, h("div", { class: "actions" }, angle, kind,
        h("button", { class: "btn primary", onclick: guard(async () => {
          const body = { topic: topic.value, rationale: why.value, brief: brief.value, angle: angle.value, kind: kind.value };
          if (kind.value === "experiment") {
            body.experiment = { question: q.value, setup: setup.value, measure: measure.value, effort: effort.value,
              needs: [...planBox.querySelectorAll("input[data-need]")].filter((b) => b.checked).map((b) => b.dataset.need) };
          }
          const row = await api(`/api/ideas/${idea.id}`, "PATCH", body);
          replaceIdea(row); S.editing = null; say("Saved"); draw();
        }) }, "Save"),
        h("button", { class: "btn", onclick: () => { S.editing = null; draw(); } }, "Cancel")));
  }

  function actionsCell(idea) {
    if (!idea.owner_editable) return h("span", { class: "muted small" }, "owned by the pipeline");
    if (S.rejecting === idea.id) {
      const reason = h("input", { placeholder: "why? (optional)", style: "width:170px" });
      return h("div", { class: "actions" }, reason,
        h("button", { class: "btn bad", onclick: guard(() => setStatus(idea, "rejected", reason.value)) }, "Reject"),
        h("button", { class: "btn", onclick: () => { S.rejecting = null; draw(); } }, "Cancel"));
    }
    return h("div", { class: "actions" },
      idea.status !== "approved" ? h("button", { class: "btn good", onclick: guard(() => setStatus(idea, "approved")) }, idea.status === "rejected" ? "Revive → approve" : "Approve") : null,
      idea.status !== "rejected" ? h("button", { class: "btn bad", onclick: () => { S.rejecting = idea.id; draw(); } }, "Reject") : null,
      idea.status !== "pending" ? h("button", { class: "btn", onclick: guard(() => setStatus(idea, "pending")) }, "Back to pending") : null,
      h("button", { class: "btn", onclick: () => { S.editing = idea.id; draw(); } }, "Edit"));
  }

  async function setStatus(idea, status, reason) {
    const row = await api(`/api/ideas/${idea.id}/status`, "POST", { status, reason: reason || null });
    replaceIdea(row); S.rejecting = null; say(`Marked ${status}`); draw();
  }
  function replaceIdea(row) { S.ideas = S.ideas.map((i) => (i.id === row.id ? row : i)); }

  draw();
  return h("div", {}, banner, bar, host);
}

// ---------------------------------------------------------------- runs
function stopPolling() { clearInterval(S.pollTimer); S.pollTimer = null; }
function startPollingIfRunning() {
  stopPolling();
  if (!S.runs.some((r) => r.state === "running")) return;
  S.pollTimer = setInterval(guard(async () => {
    await loadRuns();
    if (S.selectedRun) S.runDetail = await api("/api/runs/" + S.selectedRun);
    if (S.tab === "runs") render();
    if (!S.runs.some((r) => r.state === "running")) { stopPolling(); say("Run finished"); }
  }), 3000);
}

function runsView() {
  const areas = (S.profile && S.profile.areas) || [];
  const form = S.runForm;
  const note = h("div", { class: "muted small", style: "margin-top:6px" });

  const onlyKind = h("select", { onchange: (e) => { form.onlyKind = e.target.value; describe(); } },
    h("option", { value: "" }, "Mixed (the usual 1 + 1 + 1)"),
    IDEA_KINDS.map((k) => h("option", { value: k }, k === "experiment" ? "Experiments only" : k + " only")));
  const mode = h("select", { onchange: (e) => { form.mode = e.target.value; describe(); } },
    h("option", { value: "weekly" }, "Weekly: propose ideas"),
    h("option", { value: "profile_changed" }, "Changed topics only"),
    h("option", { value: "explore" }, "Explore: suggest new topics"));
  const area = h("select", { onchange: (e) => { form.area = e.target.value; form.topic = ""; fillTopics(); describe(); } },
    h("option", { value: "" }, "Auto: least-covered field"), areas.map((a) => h("option", { value: a.name }, a.name)));
  const topic = h("select", { onchange: (e) => {
    const [fieldName, key] = e.target.value ? e.target.value.split("/") : ["", ""];
    form.topic = key || "";
    if (fieldName && form.area !== fieldName) { form.area = fieldName; area.value = fieldName; fillTopics(); topic.value = e.target.value; }
    describe();
  } });

  function fillTopics() {
    const shown = form.area ? areas.filter((a) => a.name === form.area) : areas;
    topic.replaceChildren(
      h("option", { value: "" }, form.area ? `All sub-topics of ${form.area}` : "Any sub-topic"),
      ...shown.map((g) => h("optgroup", { label: g.name }, g.topics.map((t) => h("option", { value: g.name + "/" + t.key }, `${t.key} (${t.level})`)))));
    topic.value = form.topic && form.area ? form.area + "/" + form.topic : "";
  }

  // Plain-English summary of what the click will do, so a run never feels random.
  function describe() {
    const where = form.topic ? `the sub-topic "${form.topic}"` : form.area ? `the field "${form.area}"` : "";
    const text = {
      weekly: form.topic ? `Proposes up to 3 ideas, all for ${where}. It will not touch any other sub-topic.`
        : form.area ? `Proposes ideas for ${where}, digging into its 7 least-covered sub-topics.`
        : "Not random: it picks the field with the fewest ideas so far, then digs into that field's least-covered sub-topics.",
      profile_changed: form.topic ? `Only if ${where} is new or was edited since the last full changed-topics run.`
        : form.area ? `Only the new or edited sub-topics inside ${where}.`
        : "Only the sub-topics you added or re-levelled since the last full changed-topics run.",
      explore: form.topic ? `Suggests neighbouring and prerequisite topics around ${where}. Creates no ideas.`
        : form.area ? `Suggests gaps and neighbours for ${where}. Creates no ideas.`
        : "Suggests gaps across all your fields. Creates no ideas.",
    }[form.mode];
    onlyKind.disabled = form.mode === "explore";
    const kindNote = form.onlyKind && form.mode !== "explore"
      ? ` Only ${form.onlyKind} ideas will be accepted (up to 3); any other kind is refused.` : "";
    note.textContent = text + kindNote;
  }

  mode.value = form.mode; area.value = form.area; onlyKind.value = form.onlyKind; fillTopics(); describe();

  const running = S.runs.some((r) => r.state === "running");
  const start = h("button", { class: "btn primary", disabled: running, onclick: guard(async () => {
    await api("/api/runs", "POST", { mode: form.mode, area: form.area || null, topic: form.topic || null,
      only_kind: form.mode === "explore" ? null : (form.onlyKind || null) });
    say("Run started. This page updates while it runs.");
    await loadRuns(); render(); startPollingIfRunning();
  }) }, running ? "A run is in progress…" : "Run Scout");

  const table = S.runs.length
    ? h("table", {},
        h("thead", {}, h("tr", {}, ["Started", "Mode", "Field / sub-topic", "State", "Steps", "Ideas", "Reading list", "Suggestions", "Stopped because", "Model"].map((t) => h("th", {}, t)))),
        h("tbody", {}, S.runs.map((r) =>
          h("tr", { class: "clickable" + (S.selectedRun === r.id ? " selected" : ""), onclick: guard(() => openRun(r.id)) },
            h("td", { class: "small" }, fmtDate(r.started_at)), h("td", {}, r.only_kind ? `${r.mode} · ${r.only_kind} only` : r.mode), h("td", {}, r.topic ? `${r.area} › ${r.topic}` : (r.area || "–")),
            h("td", {}, badge(r.state)), h("td", {}, r.iterations ?? 0),
            h("td", {}, (r.proposed_ids || []).length), h("td", {}, (r.held_ids || []).length), h("td", {}, (r.suggested_ids || []).length),
            h("td", {}, r.stopped_reason || (r.state === "running" ? "…" : "–")), h("td", { class: "small muted" }, r.llm_provider || "")))))
    : h("div", { class: "empty" }, "No runs yet.");

  return h("div", {},
    S.limits && S.limits.full ? h("div", { class: "panel warn" },
      `Your backlog is full (${S.limits.pending} of ${S.limits.backlog_cap} ideas are waiting for a decision), so a run would skip. Approve or reject some on the Ideas tab first.`) : null,
    h("div", { class: "panel" }, h("h2", {}, "Start a run"),
      h("div", { class: "bar" },
        h("label", {}, "Mode ", mode), h("label", {}, "Field ", area), h("label", {}, "Sub-topic ", topic),
        h("label", {}, "Ideas ", onlyKind), start),
      note,
      h("div", { class: "muted small", style: "margin-top:6px" }, "A run uses model and search credits. Two runs cannot overlap.")),
    table, S.runDetail ? runDetailView(S.runDetail) : null);
}

async function openRun(id) {
  S.selectedRun = id;
  S.runDetail = await api("/api/runs/" + id);
  render();
}

function runDetailView(run) {
  const steps = (run.steps || []).map((s) => {
    let what;
    if (s.type === "tool") what = [h("span", { class: "what" }, s.tool), " ", h("span", { class: "muted small" }, typeof s.args === "string" ? s.args : JSON.stringify(s.args))];
    else if (s.type === "text") what = [h("span", { class: "what" }, "model said")];
    else if (s.type === "nudge") what = [h("span", { class: "what" }, "reminder sent")];
    else what = [h("span", { class: "what" }, s.type)];
    const body = s.type === "tool" ? s.result : s.content;
    return h("div", { class: "step" }, h("span", { class: "muted small" }, "#" + s.iteration + "  "), what, body ? h("pre", {}, body) : null);
  });
  return h("div", { class: "panel", style: "margin-top:14px" },
    h("div", { class: "bar" }, h("h2", { style: "margin:0" }, "Run " + run.id), badge(run.state),
      h("span", { class: "muted small" }, `${run.mode}${run.area ? " · " + run.area : ""}${run.topic ? " › " + run.topic : ""} · profile v${run.profile_version ?? "?"} · ${fmtDate(run.started_at)}`),
      h("span", { class: "grow" }),
      (run.proposed_ids || []).length ? h("button", { class: "btn", onclick: guard(async () => { await showTab("ideas"); S.filters.run = run.id; S.filters.status = "all"; render(); }) }, "View its ideas") : null),
    run.error ? h("div", { class: "why" }, "Error: " + run.error) : null,
    run.summary ? h("p", {}, run.summary) : null,
    (run.topics_scouted || []).length ? h("div", {}, h("span", { class: "muted small" }, "Topics scouted: "), run.topics_scouted.map((t) => [badge(t, "field"), " "])) : null,
    (run.queries || []).length ? h("div", { class: "small", style: "margin-top:6px" }, h("span", { class: "muted" }, "Searches: "), run.queries.join("  ·  ")) : null,
    h("h2", { style: "margin-top:14px" }, "What it did"),
    steps.length ? steps : h("div", { class: "muted" }, run.status === "running" ? "Waiting for the first step…" : "No steps were recorded (this run predates the trace)."));
}

// ---------------------------------------------------------------- suggestions
function suggestionsView() {
  const rows = S.suggestions.filter((s) => S.suggestionFilter === "all" || s.status === S.suggestionFilter);
  const filter = h("select", { value: S.suggestionFilter, onchange: (e) => { S.suggestionFilter = e.target.value; render(); } },
    ["all", "pending", "accepted", "dismissed"].map((s) => h("option", { value: s }, s)));
  const table = rows.length
    ? h("table", {},
        h("thead", {}, h("tr", {}, ["Field", "Suggestion", "Type", "Why", "Sources", "Status", "Actions"].map((t) => h("th", {}, t)))),
        h("tbody", {}, rows.map(suggestionRow)))
    : h("div", { class: "empty" }, "No suggestions here. Run Scout in “Explore” mode, or normal runs may add some.");
  return h("div", {},
    addTopicPanel(),
    h("div", { class: "bar" }, h("label", {}, "Status ", filter), h("span", { class: "grow" }),
      h("span", { class: "muted small" }, "Accepting adds the topic to your profile. Dismiss or un-accept any time; un-accepting does not remove it from the profile.")),
    table);
}

function addTopicPanel() {
  const areas = (S.profile && S.profile.areas || []).map((a) => a.name);
  const name = h("input", { placeholder: "a topic you heard about, e.g. Jev", maxlength: 60, style: "flex:2;min-width:220px" });
  const area = h("select", { onchange: () => { newArea.hidden = area.value !== "__new__"; } },
    areas.map((a) => h("option", { value: a }, "in field: " + a)), h("option", { value: "__new__" }, "in a new field…"));
  const newArea = h("input", { placeholder: "new field name", style: "min-width:160px" });
  newArea.hidden = true;
  const why = h("input", { placeholder: "what is it / why look into it? (optional)", maxlength: 500, style: "flex:3;min-width:260px" });
  const add = h("button", { class: "btn primary", onclick: guard(async () => {
    await api("/api/suggestions", "POST", { name: name.value, area: area.value === "__new__" ? newArea.value : area.value, why: why.value });
    say("Added to your suggestions. Accept it to put it in your profile, then run Scout on it.");
    await loadSuggestions(); render();
  }) }, "Add topic");
  return h("div", { class: "panel" }, h("h2", {}, "Suggest a topic yourself"),
    h("div", { class: "bar" }, name, area, newArea, why, add),
    h("div", { class: "muted small" }, "It joins the list below. Accept it to add it to your profile, then use “Run Scout on this” to get an explainer idea and an experiment idea for it."));
}

async function runOn(topicKey, onlyKind) {
  S.runForm = { mode: "weekly", area: "", topic: "", onlyKind: "" };
  await api("/api/runs", "POST", { mode: "weekly", area: null, topic: topicKey, only_kind: onlyKind || null });
  say(`Run started on ${topicKey}${onlyKind ? " (" + onlyKind + " only)" : ""}.`);
  await showTab("runs"); startPollingIfRunning();
}

function suggestionRow(s) {
  const level = h("select", { value: s.level || "curious" }, ["know", "learning", "curious"].map((l) => h("option", { value: l }, l)));
  const act = (status) => guard(async () => {
    const r = await api(`/api/suggestions/${s.id}/status`, "POST", { status, level: level.value });
    S.suggestions = S.suggestions.map((x) => (x.id === s.id ? r.suggestion : x));
    say(r.note ? `${status}: ${r.note}` : `Marked ${status}`, true);
    render();
  });
  return h("tr", {},
    h("td", {}, badge(s.area, "field")),
    h("td", {}, h("div", { class: "topic" }, s.name, " ", s.source === "you" ? badge("you", "field") : null), h("div", { class: "small muted" }, "key: " + s.key)),
    h("td", {}, s.kind === "new_area" ? "new area" : "new sub-topic"),
    h("td", {}, h("div", { class: "why" }, s.why)),
    h("td", { class: "evidence small" }, (s.evidence || []).map((e) => safeLink(e.url, e.title || undefined))),
    h("td", {}, badge(s.status)),
    h("td", {}, h("div", { class: "actions" },
      s.status !== "accepted" ? [h("span", { class: "muted small" }, "level"), level] : null,
      s.status !== "accepted" ? h("button", { class: "btn good", onclick: act("accepted") }, "Accept") : null,
      s.status === "accepted" ? h("button", { class: "btn primary", title: "Proposes up to 3 ideas for this sub-topic", onclick: guard(() => runOn(s.key)) }, "Run Scout on this") : null,
      s.status === "accepted" ? h("button", { class: "btn", title: "Only experiment ideas for this sub-topic", onclick: guard(() => runOn(s.key, "experiment")) }, "Experiments only") : null,
      s.status === "accepted" ? h("button", { class: "btn", onclick: act("pending") }, "Un-accept") : null,
      s.status === "dismissed" ? h("button", { class: "btn", onclick: act("pending") }, "Back to pending") : null,
      s.status !== "dismissed" ? h("button", { class: "btn bad", onclick: act("dismissed") }, "Dismiss") : null)));
}

// ---------------------------------------------------------------- profile
function profileView() {
  const d = S.profileDraft;
  if (!d) return h("div", { class: "empty" }, "Loading…");
  const redraw = () => render();

  const areas = d.areas.map((area, ai) => h("div", { class: "area-card" },
    h("div", { class: "bar" },
      h("input", { value: area.name, placeholder: "area-name", oninput: (e) => { area.name = e.target.value; } }),
      h("span", { class: "grow" }),
      h("button", { class: "btn bad", onclick: () => { d.areas.splice(ai, 1); redraw(); } }, "Remove area")),
    area.topics.map((t, ti) => h("div", { class: "topic-row" },
      h("input", { value: t.key, placeholder: "sub-topic-key", oninput: (e) => { t.key = e.target.value; } }),
      h("select", { value: t.level, onchange: (e) => { t.level = e.target.value; } },
        ["know", "learning", "curious"].map((l) => h("option", { value: l }, l))),
      h("button", { class: "btn", onclick: () => { area.topics.splice(ti, 1); redraw(); } }, "✕"))),
    h("button", { class: "btn", onclick: () => { area.topics.push({ key: "", level: "curious" }); redraw(); } }, "+ sub-topic")));

  const avoid = h("textarea", { oninput: (e) => { d.avoid = e.target.value.split("\n").map((x) => x.trim()).filter(Boolean); } });
  avoid.value = (d.avoid || []).join("\n");
  d.mix = d.mix || {};
  const mixInput = (key) => h("input", { type: "number", min: 0, style: "width:70px", value: d.mix[key] ?? 0,
    oninput: (e) => { d.mix[key] = Math.max(0, parseInt(e.target.value || "0", 10)); } });

  const save = h("button", { class: "btn primary", onclick: guard(async () => {
    S.profileErrors = [];
    try {
      const r = await api("/api/profile", "PUT", { areas: d.areas, avoid: d.avoid || [], mix: d.mix, resources: d.resources });
      S.profile = r.profile; S.profileDraft = draftFrom(r.profile);
      S.profileBanner = { version: r.profile.version, changed: r.changed_topics };
      say("Profile saved as version " + r.profile.version);
    } catch (e) {
      if (e.status === 400) S.profileErrors = e.message.split("; "); else throw e;
    }
    redraw();
  }) }, "Save profile");

  const banner = S.profileBanner ? h("div", { class: "panel" },
    `Saved as version ${S.profileBanner.version}. ${S.profileBanner.changed.length} topic(s) are new or changed` +
    (S.profileBanner.changed.length ? ": " + S.profileBanner.changed.join(", ") : "."),
    S.profileBanner.changed.length ? h("div", { style: "margin-top:8px" },
      h("button", { class: "btn primary", onclick: guard(async () => {
        await api("/api/runs", "POST", { mode: "profile_changed", area: null });
        S.profileBanner = null; say("Run started for the changed topics"); await showTab("runs");
      }) }, "Run Scout on the changed topics"),
      h("span", { class: "muted small" }, "  Saving never starts a run by itself.")) : null) : null;

  return h("div", {},
    banner,
    S.profileErrors.length ? h("div", { class: "panel", style: "border-color:var(--bad)" }, S.profileErrors.map((e) => h("div", {}, "• " + e))) : null,
    h("div", { class: "bar" }, h("h2", { style: "margin:0" }, "Profile"), h("span", { class: "muted small" }, "version " + (d.version ?? 0)),
      h("span", { class: "grow" }), save),
    h("p", { class: "muted small" }, "Each area is a big field; its sub-topics are what Scout digs into. Level: know = only advanced angles, learning = refreshers and what's new, curious = start-here posts are fine. Keys are lowercase letters, digits and dashes, unique across all areas."),
    areas,
    h("button", { class: "btn", onclick: () => { d.areas.push({ name: "", topics: [{ key: "", level: "curious" }] }); redraw(); } }, "+ area"),
    h("div", { class: "panel", style: "margin-top:14px" },
      h("h2", {}, "Never propose (things you already know), one per line"), avoid,
      h("div", { class: "bar", style: "margin-top:10px" }, "Per run, aim for:",
        h("label", {}, "trending ", mixInput("trending")), h("label", {}, "experiments ", mixInput("experiment")),
        h("label", {}, "refresher/deep-dive ", mixInput("refresher_or_deep_dive"))),
      h("div", { class: "bar", style: "margin-top:10px" }, h("strong", {}, "What I can run experiments on:"),
        [["cpu", "laptop CPU"], ["small-gpu", "a small GPU (only sometimes)"]].map(([key, label]) => {
          const box = h("input", { type: "checkbox", onchange: (e) => {
            const set = new Set(d.resources); e.target.checked ? set.add(key) : set.delete(key); d.resources = [...set];
          } });
          box.checked = (d.resources || []).includes(key);
          return h("label", {}, box, " " + label);
        }),
        h("span", { class: "muted small" }, "Experiments stay local and no bigger than a weekend. Scout only proposes ones that fit this."))));
}

// ---------------------------------------------------------------- start
showTab("ideas");

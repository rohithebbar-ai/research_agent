"""What the Scout model is told: tool schemas, system prompt, and the per-run briefing.

Pure functions only (no LLM, no database), so everything here is unit-testable.
"""
import copy

from tools.ideas import (
    ANGLES, EFFORTS, EXPERIMENT_TEXT_LIMITS, KINDS, MAX_BRIEF_CHARS, MAX_RATIONALE_CHARS, MAX_TOPIC_CHARS,
    NEEDS, STATUSES,
)
from tools.profile import allowed_resources, area_topics, changed_topics, topic_levels

ACTIVE = ("pending",)       # undecided ideas: the only ones that count against the cap
MAX_EXISTING_LINES = 120   # keep the briefing small as the backlog grows
MAX_REJECTED_LINES = 10
MAX_FOCUS_TOPICS = 7       # weekly runs focus on the 7 least-covered topics

_EVIDENCE = {
    "type": "array",
    "description": ("Sources for the claim. Copy url, title and published_date EXACTLY from "
                    "search_web results; never invent them."),
    "items": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "title": {"type": "string"},
            "published_date": {"type": "string"},
        },
        "required": ["url"],
    },
}


_EXPERIMENT = {
    "type": "object",
    "description": ("Required when kind is 'experiment', and only then. A small learning experiment the owner "
                    "can run locally in up to a weekend."),
    "properties": {
        "question": {"type": "string", "description": f"What the experiment finds out (max {EXPERIMENT_TEXT_LIMITS['question']} chars)."},
        "setup": {"type": "string", "description": f"What to build or run, concretely (max {EXPERIMENT_TEXT_LIMITS['setup']} chars)."},
        "measure": {"type": "string", "description": f"What to measure or observe, and what a clear result looks like (max {EXPERIMENT_TEXT_LIMITS['measure']} chars)."},
        "effort": {"type": "string", "enum": list(EFFORTS)},
        "needs": {"type": "array", "items": {"type": "string", "enum": list(NEEDS)},
                  "description": "What it needs to run. Prefer cpu; small-gpu only if it really needs one."},
    },
    "required": ["question", "setup", "measure", "effort", "needs"],
}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


TOOL_SCHEMAS = [
    _tool("read_backlog",
          "List ideas already in the backlog (id, topic, status, kind, profile_topic).",
          {"status": {"type": "string", "enum": sorted(STATUSES)},
           "profile_topic": {"type": "string", "description": "Only ideas for this profile topic."}},
          []),
    _tool("search_web",
          "Search the web. Use news=true with recency=week or month to find what is new.",
          {"query": {"type": "string"},
           "recency": {"type": "string", "enum": ["any", "week", "month"]},
           "news": {"type": "boolean", "description": "Search the news index."}},
          ["query"]),
    _tool("propose_idea",
          "Propose one blog post idea for the backlog. It is saved as 'pending' for the owner to approve.",
          {"topic": {"type": "string", "description": "A specific post topic, not a broad subject."},
           "angle": {"type": "string", "enum": sorted(ANGLES)},
           "kind": {"type": "string", "enum": sorted(KINDS)},
           "profile_topic": {"type": "string", "description": "The profile topic key this serves."},
           "rationale": {"type": "string", "description": "One or two sentences: why this post, why now."},
           "evidence": _EVIDENCE,
           "brief": {"type": "string",
                     "description": ("Optional. 2-3 sentences on what the post would argue or cover and "
                                     "the takeaway; this is the paragraph the owner reads when deciding.")},
           "experiment": _EXPERIMENT,
           "builds_on": {"type": "string",
                         "description": ("Optional. The id of an earlier idea (for example the concept post) "
                                         "that this one follows up on. Ids are listed in the briefing.")}},
          ["topic", "angle", "kind", "profile_topic", "rationale"]),
    _tool("hold_trend",
          "Save a noteworthy trend to the reading list instead of the backlog.",
          {"topic": {"type": "string"},
           "why": {"type": "string"},
           "evidence": _EVIDENCE},
          ["topic", "why"]),
    _tool("suggest_topic",
          "Suggest a new sub-topic for the owner's profile, or a whole new area worth knowing about. "
          "The owner decides; this never changes the profile by itself.",
          {"name": {"type": "string", "description": "Short name of the sub-topic, e.g. 'world models'."},
           "area": {"type": "string",
                    "description": ("EXACTLY an existing area name to add a sub-topic to it, or a new "
                                    "lowercase-dashed name to propose a whole new area.")},
           "why": {"type": "string", "description": "Why it matters for this reader, 1-2 sentences."},
           "evidence": _EVIDENCE},
          ["name", "area", "why"]),
    _tool("finish",
          "End the run. Call this when you have proposed what you can, or nothing good was found.",
          {"summary": {"type": "string", "description": "What you did and found, in 1-3 sentences."}},
          []),
]


def schemas_for(mode: str, only_kind: str | None = None) -> list[dict]:
    """Which tools the model is offered. Tools it must not use in a mode are simply not shown.

    only_kind: the propose_idea tool is offered with `kind` limited to that single value."""
    if mode == "explore":
        allowed = {"search_web", "suggest_topic", "finish"}
        return [s for s in TOOL_SCHEMAS if s["function"]["name"] in allowed]
    schemas = [s for s in TOOL_SCHEMAS if not (mode == "hold_only" and s["function"]["name"] == "propose_idea")]
    if only_kind:
        schemas = [_restrict_kind(s, only_kind) if s["function"]["name"] == "propose_idea" else s for s in schemas]
    return schemas


def _restrict_kind(schema: dict, kind: str) -> dict:
    limited = copy.deepcopy(schema)          # never change the shared TOOL_SCHEMAS
    limited["function"]["parameters"]["properties"]["kind"]["enum"] = [kind]
    return limited


SYSTEM_PROMPT = f"""You are Scout, a research assistant for one person's technical blog. \
Your job is to find post ideas that fit their learning profile and put them in their backlog \
for them to approve. You never write posts and never approve anything.

How to work
1. Read the briefing. It lists the profile, the topics to focus on, what already exists, and your limits.
2. Look at the backlog (read_backlog) if you need detail, then search the web for ideas.
3. Propose ideas with propose_idea. Quality over quantity: if nothing good turns up, propose fewer.
4. When done, call finish.

What a good idea looks like
- The topic is ONE specific, opinionated line of at most {MAX_TOPIC_CHARS} characters that makes a claim, \
asks a sharp question, or names a concrete failure, tradeoff or release. \
Good: "Why KV cache eviction breaks long-running agent loops". \
Bad: "Modern evaluation tools and methods for agent systems" (a vague survey), \
or "Shifting software development lifecycles for AI agents: design to maintain" (a mouthful).
- Prefer a sharp question or a claim. Never use headline filler: no "overview", "introduction", \
"trends in", "modern X methods", "everything about", "the race for", "the rise of", "the future of".
- The rationale is 1-2 sentences (under {MAX_RATIONALE_CHARS} characters) and MUST name one concrete thing \
you actually found in the search results: a tool, paper, release, benchmark number or incident. \
Never write "is crucial", "is transforming", "is gathering attention", "is becoming more important" \
or "this would help readers". If you cannot name a concrete hook for an idea, do not propose it.
- Also give a brief (2-3 sentences, under {MAX_BRIEF_CHARS} characters): what the post would actually argue \
or walk through, and what the reader takes away. Always include the evidence sources you used, even for \
refresher and deep-dive ideas, so the owner can open them.
- It matches the topic's level: 'know' = advanced or applied angles only, never basics; \
'learning' = refreshers on core concepts, deep dives, and what is new; \
'curious' = a foundational "start here" post is fine.
- kind: 'trending' = something new right now; 'refresher' = an older core concept worth revisiting; \
'deep-dive' = a closer look at part of a topic. Older ideas are welcome for refresher and deep-dive.
- angle: 'broad' = wide overview; 'niche' = one narrow question.
- Follow the target mix in the briefing, spread across the topics you were asked to focus on.

Experiments
- Besides posts that explain, propose small hands-on experiments (kind 'experiment') where trying the \
thing teaches more than reading about it. The owner posts about experiments too.
- An experiment is a LEARNING experiment: one clear question, a concrete setup, and one thing to \
measure or observe. It must be doable by one person, locally, in at most a weekend (effort 'hours' or \
'weekend'), using only the resources named in the briefing (usually a laptop CPU; sometimes a small GPU). \
No cloud spend, no robot hardware, no large-scale training, no multi-day benchmarks.
- The SHAPE of a good one (the subject is only an illustration; do not reuse it): \
"How much faster is a hash lookup than a list scan for 100,000 items?" with a setup of building both and \
timing 1,000 lookups, and a measure of microseconds per lookup. \
Bad: "Benchmark inference engines" (too big, vague) or "Train a VLA model" (needs hardware).
- Experiments pair with explaining posts, as a series: first the post that explains the concept, then a \
smaller post where the owner tries it. If the briefing shows an earlier idea that covers the concept, pass \
its id as builds_on. You may also propose the explaining idea first in this same run: the tool result \
returns its id, which you can then pass as builds_on for the experiment. \
Fill in the experiment plan completely. Propose an experiment only when you can describe one that really fits \
the resources; otherwise skip that slot.

Suggestions
- If while researching you find an important sub-topic or a whole field that is missing from the profile, \
you may call suggest_topic (at most a few times). It only notes the idea for the owner; it changes nothing.

Rules (the tools enforce them, so do not fight them)
- 'trending' needs evidence: at least 2 different websites, each with a published_date from the last 30 days. \
Find these with search_web using news=true and recency=week or month, and copy url, title, \
published_date exactly. Never invent sources.
- Never propose anything listed as already existing, or a close paraphrase of it.
- If a tool returns ERROR, read the message and adapt. Do not repeat the same call.
- Stay within the limits given in the briefing."""


EXPLORE_SYSTEM_PROMPT = """You are Scout, a research assistant for one person's technical blog. \
This is an EXPLORE run: you do not propose blog posts. Your job is to find sub-topics, or whole \
fields, that this person should know about but has not listed in their profile.

How to work
1. Read the briefing: the profile (their areas and sub-topics), and what has already been suggested.
2. Search the web for what is emerging, important or commonly taught in the fields around the profile. \
Use both news searches (news=true) for what is new, and ordinary searches for foundations that are missing.
3. Call suggest_topic for each worthwhile finding. area = EXACTLY an existing area name to add a sub-topic \
to it, or a new lowercase-dashed name to propose a whole new area. Give a concrete why.
4. Call finish when done.

Rules
- Never suggest something already in the profile or already suggested (the tools reject it).
- Prefer specific, nameable sub-topics ("world models for robot control") over vague fields ("AI").
- Fewer, better suggestions beat many. If an ERROR comes back, read it and adapt."""


def pick_area(profile: dict, coverage: dict[str, dict]) -> str:
    """The area with the fewest ideas so far; ties go to the one proposed for longest ago."""
    def least_covered(item):
        name, keys = item
        count = sum(coverage.get(k, {}).get("count", 0) for k in keys)
        newest = max((coverage.get(k, {}).get("last_created") or "" for k in keys), default="")
        return (count, newest, name)

    return min(area_topics(profile).items(), key=least_covered)[0]


def select_topics(profile: dict, mode: str, previous_profile: dict | None,
                  coverage: dict[str, dict], area: str | None = None,
                  topic: str | None = None) -> list[str]:
    """Which profile topics to scout this run, least covered first.

    topic: exactly this one sub-topic (raises ValueError if unknown or not inside `area`).
    area: only topics inside this area (raises ValueError for an unknown area).
    weekly / hold_only: the MAX_FOCUS_TOPICS least-covered topics.
    profile_changed: every changed topic (not capped, or edits would be silently dropped).
    """
    keys = list(topic_levels(profile))
    if area is not None:
        areas = area_topics(profile)
        if area not in areas:
            raise ValueError(f"unknown area {area!r}; choose from {sorted(areas)}")
        keys = areas[area]
    if topic is not None:
        if topic not in topic_levels(profile):
            raise ValueError(f"unknown sub-topic {topic!r}")
        if topic not in keys:
            raise ValueError(f"sub-topic {topic!r} is not in area {area!r}")
        keys = [topic]
    if mode == "profile_changed":
        changed = set(changed_topics(previous_profile, profile))
        keys = [k for k in keys if k in changed]

    def least_covered(key: str):
        info = coverage.get(key, {})
        return (info.get("count", 0), info.get("last_created") or "", key)

    ordered = sorted(keys, key=least_covered)
    return ordered if mode == "profile_changed" else ordered[:MAX_FOCUS_TOPICS]


def target_mix_line(profile: dict, max_proposals: int) -> str:
    """How many of each kind to aim for. An older profile without an 'experiment' count gets one
    experiment, taken out of the refresher/deep-dive share so the total stays the same."""
    mix = profile.get("mix", {})
    trending = mix.get("trending", 1)
    refresher = mix.get("refresher_or_deep_dive", 2)
    if "experiment" in mix:
        experiments = mix["experiment"]
    else:
        experiments = 1
        refresher = max(0, refresher - 1)
    parts = [f"{trending} trending"]
    if experiments:
        parts.append(f"{experiments} experiment")
    parts.append(f"{refresher} refresher/deep-dive")
    return (f"TARGET MIX: about {', '.join(parts)} (at most {max_proposals} proposals). "
            "Skip a slot rather than force a weak idea.")


def resources_text(profile: dict) -> str:
    names = {"cpu": "a laptop CPU", "small-gpu": "a small GPU that is only sometimes available"}
    return ("; ".join(names.get(r, r) for r in allowed_resources(profile))
            + ". Everything runs locally, with no cloud spend.")


def build_briefing(profile: dict, topics: list[str], ideas: list[dict], trends: list[dict],
                   coverage: dict[str, dict], config, today: str, area: str | None = None,
                   topic: str | None = None, only_kind: str | None = None) -> str:
    """The user message for the run: everything the model needs, as plain text."""
    levels = topic_levels(profile)
    lines = [f"Today: {today}. Run mode: {config.mode}.", ""]

    if topic:
        lines += [f"FOCUS SUB-TOPIC: {topic} (level: {levels.get(topic, '?')}, area: {area})",
                  f"This whole run is about ONE sub-topic: '{topic}'. Every idea you propose must be for it. "
                  "Dig into it from different angles and kinds (a foundation, a failure mode, "
                  "something new) instead of repeating one idea.", ""]
    elif area:
        lines += [f"FOCUS AREA: {area}",
                  f"This whole run is about the '{area}' area. Propose ideas ONLY for its sub-topics "
                  "listed below, and go deep: cover different sub-topics and different angles "
                  "instead of repeating one.", ""]

    lines.append("PROFILE" if not area else f"PROFILE (the '{area}' area)")
    for profile_area in profile["areas"]:
        if area and profile_area["name"] != area:
            continue
        lines.append(f"{profile_area['name']}:")
        for t in profile_area["topics"]:
            lines.append(f"  - {t['key']} ({t['level']})")
    if profile.get("avoid"):
        lines.append("Never propose these (the reader already knows them): " + "; ".join(profile["avoid"]))

    lines += ["", "TOPICS TO FOCUS ON THIS RUN (least covered first)"]
    for key in topics:
        info = coverage.get(key, {})
        last = (info.get("last_created") or "never")[:10]
        lines.append(f"- {key} ({levels.get(key, '?')}): {info.get('count', 0)} ideas so far, last proposed {last}")

    if only_kind:
        lines += ["", f"TARGET: propose ONLY ideas of kind '{only_kind}' this run (up to {config.max_proposals}). "
                      "Do not propose any other kind. Skip a slot rather than force a weak idea."]
    else:
        lines += ["", target_mix_line(profile, config.max_proposals)]
    lines.append("RESOURCES for experiments: " + resources_text(profile))

    newest_first = sorted(ideas, key=lambda i: i.get("created_at", ""), reverse=True)
    shown = newest_first[:MAX_EXISTING_LINES]
    lines += ["", "ALREADY EXISTS (do not propose these again, or close paraphrases)"]
    lines += [f"- [{i['status']}] {i['topic']}  (id: {i['id']}{', experiment' if i.get('kind') == 'experiment' else ''})"
              for i in shown]
    if len(newest_first) > len(shown):
        lines.append(f"(+{len(newest_first) - len(shown)} older ideas not shown; duplicates are still blocked)")
    if trends:
        lines.append("Reading list: " + "; ".join(t["topic"] for t in trends[:30]))

    rejected = [i for i in newest_first if i["status"] == "rejected"][:MAX_REJECTED_LINES]
    if rejected:
        lines += ["", "RECENTLY REJECTED BY THE OWNER (learn from these)"]
        for i in rejected:
            reason = i.get("reject_reason") or "no reason given"
            lines.append(f'- "{i["topic"]}": {reason}')

    active = sum(1 for i in ideas if i["status"] in ACTIVE)
    lines += ["", f"LIMITS: up to {config.max_searches} searches, {config.max_proposals} proposals, "
                  f"{config.max_holds} reading-list items. The backlog has {active} of "
                  f"{config.backlog_cap} undecided (pending) ideas."]

    lines.append("")
    if config.mode == "hold_only":
        lines.append("The backlog is full. Do NOT propose ideas. Use hold_trend to save noteworthy "
                     "trends for later, then finish.")
    elif config.mode == "profile_changed":
        lines.append("The profile was just edited. The focus topics above are new or changed; "
                     "concentrate on them.")
    else:
        lines.append("Weekly run: look across the focus topics, starting with the least covered.")
    return "\n".join(lines)


def build_explore_briefing(profile: dict, suggestions: list[dict], config, today: str,
                           area: str | None = None, topic: str | None = None) -> str:
    """The user message for an explore run."""
    lines = [f"Today: {today}. Run mode: explore.", ""]
    lines.append("PROFILE (what the owner already tracks)")
    for profile_area in profile["areas"]:
        lines.append(f"{profile_area['name']}: " +
                     ", ".join(f"{t['key']} ({t['level']})" for t in profile_area["topics"]))
    if topic:
        lines += ["", f"FOCUS: look for neighbouring and prerequisite sub-topics around '{topic}' (area '{area}')."]
    elif area:
        lines += ["", f"FOCUS: look for gaps and neighbours of the '{area}' area in particular."]
    else:
        lines += ["", "FOCUS: look across all areas for gaps, and for whole fields that are missing."]
    if suggestions:
        lines += ["", "ALREADY SUGGESTED (do not repeat; dismissed ones were declined by the owner)"]
        lines += [f"- [{x['status']}] {x['name']} ({x['area']})" for x in suggestions[:80]]
    lines += ["", f"LIMITS: up to {config.max_searches} searches and {config.max_suggestions} suggestions."]
    return "\n".join(lines)

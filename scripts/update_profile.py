"""Replaces the profile's areas with the restructured version: big topics with sub-topics.

Review the levels below first (know / learning / curious), then run once:
    python -m scripts.update_profile

It saves a NEW profile version (the old one stays as a snapshot) and prints what changed.
"""
from tools.profile import changed_topics, load_profile, save_profile, topic_levels, validate_profile

AREAS = [
    {"name": "agents", "topics": [
        {"key": "agents", "level": "curious"},
        {"key": "multi-agent", "level": "curious"},
        {"key": "agentic-workflows", "level": "curious"},
        {"key": "agentic-lifecycle", "level": "curious"},
        {"key": "agentic-observability", "level": "curious"},
        {"key": "agentic-evals", "level": "curious"},
    ]},
    {"name": "computer-vision", "topics": [
        {"key": "object-detection", "level": "learning"},
        {"key": "sam", "level": "learning"},
        {"key": "depth-anything", "level": "learning"},
    ]},
    {"name": "cv-bin-picking", "topics": [
        {"key": "object-perception", "level": "learning"},
        {"key": "pose-estimation", "level": "learning"},
        {"key": "rotation-representations", "level": "learning"},
        {"key": "point-clouds", "level": "learning"},
        {"key": "3d-estimation", "level": "learning"},
        {"key": "2d-estimation", "level": "learning"},
        {"key": "cad-models", "level": "learning"},
    ]},
    {"name": "robotics", "topics": [
        {"key": "vla", "level": "learning"},
        {"key": "autonomous-driving", "level": "learning"},
    ]},
    {"name": "system-design", "topics": [
        {"key": "caching", "level": "curious"},
        {"key": "load-balancing", "level": "curious"},
        {"key": "nginx", "level": "curious"},
        {"key": "inference-serving", "level": "curious"},
        {"key": "scaling-ai-systems", "level": "curious"},
        {"key": "hld-lld", "level": "curious"},
        {"key": "spec-docs", "level": "curious"},
    ]},
    {"name": "ai-engineering", "topics": [
        {"key": "llm-basics", "level": "know"},
        {"key": "rag", "level": "know"},
        {"key": "llm-inference", "level": "curious"},
        {"key": "kv-caching", "level": "curious"},
        {"key": "prefill-decode", "level": "curious"},
        {"key": "gpu-management", "level": "curious"},
        {"key": "fine-tuning", "level": "curious"},
        {"key": "lora", "level": "curious"},
        {"key": "qlora", "level": "curious"},
        {"key": "rlhf", "level": "curious"},
        {"key": "observability-and-evals", "level": "curious"},
    ]},
]

current = load_profile()
if current is None:
    raise SystemExit("No profile yet. Run: python -m scripts.seed_profile")

new_profile = {**current, "areas": AREAS}
errors = validate_profile(new_profile)   # same rules as the Profile tab on the web page
if errors:
    raise SystemExit("Profile is not valid:\n  " + "\n  ".join(errors))

changed = changed_topics(current, new_profile)
saved = save_profile(new_profile)

removed = sorted(set(topic_levels(current)) - set(topic_levels(saved)))
print(f"saved profile version {saved['version']}")
print(f"{len(changed)} new or changed topics: {', '.join(changed)}")
print(f"{len(removed)} topics removed: {', '.join(removed) or '-'}")

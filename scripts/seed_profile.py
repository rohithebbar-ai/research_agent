
"""Saves the starting profile. Does nothing if one already exists."""
from tools.profile import load_profile, save_profile

PROFILE = {
    "areas": [
        {"name": "robotics", "topics": [
            {"key": "vla", "level": "learning"},
            {"key": "computer-vision", "level": "learning"},
            {"key": "autonomous-driving", "level": "learning"},
        ]},
        {"name": "llm", "topics": [
            {"key": "llm-basics", "level": "know"},
            {"key": "rag", "level": "know"},
            {"key": "llm-inference", "level": "curious"},
            {"key": "gpu-management", "level": "curious"},
            {"key": "fine-tuning", "level": "curious"},
            {"key": "agents", "level": "curious"},
            {"key": "multi-agent", "level": "curious"},
            {"key": "agentic-lifecycle", "level": "curious"},
            {"key": "agentic-observability", "level": "curious"},
            {"key": "agentic-evals", "level": "curious"},
            {"key": "observability-and-evals", "level": "curious"},
        ]},
        {"name": "system-design", "topics": [
            {"key": "caching", "level": "curious"},
            {"key": "load-balancers-nginx", "level": "curious"},
            {"key": "scaling-ai-systems", "level": "curious"},
            {"key": "hld-lld", "level": "curious"},
            {"key": "spec-docs", "level": "curious"},
        ]},
    ],
    "avoid": ["what is a transformer", "RAG basics"],
    "mix": {"trending": 1, "refresher_or_deep_dive": 2},
}

if load_profile():
    print("profile already exists, not touching it")
else:
    saved = save_profile(PROFILE)
    print("saved profile version", saved["version"])
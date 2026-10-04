"""Scout profile: load, save (versioned), and work out what changed."""
import copy
import re
from datetime import datetime, timezone

from tools.cosmos_client import get_document, upsert_document

PROFILE_ID = "profile"
LEVELS = ("know", "learning", "curious")
RESOURCE_CHOICES = ("cpu", "small-gpu")   # what the owner can run experiments on (see tools/ideas.py NEEDS)
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")   # e.g. 'kv-caching', '3d-estimation'


def load_profile() -> dict | None:
    """The current profile, or None if none was saved yet."""
    return get_document("scout_profile", PROFILE_ID)


def get_snapshot(version: int) -> dict | None:
    """The profile exactly as it was at a given version."""
    return get_document("scout_profile", f"profile_v{version}")


def save_profile(profile: dict) -> dict:
    """Save as the new current version and keep an immutable snapshot of it."""
    current = load_profile()
    clean = {k: v for k, v in profile.items() if not k.startswith("_")}  # drop Cosmos system fields
    clean["id"] = PROFILE_ID
    clean["version"] = current["version"] + 1 if current else 1
    clean["updated_at"] = datetime.now(timezone.utc).isoformat()

    upsert_document("scout_profile", clean)
    upsert_document("scout_profile", {**clean, "id": f"profile_v{clean['version']}"})
    return clean


def topic_levels(profile: dict) -> dict[str, str]:
    """{'vla': 'learning', 'rag': 'know', ...} across all areas."""
    return {
        topic["key"]: topic["level"]
        for area in profile["areas"]
        for topic in area["topics"]
    }


def changed_topics(old: dict | None, new: dict) -> list[str]:
    """Topics that are new, or whose level changed. Removed topics are ignored."""
    new_levels = topic_levels(new)
    if old is None:
        return sorted(new_levels)
    old_levels = topic_levels(old)
    return sorted(key for key, level in new_levels.items() if old_levels.get(key) != level)


def area_topics(profile: dict) -> dict[str, list[str]]:
    """{'agents': ['multi-agent', ...], 'system-design': [...]} in profile order."""
    return {area["name"]: [t["key"] for t in area["topics"]] for area in profile["areas"]}


def area_of(profile: dict, key: str) -> str | None:
    """The area a topic key currently lives in, or None if it is not in the profile."""
    for area in profile["areas"]:
        if any(t["key"] == key for t in area["topics"]):
            return area["name"]
    return None


def validate_profile(profile: dict) -> list[str]:
    """Human-readable problems with a profile; an empty list means it is valid."""
    areas = profile.get("areas")
    if not isinstance(areas, list) or not areas:
        return ["the profile needs at least one area"]
    errors, seen_areas, seen_keys = [], set(), set()
    for area in areas:
        name = area.get("name") if isinstance(area, dict) else None
        if not isinstance(name, str) or not _SLUG.match(name):
            errors.append(f"area name {name!r} must be lowercase letters, digits and dashes")
        elif name in seen_areas:
            errors.append(f"duplicate area {name!r}")
        else:
            seen_areas.add(name)
        topics = area.get("topics") if isinstance(area, dict) else None
        if not isinstance(topics, list) or not topics:
            errors.append(f"area {name!r} needs at least one topic")
            continue
        for topic in topics:
            key = topic.get("key") if isinstance(topic, dict) else None
            level = topic.get("level") if isinstance(topic, dict) else None
            if not isinstance(key, str) or not _SLUG.match(key):
                errors.append(f"topic key {key!r} must be lowercase letters, digits and dashes")
            elif key in seen_keys:
                errors.append(f"duplicate topic key {key!r} (keys must be unique across all areas)")
            else:
                seen_keys.add(key)
            if level not in LEVELS:
                errors.append(f"topic {key!r}: level must be one of {list(LEVELS)}, got {level!r}")
    avoid = profile.get("avoid", [])
    if not isinstance(avoid, list) or not all(isinstance(a, str) and a.strip() for a in avoid):
        errors.append("avoid must be a list of non-empty strings")
    resources = profile.get("resources", ["cpu"])
    if (not isinstance(resources, list) or not resources
            or any(r not in RESOURCE_CHOICES for r in resources)):
        errors.append(f"resources must be a non-empty list drawn from {list(RESOURCE_CHOICES)}")
    mix = profile.get("mix", {})
    if not isinstance(mix, dict) or not all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in mix.values()):
        errors.append("mix values must be whole numbers, 0 or more")
    return errors


def profile_with_topic(profile: dict, area: str, key: str, level: str) -> dict:
    """A copy of the profile with one more topic (creating the area if it is new)."""
    new = copy.deepcopy(profile)
    if key in topic_levels(new):
        raise ValueError(f"topic {key!r} is already in the profile")
    target = next((a for a in new["areas"] if a["name"] == area), None)
    if target is None:
        target = {"name": area, "topics": []}
        new["areas"].append(target)
    target["topics"].append({"key": key, "level": level})
    errors = validate_profile(new)
    if errors:
        raise ValueError("; ".join(errors))
    return new


def allowed_resources(profile: dict | None) -> list[str]:
    """What experiments may need. A profile without the field means a plain laptop."""
    return list((profile or {}).get("resources") or ["cpu"])

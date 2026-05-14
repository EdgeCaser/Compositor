from __future__ import annotations

from collections import Counter
import re

from .models import now_iso

QUOTE_RE = re.compile(r"[\"“”]")

ACTIONS = [
    {
        "id": "separate_dialogue_narration",
        "label": "Separate Dialogue/Narration",
        "description": "Run a first-pass paragraph classifier over imported prose.",
    },
    {
        "id": "generate_emotional_guidance",
        "label": "Generate Emotional Guidance",
        "description": "Assign rough mood tags to paragraphs for review.",
    },
    {
        "id": "assign_voices",
        "label": "Assign Voices",
        "description": "Apply provisional narrator and dialogue voice routing.",
    },
]

MOODS = (
    "flat",
    "clinical",
    "procedural",
    "weary",
    "sharp",
    "resolved",
    "intimate",
    "hesitant",
    "tense",
    "wrecked",
)


def list_actions() -> list[dict]:
    return ACTIONS


def analyze_paragraph_kind(text: str) -> str:
    quote_count = len(QUOTE_RE.findall(text))
    stripped = text.strip()
    if quote_count >= 2 and stripped.startswith(("\"", "“")) and stripped.endswith(("\"", "”")):
        return "dialogue"
    if quote_count >= 2:
        return "mixed"
    return "narration"


def guidance_for(text: str, kind: str) -> str:
    lower = text.lower()
    if "!" in text:
        return "sharp"
    if "?" in text:
        return "hesitant"
    if any(word in lower for word in ("blood", "report", "exam", "body", "evidence")):
        return "clinical"
    if any(word in lower for word in ("order", "court", "hearing", "rule", "motion")):
        return "procedural"
    if any(word in lower for word in ("tired", "sleep", "hurt", "ache", "late")):
        return "weary"
    if any(word in lower for word in ("cry", "grief", "dead", "loss", "alone")):
        return "wrecked"
    if kind == "dialogue" and len(text.split()) <= 6:
        return "resolved"
    if kind == "mixed":
        return "tense"
    if kind == "dialogue":
        return "intimate"
    return "flat"


def _narrator_slot(cast: list[dict]) -> str:
    for voice in cast:
        if voice.get("role") == "narrator":
            return voice.get("slot", "narrator")
    return "narrator"


def _dialogue_slot(cast: list[dict]) -> str:
    for voice in cast:
        if voice.get("role") == "dialogue_default":
            return voice.get("slot", "generic_dialogue")
    return "generic_dialogue"


def apply_dialogue_narration(chapter: dict) -> dict:
    dialogue = 0
    mixed = 0
    narration = 0
    for para in chapter.get("paragraphs", []):
        kind = analyze_paragraph_kind(para.get("text", ""))
        para["kind"] = kind
        if kind == "dialogue":
            dialogue += 1
        elif kind == "mixed":
            mixed += 1
        else:
            narration += 1
    chapter.setdefault("analysis", {})["dialogue_narration"] = {
        "dialogue": dialogue,
        "mixed": mixed,
        "narration": narration,
        "ran_at": now_iso(),
    }
    chapter.setdefault("stats", {})["dialogue_paragraphs"] = dialogue
    chapter["stats"]["mixed_paragraphs"] = mixed
    chapter["stats"]["narration_paragraphs"] = narration
    chapter["stats"]["estimated_lines"] = dialogue + mixed
    chapter["stats"]["paragraphs"] = len(chapter.get("paragraphs", []))
    chapter["stats"]["lines_read"] = int(chapter["stats"].get("lines_read", 0) or 0)
    return {
        "dialogue": dialogue,
        "mixed": mixed,
        "narration": narration,
    }


def apply_emotional_guidance(chapter: dict) -> dict:
    counts = Counter()
    for para in chapter.get("paragraphs", []):
        kind = para.get("kind") or analyze_paragraph_kind(para.get("text", ""))
        mood = guidance_for(para.get("text", ""), kind)
        if mood not in MOODS:
            mood = "flat"
        para["guidance"] = mood
        counts[mood] += 1
    chapter.setdefault("analysis", {})["guidance"] = {
        "counts": dict(counts),
        "ran_at": now_iso(),
    }
    return dict(counts)


def apply_voice_assignment(chapter: dict, cast: list[dict]) -> dict:
    narrator = _narrator_slot(cast)
    dialogue = _dialogue_slot(cast)
    assignments = Counter()
    for para in chapter.get("paragraphs", []):
        kind = para.get("kind") or analyze_paragraph_kind(para.get("text", ""))
        if kind == "narration":
            slot = narrator
        elif kind == "dialogue":
            slot = dialogue
        else:
            slot = dialogue
        para["voice_slot"] = slot
        assignments[slot] += 1
    chapter.setdefault("analysis", {})["voice_assignment"] = {
        "counts": dict(assignments),
        "ran_at": now_iso(),
    }
    return dict(assignments)


def run_action(project: dict, chapter_id: str, action_id: str) -> dict:
    chapter = next((item for item in project.get("chapters", []) if item.get("id") == chapter_id), None)
    if chapter is None:
        raise ValueError(f"chapter not found: {chapter_id}")

    if action_id == "separate_dialogue_narration":
        summary = apply_dialogue_narration(chapter)
    elif action_id == "generate_emotional_guidance":
        if not chapter.get("analysis", {}).get("dialogue_narration"):
            apply_dialogue_narration(chapter)
        summary = apply_emotional_guidance(chapter)
    elif action_id == "assign_voices":
        if not chapter.get("analysis", {}).get("dialogue_narration"):
            apply_dialogue_narration(chapter)
        if not chapter.get("analysis", {}).get("guidance"):
            apply_emotional_guidance(chapter)
        summary = apply_voice_assignment(chapter, project.get("cast", []))
    else:
        raise ValueError(f"unknown action: {action_id}")

    job = {
        "id": f"{action_id}-{chapter_id}-{len(project.get('jobs', [])) + 1}",
        "action_id": action_id,
        "chapter_id": chapter_id,
        "chapter_title": chapter.get("title", chapter_id),
        "status": "completed",
        "summary": summary,
        "ran_at": now_iso(),
    }
    project.setdefault("jobs", []).insert(0, job)
    return job

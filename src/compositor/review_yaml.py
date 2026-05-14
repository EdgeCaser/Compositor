from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Optional

import yaml

DIALOGUE_VERBS = {
    "said", "asked", "replied", "whispered", "called", "muttered", "continued",
    "added", "told", "murmured", "growled", "insisted", "noted", "observed",
    "remarked", "repeated", "responded", "shouted", "snapped", "stated",
    "suggested", "wondered", "answered", "began", "explained", "agreed",
    "warned", "offered", "demanded", "ordered", "admitted", "confirmed",
    "interrupted", "echoed", "hissed", "breathed", "barked", "drawled",
    "pressed", "prompted", "countered", "conceded", "mused", "ventured",
    "gritted", "rasped", "managed", "emphasized", "snorted", "sighed",
    "smiled", "frowned", "nodded", "shrugged", "gestured", "leaned", "paused",
    "hesitated", "grimaced", "chuckled", "laughed", "groaned", "cleared",
    "exhaled", "inhaled", "swallowed", "coughed", "scoffed", "huffed",
    "smirked", "sniffed", "blinked", "considered", "regarded", "studied",
    "watched", "eyed", "glanced", "glared", "stared", "checked", "tilted",
    "cocked",
}
VERBS_ALT = "|".join(sorted(DIALOGUE_VERBS, key=len, reverse=True))
VERB_GROUP = rf"(?i:{VERBS_ALT})"

QUOTE_MAP = str.maketrans({
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u00ab": '"',
    "\u00bb": '"',
})
QUOTE_SPAN_RE = re.compile(r'"[^"]+"')
INLINE_ATTRIBUTION_TAIL_RE = re.compile(
    rf"^(?:I|[Hh]e|[Ss]he|[Tt]hey|(?:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){{0,2}}))\s+{VERB_GROUP}\.?$"
)


@dataclass
class ReviewSegment:
    voice_slot: str
    text: str
    attribution: Optional[str] = None
    mood: Optional[str] = None
    kind: str = "narration"
    pause_ms: int = 0
    paragraph_idx: Optional[int] = None
    tag: Optional[str] = None
    performance: Optional[str] = None
    trim_ms_in: int = 0
    trim_ms_out: int = 0


def is_dialogue_text(text: str) -> bool:
    return text.lstrip().startswith(('"', "'"))


def parse_yaml_text(text: str) -> dict[str, Any]:
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise ValueError("Top-level YAML document must be a mapping.")
    segments = doc.get("segments")
    if not isinstance(segments, list):
        raise ValueError("YAML must contain a top-level 'segments' list.")
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            raise ValueError(f"Segment {idx} must be a mapping.")
        for key in ("voice", "kind", "text"):
            if key not in seg:
                raise ValueError(f"Segment {idx} is missing required key '{key}'.")
    return doc


def yaml_error_payload(exc: Exception) -> dict[str, Any]:
    payload = {"message": str(exc)}
    mark = getattr(exc, "problem_mark", None)
    if mark is not None:
        payload["line"] = mark.line + 1
        payload["column"] = mark.column + 1
    return payload


def ordered_voice_slots(configured_slots: list[str], slots: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for slot in slots:
        clean = str(slot or "").strip()
        if not clean or clean in seen:
            continue
        deduped.append(clean)
        seen.add(clean)

    ordered: list[str] = []
    emitted: set[str] = set()
    for slot in configured_slots:
        if slot in seen and slot not in emitted:
            ordered.append(slot)
            emitted.add(slot)
    for slot in deduped:
        if slot not in emitted:
            ordered.append(slot)
            emitted.add(slot)
    return ordered


def segments_from_review(data: dict[str, Any]) -> list[ReviewSegment]:
    return [
        ReviewSegment(
            voice_slot=segment["voice"],
            text=segment["text"],
            attribution=None if segment.get("attribution") == "-" else segment.get("attribution"),
            mood=segment.get("mood"),
            kind=segment.get("kind", "dialogue" if is_dialogue_text(segment.get("text", "")) else "narration"),
            pause_ms=int(segment.get("pause_ms", 0) or 0),
            paragraph_idx=segment.get("paragraph_idx"),
            tag=segment.get("tag"),
            performance=segment.get("performance"),
            trim_ms_in=int(segment.get("trim_ms_in", 0) or 0),
            trim_ms_out=int(segment.get("trim_ms_out", 0) or 0),
        )
        for segment in data["segments"]
    ]


def spoken_char_len(segment: ReviewSegment) -> int:
    return 0 if segment.kind == "pause" else len(segment.text)


def voice_usage_for_segments(segments: list[ReviewSegment]) -> dict[str, int]:
    usage: dict[str, int] = {}
    for segment in segments:
        if segment.kind == "pause":
            continue
        usage[segment.voice_slot] = usage.get(segment.voice_slot, 0) + len(segment.text)
    return usage


def quoted_span_looks_like_dialogue(span: str) -> bool:
    inner = span.strip().strip('"').strip("'").strip()
    if not inner:
        return False
    words = re.findall(r"[A-Za-z0-9']+", inner)
    return any(char in inner for char in ".?!") or len(words) >= 4


def narration_contains_spoken_dialogue(text: str, quoted: list[str]) -> bool:
    dialogue_like = [span for span in quoted if quoted_span_looks_like_dialogue(span)]
    if not dialogue_like:
        return False
    stripped = text.lstrip()
    if stripped.startswith('"'):
        return True
    if len(dialogue_like) >= 2:
        return True
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(verb)}\b", lowered) for verb in DIALOGUE_VERBS)


def find_structural_validation_issues(segments: list[ReviewSegment]) -> dict[str, list[int]]:
    issues = {
        "narration_contains_dialogue": [],
        "dialogue_contains_narration": [],
        "dialogue_unclosed_quote": [],
        "dialogue_multiple_quotes": [],
    }
    for idx, segment in enumerate(segments):
        if segment.kind == "pause":
            continue
        text = segment.text.translate(QUOTE_MAP).strip()
        if not text:
            continue
        if segment.kind != "dialogue":
            quoted = QUOTE_SPAN_RE.findall(text)
            if narration_contains_spoken_dialogue(text, quoted):
                issues["narration_contains_dialogue"].append(idx)
            continue

        if text.count('"') % 2 == 1:
            issues["dialogue_unclosed_quote"].append(idx)
            continue

        quoted = QUOTE_SPAN_RE.findall(text)
        if len(quoted) >= 2:
            issues["dialogue_multiple_quotes"].append(idx)

        last_quote = text.rfind('"')
        if last_quote == -1:
            continue
        tail = text[last_quote + 1 :].strip()
        if tail and not INLINE_ATTRIBUTION_TAIL_RE.match(tail):
            issues["dialogue_contains_narration"].append(idx)
    return issues


def refresh_review_metadata(doc: dict[str, Any], configured_slots: list[str]) -> None:
    segments = segments_from_review(doc)
    stats = dict(doc.get("stats") or {})
    stats["segments"] = len(doc.get("segments") or [])
    stats["total_chars"] = sum(spoken_char_len(segment) for segment in segments)
    stats["voice_usage_chars"] = voice_usage_for_segments(segments)
    doc["stats"] = stats
    segment_slots = [segment.voice_slot for segment in segments if segment.kind != "pause"]
    doc["voice_slots_available"] = ordered_voice_slots(
        configured_slots,
        list(doc.get("voice_slots_available") or []) + segment_slots,
    )


def build_preview(doc: dict[str, Any], configured_slots: list[str]) -> dict[str, Any]:
    refresh_review_metadata(doc, configured_slots)
    segments = segments_from_review(doc)
    validation = find_structural_validation_issues(segments)
    preview_segments: list[dict[str, Any]] = []
    for idx, segment in enumerate(segments):
        raw = doc["segments"][idx]
        preview_segments.append(
            {
                "index": idx,
                "id": raw.get("id", idx),
                "voice": segment.voice_slot,
                "kind": segment.kind,
                "text": segment.text,
                "attribution": segment.attribution or "-",
                "pause_ms": segment.pause_ms if segment.kind == "pause" else None,
                "mood": segment.mood,
                "performance": raw.get("performance"),
                "trim_ms_in": int(raw.get("trim_ms_in", 0) or 0),
                "trim_ms_out": int(raw.get("trim_ms_out", 0) or 0),
            }
        )
    return {
        "source": doc.get("source", ""),
        "output": doc.get("output", ""),
        "narrator": doc.get("narrator", ""),
        "approved": bool(doc.get("approved")),
        "voice_slots_available": doc.get("voice_slots_available", []),
        "stats": doc.get("stats", {}),
        "validation": validation,
        "segments": preview_segments,
    }


def dump_yaml_text(doc: dict[str, Any]) -> str:
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=200)

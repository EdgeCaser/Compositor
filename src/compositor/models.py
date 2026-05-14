from __future__ import annotations

from datetime import datetime, timezone
import re
import unicodedata

VOICE_LIBRARY_URL = "https://elevenlabs.io/app/voice-library"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "project"


def default_cast() -> list[dict]:
    return [
        {
            "slot": "narrator",
            "display_name": "Narrator",
            "voice_id": "",
            "gain_db": 0.0,
            "role": "narrator",
            "provider": "elevenlabs",
            "provider_url": VOICE_LIBRARY_URL,
            "notes": "Default narration voice for imported source.",
        },
        {
            "slot": "generic_dialogue",
            "display_name": "Generic Dialogue",
            "voice_id": "",
            "gain_db": 0.0,
            "role": "dialogue_default",
            "provider": "elevenlabs",
            "provider_url": VOICE_LIBRARY_URL,
            "notes": "Fallback for unresolved spoken lines.",
        },
        {
            "slot": "generic_female",
            "display_name": "Generic Female",
            "voice_id": "",
            "gain_db": 0.0,
            "role": "dialogue_female",
            "provider": "elevenlabs",
            "provider_url": VOICE_LIBRARY_URL,
            "notes": "Optional unnamed female slot.",
        },
        {
            "slot": "generic_male",
            "display_name": "Generic Male",
            "voice_id": "",
            "gain_db": 0.0,
            "role": "dialogue_male",
            "provider": "elevenlabs",
            "provider_url": VOICE_LIBRARY_URL,
            "notes": "Optional unnamed male slot.",
        },
    ]


def new_project(project_id: str, name: str) -> dict:
    timestamp = now_iso()
    return {
        "id": project_id,
        "name": name,
        "created_at": timestamp,
        "updated_at": timestamp,
        "voice_library_url": VOICE_LIBRARY_URL,
        "source_documents": [],
        "chapters": [],
        "review_files": [],
        "performance_packets": [],
        "cast": default_cast(),
        "jobs": [],
        "history": [],
    }

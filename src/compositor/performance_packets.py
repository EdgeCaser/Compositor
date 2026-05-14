from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

SEGMENT_RE = re.compile(r"^seg(?P<seg_id>\d{3})_gen_take(?P<take>\d+)\.(?P<ext>mp3|wav)$", re.IGNORECASE)


@dataclass(frozen=True)
class PacketPaths:
    packet_dir: Path
    staging_dir: Path
    performance_dir: Path
    archive_dir: Path


def load_shotlist(packet_dir: Path) -> list[dict[str, Any]]:
    shotlist_path = packet_dir / "shotlist.json"
    if not shotlist_path.exists():
        raise FileNotFoundError(f"shotlist.json not found in {packet_dir}")
    data = json.loads(shotlist_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError(f"shotlist.json in {packet_dir} must be a non-empty list")
    return [entry for entry in data if isinstance(entry, dict)]


def packet_review_name(shotlist: list[dict[str, Any]]) -> str:
    names = {str(entry.get("review_file") or "").strip() for entry in shotlist}
    names.discard("")
    if not names:
        raise ValueError("shotlist entries must include review_file")
    if len(names) != 1:
        raise ValueError("all shotlist entries must share the same review_file")
    return next(iter(names))


def packet_paths(packet_dir: Path) -> PacketPaths:
    return PacketPaths(
        packet_dir=packet_dir,
        staging_dir=packet_dir / "staging",
        performance_dir=packet_dir / "performances",
        archive_dir=packet_dir / "archive",
    )


def chapter_reference_files(packet_dir: Path) -> list[str]:
    names = []
    for path in sorted(packet_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name == "shotlist.json":
            continue
        if path.suffix.lower() in {".wav", ".mp3", ".m4a"}:
            names.append(path.name)
    return names


def staging_ref_candidates(staging_dir: Path, segment_id: int) -> list[Path]:
    return [staging_dir / f"seg{segment_id:03d}_ref.wav"]


def staging_gen_candidates(staging_dir: Path, segment_id: int) -> list[Path]:
    return [
        staging_dir / f"seg{segment_id:03d}_gen.mp3",
        staging_dir / f"seg{segment_id:03d}_gen.wav",
    ]


def list_segment_takes(staging_dir: Path, segment_id: int) -> list[dict[str, Any]]:
    takes: list[dict[str, Any]] = []
    if not staging_dir.exists():
        return takes
    prefix = f"seg{segment_id:03d}_gen_take"
    for path in sorted(staging_dir.iterdir(), reverse=True):
        if not path.is_file() or not path.name.startswith(prefix):
            continue
        match = SEGMENT_RE.match(path.name)
        if not match:
            continue
        takes.append(
            {
                "take": int(match.group("take")),
                "name": path.name,
                "size": path.stat().st_size,
            }
        )
    return takes


def performance_candidates(performance_dir: Path, segment_id: int) -> list[Path]:
    if not performance_dir.exists():
        return []
    prefix = f"{segment_id:03d}_"
    return sorted(
        [
            path
            for path in performance_dir.iterdir()
            if path.is_file() and path.name.startswith(prefix) and path.suffix.lower() in {".mp3", ".wav"}
        ]
    )


def performance_filename(segment_id: int, voice: str, text: str) -> str:
    words = re.findall(r"[A-Za-z]+", text or "")[:3]
    slug = "_".join(word.lower() for word in words) or "line"
    return f"{segment_id:03d}_{voice}_{slug}.mp3"


def context_for_segment(preview_segments: list[dict[str, Any]], index_by_id: dict[int, int], segment_id: int) -> tuple[str | None, str | None]:
    idx = index_by_id.get(int(segment_id))
    if idx is None:
        return None, None
    before = None
    after = None
    for probe in range(idx - 1, -1, -1):
        candidate = preview_segments[probe]
        if candidate.get("kind") != "pause":
            before = str(candidate.get("text") or "")
            break
    for probe in range(idx + 1, len(preview_segments)):
        candidate = preview_segments[probe]
        if candidate.get("kind") != "pause":
            after = str(candidate.get("text") or "")
            break
    return before, after

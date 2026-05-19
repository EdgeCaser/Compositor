"""Stitch per-segment mp3s + pauses into one chapter mp3 via ffmpeg."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile


FFMPEG_BIN = "ffmpeg"
TARGET_SAMPLE_RATE = 44100
TARGET_BITRATE = "128k"
TARGET_CHANNELS = 1


class RenderError(RuntimeError):
    pass


@dataclass
class SegmentClip:
    seg_id: int
    kind: str
    audio_path: Path | None
    pause_ms: int = 0


def is_available() -> dict:
    path = shutil.which(FFMPEG_BIN)
    if path is None:
        return {"available": False, "path": None, "error": "ffmpeg not on PATH"}
    try:
        proc = subprocess.run(
            [FFMPEG_BIN, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "path": path, "error": str(exc)}
    if proc.returncode != 0:
        return {"available": False, "path": path, "error": (proc.stderr or "").strip() or "ffmpeg -version failed"}
    first_line = (proc.stdout.splitlines() or [""])[0]
    return {"available": True, "path": path, "version": first_line, "error": None}


def _run_ffmpeg(args: list[str], *, timeout: int = 600) -> None:
    try:
        proc = subprocess.run(
            [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RenderError("ffmpeg not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"ffmpeg timed out after {timeout}s") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise RenderError(f"ffmpeg exited {proc.returncode}: {stderr[:600]}")


def _silence_clip(work_dir: Path, ms: int) -> Path:
    out = work_dir / f"silence_{ms}ms.mp3"
    if out.exists():
        return out
    seconds = max(ms, 1) / 1000.0
    _run_ffmpeg(
        [
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=mono:sample_rate={TARGET_SAMPLE_RATE}",
            "-t", f"{seconds:.3f}",
            "-c:a", "libmp3lame",
            "-b:a", TARGET_BITRATE,
            "-ar", str(TARGET_SAMPLE_RATE),
            "-ac", str(TARGET_CHANNELS),
            str(out),
        ]
    )
    return out


def _normalize_clip(work_dir: Path, src: Path, seg_id: int) -> Path:
    """Re-encode a segment to the canonical format so concat -c copy can stitch."""
    out = work_dir / f"seg{seg_id:04d}.mp3"
    _run_ffmpeg(
        [
            "-i", str(src),
            "-c:a", "libmp3lame",
            "-b:a", TARGET_BITRATE,
            "-ar", str(TARGET_SAMPLE_RATE),
            "-ac", str(TARGET_CHANNELS),
            str(out),
        ]
    )
    return out


def _concat_file_line(path: Path) -> str:
    escaped = str(path).replace("\\", "/").replace("'", r"'\''")
    return f"file '{escaped}'\n"


def render_chapter(clips: list[SegmentClip], output_path: Path) -> dict:
    if not clips:
        raise RenderError("nothing to render -- no clips supplied")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="compositor_render_") as tmp:
        work = Path(tmp)
        concat_lines: list[str] = []
        normalized_count = 0
        for clip in clips:
            if clip.kind == "pause":
                if clip.pause_ms <= 0:
                    continue
                concat_lines.append(_concat_file_line(_silence_clip(work, clip.pause_ms)))
            else:
                if clip.audio_path is None or not clip.audio_path.exists():
                    raise RenderError(f"segment {clip.seg_id} has no audio file on disk")
                normalized = _normalize_clip(work, clip.audio_path, clip.seg_id)
                normalized_count += 1
                concat_lines.append(_concat_file_line(normalized))
        if not concat_lines:
            raise RenderError("nothing to render -- all clips were empty pauses")
        concat_file = work / "concat.txt"
        concat_file.write_text("".join(concat_lines), encoding="utf-8")
        _run_ffmpeg(
            [
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(output_path),
            ]
        )
    size = output_path.stat().st_size
    return {
        "path": str(output_path),
        "bytes": size,
        "segments_rendered": normalized_count,
        "clips_total": len(clips),
    }

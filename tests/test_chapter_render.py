import shutil
import subprocess

import pytest

from compositor.chapter_render import RenderError, SegmentClip, is_available, render_chapter


pytestmark = pytest.mark.ffmpeg


def test_is_available_reports_truthful_state():
    info = is_available()
    if shutil.which("ffmpeg") is None:
        assert info["available"] is False
    else:
        assert info["available"] is True
        assert "ffmpeg" in (info.get("version") or "").lower()


def test_render_chapter_stitches_audio_and_pause(tmp_path, make_sine_mp3):
    a = make_sine_mp3("a.mp3", freq=440, seconds=0.3)
    b = make_sine_mp3("b.mp3", freq=660, seconds=0.3)
    output = tmp_path / "chapter.mp3"
    summary = render_chapter(
        [
            SegmentClip(seg_id=1, kind="narration", audio_path=a),
            SegmentClip(seg_id=2, kind="pause", audio_path=None, pause_ms=200),
            SegmentClip(seg_id=3, kind="dialogue", audio_path=b),
        ],
        output,
    )
    assert output.exists()
    assert summary["segments_rendered"] == 2
    assert summary["clips_total"] == 3
    duration = _probe_duration(output)
    # 0.3 + 0.2 + 0.3 = 0.8s, allow generous slack for mp3 encoder padding.
    assert 0.6 <= duration <= 1.2


def test_render_chapter_missing_audio_raises(tmp_path):
    output = tmp_path / "chapter.mp3"
    with pytest.raises(RenderError):
        render_chapter(
            [SegmentClip(seg_id=1, kind="narration", audio_path=tmp_path / "missing.mp3")],
            output,
        )


def test_render_chapter_empty_clips_raises(tmp_path):
    with pytest.raises(RenderError):
        render_chapter([], tmp_path / "x.mp3")


def _probe_duration(path) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float((proc.stdout or "0").strip())

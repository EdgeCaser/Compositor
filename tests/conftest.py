"""Shared fixtures for the compositor test suite."""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib import error, request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

DEFAULT_PARAGRAPHS = [
    "The body lay on the slab, cold as the report on the desk beside it.",
    '"Tell me what you found," Frank said.',
    "She paused, then handed him the folder.",
    '"It is worse than we thought."',
]


def _build_docx(path: Path, paragraphs: list[str] = None) -> Path:
    paragraphs = paragraphs if paragraphs is not None else DEFAULT_PARAGRAPHS
    body_parts = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{p.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")}</w:t></w:r></w:p>'
        for p in paragraphs
    )
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{body_parts}</w:body>'
        '</w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("word/document.xml", doc_xml)
    return path


@pytest.fixture
def make_docx(tmp_path):
    def _make(name: str = "Chapter_1.docx", paragraphs: list[str] | None = None) -> Path:
        return _build_docx(tmp_path / name, paragraphs)
    return _make


@pytest.fixture
def sample_docx(make_docx) -> Path:
    return make_docx()


@pytest.fixture
def sample_review_yaml(tmp_path) -> Path:
    p = tmp_path / "Chapter_1.review.yaml"
    p.write_text(
        "source: Chapter_1.docx\n"
        "output: Chapter_1.mp3\n"
        "narrator: narrator\n"
        "approved: false\n"
        "voice_slots_available: [narrator, generic_dialogue, generic_male]\n"
        "segments:\n"
        "  - id: 1\n"
        "    kind: narration\n"
        "    voice: narrator\n"
        "    text: \"The body lay on the slab.\"\n"
        "  - id: 2\n"
        "    kind: dialogue\n"
        "    voice: generic_male\n"
        "    text: '\"Tell me what you found,\" Frank said.'\n"
        "  - id: 3\n"
        "    kind: dialogue\n"
        "    voice: generic_dialogue\n"
        "    text: '\"It is worse than we thought.\"'\n",
        encoding="utf-8",
    )
    return p


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


@pytest.fixture
def ffmpeg_required():
    if not _ffmpeg_available():
        pytest.skip("ffmpeg not on PATH")


@pytest.fixture
def make_sine_mp3(tmp_path, ffmpeg_required):
    def _make(name: str, freq: int = 440, seconds: float = 0.3) -> Path:
        out = tmp_path / name
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi",
                "-i", f"sine=frequency={freq}:duration={seconds}",
                "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "1",
                str(out),
            ],
            check=True,
            capture_output=True,
        )
        return out
    return _make


@dataclass
class ServerHandle:
    base: str
    store: object
    settings: object
    elevenlabs: object
    root: Path
    httpd: ThreadingHTTPServer
    thread: threading.Thread


def _pick_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path, monkeypatch):
    """In-process HTTP server with an isolated store + settings dir."""
    from compositor import app as compositor_app
    from compositor.elevenlabs_client import ElevenLabsService
    from compositor.project_store import ProjectStore
    from compositor.secure_store import AppSettingsStore

    test_root = tmp_path / "repo"
    test_root.mkdir()
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()

    store = ProjectStore(test_root)
    settings = AppSettingsStore(settings_dir)
    elevenlabs = ElevenLabsService(settings)

    monkeypatch.setattr(compositor_app, "STORE", store)
    monkeypatch.setattr(compositor_app, "SETTINGS", settings)
    monkeypatch.setattr(compositor_app, "ELEVENLABS", elevenlabs)
    monkeypatch.setattr(compositor_app, "ROOT", test_root)

    port = _pick_free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), compositor_app.AppHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    # Wait until the port answers (sub-second on a healthy box).
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            with request.urlopen(base + "/api/health", timeout=1) as resp:
                if resp.status == 200:
                    break
        except (error.URLError, OSError):
            time.sleep(0.05)

    handle = ServerHandle(
        base=base, store=store, settings=settings, elevenlabs=elevenlabs,
        root=test_root, httpd=httpd, thread=thread,
    )
    try:
        yield handle
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def call(base: str, method: str, path: str, body=None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = request.Request(
        base + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            return resp.status, json.loads(raw)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload


@pytest.fixture
def http():
    return call

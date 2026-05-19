"""HTTP-level smoke tests against an in-process server."""
from __future__ import annotations

import shutil
from urllib import request

import pytest


def test_health_actions_settings_integrations(server, http):
    status, payload = http(server.base, "GET", "/api/health")
    assert (status, payload) == (200, {"ok": True})

    status, payload = http(server.base, "GET", "/api/actions")
    assert status == 200
    assert len(payload["actions"]) == 3

    status, payload = http(server.base, "GET", "/api/settings")
    assert status == 200
    assert "storage_backend" in payload["providers"]["elevenlabs"]

    status, payload = http(server.base, "GET", "/api/integrations")
    assert status == 200
    assert "claude_cli" in payload
    assert "ffmpeg" in payload


def test_malformed_json_returns_400(server, http):
    req = request.Request(
        server.base + "/api/projects",
        data=b"not json",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    from urllib import error
    try:
        with request.urlopen(req, timeout=5) as resp:
            status = resp.status
        body = ""
    except error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8")
    assert status == 400
    assert "invalid JSON body" in body


def test_create_and_load_project(server, http):
    status, payload = http(server.base, "POST", "/api/projects", {"name": "alpha"})
    assert status == 201
    assert payload["project"]["id"] == "alpha"

    status, payload = http(server.base, "GET", "/api/projects/alpha")
    assert status == 200
    assert payload["project"]["name"] == "alpha"


def test_create_project_requires_name(server, http):
    status, payload = http(server.base, "POST", "/api/projects", {"name": "  "})
    assert status == 400
    assert "name is required" in payload["error"]


def test_unknown_project_404(server, http):
    status, payload = http(server.base, "GET", "/api/projects/nope")
    assert status == 404


def test_full_review_flow(server, http, sample_docx, monkeypatch):
    # Stub out the network-touching pieces.
    import compositor.project_store as ps_mod

    def fake_run_prompt(prompt, **kwargs):
        return '{"2": "Frank", "4": "the woman"}'
    monkeypatch.setattr(ps_mod, "run_prompt", fake_run_prompt)

    # 1. Create project + import docx.
    http(server.base, "POST", "/api/projects", {"name": "flow"})
    status, payload = http(
        server.base, "POST", "/api/projects/import-docx",
        {"project_id": "flow", "source_path": str(sample_docx)},
    )
    assert status == 201
    chapter_id = payload["project"]["chapters"][0]["id"]

    # 2. Export review YAML.
    status, payload = http(
        server.base, "POST",
        f"/api/projects/flow/chapters/{chapter_id}/export-review",
        {},
    )
    assert status == 200
    review_id = payload["review_file_id"]

    # 3. AI attribute (stubbed).
    status, payload = http(
        server.base, "POST",
        f"/api/projects/flow/review-files/{review_id}/attribute",
        {},
    )
    assert status == 200
    assert payload["ok"] is True
    # At least the dialogue-flagged segments should have been considered.
    seg_attributions = {s["id"]: s.get("attribution") for s in payload["preview"]["segments"]}
    assert any(v not in (None, "-", "") for v in seg_attributions.values())


def test_synthesize_without_api_key_returns_400(server, http, sample_docx):
    http(server.base, "POST", "/api/projects", {"name": "synth"})
    http(server.base, "POST", "/api/projects/import-docx",
         {"project_id": "synth", "source_path": str(sample_docx)})
    status, payload = http(server.base, "POST",
                           "/api/projects/synth/chapters/chapter-1/export-review", {})
    review_id = payload["review_file_id"]

    status, payload = http(
        server.base, "POST",
        f"/api/projects/synth/review-files/{review_id}/synthesize",
        {},
    )
    assert status == 400
    assert "ElevenLabs API key" in payload["error"]


def test_clear_performance_missing_segment_id_returns_400(server, http, sample_docx):
    http(server.base, "POST", "/api/projects", {"name": "clr"})
    http(server.base, "POST", "/api/projects/import-docx",
         {"project_id": "clr", "source_path": str(sample_docx)})
    status, payload = http(server.base, "POST",
                           "/api/projects/clr/chapters/chapter-1/export-review", {})
    review_id = payload["review_file_id"]

    status, payload = http(
        server.base, "POST",
        f"/api/projects/clr/review-files/{review_id}/clear-performance",
        {},
    )
    assert status == 400
    assert "segment_id is required" in payload["error"]


def test_save_review_409_on_stale_sha(server, http, sample_docx):
    http(server.base, "POST", "/api/projects", {"name": "stale"})
    http(server.base, "POST", "/api/projects/import-docx",
         {"project_id": "stale", "source_path": str(sample_docx)})
    status, payload = http(server.base, "POST",
                           "/api/projects/stale/chapters/chapter-1/export-review", {})
    review_id = payload["review_file_id"]
    status, payload = http(
        server.base, "GET",
        f"/api/projects/stale/review-files/{review_id}",
    )
    text = payload["text"]
    sha = payload["sha256"]
    modified = "# touched by test\n" + text
    # First save changes disk content (sha bumps).
    status, _ = http(
        server.base, "POST",
        f"/api/projects/stale/review-files/{review_id}/save",
        {"text": modified, "expected_sha256": sha},
    )
    assert status == 200
    # Second save passes the original sha -- on-disk sha is now different.
    status, payload = http(
        server.base, "POST",
        f"/api/projects/stale/review-files/{review_id}/save",
        {"text": modified, "expected_sha256": sha},
    )
    assert status == 409


def test_rendered_file_path_traversal_blocked(server, http):
    http(server.base, "POST", "/api/projects", {"name": "traverse"})
    # Even though the rendered/ dir doesn't exist yet, the server must not serve files outside it.
    from urllib import error
    try:
        with request.urlopen(
            server.base + "/api/projects/traverse/rendered/..%2F..%2F..%2Fproject.json",
            timeout=5,
        ) as resp:
            status = resp.status
    except error.HTTPError as exc:
        status = exc.code
    assert status in (403, 404)


@pytest.mark.ffmpeg
def test_render_endpoint_produces_playable_mp3(server, http, sample_docx, make_sine_mp3):
    """End-to-end render through the HTTP layer using sine-tone fixtures."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    import yaml as _yaml

    http(server.base, "POST", "/api/projects", {"name": "rend"})
    http(server.base, "POST", "/api/projects/import-docx",
         {"project_id": "rend", "source_path": str(sample_docx)})
    status, payload = http(server.base, "POST",
                           "/api/projects/rend/chapters/chapter-1/export-review", {})
    review_id = payload["review_file_id"]

    # Place real audio files where the YAML expects them, then patch the YAML.
    rendered_dir = server.root / "projects" / "rend" / "rendered" / "Chapter_1"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = server.root / "projects" / "rend" / "review" / "Chapter_1.review.yaml"
    doc = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    for seg in doc["segments"]:
        sid = seg["id"]
        audio = make_sine_mp3(f"seg{sid}.mp3", freq=300 + sid * 100, seconds=0.2)
        target = rendered_dir / f"00{sid}_seg.mp3"
        shutil.copy(audio, target)
        seg["performance"] = f"rendered/Chapter_1/00{sid}_seg.mp3"
    yaml_path.write_text(
        _yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8", newline="\n",
    )

    status, payload = http(
        server.base, "POST",
        f"/api/projects/rend/review-files/{review_id}/render", {},
    )
    assert status == 200, payload
    assert payload["bytes"] > 0

    # Fetch the rendered mp3 back through the GET route.
    with request.urlopen(
        server.base + f"/api/projects/rend/rendered/{payload['name']}",
        timeout=10,
    ) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "audio/mpeg"
        body = resp.read()
        assert len(body) == payload["bytes"]

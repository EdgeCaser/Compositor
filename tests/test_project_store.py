from pathlib import Path

import pytest
import yaml

from compositor.project_store import ProjectStore


@pytest.fixture
def store(tmp_path) -> ProjectStore:
    repo = tmp_path / "repo"
    repo.mkdir()
    return ProjectStore(repo)


def test_create_project_makes_dirs(store, tmp_path):
    project = store.create_project("Smoke Test")
    pid = project["id"]
    base = store.project_dir(pid)
    for sub in ("source", "review", "packets", "history"):
        assert (base / sub).is_dir()
    assert (base / "project.json").is_file()


def test_list_projects_skips_dirs_without_project_json(store):
    store.create_project("alpha")
    # Create a dir under projects/ without a project.json -- list should skip it.
    (store.projects_dir / "stray").mkdir()
    listed = store.list_projects()
    ids = {p["id"] for p in listed}
    assert "alpha" in ids
    assert "stray" not in ids


def test_import_docx_classifies_paragraphs(store, sample_docx):
    project = store.import_docx(project_id=None, name="Doc Test", source_path=str(sample_docx))
    chapter = project["chapters"][0]
    assert chapter["stats"]["paragraphs"] == 4
    # Heuristic should detect at least one dialogue/mixed line.
    assert chapter["stats"]["dialogue_paragraphs"] + chapter["stats"]["mixed_paragraphs"] >= 1


def test_export_chapter_review_yaml_writes_and_links(store, sample_docx):
    project = store.import_docx(project_id=None, name="Export Test", source_path=str(sample_docx))
    chapter_id = project["chapters"][0]["id"]
    result = store.export_chapter_review_yaml(project["id"], chapter_id)
    review_id = result["review_file_id"]
    assert result["name"].endswith(".review.yaml")
    fresh = store.load_project(project["id"])
    assert any(r["id"] == review_id for r in fresh["review_files"])
    payload = store.load_review_file(project["id"], review_id)
    assert payload["parse_error"] is None
    assert len(payload["preview"]["segments"]) >= 1


def test_save_review_file_rejects_stale_sha(store, sample_docx):
    project = store.import_docx(project_id=None, name="Sha", source_path=str(sample_docx))
    chapter_id = project["chapters"][0]["id"]
    result = store.export_chapter_review_yaml(project["id"], chapter_id)
    review_id = result["review_file_id"]
    payload = store.load_review_file(project["id"], review_id)
    # First save writes a *different* text so the on-disk sha changes.
    modified = "# touched by test\n" + payload["text"]
    store.save_review_file(
        project["id"], review_id,
        text=modified,
        expected_sha256=payload["sha256"],
    )
    # Second save still passes the *old* sha -- on-disk sha now differs.
    with pytest.raises(ValueError, match="differs from what was loaded"):
        store.save_review_file(
            project["id"], review_id,
            text=modified,
            expected_sha256=payload["sha256"],
        )


def test_clear_review_segment_performance_removes_field(store, sample_docx):
    project = store.import_docx(project_id=None, name="Clear", source_path=str(sample_docx))
    chapter_id = project["chapters"][0]["id"]
    export = store.export_chapter_review_yaml(project["id"], chapter_id)
    review_id = export["review_file_id"]
    # Manually patch a performance into the YAML so clear has something to drop.
    payload = store.load_review_file(project["id"], review_id)
    doc = yaml.safe_load(payload["text"])
    doc["segments"][0]["performance"] = "rendered/fake.mp3"
    store.save_review_file(
        project["id"], review_id,
        text=yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
        expected_sha256=payload["sha256"],
    )
    seg_id = doc["segments"][0]["id"]
    result = store.clear_review_segment_performance(project["id"], review_id, seg_id)
    assert result["cleared"] == "rendered/fake.mp3"
    after = yaml.safe_load(result["text"])
    assert "performance" not in after["segments"][0]


def test_undo_restores_prior_state(store, sample_docx):
    project = store.import_docx(project_id=None, name="Undo", source_path=str(sample_docx))
    pid = project["id"]
    chapter_id = project["chapters"][0]["id"]
    store.update_progress(pid, chapter_id, 5)
    after_update = store.load_project(pid)
    assert after_update["chapters"][0]["stats"]["lines_read"] == 5
    store.undo(pid)
    restored = store.load_project(pid)
    assert restored["chapters"][0]["stats"]["lines_read"] == 0


def test_render_review_chapter_requires_audio(store, sample_docx):
    project = store.import_docx(project_id=None, name="Render", source_path=str(sample_docx))
    export = store.export_chapter_review_yaml(project["id"], project["chapters"][0]["id"])
    with pytest.raises(ValueError, match="missing audio"):
        store.render_review_chapter(project["id"], export["review_file_id"])


def test_synthesize_skips_segments_without_voice_id(store, sample_docx):
    project = store.import_docx(project_id=None, name="Synth", source_path=str(sample_docx))
    export = store.export_chapter_review_yaml(project["id"], project["chapters"][0]["id"])
    review_id = export["review_file_id"]

    calls = []

    def fake_synth(voice_id, text):
        calls.append((voice_id, text))
        return b"fake mp3 bytes"

    # Cast slots have empty voice_id by default -- everything should land in skipped.
    result = store.synthesize_review_segments(
        project["id"], review_id, synthesize_fn=fake_synth,
    )
    assert calls == []
    assert len(result["skipped"]) >= 1
    assert all("no ElevenLabs voice_id" in s["reason"] for s in result["skipped"])


def test_synthesize_writes_audio_for_assigned_voice(store, sample_docx):
    project = store.import_docx(project_id=None, name="Synth2", source_path=str(sample_docx))
    pid = project["id"]
    store.upsert_cast_voice(pid, {
        "slot": "narrator",
        "display_name": "Narrator",
        "voice_id": "fake_voice_id",
        "role": "narrator",
    })
    store.upsert_cast_voice(pid, {
        "slot": "generic_dialogue",
        "display_name": "Generic Dialogue",
        "voice_id": "fake_dialogue_id",
        "role": "dialogue_default",
    })
    export = store.export_chapter_review_yaml(pid, project["chapters"][0]["id"])
    review_id = export["review_file_id"]

    def fake_synth(voice_id, text):
        return b"\xff\xfb\x90\x00" + b"x" * 256  # mp3-ish header + filler

    result = store.synthesize_review_segments(pid, review_id, synthesize_fn=fake_synth)
    assert len(result["synthesized"]) >= 1
    # Every synthesized entry should point to a real file under rendered/.
    for entry in result["synthesized"]:
        out = Path(store.project_dir(pid)) / entry["path"]
        assert out.exists()
        assert out.read_bytes().startswith(b"\xff\xfb")

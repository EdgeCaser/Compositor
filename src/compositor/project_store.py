from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from .actions import apply_dialogue_narration, apply_emotional_guidance, apply_voice_assignment, run_action
from .docx_import import extract_docx_paragraphs
from .models import new_project, now_iso, slugify
from .performance_packets import (
    chapter_reference_files,
    context_for_segment,
    list_segment_takes,
    load_shotlist,
    packet_paths,
    packet_review_name,
    performance_candidates,
    performance_filename,
    staging_gen_candidates,
    staging_ref_candidates,
)
from .review_yaml import build_preview, dump_yaml_text, parse_yaml_text, yaml_error_payload


class ProjectStore:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.projects_dir = repo_root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> list[dict]:
        projects: list[dict] = []
        for path in sorted(self.projects_dir.iterdir()):
            state = path / "project.json"
            if not state.exists():
                continue
            project = self._normalize_project(self._read_json(state))
            projects.append(
                {
                    "id": project["id"],
                    "name": project["name"],
                    "updated_at": project.get("updated_at"),
                    "chapters": len(project.get("chapters", [])),
                    "review_files": len(project.get("review_files", [])),
                    "performance_packets": len(project.get("performance_packets", [])),
                    "jobs": len(project.get("jobs", [])),
                }
            )
        return sorted(projects, key=lambda item: item.get("updated_at") or "", reverse=True)

    def create_project(self, name: str) -> dict:
        project_id = self._unique_project_id(slugify(name))
        project = new_project(project_id, name)
        project_dir = self.project_dir(project_id)
        (project_dir / "source").mkdir(parents=True, exist_ok=True)
        (project_dir / "review").mkdir(parents=True, exist_ok=True)
        (project_dir / "packets").mkdir(parents=True, exist_ok=True)
        (project_dir / "history").mkdir(parents=True, exist_ok=True)
        self._save(project, "Created project")
        return project

    def load_project(self, project_id: str) -> dict:
        state_path = self.project_dir(project_id) / "project.json"
        if not state_path.exists():
            raise FileNotFoundError(project_id)
        return self._normalize_project(self._read_json(state_path))

    def import_docx(self, *, project_id: str | None, name: str | None, source_path: str) -> dict:
        if project_id:
            project = self.load_project(project_id)
        else:
            if not name:
                raise ValueError("name is required when creating a project from import")
            project = self.create_project(name)

        src = Path(source_path).expanduser()
        if not src.exists():
            raise FileNotFoundError(source_path)
        if src.suffix.lower() != ".docx":
            raise ValueError("source_path must point to a .docx file")

        project_dir = self.project_dir(project["id"])
        source_dir = project_dir / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        copied_path = source_dir / self._unique_filename(source_dir, src.name)
        shutil.copy2(src, copied_path)

        paragraphs = extract_docx_paragraphs(copied_path)
        chapter_id = self._unique_chapter_id(project, slugify(src.stem))
        document_id = f"doc-{len(project.get('source_documents', [])) + 1}"
        chapter = {
            "id": chapter_id,
            "title": src.stem,
            "source_document_id": document_id,
            "source_name": src.name,
            "paragraphs": [
                {
                    "index": idx,
                    "text": text,
                    "kind": "narration",
                    "guidance": "flat",
                    "voice_slot": "narrator",
                }
                for idx, text in enumerate(paragraphs)
            ],
            "stats": {
                "paragraphs": len(paragraphs),
                "dialogue_paragraphs": 0,
                "mixed_paragraphs": 0,
                "narration_paragraphs": len(paragraphs),
                "estimated_lines": 0,
                "lines_read": 0,
            },
            "analysis": {},
        }

        apply_dialogue_narration(chapter)
        apply_emotional_guidance(chapter)
        apply_voice_assignment(chapter, project.get("cast", []))

        project.setdefault("source_documents", []).append(
            {
                "id": document_id,
                "name": src.name,
                "copied_path": str(copied_path.relative_to(project_dir)),
                "source_path": str(src),
                "imported_at": now_iso(),
            }
        )
        project.setdefault("chapters", []).append(chapter)
        self._save(project, f"Imported {src.name}")
        return project

    def import_review_yaml(self, *, project_id: str | None, name: str | None, source_path: str) -> dict:
        if project_id:
            project = self.load_project(project_id)
        else:
            if not name:
                raise ValueError("name is required when creating a project from import")
            project = self.create_project(name)

        src = Path(source_path).expanduser()
        if not src.exists():
            raise FileNotFoundError(source_path)
        if src.suffix.lower() not in {".yaml", ".yml"}:
            raise ValueError("source_path must point to a YAML review file")

        project_dir = self.project_dir(project["id"])
        review_dir = project_dir / "review"
        review_dir.mkdir(parents=True, exist_ok=True)
        copied_path = review_dir / self._unique_filename(review_dir, src.name)
        shutil.copy2(src, copied_path)

        file_id = self._unique_review_id(project, slugify(src.stem))
        project.setdefault("review_files", []).append(
            {
                "id": file_id,
                "name": copied_path.name,
                "copied_path": str(copied_path.relative_to(project_dir)),
                "source_path": str(src),
                "imported_at": now_iso(),
            }
        )
        self._relink_packets_for_review(project, file_id, copied_path.name)
        for packet in project.get("performance_packets", []):
            if packet.get("review_name") == copied_path.name:
                self._normalize_packet_review_paths(
                    project,
                    Path(str(packet.get("source_path") or "")).name or str(packet.get("name") or ""),
                    str(packet.get("name") or ""),
                    file_id,
                )
        self._save(project, f"Imported review {src.name}")
        return project

    def import_performance_packet(self, *, project_id: str | None, name: str | None, source_path: str) -> dict:
        if project_id:
            project = self.load_project(project_id)
        else:
            if not name:
                raise ValueError("name is required when creating a project from import")
            project = self.create_project(name)

        src = Path(source_path).expanduser()
        if not src.exists():
            raise FileNotFoundError(source_path)
        if not src.is_dir():
            raise ValueError("source_path must point to a recording packet directory")

        shotlist = load_shotlist(src)
        review_name = packet_review_name(shotlist)

        project_dir = self.project_dir(project["id"])
        packets_dir = project_dir / "packets"
        packets_dir.mkdir(parents=True, exist_ok=True)

        copied_name = self._unique_dir_name(packets_dir, src.name)
        copied_path = packets_dir / copied_name
        shutil.copytree(src, copied_path)

        src_audio_root = src.parent.parent if src.parent.parent.exists() else None
        if src_audio_root is not None:
            staging_src = src_audio_root / "_sts_staging" / src.name
            perf_src = src_audio_root / "_performances" / src.name
            if staging_src.exists() and staging_src.is_dir():
                shutil.copytree(staging_src, copied_path / "staging")
            if perf_src.exists() and perf_src.is_dir():
                shutil.copytree(perf_src, copied_path / "performances")

        packet_id = self._unique_packet_id(project, slugify(src.stem))
        linked_review = self._resolve_review_file(project, review_name)
        project.setdefault("performance_packets", []).append(
            {
                "id": packet_id,
                "name": copied_name,
                "review_name": review_name,
                "linked_review_file_id": linked_review.get("id") if linked_review else None,
                "copied_path": str(copied_path.relative_to(project_dir)),
                "source_path": str(src),
                "imported_at": now_iso(),
            }
        )
        if linked_review is not None:
            self._normalize_packet_review_paths(project, src.name, copied_name, linked_review["id"])
        self._save(project, f"Imported packet {src.name}")
        return project

    def upsert_cast_voice(self, project_id: str, payload: dict) -> dict:
        project = self.load_project(project_id)
        slot = str(payload.get("slot", "")).strip()
        if not slot:
            raise ValueError("slot is required")

        cast = project.setdefault("cast", [])
        existing = next((voice for voice in cast if voice.get("slot") == slot), None)
        cleaned = {
            "slot": slot,
            "display_name": str(payload.get("display_name") or slot),
            "voice_id": str(payload.get("voice_id") or ""),
            "gain_db": float(payload.get("gain_db") or 0.0),
            "role": str(payload.get("role") or "custom"),
            "provider": str(payload.get("provider") or "elevenlabs"),
            "provider_url": str(payload.get("provider_url") or ""),
            "notes": str(payload.get("notes") or ""),
        }
        if existing is None:
            cast.append(cleaned)
            label = f"Added cast voice {slot}"
        else:
            existing.update(cleaned)
            label = f"Updated cast voice {slot}"
        self._save(project, label)
        return project

    def update_progress(self, project_id: str, chapter_id: str, lines_read: int) -> dict:
        project = self.load_project(project_id)
        chapter = next((item for item in project.get("chapters", []) if item.get("id") == chapter_id), None)
        if chapter is None:
            raise ValueError(f"chapter not found: {chapter_id}")
        chapter.setdefault("stats", {})["lines_read"] = max(0, int(lines_read))
        self._save(project, f"Updated progress for {chapter.get('title', chapter_id)}")
        return project

    def run_action(self, project_id: str, chapter_id: str, action_id: str) -> dict:
        project = self.load_project(project_id)
        run_action(project, chapter_id, action_id)
        self._save(project, f"Ran {action_id} on {chapter_id}")
        return project

    def load_review_file(self, project_id: str, file_id: str) -> dict:
        project = self.load_project(project_id)
        meta = self._find_review_file(project, file_id)
        path = self.project_dir(project_id) / meta["copied_path"]
        text = path.read_text(encoding="utf-8")
        sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            doc = parse_yaml_text(text)
            preview = build_preview(doc, self._project_voice_slots(project))
            parse_error = None
        except Exception as exc:  # noqa: BLE001
            preview = None
            parse_error = yaml_error_payload(exc)
        return {
            "file": meta,
            "path": str(path),
            "text": text,
            "sha256": sha256,
            "mtime_ns": path.stat().st_mtime_ns,
            "preview": preview,
            "parse_error": parse_error,
        }

    def preview_review_text(self, project_id: str, text: str) -> dict:
        project = self.load_project(project_id)
        doc = parse_yaml_text(text)
        return build_preview(doc, self._project_voice_slots(project))

    def set_review_segment_voice(
        self,
        project_id: str,
        text: str,
        segment_id: int,
        voice: str,
    ) -> dict:
        project = self.load_project(project_id)
        voice = str(voice or "").strip()
        if not voice:
            raise ValueError("voice is required")

        doc = parse_yaml_text(text)
        valid_slots = self._project_voice_slots(project) + list(doc.get("voice_slots_available") or [])
        valid = list(dict.fromkeys([slot for slot in valid_slots if slot]))
        if voice not in valid:
            raise ValueError(f"Unknown voice slot: {voice}")

        target: dict | None = None
        for segment in doc.get("segments", []):
            if int(segment.get("id", -1)) == int(segment_id):
                target = segment
                break
        if target is None:
            raise FileNotFoundError(f"Segment id {segment_id} not found.")
        if target.get("kind") == "pause":
            raise ValueError("Pause segments do not have editable voice assignments.")

        cleared_performance = bool(target.get("performance"))
        target["voice"] = voice
        if target.get("kind") == "dialogue":
            target["attribution"] = "manual"
        if cleared_performance:
            target.pop("performance", None)

        preview = build_preview(doc, self._project_voice_slots(project))
        updated_text = dump_yaml_text(doc)
        return {
            "text": updated_text,
            "preview": preview,
            "cleared_performance": cleared_performance,
        }

    def save_review_file(self, project_id: str, file_id: str, text: str, expected_sha256: str = "") -> dict:
        project = self.load_project(project_id)
        meta = self._find_review_file(project, file_id)
        path = self.project_dir(project_id) / meta["copied_path"]
        current_text = path.read_text(encoding="utf-8")
        current_sha = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
        if expected_sha256 and current_sha != expected_sha256:
            raise ValueError("File content on disk differs from what was loaded.")

        doc = parse_yaml_text(text)
        preview = build_preview(doc, self._project_voice_slots(project))
        path.write_text(text, encoding="utf-8", newline="\n")
        self._save(project, f"Saved review {meta['name']}")
        stat = path.stat()
        return {
            "name": meta["name"],
            "mtime_ns": stat.st_mtime_ns,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "preview": preview,
        }

    def load_performance_packet(self, project_id: str, packet_id: str) -> dict:
        project = self.load_project(project_id)
        packet_meta = self._find_packet(project, packet_id)
        project_dir = self.project_dir(project_id)
        packet_dir = project_dir / packet_meta["copied_path"]
        shotlist = load_shotlist(packet_dir)
        review_name = str(packet_meta.get("review_name") or packet_review_name(shotlist))
        review_meta = self._resolve_packet_review(project, packet_meta, review_name)
        review_preview = None
        review_parse_error = None
        review_segments: list[dict] = []
        index_by_id: dict[int, int] = {}

        if review_meta is not None:
            review_payload = self.load_review_file(project_id, review_meta["id"])
            review_preview = review_payload["preview"]
            review_parse_error = review_payload["parse_error"]
            if review_preview:
                review_segments = list(review_preview.get("segments") or [])
                index_by_id = {int(segment.get("id", -1)): idx for idx, segment in enumerate(review_segments)}

        paths = packet_paths(packet_dir)
        segment_rows: list[dict] = []
        counts = {"pending": 0, "recorded": 0, "ready": 0, "approved": 0, "issues": 0}

        for entry in shotlist:
            segment_id = int(entry.get("segment_id") or -1)
            if segment_id < 0:
                continue
            review_segment = review_segments[index_by_id[segment_id]] if segment_id in index_by_id else None
            before, after = context_for_segment(review_segments, index_by_id, segment_id) if review_segment else (None, None)

            ref_exists = any(candidate.exists() for candidate in staging_ref_candidates(paths.staging_dir, segment_id))
            gen_path = next((candidate for candidate in staging_gen_candidates(paths.staging_dir, segment_id) if candidate.exists()), None)
            takes = list_segment_takes(paths.staging_dir, segment_id)
            perf_files = performance_candidates(paths.performance_dir, segment_id)
            shotlist_voice = str(entry.get("voice") or "").strip()
            review_voice = review_segment.get("voice") if review_segment else None

            performance_path = None
            performance_exists = False
            performance_source = None
            expected_voice = review_voice or shotlist_voice
            chosen = None
            if review_segment and review_segment.get("performance"):
                performance_path = str(review_segment.get("performance"))
                perf_candidate = project_dir / performance_path
                if perf_candidate.exists():
                    performance_exists = True
                    performance_source = "review"
                else:
                    local_match = paths.performance_dir / Path(performance_path).name
                    if local_match.exists():
                        performance_path = str((Path(packet_meta["copied_path"]) / "performances" / local_match.name).as_posix())
                        performance_exists = True
                        performance_source = "packet"
            if not performance_exists and perf_files:
                chosen = next(
                    (path for path in perf_files if not expected_voice or path.name.startswith(f"{segment_id:03d}_{expected_voice}_")),
                    None,
                )
                if chosen is None:
                    chosen = None
            if not performance_exists and chosen is not None:
                performance_path = str((Path(packet_meta["copied_path"]) / "performances" / chosen.name).as_posix())
                performance_exists = True
                performance_source = "packet"

            status = "pending"
            if performance_exists:
                status = "approved"
            elif gen_path is not None:
                status = "ready"
            elif ref_exists:
                status = "recorded"

            issue_flags: list[str] = []
            if review_segment is None:
                issue_flags.append("missing_review_segment")
            elif shotlist_voice and review_voice and review_voice != shotlist_voice:
                issue_flags.append("voice_mismatch")
            if review_parse_error:
                issue_flags.append("review_parse_error")

            counts[status] += 1
            if issue_flags:
                counts["issues"] += 1

            segment_rows.append(
                {
                    "segment_id": segment_id,
                    "paragraph_index": entry.get("paragraph_index"),
                    "chapter": entry.get("chapter"),
                    "text": str(entry.get("text") or review_segment.get("text") if review_segment else entry.get("text") or ""),
                    "rationale": entry.get("rationale"),
                    "direction_file": entry.get("direction_file"),
                    "status": status,
                    "voice_slot": review_voice or shotlist_voice,
                    "shotlist_voice": shotlist_voice,
                    "review_voice": review_voice,
                    "mood": review_segment.get("mood") if review_segment else None,
                    "performance_path": performance_path,
                    "performance_source": performance_source,
                    "performance_exists": performance_exists,
                    "has_ref": ref_exists,
                    "has_gen": gen_path is not None,
                    "generated_name": gen_path.name if gen_path else None,
                    "takes": takes,
                    "takes_count": len(takes),
                    "context_before": before,
                    "context_after": after,
                    "attribution": review_segment.get("attribution") if review_segment else None,
                    "issues": issue_flags,
                }
            )

        return {
            "packet": packet_meta,
            "review_file": review_meta,
            "review_name": review_name,
            "review_parse_error": review_parse_error,
            "chapter_reference_files": chapter_reference_files(packet_dir),
            "counts": counts,
            "segments": segment_rows,
        }

    def set_packet_segment_voice(self, project_id: str, packet_id: str, segment_id: int, voice: str) -> dict:
        project = self.load_project(project_id)
        packet_meta = self._find_packet(project, packet_id)
        review_meta = self._resolve_packet_review(project, packet_meta, str(packet_meta.get("review_name") or ""))
        if review_meta is None:
            raise ValueError("No linked review YAML found for this packet.")

        project_dir = self.project_dir(project_id)
        review_path = project_dir / review_meta["copied_path"]
        shotlist_path = project_dir / packet_meta["copied_path"] / "shotlist.json"

        doc = parse_yaml_text(review_path.read_text(encoding="utf-8"))
        valid_slots = self._project_voice_slots(project) + list(doc.get("voice_slots_available") or [])
        valid = list(dict.fromkeys([slot for slot in valid_slots if slot]))
        if voice not in valid:
            raise ValueError(f"Unknown voice slot: {voice}")

        target = self._find_review_segment(doc, segment_id)
        if target is None:
            raise FileNotFoundError(f"Segment id {segment_id} not found in linked review.")
        if target.get("kind") == "pause":
            raise ValueError("Pause segments do not have editable voice assignments.")

        target["voice"] = voice
        if target.get("kind") == "dialogue":
            target["attribution"] = "manual"
        target.pop("performance", None)
        build_preview(doc, self._project_voice_slots(project))
        review_path.write_text(dump_yaml_text(doc), encoding="utf-8", newline="\n")

        shotlist = load_shotlist(shotlist_path.parent)
        updated = False
        for entry in shotlist:
            if int(entry.get("segment_id") or -1) == int(segment_id):
                entry["voice"] = voice
                updated = True
                break
        if not updated:
            raise FileNotFoundError(f"Segment id {segment_id} not found in shotlist.")
        shotlist_path.write_text(json.dumps(shotlist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        self._archive_active_generation(project_dir / packet_meta["copied_path"], segment_id)
        self._save(project, f"Updated packet {packet_meta['name']} segment {segment_id} voice")
        return self.load_performance_packet(project_id, packet_id)

    def set_packet_segment_approval(self, project_id: str, packet_id: str, segment_id: int, approved: bool) -> dict:
        project = self.load_project(project_id)
        packet_meta = self._find_packet(project, packet_id)
        review_meta = self._resolve_packet_review(project, packet_meta, str(packet_meta.get("review_name") or ""))
        if review_meta is None:
            raise ValueError("No linked review YAML found for this packet.")

        project_dir = self.project_dir(project_id)
        packet_dir = project_dir / packet_meta["copied_path"]
        paths = packet_paths(packet_dir)
        review_path = project_dir / review_meta["copied_path"]
        doc = parse_yaml_text(review_path.read_text(encoding="utf-8"))
        target = self._find_review_segment(doc, segment_id)
        if target is None:
            raise FileNotFoundError(f"Segment id {segment_id} not found in linked review.")

        if approved:
            perf_path = next(iter(performance_candidates(paths.performance_dir, segment_id)), None)
            if perf_path is None:
                gen_path = next((candidate for candidate in staging_gen_candidates(paths.staging_dir, segment_id) if candidate.exists()), None)
                if gen_path is None:
                    raise ValueError("No generated or performance file exists for this segment yet.")
                ext = gen_path.suffix.lower() or ".mp3"
                filename = performance_filename(segment_id, str(target.get("voice") or "voice"), str(target.get("text") or ""))
                if ext != ".mp3":
                    filename = Path(filename).with_suffix(ext).name
                paths.performance_dir.mkdir(parents=True, exist_ok=True)
                perf_path = paths.performance_dir / filename
                shutil.copy2(gen_path, perf_path)
            relpath = (Path(packet_meta["copied_path"]) / "performances" / perf_path.name).as_posix()
            target["performance"] = relpath
            label = f"Approved packet {packet_meta['name']} segment {segment_id}"
        else:
            target.pop("performance", None)
            label = f"Cleared packet {packet_meta['name']} segment {segment_id} performance"

        build_preview(doc, self._project_voice_slots(project))
        review_path.write_text(dump_yaml_text(doc), encoding="utf-8", newline="\n")
        self._save(project, label)
        return self.load_performance_packet(project_id, packet_id)

    def undo(self, project_id: str) -> dict:
        project = self.load_project(project_id)
        history = list(project.get("history", []))
        if len(history) < 2:
            raise ValueError("nothing to undo")
        target = history[-2]
        snapshot_path = self.project_dir(project_id) / target["snapshot_file"]
        restored = self._normalize_project(self._read_json(snapshot_path))
        self._restore_review_snapshot(project_id, target.get("review_snapshot_dir"))
        self._restore_packet_snapshot(project_id, target.get("packet_snapshot_dir"))
        self._write_project(restored)
        return restored

    def project_dir(self, project_id: str) -> Path:
        return self.projects_dir / project_id

    def _save(self, project: dict, label: str) -> None:
        timestamp = now_iso()
        project["updated_at"] = timestamp
        project_dir = self.project_dir(project["id"])
        project_dir.mkdir(parents=True, exist_ok=True)
        history_dir = project_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)

        snapshot_id = f"{timestamp.replace(':', '').replace('+00:00', 'z').replace('-', '')}-{slugify(label)}"
        entry = {
            "id": snapshot_id,
            "label": label,
            "timestamp": timestamp,
            "snapshot_file": f"history/{snapshot_id}.json",
        }
        review_snapshot_dir = self._snapshot_review_files(project, snapshot_id)
        if review_snapshot_dir is not None:
            entry["review_snapshot_dir"] = review_snapshot_dir
        packet_snapshot_dir = self._snapshot_packet_files(project, snapshot_id)
        if packet_snapshot_dir is not None:
            entry["packet_snapshot_dir"] = packet_snapshot_dir
        project.setdefault("history", []).append(entry)
        self._write_project(project)
        snapshot_path = project_dir / entry["snapshot_file"]
        snapshot_path.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")

    def _write_project(self, project: dict) -> None:
        path = self.project_dir(project["id"]) / "project.json"
        path.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _normalize_project(project: dict) -> dict:
        project.setdefault("source_documents", [])
        project.setdefault("chapters", [])
        project.setdefault("review_files", [])
        project.setdefault("performance_packets", [])
        project.setdefault("cast", [])
        project.setdefault("jobs", [])
        project.setdefault("history", [])
        return project

    def _snapshot_review_files(self, project: dict, snapshot_id: str) -> str | None:
        review_files = list(project.get("review_files") or [])
        if not review_files:
            return None
        project_dir = self.project_dir(project["id"])
        snapshot_dir = project_dir / "history" / f"{snapshot_id}__review"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        copied = False
        for meta in review_files:
            copied_path = str(meta.get("copied_path") or "")
            if not copied_path:
                continue
            src = project_dir / copied_path
            if not src.exists():
                continue
            shutil.copy2(src, snapshot_dir / Path(copied_path).name)
            copied = True
        if not copied:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            return None
        return str(snapshot_dir.relative_to(project_dir))

    def _restore_review_snapshot(self, project_id: str, snapshot_dir_rel: str | None) -> None:
        if not snapshot_dir_rel:
            return
        project_dir = self.project_dir(project_id)
        snapshot_dir = project_dir / snapshot_dir_rel
        if not snapshot_dir.exists():
            return
        review_dir = project_dir / "review"
        shutil.rmtree(review_dir, ignore_errors=True)
        review_dir.mkdir(parents=True, exist_ok=True)
        for item in snapshot_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, review_dir / item.name)

    def _snapshot_packet_files(self, project: dict, snapshot_id: str) -> str | None:
        packets = list(project.get("performance_packets") or [])
        if not packets:
            return None
        project_dir = self.project_dir(project["id"])
        snapshot_dir = project_dir / "history" / f"{snapshot_id}__packets"
        copied = False
        for meta in packets:
            copied_path = str(meta.get("copied_path") or "")
            if not copied_path:
                continue
            packet_dir = project_dir / copied_path
            if not packet_dir.exists():
                continue
            for path in packet_dir.rglob("*.json"):
                rel = path.relative_to(project_dir)
                dest = snapshot_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
                copied = True
        if not copied:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            return None
        return str(snapshot_dir.relative_to(project_dir))

    def _restore_packet_snapshot(self, project_id: str, snapshot_dir_rel: str | None) -> None:
        if not snapshot_dir_rel:
            return
        project_dir = self.project_dir(project_id)
        snapshot_dir = project_dir / snapshot_dir_rel
        if not snapshot_dir.exists():
            return
        for item in snapshot_dir.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(snapshot_dir)
            dest = project_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)

    @staticmethod
    def _project_voice_slots(project: dict) -> list[str]:
        return [str(voice.get("slot") or "").strip() for voice in project.get("cast", []) if str(voice.get("slot") or "").strip()]

    @staticmethod
    def _find_review_file(project: dict, file_id: str) -> dict:
        meta = next((item for item in project.get("review_files", []) if item.get("id") == file_id), None)
        if meta is None:
            raise FileNotFoundError(f"review file not found: {file_id}")
        return meta

    @staticmethod
    def _find_packet(project: dict, packet_id: str) -> dict:
        meta = next((item for item in project.get("performance_packets", []) if item.get("id") == packet_id), None)
        if meta is None:
            raise FileNotFoundError(f"packet not found: {packet_id}")
        return meta

    def _unique_project_id(self, base: str) -> str:
        existing = {path.name for path in self.projects_dir.iterdir() if path.is_dir()}
        if base not in existing:
            return base
        index = 2
        while f"{base}-{index}" in existing:
            index += 1
        return f"{base}-{index}"

    @staticmethod
    def _unique_filename(directory: Path, name: str) -> str:
        target = directory / name
        if not target.exists():
            return name
        stem = target.stem
        suffix = target.suffix
        index = 2
        while (directory / f"{stem}-{index}{suffix}").exists():
            index += 1
        return f"{stem}-{index}{suffix}"

    @staticmethod
    def _unique_chapter_id(project: dict, base: str) -> str:
        existing = {chapter.get("id") for chapter in project.get("chapters", [])}
        if base not in existing:
            return base
        index = 2
        while f"{base}-{index}" in existing:
            index += 1
        return f"{base}-{index}"

    @staticmethod
    def _unique_review_id(project: dict, base: str) -> str:
        existing = {item.get("id") for item in project.get("review_files", [])}
        if base not in existing:
            return base
        index = 2
        while f"{base}-{index}" in existing:
            index += 1
        return f"{base}-{index}"

    @staticmethod
    def _unique_packet_id(project: dict, base: str) -> str:
        existing = {item.get("id") for item in project.get("performance_packets", [])}
        if base not in existing:
            return base
        index = 2
        while f"{base}-{index}" in existing:
            index += 1
        return f"{base}-{index}"

    @staticmethod
    def _unique_dir_name(directory: Path, name: str) -> str:
        target = directory / name
        if not target.exists():
            return name
        index = 2
        while (directory / f"{name}-{index}").exists():
            index += 1
        return f"{name}-{index}"

    @staticmethod
    def _resolve_review_file(project: dict, review_name: str) -> dict | None:
        return next((item for item in project.get("review_files", []) if item.get("name") == review_name), None)

    def _resolve_packet_review(self, project: dict, packet_meta: dict, review_name: str) -> dict | None:
        linked_id = str(packet_meta.get("linked_review_file_id") or "").strip()
        if linked_id:
            try:
                return self._find_review_file(project, linked_id)
            except FileNotFoundError:
                pass
        return self._resolve_review_file(project, review_name)

    @staticmethod
    def _find_review_segment(doc: dict, segment_id: int) -> dict | None:
        for segment in doc.get("segments", []):
            if int(segment.get("id", -1)) == int(segment_id):
                return segment
        return None

    def _normalize_packet_review_paths(self, project: dict, source_packet_name: str, local_packet_name: str, review_file_id: str) -> None:
        project_dir = self.project_dir(project["id"])
        review_meta = self._find_review_file(project, review_file_id)
        review_path = project_dir / review_meta["copied_path"]
        doc = parse_yaml_text(review_path.read_text(encoding="utf-8"))
        packet_perf_prefix = f"_performances/{source_packet_name}/"
        new_prefix = f"packets/{local_packet_name}/performances/"
        changed = False
        for segment in doc.get("segments", []):
            performance = str(segment.get("performance") or "").strip()
            if not performance:
                continue
            if packet_perf_prefix not in performance:
                continue
            filename = Path(performance).name
            local_path = project_dir / "packets" / local_packet_name / "performances" / filename
            if not local_path.exists():
                continue
            segment["performance"] = f"{new_prefix}{filename}"
            changed = True
        if changed:
            build_preview(doc, self._project_voice_slots(project))
            review_path.write_text(dump_yaml_text(doc), encoding="utf-8", newline="\n")

    @staticmethod
    def _relink_packets_for_review(project: dict, review_file_id: str, review_name: str) -> None:
        for packet in project.get("performance_packets", []):
            if packet.get("review_name") == review_name and not packet.get("linked_review_file_id"):
                packet["linked_review_file_id"] = review_file_id

    def _archive_active_generation(self, packet_dir: Path, segment_id: int) -> None:
        paths = packet_paths(packet_dir)
        paths.archive_dir.mkdir(parents=True, exist_ok=True)
        timestamp = now_iso().replace(":", "").replace("+00:00", "z").replace("-", "")
        for candidate in list(staging_gen_candidates(paths.staging_dir, segment_id)):
            if not candidate.exists():
                continue
            dest = paths.archive_dir / f"{candidate.stem}__{timestamp}{candidate.suffix}"
            shutil.move(str(candidate), str(dest))
        for take in list_segment_takes(paths.staging_dir, segment_id):
            candidate = paths.staging_dir / take["name"]
            if not candidate.exists():
                continue
            dest = paths.archive_dir / f"{Path(take['name']).stem}__{timestamp}{Path(take['name']).suffix}"
            shutil.move(str(candidate), str(dest))
        overrides = paths.staging_dir / f"seg{segment_id:03d}_overrides.json"
        if overrides.exists():
            dest = paths.archive_dir / f"{overrides.stem}__{timestamp}{overrides.suffix}"
            shutil.move(str(overrides), str(dest))

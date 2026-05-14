from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse
import webbrowser

from .actions import list_actions
from .elevenlabs_client import ElevenLabsError, ElevenLabsService
from .project_store import ProjectStore
from .review_yaml import yaml_error_payload
from .secure_store import AppSettingsStore

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "web"
STORE = ProjectStore(ROOT)
SETTINGS = AppSettingsStore()
ELEVENLABS = ElevenLabsService(SETTINGS)


def json_bytes(payload: dict | list) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class AppHandler(BaseHTTPRequestHandler):
    server_version = "Compositor/0.4"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/":
            return self._serve_static("index.html", "text/html; charset=utf-8")
        if parsed.path == "/app.js":
            return self._serve_static("app.js", "application/javascript; charset=utf-8")
        if parsed.path == "/styles.css":
            return self._serve_static("styles.css", "text/css; charset=utf-8")
        if parsed.path == "/api/health":
            return self._json({"ok": True})
        if parsed.path == "/api/settings":
            return self._json(ELEVENLABS.public_settings())
        if parsed.path == "/api/providers/elevenlabs/voices":
            refresh = parse_qs(parsed.query or "").get("refresh", ["0"])[0] == "1"
            return self._handle_elevenlabs_voices(refresh=refresh)
        if parsed.path == "/api/actions":
            return self._json({"actions": list_actions()})
        if parsed.path == "/api/projects":
            return self._json({"projects": STORE.list_projects()})
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "projects":
            return self._handle_get_project(parts[2])
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "review-files":
            return self._handle_get_review_file(parts[2], parts[4])
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "packets":
            return self._handle_get_packet(parts[2], parts[4])
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/projects":
            return self._handle_create_project()
        if parsed.path == "/api/projects/import-docx":
            return self._handle_import_docx()
        if parsed.path == "/api/projects/import-review":
            return self._handle_import_review()
        if parsed.path == "/api/projects/import-packet":
            return self._handle_import_packet()
        if parsed.path == "/api/settings/elevenlabs":
            return self._handle_elevenlabs_settings()
        if parsed.path == "/api/settings/elevenlabs/clear":
            return self._handle_elevenlabs_clear()

        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "projects":
            project_id = parts[2]
            if len(parts) == 4 and parts[3] == "undo":
                return self._handle_undo(project_id)
            if len(parts) == 4 and parts[3] == "cast":
                return self._handle_cast(project_id)
            if len(parts) == 5 and parts[3] == "actions" and parts[4] == "run":
                return self._handle_run_action(project_id)
            if len(parts) == 5 and parts[3] == "review-files" and parts[4] == "preview":
                return self._handle_review_preview(project_id)
            if len(parts) == 6 and parts[3] == "review-files" and parts[5] == "segment-voice":
                return self._handle_review_segment_voice(project_id, parts[4])
            if len(parts) == 6 and parts[3] == "review-files" and parts[5] == "save":
                return self._handle_review_save(project_id, parts[4])
            if len(parts) == 6 and parts[3] == "packets" and parts[5] == "segment-voice":
                return self._handle_packet_segment_voice(project_id, parts[4])
            if len(parts) == 6 and parts[3] == "packets" and parts[5] == "performance":
                return self._handle_packet_performance(project_id, parts[4])
            if len(parts) == 6 and parts[3] == "chapters" and parts[5] == "progress":
                return self._handle_progress(project_id, parts[4])

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _serve_static(self, name: str, content_type: str) -> None:
        payload = (STATIC_DIR / name).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle_get_project(self, project_id: str) -> None:
        try:
            project = STORE.load_project(project_id)
        except FileNotFoundError:
            return self._json({"error": f"project not found: {project_id}"}, status=HTTPStatus.NOT_FOUND)
        self._json({"project": project})

    def _handle_get_review_file(self, project_id: str, file_id: str) -> None:
        try:
            payload = STORE.load_review_file(project_id, file_id)
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        self._json(payload)

    def _handle_get_packet(self, project_id: str, packet_id: str) -> None:
        try:
            payload = STORE.load_performance_packet(project_id, packet_id)
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        self._json(payload)

    def _handle_create_project(self) -> None:
        payload = self._read_json()
        name = str(payload.get("name") or "").strip()
        if not name:
            return self._json({"error": "name is required"}, status=HTTPStatus.BAD_REQUEST)
        project = STORE.create_project(name)
        self._json({"project": project}, status=HTTPStatus.CREATED)

    def _handle_elevenlabs_voices(self, *, refresh: bool) -> None:
        try:
            payload = ELEVENLABS.list_cached_or_live_voices(refresh=refresh)
        except ValueError as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except ElevenLabsError as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
        self._json(payload)

    def _handle_elevenlabs_settings(self) -> None:
        payload = self._read_json()
        validate = bool(payload.get("validate"))
        try:
            settings = ELEVENLABS.configure_api_key(str(payload.get("api_key") or ""), validate=validate)
        except ValueError as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json(settings)

    def _handle_elevenlabs_clear(self) -> None:
        settings = ELEVENLABS.clear_api_key()
        self._json(settings)

    def _handle_import_docx(self) -> None:
        payload = self._read_json()
        try:
            project = STORE.import_docx(
                project_id=str(payload.get("project_id") or "").strip() or None,
                name=str(payload.get("name") or "").strip() or None,
                source_path=str(payload.get("source_path") or "").strip(),
            )
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"project": project}, status=HTTPStatus.CREATED)

    def _handle_import_review(self) -> None:
        payload = self._read_json()
        try:
            project = STORE.import_review_yaml(
                project_id=str(payload.get("project_id") or "").strip() or None,
                name=str(payload.get("name") or "").strip() or None,
                source_path=str(payload.get("source_path") or "").strip(),
            )
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"project": project}, status=HTTPStatus.CREATED)

    def _handle_import_packet(self) -> None:
        payload = self._read_json()
        try:
            project = STORE.import_performance_packet(
                project_id=str(payload.get("project_id") or "").strip() or None,
                name=str(payload.get("name") or "").strip() or None,
                source_path=str(payload.get("source_path") or "").strip(),
            )
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"project": project}, status=HTTPStatus.CREATED)

    def _handle_cast(self, project_id: str) -> None:
        payload = self._read_json()
        try:
            project = STORE.upsert_cast_voice(project_id, payload)
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"project": project})

    def _handle_run_action(self, project_id: str) -> None:
        payload = self._read_json()
        chapter_id = str(payload.get("chapter_id") or "").strip()
        action_id = str(payload.get("action_id") or "").strip()
        if not chapter_id or not action_id:
            return self._json({"error": "chapter_id and action_id are required"}, status=HTTPStatus.BAD_REQUEST)
        try:
            project = STORE.run_action(project_id, chapter_id, action_id)
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"project": project})

    def _handle_progress(self, project_id: str, chapter_id: str) -> None:
        payload = self._read_json()
        try:
            project = STORE.update_progress(project_id, chapter_id, int(payload.get("lines_read") or 0))
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"project": project})

    def _handle_review_preview(self, project_id: str) -> None:
        payload = self._read_json()
        text = str(payload.get("text") or "")
        try:
            preview = STORE.preview_review_text(project_id, text)
        except Exception as exc:  # noqa: BLE001
            return self._json({"ok": False, "preview": None, "parse_error": yaml_error_payload(exc)}, status=HTTPStatus.OK)
        self._json({"ok": True, "preview": preview, "parse_error": None})

    def _handle_review_segment_voice(self, project_id: str, file_id: str) -> None:
        payload = self._read_json()
        try:
            result = STORE.set_review_segment_voice(
                project_id=project_id,
                text=str(payload.get("text") or ""),
                segment_id=int(payload.get("segment_id")),
                voice=str(payload.get("voice") or ""),
            )
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"ok": True, "file_id": file_id, **result})

    def _handle_review_save(self, project_id: str, file_id: str) -> None:
        payload = self._read_json()
        try:
            result = STORE.save_review_file(
                project_id=project_id,
                file_id=file_id,
                text=str(payload.get("text") or ""),
                expected_sha256=str(payload.get("expected_sha256") or ""),
            )
        except ValueError as exc:
            message = str(exc)
            status = HTTPStatus.CONFLICT if "differs from what was loaded" in message else HTTPStatus.BAD_REQUEST
            return self._json({"error": message}, status=status)
        except FileNotFoundError as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        self._json({"ok": True, **result})

    def _handle_packet_segment_voice(self, project_id: str, packet_id: str) -> None:
        payload = self._read_json()
        try:
            packet = STORE.set_packet_segment_voice(
                project_id=project_id,
                packet_id=packet_id,
                segment_id=int(payload.get("segment_id")),
                voice=str(payload.get("voice") or ""),
            )
            project = STORE.load_project(project_id)
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"ok": True, "project": project, "packet": packet})

    def _handle_packet_performance(self, project_id: str, packet_id: str) -> None:
        payload = self._read_json()
        try:
            packet = STORE.set_packet_segment_approval(
                project_id=project_id,
                packet_id=packet_id,
                segment_id=int(payload.get("segment_id")),
                approved=bool(payload.get("approved")),
            )
            project = STORE.load_project(project_id)
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"ok": True, "project": project, "packet": packet})

    def _handle_undo(self, project_id: str) -> None:
        try:
            project = STORE.undo(project_id)
        except (FileNotFoundError, ValueError) as exc:
            return self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        self._json({"project": project})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def _json(self, payload: dict | list, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("compositor: " + (fmt % args) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the standalone Compositor app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8876, type=int)
    parser.add_argument("--open", action="store_true", help="Open the UI in the default browser.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Compositor listening on {url}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

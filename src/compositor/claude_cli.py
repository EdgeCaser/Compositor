"""Thin wrapper around the local `claude` CLI.

Uses the user's authenticated Pro/Max session via their installed Claude
Code CLI -- no API key required. If the CLI isn't installed or signed in,
the wrapper surfaces a clear error instead of crashing the request.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any


CLAUDE_BIN = "claude"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class ClaudeCliError(RuntimeError):
    pass


def is_available() -> dict[str, Any]:
    """Probe the CLI. Returns {available, path, version, error}."""
    path = shutil.which(CLAUDE_BIN)
    if path is None:
        return {"available": False, "path": None, "version": None, "error": "claude CLI not on PATH"}
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "path": path, "version": None, "error": str(exc)}
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return {"available": False, "path": path, "version": None, "error": stderr or "claude --version failed"}
    return {
        "available": True,
        "path": path,
        "version": (proc.stdout or "").strip(),
        "error": None,
    }


def run_prompt(prompt: str, *, model: str = DEFAULT_MODEL, timeout: int = 180) -> str:
    """Run a single non-interactive prompt and return Claude's text response."""
    if shutil.which(CLAUDE_BIN) is None:
        raise ClaudeCliError("claude CLI not on PATH -- install Claude Code and sign in.")

    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--output-format", "json", "--model", model],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCliError(f"claude CLI timed out after {timeout}s") from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip() or (proc.stdout or "").strip()
        raise ClaudeCliError(f"claude CLI exited {proc.returncode}: {stderr[:400]}")

    raw = (proc.stdout or "").strip()
    if not raw:
        raise ClaudeCliError("claude CLI returned empty output")

    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClaudeCliError(f"claude CLI returned non-JSON output: {raw[:300]}") from exc

    result = envelope.get("result")
    if not isinstance(result, str):
        raise ClaudeCliError(f"claude CLI envelope missing 'result' string: {envelope}")
    return result


def extract_json_block(text: str) -> Any:
    """Pull a JSON object out of Claude's response, tolerating code fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise

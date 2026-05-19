"""Native OS file/folder pickers via a tkinter subprocess.

Runs in its own process so a Tk mainloop never enters the HTTP server's
thread, and so a crashed picker can't take the app with it.
"""
from __future__ import annotations

import subprocess
import sys


_FILE_SCRIPT = (
    "import sys, tkinter as tk\n"
    "from tkinter import filedialog\n"
    "root = tk.Tk(); root.withdraw(); root.wm_attributes('-topmost', 1)\n"
    "title = sys.argv[1] if len(sys.argv) > 1 else ''\n"
    "spec  = sys.argv[2] if len(sys.argv) > 2 else ''\n"
    "filetypes = []\n"
    "for chunk in spec.split('|'):\n"
    "    if not chunk: continue\n"
    "    label, _, patterns = chunk.partition(':')\n"
    "    filetypes.append((label, patterns))\n"
    "path = filedialog.askopenfilename(title=title, filetypes=filetypes or None)\n"
    "sys.stdout.write(path or '')\n"
)

_DIR_SCRIPT = (
    "import sys, tkinter as tk\n"
    "from tkinter import filedialog\n"
    "root = tk.Tk(); root.withdraw(); root.wm_attributes('-topmost', 1)\n"
    "title = sys.argv[1] if len(sys.argv) > 1 else ''\n"
    "path = filedialog.askdirectory(title=title)\n"
    "sys.stdout.write(path or '')\n"
)


class PickerError(RuntimeError):
    pass


def _run(script: str, *args: str, timeout: int = 600) -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PickerError(f"python interpreter not found: {sys.executable}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PickerError("picker timed out") from exc
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if "no display" in stderr.lower() or "tkinter" in stderr.lower():
            raise PickerError(f"native picker unavailable: {stderr}")
        raise PickerError(stderr or f"picker exited {result.returncode}")
    return (result.stdout or "").strip()


def pick_file(title: str, filetypes: list[tuple[str, str]] | None = None) -> str:
    spec = "|".join(f"{label}:{patterns}" for label, patterns in (filetypes or []))
    return _run(_FILE_SCRIPT, title, spec)


def pick_directory(title: str) -> str:
    return _run(_DIR_SCRIPT, title)

"""Native OS file/folder pickers.

Two implementations live here:

- A tkinter subprocess used when running from source. Lets tk own its
  own mainloop in a child process so a crashed picker can never take
  the HTTP server with it.
- A Win32 ctypes path used when frozen (PyInstaller). The subprocess
  trick falls over when ``sys.executable`` is the packaged ``.exe``
  itself, so we drive ``comdlg32``/``shell32`` directly.

The macOS-and-Linux frozen story is not solved here -- callers get a
``PickerError`` and the UI's path inputs stay editable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class PickerError(RuntimeError):
    pass


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


# ---------------------------------------------------------------------------
# tkinter subprocess path (running from source)
# ---------------------------------------------------------------------------

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


def _run_subprocess(script: str, *args: str, timeout: int = 600) -> str:
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


# ---------------------------------------------------------------------------
# Win32 ctypes path (frozen exe on Windows)
# ---------------------------------------------------------------------------

def _pick_file_win32(title: str, filetypes: list[tuple[str, str]] | None) -> str:
    import ctypes
    from ctypes import wintypes

    OFN_FILEMUSTEXIST = 0x00001000
    OFN_PATHMUSTEXIST = 0x00000800
    OFN_HIDEREADONLY = 0x00000004
    OFN_EXPLORER = 0x00080000

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", ctypes.c_void_p),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    path_buf = ctypes.create_unicode_buffer(1024)
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.lpstrFile = ctypes.cast(path_buf, wintypes.LPWSTR)
    ofn.nMaxFile = 1024
    ofn.lpstrTitle = title or None
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY | OFN_EXPLORER

    filter_string: str | None = None
    if filetypes:
        chunks: list[str] = []
        for label, patterns in filetypes:
            chunks.append(label)
            chunks.append(patterns.replace(" ", ";"))
        filter_string = "\0".join(chunks) + "\0\0"
        ofn.lpstrFilter = filter_string

    if not ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
        # 0 means cancelled or error. CommDlgExtendedError gives detail; 0 == cancelled.
        err = ctypes.windll.comdlg32.CommDlgExtendedError()
        if err:
            raise PickerError(f"GetOpenFileName failed with code 0x{err:04x}")
        return ""
    return path_buf.value


def _pick_dir_win32(title: str) -> str:
    import ctypes
    from ctypes import wintypes

    BIF_RETURNONLYFSDIRS = 0x00000001
    BIF_NEWDIALOGSTYLE = 0x00000040

    class BROWSEINFO(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", wintypes.LPWSTR),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", wintypes.UINT),
            ("lpfn", ctypes.c_void_p),
            ("lParam", wintypes.LPARAM),
            ("iImage", ctypes.c_int),
        ]

    display_buf = ctypes.create_unicode_buffer(260)
    bi = BROWSEINFO()
    bi.lpszTitle = title or None
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
    bi.pszDisplayName = ctypes.cast(display_buf, wintypes.LPWSTR)

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32

    # Initialize COM for new-style dialog. OK to call repeatedly.
    ole32.CoInitialize(None)
    try:
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return ""
        path_buf = ctypes.create_unicode_buffer(1024)
        if not shell32.SHGetPathFromIDListW(pidl, path_buf):
            ole32.CoTaskMemFree(pidl)
            raise PickerError("SHGetPathFromIDList failed")
        ole32.CoTaskMemFree(pidl)
        return path_buf.value
    finally:
        ole32.CoUninitialize()


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# macOS path (frozen exe on Darwin)
# ---------------------------------------------------------------------------

def _pick_file_osascript(title: str, filetypes: list[tuple[str, str]] | None) -> str:
    """Native macOS picker via AppleScript -- works in any bundled app."""
    import shutil as _shutil
    if _shutil.which("osascript") is None:
        raise PickerError("osascript not found")

    of_type = ""
    if filetypes:
        exts: list[str] = []
        for _, patterns in filetypes:
            for pattern in patterns.replace(",", " ").split():
                pattern = pattern.strip().lstrip("*").lstrip(".")
                if pattern and pattern != "*":
                    exts.append(pattern)
        if exts:
            of_type = " of type {" + ", ".join(f'"{e}"' for e in exts) + "}"

    safe_title = (title or "Select a file").replace('"', "'")
    script = f'POSIX path of (choose file{of_type} with prompt "{safe_title}")'
    return _osascript(script)


def _pick_dir_osascript(title: str) -> str:
    import shutil as _shutil
    if _shutil.which("osascript") is None:
        raise PickerError("osascript not found")
    safe_title = (title or "Select a folder").replace('"', "'")
    return _osascript(f'POSIX path of (choose folder with prompt "{safe_title}")')


def _osascript(script: str) -> str:
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True, check=False, timeout=600,
    )
    if proc.returncode != 0:
        stderr = (proc.stderr or "").lower()
        # User cancelled: AppleScript returns exit 1 with "User canceled."
        if "user canceled" in stderr or "user cancelled" in stderr or "-128" in stderr:
            return ""
        raise PickerError((proc.stderr or "").strip() or "osascript failed")
    return (proc.stdout or "").strip()


# ---------------------------------------------------------------------------
# Linux path (frozen exe on Linux)
# ---------------------------------------------------------------------------

def _pick_file_linux(title: str, filetypes: list[tuple[str, str]] | None) -> str:
    import shutil as _shutil
    if _shutil.which("zenity"):
        args = ["zenity", "--file-selection", f"--title={title or 'Select a file'}"]
        for label, patterns in filetypes or []:
            pats = " ".join(p.strip() for p in patterns.replace(",", " ").split() if p.strip())
            args.append(f"--file-filter={label} | {pats}")
        return _run_linux_picker(args)
    if _shutil.which("kdialog"):
        ext_filter = ""
        if filetypes:
            chunks: list[str] = []
            for label, patterns in filetypes:
                pats = " ".join(patterns.replace(",", " ").split())
                chunks.append(f"{pats}|{label}")
            ext_filter = "\n".join(chunks)
        args = ["kdialog", "--getopenfilename", str(Path.home())]
        if ext_filter:
            args.append(ext_filter)
        if title:
            args += ["--title", title]
        return _run_linux_picker(args)
    raise PickerError("install 'zenity' or 'kdialog' to use the native file picker")


def _pick_dir_linux(title: str) -> str:
    import shutil as _shutil
    if _shutil.which("zenity"):
        return _run_linux_picker(["zenity", "--file-selection", "--directory", f"--title={title or 'Select a folder'}"])
    if _shutil.which("kdialog"):
        args = ["kdialog", "--getexistingdirectory", str(Path.home())]
        if title:
            args += ["--title", title]
        return _run_linux_picker(args)
    raise PickerError("install 'zenity' or 'kdialog' to use the native folder picker")


def _run_linux_picker(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True, check=False, timeout=600)
    if proc.returncode == 0:
        return (proc.stdout or "").strip()
    if proc.returncode == 1 and not (proc.stderr or "").strip():
        # zenity/kdialog return 1 on cancel without writing stderr.
        return ""
    raise PickerError((proc.stderr or "").strip() or f"picker exited {proc.returncode}")


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def pick_file(title: str, filetypes: list[tuple[str, str]] | None = None) -> str:
    if _is_frozen():
        if sys.platform == "win32":
            return _pick_file_win32(title, filetypes)
        if sys.platform == "darwin":
            return _pick_file_osascript(title, filetypes)
        return _pick_file_linux(title, filetypes)
    spec = "|".join(f"{label}:{patterns}" for label, patterns in (filetypes or []))
    return _run_subprocess(_FILE_SCRIPT, title, spec)


def pick_directory(title: str) -> str:
    if _is_frozen():
        if sys.platform == "win32":
            return _pick_dir_win32(title)
        if sys.platform == "darwin":
            return _pick_dir_osascript(title)
        return _pick_dir_linux(title)
    return _run_subprocess(_DIR_SCRIPT, title)

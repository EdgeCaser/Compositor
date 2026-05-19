# PyInstaller spec for the Compositor standalone app.
#
# Build with:
#   pyinstaller packaging/compositor.spec --noconfirm
#
# Produces:
#   dist/compositor.exe (Windows) / dist/compositor (Linux/macOS)
#
# Runtime requirements that are NOT bundled (detected at runtime via
# /api/integrations, surfaced in the UI):
#   - ffmpeg (~200 MB, expected on PATH)
#   - claude CLI (Pro/Max account distribution, expected on PATH)

from pathlib import Path

import PyInstaller.config  # noqa: F401 -- ensure PyInstaller env is loaded

block_cipher = None
project_root = Path(SPECPATH).resolve().parent
web_dir = project_root / "src" / "compositor" / "web"

a = Analysis(
    [str(project_root / "src" / "compositor" / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=[
        (str(web_dir / "index.html"), "compositor/web"),
        (str(web_dir / "app.js"), "compositor/web"),
        (str(web_dir / "styles.css"), "compositor/web"),
    ],
    hiddenimports=[
        "yaml",
        "compositor",
        "compositor.actions",
        "compositor.app",
        "compositor.chapter_render",
        "compositor.claude_cli",
        "compositor.docx_import",
        "compositor.elevenlabs_client",
        "compositor.models",
        "compositor.native_picker",
        "compositor.performance_packets",
        "compositor.project_store",
        "compositor.review_yaml",
        "compositor.secure_store",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # tkinter is not used by the frozen build (we use ctypes for the
    # Windows picker). Drop it to shave ~10 MB.
    excludes=["tkinter", "tcl"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="compositor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX flags as malware too often
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # keep the console so users see the listen URL + errors
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

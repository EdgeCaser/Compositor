# Compositor

Compositor is a local workstation for audiobook production:

- import `.docx` source chapters
- separate likely dialogue from narration
- generate rough emotional guidance
- assign cast voices
- track chapter progress
- manage project history with undo
- keep review and performance work in one app

This repo is the standalone extraction target for the tooling that currently
lives inside the Cold Storage book workspace.

## Current Shape

The first scaffold focuses on one unified local web app with shared project
state instead of two separate servers.

Tabs:

- `Import`: create a project and ingest Word source files
- `Review`: inspect paragraphs, dialogue/narration heuristics, guidance, and
  provisional voice routing
- `Performance`: run project actions and track lines read per chapter
- `Cast`: manage voice slots and ElevenLabs IDs, keep a prompt scratchpad
  for voice creation, and configure ElevenLabs account access
- `Jobs`: see action history

## What This Scaffold Does

- stores project state under `projects/<project-id>/project.json`
- copies imported `.docx` files into the project
- extracts paragraphs from Word docs without external dependencies
- runs simple built-in actions:
  - `separate_dialogue_narration`
  - `generate_emotional_guidance`
  - `assign_voices`
- snapshots project state after changes so undo works

## What Still Needs Extraction

This repo does not yet fully port the legacy Cold Storage runtime:

- manifest patching
- live STS convert / regenerate / trim actions
- chapter cache management
- chapter reassembly from the app
- ElevenLabs API write operations

The scaffold is built so those capabilities can plug into the same project
model instead of remaining separate one-off servers.

## Run

Windows:

```bat
start_compositor.bat
```

macOS / Linux:

```bash
./start_compositor.sh
```

Manual cross-platform:

```bash
PYTHONPATH=src python -m compositor --open
```

Then open `http://127.0.0.1:8876/`.

## Platform Notes

- Core project import, review editing, packet state management, and cast
  management are intended to run on both Windows and macOS.
- ElevenLabs API keys are stored outside the repo:
  - Windows uses `DPAPI`
  - macOS uses `Keychain`
- `start_compositor.bat` is the Windows launcher.
- `start_compositor.sh` is the shell launcher for macOS / Linux terminals.

## Repo Layout

```text
src/compositor/
  app.py            HTTP server + API
  actions.py        project actions and heuristics
  docx_import.py    Word paragraph extraction
  models.py         shared defaults and IDs
  project_store.py  persistent project state
  web/              static frontend

docs/
  migration.md      mapping from Cold Storage repo pieces to this repo
```

## Product Direction

Immediate next steps after this scaffold:

1. Extract the current YAML review editor into the shared project model.
2. Extract the STS pipeline into the same backend and frontend shell.
3. Add action adapters for legacy scripts instead of heuristic placeholders.
4. Add safe redo/undo around destructive regeneration operations.
5. Add direct ElevenLabs voice-library and voice-creation flows.

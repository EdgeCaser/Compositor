# Compositor Session Handoff

## Current Repo State

Standalone Compositor now has:

- one local web app with shared project state
- source `.docx` import
- imported review YAML editing with preview/validation
- imported recording packet support
- packet/review linking and packet-level performance state
- packet segment voice reassignment with review + shotlist propagation
- packet approval clearing/relinking against `performance:` paths
- cast management
- ElevenLabs provider configuration UI
- secure API-key storage by platform

## Secure Provider Storage

Implemented in `src/compositor/secure_store.py`.

- Windows: `windows_dpapi`
- macOS: `macos_keychain`
- unsupported platforms currently return no secure backend

The frontend only receives public provider state:

- configured / not configured
- backend label
- cached voices
- account metadata

The raw API key is not written into project files or repo files.

## Main Files Added / Changed

- `src/compositor/app.py`
- `src/compositor/project_store.py`
- `src/compositor/review_yaml.py`
- `src/compositor/performance_packets.py`
- `src/compositor/secure_store.py`
- `src/compositor/elevenlabs_client.py`
- `src/compositor/web/app.js`
- `src/compositor/web/styles.css`
- `src/compositor/models.py`
- `README.md`
- `start_compositor.bat`
- `start_compositor.sh`

## What Has Been Verified

Local verification completed on this Windows machine:

- Python syntax checks across `src/compositor/*.py`
- frontend syntax check on `src/compositor/web/app.js`
- `python -m compositor --help`
- review YAML import + preview
- recording packet import + packet state loading
- packet voice change clears stale approval state
- packet re-approval restores approved state
- secure provider storage smoke test on Windows DPAPI

## What Is Not Yet Live-Tested

- macOS Keychain path in `secure_store.py`
- live ElevenLabs API validation against a real key from the app
- live account voice refresh against ElevenLabs
- STS convert / regenerate / trim / upload actions inside the standalone app
- chapter reassembly from the standalone app

## Best Next Task Split

If using the Mac specifically for platform testing:

1. Run `./start_compositor.sh`
2. Open the app and verify:
   - ElevenLabs provider dialog opens
   - API key saves
   - restart retains configured state
   - `Refresh Account Voices` works
   - backend reports `macos_keychain`

If continuing on this Windows machine for product work:

1. Port live STS actions into the `Performance` tab:
   - upload or browser-record reference audio
   - convert
   - regenerate
   - approve / clear
   - take restore
   - trim
2. Then add chapter assembly from the standalone app.

## Architecture Notes For STS Work

Do not re-import the whole legacy `Utils/sts_pipeline.py` server.

Preferred direction:

- keep `elevenlabs_client.py` as the provider boundary
- add a separate service layer for STS segment actions
- keep project-local packet assets under `projects/<id>/packets/...`
- keep review YAML as the source of truth for approval linkage
- keep destructive audio actions undo-friendly or archive-first

## Run Commands

Windows:

```bat
start_compositor.bat
```

macOS / shell:

```bash
./start_compositor.sh
```

manual:

```bash
PYTHONPATH=src python -m compositor --open
```

## Important Context

- This repo did not have an `origin` remote configured during this session.
- If pushing from this machine later, either add an existing GitHub repo as `origin` or create one first.

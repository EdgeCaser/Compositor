# Migration Notes

This repo is the extraction target for the current Compositor tooling inside
the Cold Storage workspace.

## Current Cold Storage Sources

- `Utils/review_yaml_editor.py`
- `Utils/review_yaml_editor_static/`
- `Utils/sts_pipeline.py`
- `Utils/reassemble_chapter.py`
- `Utils/tts_multivoice.py`
- `Utils/voices_config.yaml`
- `Audio/ElevenLabs_MultiVoice/_review*`
- `Audio/ElevenLabs_MultiVoice/_manifest`
- `Audio/ElevenLabs_MultiVoice/_recording_packs`
- `Audio/ElevenLabs_MultiVoice/_segment_cache`

## Extraction Strategy

### Phase 1

Create a shared standalone shell:

- one backend
- one frontend
- project-based storage
- importable source docs
- cast management
- action registry
- history and undo

### Phase 2

Port the review editor into the new shared shell:

- review YAML loading and saving
- structural validation
- segment-level editing
- voice-slot editing
- manifest awareness

### Phase 3

Port the STS pipeline:

- recording-pack ingestion
- segment approval UI
- trim and regenerate
- cache writes
- per-segment undo and provenance

### Phase 4

Add direct product features:

- ElevenLabs voice management
- guided voice creation workflow
- richer progress analytics
- waveform tools and gain controls
- packaging/distribution

## Mapping

| Cold Storage | Standalone target |
| --- | --- |
| `review_yaml_editor.py` | `src/compositor/app.py` + future review module |
| `review_yaml_editor_static/*` | `src/compositor/web/*` |
| `sts_pipeline.py` | future performance adapter module |
| `voices_config.yaml` | future project-level cast config |
| `_review/*.review.yaml` | future project review assets |
| `_recording_packs/*` | future project performance assets |
| `_segment_cache/*` | future render/cache subsystem |

## Design Rule

The standalone repo should not assume one book, one folder layout, or Cold
Storage-specific narrator logic. Those become project adapters, not global
hardcoded rules.

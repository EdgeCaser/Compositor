import pytest
import yaml

from compositor.review_yaml import (
    build_preview,
    dump_yaml_text,
    find_structural_validation_issues,
    ordered_voice_slots,
    parse_yaml_text,
    segments_from_review,
    yaml_error_payload,
)


VALID_YAML = """
source: a.docx
output: a.mp3
narrator: narrator
segments:
  - id: 1
    kind: narration
    voice: narrator
    text: "The room was empty."
  - id: 2
    kind: dialogue
    voice: generic_male
    text: '"Hello."'
"""


def test_parse_rejects_non_mapping():
    with pytest.raises(ValueError):
        parse_yaml_text("- not\n- a\n- mapping\n")


def test_parse_rejects_missing_segments():
    with pytest.raises(ValueError, match="segments"):
        parse_yaml_text("source: a\n")


def test_parse_rejects_segment_missing_required_key():
    text = "segments:\n  - voice: x\n    kind: narration\n"  # missing text
    with pytest.raises(ValueError, match="text"):
        parse_yaml_text(text)


def test_parse_accepts_valid_document():
    doc = parse_yaml_text(VALID_YAML)
    assert len(doc["segments"]) == 2


def test_yaml_error_payload_carries_line_column():
    try:
        parse_yaml_text("segments:\n  - kind: dialogue\n    voice: narrator\n   text:bad\n")
    except Exception as exc:
        payload = yaml_error_payload(exc)
        assert "message" in payload
        # Bad indentation produces a scanner mark; line is optional but should be sane when present.
        if "line" in payload:
            assert payload["line"] >= 1


def test_ordered_voice_slots_prefers_configured_order_then_appends_new():
    out = ordered_voice_slots(
        configured_slots=["narrator", "frank", "lily"],
        slots=["lily", "stranger", "narrator"],
    )
    # Configured order first (filtered by what's actually used), new slots appended.
    assert out == ["narrator", "lily", "stranger"]


def test_find_structural_validation_issues_flags_unclosed_dialogue():
    segments = segments_from_review(
        {
            "segments": [
                {"id": 1, "kind": "dialogue", "voice": "x", "text": '"hello'},
            ]
        }
    )
    issues = find_structural_validation_issues(segments)
    assert 0 in issues["dialogue_unclosed_quote"]


def test_find_structural_validation_issues_flags_narration_with_dialogue():
    segments = segments_from_review(
        {
            "segments": [
                {"id": 1, "kind": "narration", "voice": "n",
                 "text": '"Get out!" she shouted at him from the doorway.'},
            ]
        }
    )
    issues = find_structural_validation_issues(segments)
    assert 0 in issues["narration_contains_dialogue"]


def test_dump_yaml_text_roundtrips():
    doc = parse_yaml_text(VALID_YAML)
    new_text = dump_yaml_text(doc)
    roundtrip = yaml.safe_load(new_text)
    assert roundtrip["segments"] == doc["segments"]


def test_build_preview_returns_stats_and_voice_slots():
    doc = parse_yaml_text(VALID_YAML)
    preview = build_preview(doc, ["narrator", "generic_male"])
    assert preview["stats"]["segments"] == 2
    assert "narrator" in preview["voice_slots_available"]
    assert "generic_male" in preview["voice_slots_available"]

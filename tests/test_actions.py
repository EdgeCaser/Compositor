from compositor.actions import (
    analyze_paragraph_kind,
    apply_dialogue_narration,
    apply_emotional_guidance,
    apply_voice_assignment,
    guidance_for,
)


def test_dialogue_paragraph_starts_and_ends_with_quotes():
    assert analyze_paragraph_kind('"Hello," she said.') == "mixed"
    assert analyze_paragraph_kind('"Hello there friend."') == "dialogue"


def test_pure_narration_has_no_quotes():
    assert analyze_paragraph_kind("The room was empty.") == "narration"


def test_mixed_paragraph_has_quotes_mid_text():
    assert analyze_paragraph_kind('He said, "go away," and turned.') == "mixed"


def test_guidance_sharp_when_exclamation():
    assert guidance_for("Stop!", "dialogue") == "sharp"


def test_guidance_hesitant_when_question_present():
    assert guidance_for("What is happening?", "dialogue") == "hesitant"


def test_guidance_keyword_clinical():
    assert guidance_for("The report on the body confirmed it.", "narration") == "clinical"


def test_guidance_short_dialogue_resolves():
    assert guidance_for('"Yes."', "dialogue") == "resolved"


def test_apply_dialogue_narration_counts():
    chapter = {
        "paragraphs": [
            {"index": 0, "text": "The body lay on the slab."},
            {"index": 1, "text": '"Tell me what you found," Frank said.'},
            {"index": 2, "text": "She paused."},
            {"index": 3, "text": '"It is worse than we thought."'},
        ],
        "stats": {},
    }
    summary = apply_dialogue_narration(chapter)
    assert summary["narration"] == 2
    assert summary["dialogue"] + summary["mixed"] == 2
    assert chapter["stats"]["paragraphs"] == 4
    assert chapter["stats"]["estimated_lines"] == summary["dialogue"] + summary["mixed"]


def test_apply_emotional_guidance_tags_each_paragraph():
    chapter = {
        "paragraphs": [
            {"index": 0, "text": "He hurt and felt tired.", "kind": "narration"},
            {"index": 1, "text": '"Run!"', "kind": "dialogue"},
        ],
        "stats": {},
    }
    apply_emotional_guidance(chapter)
    assert chapter["paragraphs"][0]["guidance"] == "weary"
    assert chapter["paragraphs"][1]["guidance"] == "sharp"


def test_apply_voice_assignment_routes_by_kind():
    chapter = {
        "paragraphs": [
            {"index": 0, "text": "Narration line.", "kind": "narration"},
            {"index": 1, "text": '"A line."', "kind": "dialogue"},
            {"index": 2, "text": '"Another."', "kind": "mixed"},
        ],
        "stats": {},
    }
    cast = [
        {"slot": "narrator", "role": "narrator"},
        {"slot": "generic_dialogue", "role": "dialogue_default"},
    ]
    apply_voice_assignment(chapter, cast)
    assert chapter["paragraphs"][0]["voice_slot"] == "narrator"
    assert chapter["paragraphs"][1]["voice_slot"] == "generic_dialogue"
    assert chapter["paragraphs"][2]["voice_slot"] == "generic_dialogue"

import json

import pytest

from compositor.claude_cli import extract_json_block


def test_bare_json():
    assert extract_json_block('{"2": "Frank"}') == {"2": "Frank"}


def test_json_in_triple_fence_with_language():
    raw = '```json\n{"2": "Frank", "4": "the woman"}\n```'
    assert extract_json_block(raw) == {"2": "Frank", "4": "the woman"}


def test_json_in_triple_fence_without_language():
    raw = '```\n{"x": 1}\n```'
    assert extract_json_block(raw) == {"x": 1}


def test_json_surrounded_by_prose():
    raw = "Sure thing! Here is the mapping you asked for:\n{\"5\": \"Lily\"}\nLet me know if anything is off."
    assert extract_json_block(raw) == {"5": "Lily"}


def test_garbage_raises():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        extract_json_block("nothing JSON here at all")


def test_whitespace_only_raises():
    with pytest.raises((ValueError, json.JSONDecodeError)):
        extract_json_block("   \n   ")

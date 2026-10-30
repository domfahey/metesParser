"""PR #60 round 40: all six cardinal-only vocabularies accept and reject the same words."""

from __future__ import annotations

import importlib.util
import itertools
from pathlib import Path

import mp_parse.calls as package_calls
import mp_parse.metadata as package_metadata
import pytest
from mp_bearing.azimuth import normalize_cardinal_word

from metesparser import call_extractor, text_parser

ROOT = Path(__file__).resolve().parents[2]


def _audit_pattern():
    spec = importlib.util.spec_from_file_location(
        "audit_gt_vs_md_sync", ROOT / "scripts" / "audit_gt_vs_md.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CARDINAL_ONLY_PATTERN


BASES = ["north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"]
ABBREVIATIONS = ["NE", "NW", "SE", "SW"]
SUFFIXES = ["", "erly", "wardly"]
ACCEPTS = [f"{base}{suffix}" for base, suffix in itertools.product(BASES + ABBREVIATIONS, SUFFIXES)]
ACCEPTS += [w.upper() for w in ACCEPTS] + [w.capitalize() for w in ACCEPTS]
REJECTS = [
    "",
    "n",
    "e",
    "s",
    "w",
    "ENE",
    "north-northeast",
    "northish",
    "norther",
    "northerlyly",
    "northerlyerly",
    "up",
    "northeast by east",
    "north 5",
]


def _matchers():
    return {
        "mp_parse.calls": lambda w: package_calls._CARDINAL_ONLY_PATTERN.fullmatch(w) is not None,
        "mp_parse.metadata": lambda w: (
            package_metadata.CARDINAL_ONLY_PATTERN.fullmatch(w) is not None
        ),
        "call_extractor": lambda w: call_extractor._CARDINAL_ONLY_PATTERN.fullmatch(w) is not None,
        "text_parser": lambda w: (
            text_parser.TextParser.CARDINAL_ONLY_PATTERN.fullmatch(w) is not None
        ),
        "audit_gt_vs_md": lambda w: _audit_pattern().fullmatch(w) is not None,
        "mp_bearing.normalize_cardinal_word": lambda w: normalize_cardinal_word(w) is not None,
    }


@pytest.mark.parametrize("name", list(_matchers()))
def test_vocabulary_accepts_every_cardinal_form(name):
    match = _matchers()[name]
    assert [w for w in ACCEPTS if not match(w)] == []


@pytest.mark.parametrize("name", list(_matchers()))
def test_vocabulary_rejects_non_cardinal_text(name):
    match = _matchers()[name]
    assert [w for w in REJECTS if match(w)] == []

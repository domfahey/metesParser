"""No sample deed that verified on main stops verifying.

``tests/fixtures/sample_verification_baseline_main.json`` records, for every sample
deed text (markdown, ground-truth legal description and normalized text), whether
non-strict package extraction plus ``verify_closure`` fully verified it on main.
Losing one is a regression unless allowlisted below with a justification against
ground truth (a deed whose verification on main was itself wrong).
"""

from __future__ import annotations

import json
from functools import cache

import pytest
from mp_parse.calls import extract_calls
from mp_verify.closure import verify_closure

from tests.fixtures.parser_corpus import ROOT, keyed_sample_texts

BASELINE = ROOT / "tests" / "fixtures" / "sample_verification_baseline_main.json"

_ROLE_POLICY = "two unheaded descriptions; roles inferred, blocked by the role policy"
_EXCEPTED_PART_ONLY = (
    "lot conveyed by plat less an excluded triangle; main verified t"
    "he triangle, which is not the parcel"
)
_STRIP_NOT_APPLIED = (
    "a stated strip exception is not applied to the boundary, so the parcel is not verified"
)

# key -> one-line justification against ground truth. Keep empty unless main's
# verification of that deed was itself wrong.
ALLOWED_LOSSES: dict[str, str] = {
    # Round 56 fail-closed role policy (user decision): two BEGINNING descriptions with
    # no TRACT/PARCEL heading, so both MAIN roles are inferred from position and the
    # deed is blocked for role review even though each description closes.
    # Fail-closed policies (#60): a deed whose verification on main was not the parcel's.
    "8 Kings Highway W - Deed Image (7535 - 929).md": _ROLE_POLICY,
    "deed 50306-00349.md": _ROLE_POLICY,
    "deed 50306-00349::legal": _ROLE_POLICY,
    "deed 50428-01001.md": _EXCEPTED_PART_ONLY,
    "deed 50428-01001::legal": _EXCEPTED_PART_ONLY,
    "deed 50428-01001::normalized": _EXCEPTED_PART_ONLY,
    "deed 50233-01191::legal": _STRIP_NOT_APPLIED,
    "deed 50233-01191::normalized": _STRIP_NOT_APPLIED,
    "deed 50512-00525.md": _STRIP_NOT_APPLIED,
    "deed 50512-00525::legal": _STRIP_NOT_APPLIED,
    "deed 50512-00525::normalized": _STRIP_NOT_APPLIED,
    "deed 50795-01269.md": _STRIP_NOT_APPLIED,
    "deed 50795-01269::legal": _STRIP_NOT_APPLIED,
}


def is_fully_verified(text: str) -> bool:
    """Non-strict package extraction with a skip list, then closure verification."""
    skips: list = []
    try:
        calls, tracts = extract_calls(text, strict=False, skipped_courses=skips)
        if not calls:
            return False
        if tracts:
            results = verify_closure(calls, tracts=tracts, skipped_courses=skips)
            return all(result.is_fully_verified() for result in results)
        return verify_closure(calls, skipped_courses=skips).is_fully_verified()
    except Exception:  # noqa: BLE001 - an extraction error is a failure to verify
        return False


@cache
def _results() -> tuple[dict[str, bool], dict[str, bool]]:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["verified"]
    current = {key: is_fully_verified(text) for key, text in keyed_sample_texts()}
    return baseline, current


def test_baseline_covers_every_sample_text():
    baseline, current = _results()
    assert set(baseline) == set(current)


def test_no_sample_deed_loses_verification():
    baseline, current = _results()
    lost = sorted(
        key
        for key, verified in baseline.items()
        if verified and not current.get(key) and key not in ALLOWED_LOSSES
    )
    assert lost == []


def test_allowlist_names_only_real_losses():
    baseline, current = _results()
    stale = [key for key in ALLOWED_LOSSES if not baseline.get(key) or current.get(key)]
    assert stale == []


def test_report_deeds_gained_since_main(capsys: pytest.CaptureFixture[str]):
    baseline, current = _results()
    gained = sorted(key for key, verified in current.items() if verified and not baseline[key])
    with capsys.disabled():
        print(f"\nverify now but not on main ({len(gained)}): {gained}")
    # Gaining is allowed; each gained deed is listed for review.
    assert all(current[key] for key in gained)


@pytest.mark.parametrize(
    "key",
    [
        "20 E Redman Ave - Deed Image (8214 - 294).md",
        "20 E Redman Ave - Deed Image (12427 - 01665).md",
        "17 Kings Highway W - Deed Image (10394 - 9).md",
    ],
)
def test_description_bounds_regressions_verify(key):
    _baseline, current = _results()
    assert current[key]

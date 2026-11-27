"""Behavioral and fail-closed contract tests for mp_review.api and mp_review.text."""

from __future__ import annotations

import json

import pytest
from mp_models import DeedCall, SkippedCourse, Tract, TractType
from mp_review import api
from mp_review.text import MULTIPLE_PARCELS, prepare_text

SQUARE_TEXT = (
    "BEGINNING at an iron pin; THENCE N 0° E 100 feet; "
    "THENCE N 90° E 100 feet; THENCE S 0° E 100 feet; "
    "THENCE N 90° W 100 feet to the point of beginning."
)


def _square_calls(side: float = 100.0) -> list[dict[str, object]]:
    return [
        {
            "course": 1,
            "direction_text": "N 0° E",
            "bearing_azimuth_deg_from_north": 0.0,
            "distance_ft": side,
        },
        {
            "course": 2,
            "direction_text": "N 90° E",
            "bearing_azimuth_deg_from_north": 90.0,
            "distance_ft": side,
        },
        {
            "course": 3,
            "direction_text": "S 0° E",
            "bearing_azimuth_deg_from_north": 180.0,
            "distance_ft": side,
        },
        {
            "course": 4,
            "direction_text": "N 90° W",
            "bearing_azimuth_deg_from_north": 270.0,
            "distance_ft": side,
        },
    ]


@pytest.mark.parametrize("bad_area", [True, False, 0, -50.0, float("nan"), float("inf"), "100"])
def test_invalid_stated_area_rejects_cleanly_including_invalid_utf8(bad_area):
    res = api.review_text(SQUARE_TEXT, stated_area_sq_ft=bad_area)  # type: ignore[arg-type]
    assert res["status"] == "error"
    assert res["errors"][0]["code"] == "invalid_input"
    assert res["calls"] == []

    # Invalid stated_area paired with non-UTF-8 bytes also produces an error without crashing.
    bad_bytes_res = api.replay_review(
        b"\xff\xfeinvalid",
        input_kind="text",
        stated_area_sq_ft=bad_area,  # type: ignore[arg-type]
    )
    assert bad_bytes_res["status"] == "error"
    assert bad_bytes_res["errors"][0]["code"] == "invalid_input"
    assert bad_bytes_res["audit"]["original_source"] == ""


def test_output_dir_os_error_and_artifact_write_error_reported_cleanly(tmp_path, monkeypatch):
    # Creating output_dir under a regular file triggers OSError -> output_error.
    blocker = tmp_path / "blocker"
    blocker.write_text("file")
    res = api.review_text(SQUARE_TEXT, output_dir=blocker / "child")
    assert res["status"] == "error"
    assert res["errors"][0]["code"] == "output_error"

    # Failure during artifact export sets artifact_error.
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(api, "export_verified_csv", boom)
    res2 = api.review_text(SQUARE_TEXT, output_dir=tmp_path / "out")
    assert res2["status"] == "error"
    assert any(
        e["code"] == "artifact_error" and "disk full" in e["message"] for e in res2["errors"]
    )


def test_review_file_missing_unsupported_and_verify_file_suffix_guard(tmp_path):
    missing = api.review_file(tmp_path / "missing.txt")
    assert missing["status"] == "error"
    assert missing["errors"][0]["code"] == "input_error"

    pdf_file = tmp_path / "deed.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")
    unsupported = api.review_file(pdf_file)
    assert unsupported["status"] == "error"
    assert unsupported["errors"][0]["code"] == "invalid_input"
    assert "PDF/OCR" in unsupported["errors"][0]["message"]

    txt_file = tmp_path / "deed.txt"
    txt_file.write_text(SQUARE_TEXT)
    verified = api.verify_file(txt_file)
    assert verified["status"] == "error"
    assert verified["errors"][0]["code"] == "invalid_input"
    assert "CSV or JSON" in verified["errors"][0]["message"]


def test_review_text_flags_historical_units_nonpositive_area_unresolved_poc_and_no_calls():
    # Historical/regional distance units add an advisory limitation.
    varas_text = (
        "BEGINNING at a pin; THENCE N 0° E 100 varas; "
        "THENCE N 90° E 100 varas; THENCE S 0° E 100 varas; "
        "THENCE N 90° W 100 varas to the point of beginning."
    )
    varas = api.review_text(varas_text)
    assert any("historical or regional distance unit" in lim for lim in varas["limitations"])

    # Non-positive stated area with calls surfaces invalid_stated_area and blocks checks_passed.
    zero_area = api.review_text(SQUARE_TEXT + " Containing 0.00 acres.")
    assert zero_area["status"] == "needs_review"
    assert any(e["code"] == "invalid_stated_area" for e in zero_area["errors"])

    # Non-positive stated area with NO calls still sets invalid_stated_area and no_calls.
    only_zero = api.review_text("Containing 0.00 acres.")
    assert only_zero["status"] == "needs_review"
    codes = {e["code"] for e in only_zero["errors"]}
    assert {"invalid_stated_area", "no_calls"} <= codes

    # Unresolved POC cannot separate commencement from boundary.
    bad_poc = api.review_text(
        "COMMENCING at a stone; THENCE N 0° E 50 feet; THENCE N 90° E 100 feet;"
    )
    assert bad_poc["status"] == "needs_review"
    assert any(e["code"] == "unresolved_poc" for e in bad_poc["errors"])


def test_json_legal_description_tracts_exceptions_easements_and_area_rules(tmp_path):
    # 1. Multiple boundary tracts fail closed with MULTIPLE_PARCELS.
    two_mains = {
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "heading",
                "calls": _square_calls(),
            },
            {
                "label": "Tract 2",
                "tract_type": "addition",
                "role_basis": "heading",
                "calls": _square_calls(20.0),
            },
        ]
    }
    multi_res = api.replay_review(json.dumps(two_mains).encode(), input_kind="json")
    assert multi_res["status"] == "error"
    assert MULTIPLE_PARCELS in multi_res["errors"][0]["message"]

    # 2. Main + Exception + Easement with explicit headings:
    #    - exception calls get is_exception=True & non-boundary note
    #    - easement calls are excluded from boundary calls
    #    - boundary stated_area propagates to top-level legal_description
    combo = {
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "heading",
                "stated_area_sq_ft": 10000.0,
                "calls": _square_calls(),
            },
            {
                "label": "Exception",
                "tract_type": "exception",
                "role_basis": "heading",
                "calls": _square_calls(20.0),
            },
            {
                "label": "Easement",
                "tract_type": "easement",
                "role_basis": "heading",
                "calls": _square_calls(20.0),
            },
        ]
    }
    combo_res = api.replay_review(json.dumps(combo).encode(), input_kind="json")
    assert combo_res["status"] == "needs_review"
    assert len(combo_res["calls"]) == 8  # main (4) + exception (4); easement excluded
    assert all(c["is_exception"] for c in combo_res["calls"][4:])
    assert combo_res["audit"]["legal_description"]["stated_area_sq_ft"] == 10000.0

    # 3. Conflicting top-level vs boundary tract stated_area_sq_ft is flagged.
    conflict = {
        "stated_area_sq_ft": 25000.0,
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "heading",
                "stated_area_sq_ft": 10000.0,
                "calls": _square_calls(),
            }
        ],
    }
    conflict_res = api.replay_review(json.dumps(conflict).encode(), input_kind="json")
    assert conflict_res["status"] == "needs_review"
    assert any(e["code"] == "conflicting_stated_area" for e in conflict_res["errors"])

    # 4. Explicit stated_area_sq_ft CLI/API override updates single boundary tract as well.
    override_res = api.replay_review(
        json.dumps(conflict).encode(), input_kind="json", stated_area_sq_ft=10000.0
    )
    assert override_res["status"] == "checks_passed", override_res["errors"]
    assert override_res["audit"]["legal_description"]["tracts"][0]["stated_area_sq_ft"] == 10000.0

    # 5. Empty exception tract triggers incomplete_exception_tract.
    empty_exc = {
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "heading",
                "calls": _square_calls(),
            },
            {"label": "Exception", "tract_type": "exception", "role_basis": "heading", "calls": []},
        ]
    }
    empty_exc_res = api.replay_review(json.dumps(empty_exc).encode(), input_kind="json")
    assert any(e["code"] == "incomplete_exception_tract" for e in empty_exc_res["errors"])

    # 6. Easement-only tract with matching calls keeps easement calls (marked non-boundary).
    easement_calls = _square_calls(20.0)
    easement_only = {
        "calls": easement_calls,
        "tracts": [
            {
                "label": "Easement",
                "tract_type": "easement",
                "role_basis": "single",
                "calls": easement_calls,
            }
        ],
    }
    easement_res = api.replay_review(json.dumps(easement_only).encode(), input_kind="json")
    assert easement_res["status"] == "needs_review"
    assert len(easement_res["calls"]) == 4

    # 7. Mismatched top-level calls vs tracts fails closed.
    mismatched = {
        "calls": _square_calls(20.0),
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "single",
                "calls": _square_calls(),
            }
        ],
    }
    mismatch_res = api.replay_review(json.dumps(mismatched).encode(), input_kind="json")
    assert mismatch_res["status"] == "error"
    assert "do not match tracts" in mismatch_res["errors"][0]["message"]

    # 8. Tract skipped_courses propagate to audit and block checks_passed.
    with_skips = {
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "single",
                "calls": _square_calls(),
                "skipped_courses": [
                    SkippedCourse(
                        course=5,
                        source_course=5,
                        source_excerpt="unparsed course",
                        error_type="ValueError",
                        error="missing bearing",
                    ).model_dump(mode="json")
                ],
            }
        ]
    }
    skip_res = api.replay_review(json.dumps(with_skips).encode(), input_kind="json")
    assert skip_res["status"] == "needs_review"
    assert len(skip_res["audit"]["skipped_courses"]) == 1

    # 9. Non-LegalDescription JSON object fails closed.
    bad_obj = api.replay_review(b'{"foo": "bar"}', input_kind="json")
    assert bad_obj["status"] == "error"
    assert "LegalDescription" in bad_obj["errors"][0]["message"]


def test_inferred_description_roles_fail_closed_and_stay_blocked_on_rereview(tmp_path):
    inferred = {
        "calls": _square_calls(),
        "tracts": [
            {
                "label": "Tract 1",
                "tract_type": "main",
                "role_basis": "inferred",
                "calls": _square_calls(),
            },
            {
                "label": "Easement",
                "tract_type": "easement",
                "role_basis": "inferred",
                "calls": _square_calls(20.0),
            },
        ],
    }
    src = tmp_path / "inferred.json"
    src.write_text(json.dumps(inferred))
    out = tmp_path / "out"
    res = api.review_file(src, output_dir=out)
    assert res["status"] == "needs_review", res
    assert any(e["code"] == "description_roles_inferred" for e in res["errors"])
    assert not (out / "calls_verified.csv").exists()

    # Re-reviewing the written calls.json remains blocked (marked with DESCRIPTION_ROLES_NOTE).
    rereview = api.verify_file(out / "calls.json")
    assert rereview["status"] == "needs_review"
    assert any(e["code"] == "description_roles_inferred" for e in rereview["errors"])


def test_prepare_text_tracts_poc_and_area_branches(monkeypatch):
    import mp_review.text as text_mod

    square_models = [DeedCall.model_validate(c) for c in _square_calls()]
    small_models = [DeedCall.model_validate(c) for c in _square_calls(20.0)]

    # 1. Single-tract with poc_description=None on tract + POC in text + approximate stated area
    headed_with_poc = (
        "COMMENCING at a stone; THENCE N 0° E 50 feet to the POINT OF BEGINNING; "
        "THENCE N 0° E 100 feet; THENCE N 90° E 100 feet; "
        "THENCE S 0° E 100 feet; THENCE N 90° W 100 feet to the POINT OF BEGINNING. "
        "Containing 10,000 square feet, more or less."
    )
    tie_call = DeedCall(
        course=1,
        direction_text="N 0° E",
        bearing_azimuth_deg_from_north=None,
        distance_ft=50.0,
        to="the POINT OF BEGINNING",
    )
    all_calls = [
        tie_call,
        *(c.model_copy(update={"course": i + 2}) for i, c in enumerate(square_models)),
    ]
    fake_single = Tract(
        label="Tract 1",
        tract_type=TractType.MAIN,
        role_basis="heading",
        poc_description=None,
        stated_area_sq_ft=10000.0,
        calls=all_calls,
    )
    monkeypatch.setattr(
        text_mod, "extract_calls", lambda norm, audit_context=None: ([], [fake_single])
    )
    patched = prepare_text(headed_with_poc)
    assert patched.multiple_tracts is True
    assert patched.legal_description.poc_description is not None
    assert patched.legal_description.calls[0].is_tie_in is True
    assert patched.legal_description.stated_area_sq_ft == 10000.0
    assert patched.legal_description.stated_area_approximate is True

    # 2. Main tract + Easement tract excludes easement calls and keeps boundary area=None when unset
    fake_pair = [
        Tract(
            label="Tract 1", tract_type=TractType.MAIN, role_basis="heading", calls=square_models
        ),
        Tract(
            label="Easement",
            tract_type=TractType.EASEMENT,
            role_basis="heading",
            calls=small_models,
        ),
    ]
    monkeypatch.setattr(text_mod, "extract_calls", lambda norm, audit_context=None: ([], fake_pair))
    combined = prepare_text(SQUARE_TEXT)
    assert combined.multiple_tracts is True
    assert len(combined.legal_description.tracts) == 2
    assert len(combined.legal_description.calls) == 4
    assert combined.legal_description.stated_area_sq_ft is None

    # 3. Easement-only tract hits non_empty_boundary == [] branch
    fake_easement = [
        Tract(
            label="Easement", tract_type=TractType.EASEMENT, role_basis="single", calls=small_models
        )
    ]
    monkeypatch.setattr(
        text_mod, "extract_calls", lambda norm, audit_context=None: ([], fake_easement)
    )
    easement_only = prepare_text(SQUARE_TEXT)
    assert easement_only.multiple_tracts is True
    assert len(easement_only.legal_description.calls) == 4
    assert easement_only.legal_description.stated_area_sq_ft is None

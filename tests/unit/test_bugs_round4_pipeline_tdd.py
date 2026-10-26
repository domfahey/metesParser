"""End-to-end regressions at parser, verifier, and verified CSV boundaries."""

import math

import pytest
from mp_export import csv_to_calls, export_verified_csv
from mp_models import DeedCall as PackageCall
from mp_models import LegalDescription as PackageLegalDescription
from mp_parse.metadata import extract_area_statement
from mp_verify import verify_closure

from metesparser.call_extractor import CallExtractor
from metesparser.closure_checker import ClosureChecker
from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall as MonolithCall
from metesparser.models import LegalDescription as MonolithLegalDescription
from metesparser.text_parser import TextParser
from tests.fixtures.package_parser import extract_calls


@pytest.fixture(params=["package", "monolith"])
def api(request):
    if request.param == "package":
        return (
            PackageCall,
            extract_calls,
            verify_closure,
            export_verified_csv,
            csv_to_calls,
            PackageLegalDescription,
            extract_area_statement,
        )
    return (
        MonolithCall,
        CallExtractor.extract_calls,
        ClosureChecker.verify_closure,
        CSVBuilder.export_verified_csv,
        CSVBuilder.csv_to_calls,
        MonolithLegalDescription,
        TextParser.extract_area_statement,
    )


def _square_text(distance: str, *, witness: bool = False) -> str:
    witness_text = (
        " to an iron pin, from which a witness tree bears S 45° W 100 feet" if witness else ""
    )
    return (
        f"THENCE due North {distance}{witness_text}; "
        "THENCE due East 100 feet; THENCE due South 100 feet; "
        "THENCE due West 100 feet to the point of beginning."
    )


def test_chain_and_links_square_survives_verified_csv_roundtrip(api, tmp_path):
    _, parse, verify, export, load, _, _ = api
    text = (
        "THENCE due North 1 chain and 25 links; THENCE due East 1 chain and 25 links; "
        "THENCE due South 1 chain and 25 links; THENCE due West 1 chain and 25 links "
        "to the point of beginning."
    )
    calls = parse(text)
    assert [call.distance_ft for call in calls] == pytest.approx([82.5] * 4)
    result = verify(calls)
    assert result.misclosure_ft < 0.01
    assert result.area_sq_ft == pytest.approx(6806.25)
    assert result.is_fully_verified()

    export(calls, result, str(tmp_path / "chain-links.csv"))
    reloaded = load(str(tmp_path / "chain-links_verified.csv"))
    fresh_result = verify(reloaded)
    assert [call.distance_ft for call in reloaded] == pytest.approx([82.5] * 4)
    assert fresh_result.misclosure_ft < 0.01
    assert fresh_result.area_sq_ft == pytest.approx(6806.25)
    assert fresh_result.is_fully_verified()


def test_witness_length_cannot_fill_missing_boundary_and_cannot_export(api, tmp_path):
    _, parse, verify, export, _, _, _ = api
    text = _square_text("", witness=True)
    with pytest.raises(ValueError, match="Malformed course"):
        parse(text, strict=True)

    # Even permissive parsing must not turn a witness measurement into a parcel edge.
    calls = parse(text, strict=False)
    result = verify(calls)
    output = tmp_path / "incomplete.csv"
    with pytest.raises(ValueError, match="verification checks failed"):
        export(calls, result, str(output))
    assert not (tmp_path / "incomplete_verified.csv").exists()


def test_pin_distance_and_total_distance_close_100_foot_square(api, tmp_path):
    _, parse, verify, export, load, _, _ = api
    text = (
        "THENCE due North, passing an iron pin at 50 feet, for a total distance of 100 feet; "
        "THENCE due East 100 feet; THENCE due South 100 feet; "
        "THENCE due West 100 feet to the point of beginning."
    )
    calls = parse(text)
    assert calls[0].distance_ft == pytest.approx(100)
    result = verify(calls)
    assert result.misclosure_ft < 0.01
    assert result.area_sq_ft == pytest.approx(10000)
    assert result.is_fully_verified()
    export(calls, result, str(tmp_path / "pin-total.csv"))
    assert verify(load(str(tmp_path / "pin-total_verified.csv"))).is_fully_verified()


def test_parcel_area_not_parent_area_flows_through_verification_and_export(api, tmp_path):
    _, parse, verify, export, load, legal_type, area_parser = api
    text = (
        "Being part of a 6 acre tract, containing 2.5 acres. "
        "THENCE due North 330 feet; THENCE due East 330 feet; "
        "THENCE due South 330 feet; THENCE due West 330 feet to the point of beginning."
    )
    calls = parse(text)
    area = area_parser(text)
    assert area is not None
    assert area["value_sq_ft"] == pytest.approx(2.5 * 43560)
    legal_desc = legal_type(calls=calls, stated_area_sq_ft=area["value_sq_ft"])
    result = verify(legal_desc.calls, stated_area_sq_ft=legal_desc.stated_area_sq_ft)
    assert result.area_sq_ft == pytest.approx(2.5 * 43560)
    assert result.is_fully_verified()
    export(calls, result, str(tmp_path / "parcel-area.csv"), legal_desc=legal_desc)
    reloaded = load(str(tmp_path / "parcel-area_verified.csv"))
    reloaded_result = verify(reloaded, stated_area_sq_ft=legal_desc.stated_area_sq_ft)
    assert reloaded_result.area_sq_ft == pytest.approx(2.5 * 43560)


def test_self_crossing_five_call_traverse_is_not_exported(api, tmp_path):
    call_type, _, verify, export, _, _, _ = api
    # The diagonals cross, and a fifth leg closes the bow tie without degeneracy.
    vertices = [(0, 0), (100, 100), (0, 100), (100, 0), (50, -30), (0, 0)]
    calls = []
    for index, ((x1, y1), (x2, y2)) in enumerate(
        zip(vertices[:-1], vertices[1:], strict=True), start=1
    ):
        dx, dy = x2 - x1, y2 - y1
        calls.append(
            call_type(
                course=index,
                direction_text="computed boundary leg",
                distance_ft=math.hypot(dx, dy),
                bearing_azimuth_deg_from_north=math.degrees(math.atan2(dx, dy)) % 360,
            )
        )
    result = verify(calls)
    assert not result.is_fully_verified()
    assert any("self-intersection" in warning for warning in result.warnings)
    output = tmp_path / "crossing.csv"
    with pytest.raises(ValueError, match="verification checks failed"):
        export(calls, result, str(output))
    assert not (tmp_path / "crossing_verified.csv").exists()


def test_two_semicircles_verify_as_full_circle_and_roundtrip(api, tmp_path):
    call_type, _, verify, export, load, _, _ = api
    radius = 100.0
    calls = [
        call_type(
            course=1,
            direction_text="first semicircle",
            distance_ft=math.pi * radius,
            bearing_azimuth_deg_from_north=90,
            curve_dir="left",
            radius_ft=radius,
            delta_deg=180,
            arc_length_ft=math.pi * radius,
        ),
        call_type(
            course=2,
            direction_text="second semicircle",
            distance_ft=math.pi * radius,
            bearing_azimuth_deg_from_north=270,
            curve_dir="left",
            radius_ft=radius,
            delta_deg=180,
            arc_length_ft=math.pi * radius,
        ),
    ]
    result = verify(calls)
    assert result.misclosure_ft < 0.01
    assert result.area_sq_ft == pytest.approx(10000 * math.pi, rel=1e-9)
    assert result.is_fully_verified(), result.warnings
    export(calls, result, str(tmp_path / "circle.csv"))
    reloaded = load(str(tmp_path / "circle_verified.csv"))
    fresh = verify(reloaded)
    assert fresh.area_sq_ft == pytest.approx(10000 * math.pi, rel=1e-9)
    assert fresh.is_fully_verified(), fresh.warnings

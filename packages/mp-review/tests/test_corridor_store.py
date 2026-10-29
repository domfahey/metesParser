"""Raw/canonical corridor preservation and deterministic artifact replay."""

import json

import pytest
from mp_models.corridor import CorridorRequest
from mp_review.corridor import analyze_corridor_file, replay_corridor


def payload():
    return {
        "id": "utility",
        "centerline": {
            "title": "recorded centerline",
            "foot_definition": "international_ft",
            "calls": [
                {
                    "id": "road",
                    "source_reference": "  deed page 3  ",
                    "quote": "  source line  ",
                    "call": {
                        "course": 1,
                        "direction_text": "  East 100 ft  ",
                        "distance_ft": 100,
                        "bearing_azimuth_deg_from_north": 90,
                    },
                }
            ],
        },
        "widths": [
            {
                "id": "taper",
                "start": {"call_id": "road", "fraction": 0},
                "end": {"call_id": "road", "fraction": 1},
                "left_start": 10,
                "left_end": 30,
                "right_start": 5,
                "right_end": 15,
                "rule": "linear_taper",
                "source_refs": [
                    {"source_id": "deed", "page": 3, "quote": "  taper width source  "}
                ],
            }
        ],
        "width_unit": "international_ft",
        "join": "bevel",
        "cap": "square",
        "construction_source_refs": [
            {"source_id": "deed", "quote": "explicit cap/join instructions"}
        ],
        "error_budget": {"max_error": 0.01, "unit": "international_ft"},
    }


def test_save_reopen_reproduces_endpoint_widths_cap_and_geometry(tmp_path):
    source = tmp_path / "input.json"
    raw = json.dumps(payload(), indent=4, ensure_ascii=False).encode() + b"\n\n"
    source.write_bytes(raw)
    directory = tmp_path / "corridor"
    response = analyze_corridor_file(source, directory)
    assert response["status"] == "needs_review"
    assert (directory / "request.json").read_bytes() == raw
    result = replay_corridor(directory)
    assert result.request == CorridorRequest.model_validate(payload())
    assert result.request.widths[0].left_end == 30
    assert result.request.cap == "square"
    assert result.request.centerline.calls[0].quote == "  source line  "
    assert result.boundary_origin_in_centerline_frame is not None
    assert result.boundary and (directory / "boundary.html").is_file()
    assert result.error.total_bound <= result.request.error_budget.max_error
    assert not result.verified_export_eligible


def test_missing_width_is_completed_advisory_without_polygon(tmp_path):
    data = payload()
    data["widths"] = []
    source = tmp_path / "input.json"
    source.write_text(json.dumps(data))
    output = tmp_path / "incomplete"
    response = analyze_corridor_file(source, output)
    assert response["status"] == "needs_review"
    result = replay_corridor(output)
    assert result.availability == "incomplete" and result.boundary is None
    assert not (output / "boundary.html").exists()


@pytest.mark.parametrize(
    "name",
    [
        "request.json",
        "corridor-request.json",
        "corridor.json",
        "boundary-prepared.json",
        "boundary.html",
    ],
)
def test_changed_retained_input_or_geometry_fails_replay(tmp_path, name):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(payload()))
    output = tmp_path / "output"
    assert analyze_corridor_file(source, output)["status"] == "needs_review"
    target = output / name
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError):
        replay_corridor(output)


def test_existing_output_and_duplicate_json_keys_are_errors_without_overwrite(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(payload()))
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "keep"
    sentinel.write_text("retained")
    assert analyze_corridor_file(source, output)["status"] == "error"
    assert sentinel.read_text() == "retained"
    source.write_text('{"id":"a","id":"b"}')
    assert analyze_corridor_file(source, tmp_path / "bad")["status"] == "error"
    assert not (tmp_path / "bad").exists()

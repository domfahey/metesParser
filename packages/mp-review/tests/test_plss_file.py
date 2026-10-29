"""File publication and composable map contract for supplied references."""

import hashlib
import json
from pathlib import Path

from mp_review.plss import prepare_plss_file


def request_data():
    section = {
        "principal_meridian": "Synthetic Meridian",
        "township": 1,
        "township_direction": "N",
        "range": 1,
        "range_direction": "E",
        "section": 1,
    }
    return {
        "dataset": {
            "id": "dataset",
            "version": "1",
            "authority_citation": "Synthetic survey sheet",
            "source": {
                "id": "survey",
                "label": "Survey",
                "sha256": "a" * 64,
                "native_crs": "EPSG:3857",
                "native_units": "m",
            },
            "scene": {
                "id": "grid",
                "name": "Grid",
                "kind": "projected",
                "crs": "EPSG:3857",
                "units": "m",
                "basis": "grid",
            },
            "references": [
                {
                    "id": "ref",
                    "section": section,
                    "subdivision_class": "rectangular",
                    "corners": [
                        {"name": n, "xy": p, "source_id": "survey"}
                        for n, p in [
                            ("SW", [0, 0]),
                            ("SE", [80, 0]),
                            ("NE", [80, 40]),
                            ("NW", [0, 40]),
                        ]
                    ],
                }
            ],
        },
        "selected_dataset_id": "dataset",
        "selected_reference_id": "ref",
        "section": section,
        "rule": "rectangular_aliquot_v1",
        "aliquot_steps": ["N2"],
    }


def test_exact_request_hash_manifest_and_prepared_layer(tmp_path):
    raw = (json.dumps(request_data(), indent=3) + "\n").encode()
    source = tmp_path / "input.json"
    source.write_bytes(raw)
    output = tmp_path / "derived"
    result = prepare_plss_file(source, output)
    assert result["status"] == "needs_review"
    assert result["availability"] == "computed"
    assert (output / "request.json").read_bytes() == raw
    manifest = json.loads((output / "plss-manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    layer = json.loads((output / "prepared-layer.json").read_text())
    assert layer["operation"]["request_sha256"] == hashlib.sha256(raw).hexdigest()
    assert layer["vector_layers"][0]["coordinates"][0] == [
        [0, 20],
        [80, 20],
        [80, 40],
        [0, 40],
        [0, 20],
    ]
    assert prepare_plss_file(source, output)["status"] == "error"


def test_unsupported_is_advisory_without_prepared_layer(tmp_path):
    data = request_data()
    data["dataset"]["references"][0]["subdivision_class"] = "government_lot"
    source = tmp_path / "input.json"
    source.write_text(json.dumps(data))
    result = prepare_plss_file(source, tmp_path / "unsupported")
    assert result["status"] == "needs_review"
    assert result["availability"] == "unsupported"
    assert "prepared-layer.json" not in result["artifacts"]


def test_duplicate_json_keys_are_input_error_without_publication(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text('{"rule":"a","rule":"b"}')
    assert prepare_plss_file(source, tmp_path / "bad")["status"] == "error"
    assert not (tmp_path / "bad").exists()


def test_interrupted_component_write_has_no_complete_manifest(tmp_path, monkeypatch):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(request_data()))
    original = Path.open

    def fail(path, *args, **kwargs):
        if path.name == "plss-result.json":
            raise OSError("simulated failed artifact write")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    output = tmp_path / "partial"
    result = prepare_plss_file(source, output)
    assert result["status"] == "error"
    assert (output / "request.json").exists()
    assert not (output / "plss-manifest.json").exists()


def test_prepared_reference_composes_without_inferred_deed_placement(tmp_path):
    from mp_review.compose import compose_map_file
    from mp_review.plot import plot_file

    source = tmp_path / "input.json"
    source.write_text(json.dumps(request_data()))
    output = tmp_path / "derived"
    assert prepare_plss_file(source, output)["availability"] == "computed"
    calls = tmp_path / "calls.json"
    calls.write_text(
        json.dumps(
            [
                {
                    "course": i + 1,
                    "direction_text": f"Bearing {b}",
                    "bearing_azimuth_deg_from_north": b,
                    "distance_ft": 100,
                }
                for i, b in enumerate([0, 90, 180, 270])
            ]
        )
    )
    plot_directory = tmp_path / "plot"
    assert plot_file(calls, plot_directory)["status"] == "needs_review"
    composed = compose_map_file(
        plot_directory, tmp_path / "map", layers=[output / "prepared-layer.json"]
    )
    assert composed["status"] == "needs_review"
    data = json.loads((tmp_path / "map" / "map-input.json").read_text())
    assert len(data["vector_layers"]) == 1
    assert data["placements"] == []
    assert len(data["map_sources"]) == 2

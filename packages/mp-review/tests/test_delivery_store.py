"""Frozen delivery snapshots and interrupted publication remain evidence-bound."""

import json
from pathlib import Path

import pytest
from mp_models.dashboard import DashboardBundle
from mp_models.delivery import DeliveryRequest
from mp_models.revisions import revision_template
from mp_review.delivery import load_delivery, prepare_delivery, publish_delivery
from mp_review.revisions import publish_revision


def _two_tracts(bundle):
    data = bundle.model_dump(mode="json")
    groups = (
        "documents",
        "pages",
        "parcels",
        "occurrences",
        "calls",
        "evidence",
        "calculations",
        "scenarios",
    )
    ids = {item["id"] for group in groups for item in data[group]}

    def remap(value):
        if isinstance(value, str):
            return "second-" + value if value in ids else value
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        return value

    for group in groups:
        data[group] += remap(data[group])
    return DashboardBundle.model_validate(data)


@pytest.fixture
def setup(tmp_path):
    bundle = DashboardBundle.model_validate_json(
        (Path(__file__).parent / "fixtures/dashboard-absolute.json").read_text()
    )
    revision = revision_template(bundle, revision_id="published")
    assert publish_revision(bundle, revision, tmp_path / "revisions")["save_state"] == "published"
    request = DeliveryRequest(
        id="package",
        baseline=revision.baseline,
        revision_id="published",
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="local",
        units="unknown_ft",
        layers=[
            {
                "id": "calc-one",
                "kind": "calculation",
                "visible": True,
                "opacity": 0.0,
                "required": True,
            }
        ],
        formats=["svg", "pdf", "dxf"],
        labels=["course", "bearing", "distance"],
        presentation_rotation_deg=35.0,
    )
    return bundle, tmp_path / "revisions" / "published", request


def test_snapshot_zero_opacity_membership_recorded_values_and_no_full_source(setup):
    bundle, revision, request = setup
    snapshot = prepare_delivery(bundle, revision, request)
    assert len(snapshot.items[0].primitives) == 4
    assert snapshot.items[0].primitives[0].start == (0.0, 0.0)
    assert snapshot.items[0].primitives[0].end == (0.0, 100.0)
    assert snapshot.items[0].primitives[0].recorded_bearing_deg == 0.0
    assert snapshot.canonical_verification == "not_requested"
    assert "image" not in json.dumps(snapshot.source_references)


def test_input_status_tracks_each_selected_call_for_scenario_and_source_correction(setup, tmp_path):
    bundle, revision_dir, base_request = setup
    revision = revision_template(bundle, revision_id="mixed-scenario").model_dump(mode="json")
    revision["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "raw_fields": {"distance_ft": "101"},
            "rationale": "Adjust one hypothetical course.",
        }
    ]
    assert publish_revision(bundle, revision, revision_dir.parent)["save_state"] == "published"
    scenario = prepare_delivery(
        bundle,
        revision_dir.parent / "mixed-scenario",
        base_request.model_copy(update={"id": "scenario-package", "revision_id": "mixed-scenario"}),
    )
    scenario_status = {p.call_id: p.input_status for p in scenario.items[0].primitives}
    assert scenario_status == {
        "call-one": "hypothetical",
        "call-two": "recorded",
        "call-three": "recorded",
        "call-four": "recorded",
    }

    recorded = prepare_delivery(
        bundle,
        revision_dir.parent / "mixed-scenario",
        base_request.model_copy(
            update={
                "id": "recorded-package",
                "revision_id": "mixed-scenario",
                "geometry": "recorded",
            }
        ),
    )
    assert {p.input_status for p in recorded.items[0].primitives} == {"recorded"}

    correction = revision_template(bundle, revision_id="mixed-correction").model_dump(mode="json")
    correction["kind"] = "source_correction"
    correction["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "raw_fields": {"distance_ft": "101"},
            "rationale": "Correct the transcription from the cited page.",
            "source_refs": [{"page_id": "page-one", "quote": "  101 feet  "}],
        }
    ]
    assert publish_revision(bundle, correction, revision_dir.parent)["save_state"] == "published"
    corrected = prepare_delivery(
        bundle,
        revision_dir.parent / "mixed-correction",
        base_request.model_copy(
            update={"id": "correction-package", "revision_id": "mixed-correction"}
        ),
    )
    corrected_status = {p.call_id: p.input_status for p in corrected.items[0].primitives}
    assert corrected_status == {
        "call-one": "source_correction",
        "call-two": "recorded",
        "call-three": "recorded",
        "call-four": "recorded",
    }


def test_scenario_status_does_not_spread_to_an_unedited_tract(setup, tmp_path):
    original, _, _ = setup
    bundle = _two_tracts(original)
    revision = revision_template(bundle, revision_id="one-tract-edited").model_dump(mode="json")
    revision["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "raw_fields": {"distance_ft": "101"},
            "rationale": "Adjust the first tract only.",
        }
    ]
    revision_root = tmp_path / "revisions"
    assert publish_revision(bundle, revision, revision_root)["save_state"] == "published"
    request = DeliveryRequest(
        id="untouched-tract-package",
        baseline=revision_template(bundle, revision_id="template").baseline,
        revision_id="one-tract-edited",
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="local",
        units="unknown_ft",
        layers=[
            {
                "id": "second-calc-one",
                "kind": "calculation",
                "visible": True,
                "opacity": 1.0,
                "required": True,
            }
        ],
        formats=["svg"],
    )
    snapshot = prepare_delivery(bundle, revision_root / "one-tract-edited", request)
    assert {p.input_status for p in snapshot.items[0].primitives} == {"recorded"}


def test_draft_or_wrong_revision_cannot_export_older_geometry(setup, tmp_path):
    bundle, directory, request = setup
    data = revision_template(bundle, revision_id="bad").model_dump(mode="json")
    data["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "raw_fields": {"distance_ft": "bad"},
        }
    ]
    assert publish_revision(bundle, data, directory.parent)["save_state"] == "published"
    with pytest.raises(ValueError, match="draft"):
        prepare_delivery(
            bundle, directory.parent / "bad", request.model_copy(update={"revision_id": "bad"})
        )
    with pytest.raises(ValueError, match="identity"):
        prepare_delivery(bundle, directory, request.model_copy(update={"revision_id": "wrong"}))


def test_manifest_last_retry_and_no_overwrite(setup, tmp_path, monkeypatch):
    import mp_review.delivery as api

    bundle, revision, request = setup
    original = api._write_once

    def fail(path, content):
        if path.name == "delivery-manifest.json":
            raise OSError("interrupted package")
        return original(path, content)

    monkeypatch.setattr(api, "_write_once", fail)
    assert publish_delivery(bundle, revision, request, tmp_path / "deliveries")["status"] == "error"
    with pytest.raises(ValueError, match="incomplete"):
        load_delivery(bundle, revision, tmp_path / "deliveries" / "package")
    monkeypatch.setattr(api, "_write_once", original)
    assert (
        publish_delivery(bundle, revision, request, tmp_path / "deliveries")["status"]
        == "needs_review"
    )
    loaded = load_delivery(bundle, revision, tmp_path / "deliveries" / "package")
    assert loaded.request == request
    changed = request.model_copy(update={"presentation_rotation_deg": 12.0})
    assert publish_delivery(bundle, revision, changed, tmp_path / "deliveries")["status"] == "error"


def _placed_case(tmp_path):
    import base64
    import hashlib
    import io
    import math

    from mp_review.revisions import load_revision
    from mp_verify.dashboard import _hash
    from PIL import Image

    data = json.loads((Path(__file__).parent / "fixtures/dashboard-absolute.json").read_text())
    data["schema_version"] = "1.1"
    data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    for record, azimuth, distance in zip(
        data["calls"], (90.0, 90.0, 270.0, 180.0), (100.0, 25 * math.pi, 100.0, 50.0), strict=True
    ):
        record["call"].update(bearing_azimuth_deg_from_north=azimuth, distance_ft=distance)
    data["calls"][1]["call"].update(
        curve_dir="left",
        radius_ft=25.0,
        delta_deg=180.0,
        arc_length_ft=25 * math.pi,
        chord_length_ft=50.0,
        chord_bearing="N 0° E",
        non_tangent=False,
    )
    data["scenes"] = [
        {
            "id": "scene",
            "name": "Explicit metre scene",
            "kind": "projected",
            "crs": "EPSG:3857",
            "units": "m",
            "basis": "supplied test frame",
        }
    ]
    image = Image.new("RGB", (2, 2))
    image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)])
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    content = stream.getvalue()
    sha = hashlib.sha256(content).hexdigest()
    data["map_sources"] = [
        {"id": "context-source", "label": "Context", "sha256": "0" * 64},
        {"id": "raster-source", "label": "Supplied raster", "sha256": sha},
    ]
    vector = {
        "id": "context",
        "label": "Context",
        "source_id": "context-source",
        "scene_id": "scene",
        "geometry_type": "Polygon",
        "coordinates": [
            [[990.0, 1990.0], [1050.0, 1990.0], [1050.0, 2040.0], [990.0, 2040.0], [990.0, 1990.0]]
        ],
    }
    data["vector_layers"] = [vector, vector | {"id": "hidden-context"}]
    data["raster_layers"] = [
        {
            "id": "raster",
            "label": "Supplied raster",
            "source_id": "raster-source",
            "scene_id": "scene",
            "mime_type": "image/png",
            "width": 2,
            "height": 2,
            "sha256": sha,
            "data_base64": base64.b64encode(content).decode(),
            "registration": {
                "matrix": [30.0, 10.0, 990.0, 0.0, -30.0, 2010.0],
                "method": "supplied_affine",
            },
        }
    ]
    bundle = DashboardBundle.model_validate(data)
    from mp_review.delivery import _recorded_plots

    plot = _recorded_plots(bundle)["calc-one"]
    assert plot.geometry.completeness == "complete", (
        plot.geometry.unresolved,
        plot.geometry.reasons,
    )
    revision = revision_template(bundle, revision_id="placed-revision")
    assert publish_revision(bundle, revision, tmp_path / "revisions")["status"] == "needs_review"
    directory = tmp_path / "revisions" / "placed-revision"
    prepared = load_revision(bundle, directory)
    placement = {
        "id": "placement",
        "calculation_id": "calc-one",
        "geometry_hash": prepared.current_geometry[0].plot.geometry.geometry_hash,
        "scene_id": "scene",
        "rotation_deg": 30.0,
        "translation": [1000.0, 2000.0],
        "status": "approximate",
        "rationale": "Supplied test translation and orientation",
        "position_evidence": ["Analytic test origin"],
        "orientation_evidence": ["Analytic test clockwise rotation"],
    }
    from mp_models.plot import PlotPlacement

    placement_hash = _hash(PlotPlacement.model_validate(placement).model_dump(mode="json"))
    request = DeliveryRequest(
        id="placed-delivery",
        baseline=revision.baseline,
        revision_id=revision.id,
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="placed",
        scene_id="scene",
        units="m",
        placements=[placement],
        layers=[
            {"id": "raster", "kind": "raster", "visible": True, "opacity": 0.4, "required": False},
            {"id": "context", "kind": "vector", "visible": True, "opacity": 0.6, "required": True},
            {
                "id": "calc-one",
                "kind": "calculation",
                "visible": True,
                "opacity": 0.0,
                "required": True,
                "placement_id": "placement",
                "placement_sha256": placement_hash,
            },
            {
                "id": "hidden-context",
                "kind": "vector",
                "visible": False,
                "opacity": 1.0,
                "required": True,
            },
        ],
        formats=["svg", "pdf", "dxf", "geojson"],
        labels=["course", "bearing", "distance"],
        presentation_rotation_deg=37.0,
        presentation_pivot=(1000.0, 2000.0),
        geo_tolerance_m=0.01,
    )
    return bundle, directory, request


def test_all_formats_agree_under_placement_rotation_raster_hidden_and_zero_opacity(tmp_path):
    import io
    import math

    import ezdxf
    from pypdf import PdfReader
    from pyproj import Transformer

    bundle, revision, request = _placed_case(tmp_path)
    result = publish_delivery(bundle, revision, request, tmp_path / "deliveries")
    assert result["status"] == "needs_review", result
    directory = tmp_path / "deliveries" / request.id
    snapshot = load_delivery(bundle, revision, directory)
    assert snapshot.metrics[0].area_sq_ft == pytest.approx(5000 + 312.5 * math.pi)
    dxf = ezdxf.read(io.StringIO((directory / "drawing.dxf").read_text()))
    entities = list(dxf.modelspace())
    assert [e.dxftype() for e in entities] == ["LWPOLYLINE", "LINE", "ARC", "LINE", "LINE"]
    start = entities[1].dxf.start
    end = entities[1].dxf.end
    assert start.isclose((1000.0, 2000.0, 0.0))
    assert end.isclose((1000 + 30.48 * math.cos(math.radians(30)), 2000 - 30.48 * 0.5, 0.0))
    assert entities[2].dxf.radius == pytest.approx(7.62)
    assert entities[1].transparency == 1.0
    assert dxf.header["$INSUNITS"] == 6
    geojson = json.loads((directory / "drawing.geojson").read_text())
    courses = [f for f in geojson["features"] if f["properties"]["kind"] == "recorded_course"]
    assert len(courses) == 4
    assert len(courses[1]["geometry"]["coordinates"]) > 2
    assert courses[0]["properties"]["opacity"] == 0
    lonlat = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    assert courses[0]["geometry"]["coordinates"][0] == pytest.approx(lonlat.transform(1000, 2000))
    assert courses[0]["geometry"]["coordinates"][-1] == pytest.approx(
        lonlat.transform(end.x, end.y)
    )
    source = (directory / "drawing.svg").read_text()
    assert (
        source.index('data-layer-id="raster"')
        < source.index('data-layer-id="context"')
        < source.index('data-layer-id="calc-one"')
    )
    assert 'data-layer-id="hidden-context"' not in source
    assert "<image " in source and 'opacity="0"' in source
    pdf = PdfReader(directory / "drawing.pdf")
    assert len(pdf.pages[0].images) == 1
    assert "placed-revision" in pdf.pages[0].extract_text()
    assert "call-one" in pdf.pages[0].extract_text()
    assert any(o.layer_id == "raster" and o.format == "dxf" for o in snapshot.omissions)
    assert not (directory / "full-source.json").exists()
    assert "image" not in json.dumps(snapshot.source_references)


def test_required_raster_stale_placement_and_unknown_units_block(tmp_path):
    bundle, revision, request = _placed_case(tmp_path)
    data = request.model_dump(mode="json")
    data["layers"][0]["required"] = True
    with pytest.raises(ValueError, match="raster"):
        prepare_delivery(bundle, revision, data)
    data = request.model_dump(mode="json")
    data["layers"][2]["placement_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        prepare_delivery(bundle, revision, data)
    data = request.model_dump(mode="json")
    data["units"] = "unknown_ft"
    with pytest.raises(ValueError):
        prepare_delivery(bundle, revision, data)
    data = request.model_dump(mode="json")
    data["required_appearance"] = True
    with pytest.raises(ValueError, match="labels"):
        prepare_delivery(bundle, revision, data)


def test_delivery_tampering_and_full_source_only_when_requested(setup, tmp_path):
    bundle, revision, request = setup
    request = request.model_copy(update={"include_full_source": True})
    assert (
        publish_delivery(bundle, revision, request, tmp_path / "deliveries")["status"]
        == "needs_review"
    )
    directory = tmp_path / "deliveries" / request.id
    assert json.loads((directory / "full-source.json").read_text())["pages"][0]["image"]
    (directory / "drawing.svg").write_text("<svg/>")
    with pytest.raises(ValueError, match="hash"):
        load_delivery(bundle, revision, directory)


def test_scenario_fields_never_replace_original_recorded_values(setup):
    bundle, directory, request = setup
    revision = revision_template(bundle, revision_id="changed").model_dump(mode="json")
    revision["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "raw_fields": {"distance_ft": "110", "bearing_azimuth_deg_from_north": "45"},
            "rationale": "Hypothetical test",
        }
    ]
    assert publish_revision(bundle, revision, directory.parent)["status"] == "needs_review"
    changed = request.model_copy(update={"revision_id": "changed"})
    snapshot = prepare_delivery(bundle, directory.parent / "changed", changed)
    primitive = snapshot.items[0].primitives[0]
    assert primitive.recorded_bearing_deg == 0
    assert primitive.selected_bearing_deg == 45
    assert primitive.recorded_distance_ft == 100
    assert primitive.selected_distance_ft == 110
    assert primitive.input_status == "hypothetical"
    assert snapshot.selected_revision_calls
    assert snapshot.selected_revision_calls[0]["original_source"]["call"]["distance_ft"] == 100


def test_open_geometry_metrics_stay_null_with_reason(tmp_path):
    data = json.loads((Path(__file__).parent / "fixtures/dashboard-absolute.json").read_text())
    data["calls"] = data["calls"][:1]
    data["scenarios"] = []
    bundle = DashboardBundle.model_validate(data)
    revision = revision_template(bundle, revision_id="open")
    assert publish_revision(bundle, revision, tmp_path / "revisions")["status"] == "needs_review"
    request = DeliveryRequest(
        id="open-package",
        baseline=revision.baseline,
        revision_id="open",
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="local",
        units="unknown_ft",
        formats=["svg"],
        layers=[
            {
                "id": "calc-one",
                "kind": "calculation",
                "visible": True,
                "opacity": 1.0,
                "required": True,
            }
        ],
    )
    snapshot = prepare_delivery(bundle, tmp_path / "revisions" / "open", request)
    assert snapshot.metrics[0].area_sq_ft is None
    assert snapshot.metrics[0].unavailable_reason
    assert not snapshot.verified_export_eligible


def test_manifest_cannot_rewrite_omission_or_identity_policy(setup, tmp_path):
    bundle, revision, request = setup
    assert (
        publish_delivery(bundle, revision, request, tmp_path / "deliveries")["status"]
        == "needs_review"
    )
    directory = tmp_path / "deliveries" / request.id
    manifest_path = directory / "delivery-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["omissions"] = []
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="policy"):
        load_delivery(bundle, revision, directory)


def test_baseline_domain_mapping_preserves_exact_binding_and_rejects_scenario_input(tmp_path):
    from mp_models.plot import PlotPlacement
    from mp_review.revisions import load_revision
    from mp_verify.dashboard import _hash
    from mp_verify.plot import _geometry

    data = json.loads((Path(__file__).parent / "fixtures/dashboard-absolute.json").read_text())
    data["schema_version"] = "1.1"
    data["calculations"][0]["frame"]["foot_definition"] = "international_ft"
    data["scenes"] = [
        {
            "id": "scene",
            "name": "Explicit scene",
            "kind": "projected",
            "crs": "EPSG:3857",
            "units": "m",
            "basis": "supplied frame",
        }
    ]
    initial = DashboardBundle.model_validate(data)
    original_geometry = _geometry(initial, initial.calculations[0], None)
    placement = PlotPlacement(
        id="baseline-placement",
        calculation_id="calc-one",
        geometry_hash=original_geometry.geometry_hash,
        scene_id="scene",
        rotation_deg=15.0,
        translation=(1000.0, 2000.0),
        status="approximate",
        rationale="Supplied control evidence",
    )
    data["placements"] = [placement.model_dump(mode="json")]
    bundle = DashboardBundle.model_validate(data)
    revision = revision_template(bundle, revision_id="original")
    assert publish_revision(bundle, revision, tmp_path / "revisions")["status"] == "needs_review"
    request = DeliveryRequest(
        id="exact-domain",
        baseline=revision.baseline,
        revision_id="original",
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="placed",
        scene_id="scene",
        units="m",
        formats=["svg"],
        layers=[
            {
                "id": "calc-one",
                "kind": "calculation",
                "visible": True,
                "opacity": 1.0,
                "required": True,
                "placement_id": placement.id,
                "placement_sha256": _hash(placement.model_dump(mode="json")),
            }
        ],
    )
    snapshot = prepare_delivery(bundle, tmp_path / "revisions" / "original", request)
    item = snapshot.items[0]
    assert item.placement_original_geometry_hash == original_geometry.geometry_hash
    assert item.placement_binding_baseline_sha256 == revision.baseline.bundle_sha256
    assert item.placement.geometry_hash != original_geometry.geometry_hash
    changed = revision_template(bundle, revision_id="changed").model_dump(mode="json")
    changed["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "raw_fields": {"distance_ft": "100"},
            "rationale": "Explicit scenario change with same numeric value",
        }
    ]
    assert publish_revision(bundle, changed, tmp_path / "revisions")["status"] == "needs_review"
    with pytest.raises(ValueError, match="Stale placement"):
        prepare_delivery(
            bundle,
            tmp_path / "revisions" / "changed",
            request.model_copy(update={"revision_id": "changed"}),
        )
    fresh = load_revision(bundle, tmp_path / "revisions" / "changed").current_geometry[0].plot
    new_placement = placement.model_copy(
        update={"id": "fresh-placement", "geometry_hash": fresh.geometry.geometry_hash}
    )
    data = request.model_dump(mode="json")
    data.update(revision_id="changed", placements=[new_placement.model_dump(mode="json")])
    data["layers"][0].update(
        placement_id=new_placement.id, placement_sha256=_hash(new_placement.model_dump(mode="json"))
    )
    assert (
        prepare_delivery(bundle, tmp_path / "revisions" / "changed", data).items[0].placement.id
        == "fresh-placement"
    )


@pytest.mark.parametrize("kind", ["calculation", "vector", "raster"])
@pytest.mark.parametrize("crs,units", [("EPSG:4326", "m"), ("EPSG:3857", "international_ft")])
def test_selected_placed_scene_rejects_geographic_or_conflicting_axis_units(
    tmp_path, kind, crs, units
):
    bundle, _, request = _placed_case(tmp_path)
    source = bundle.model_dump(mode="json")
    source["scenes"][0].update(crs=crs, units=units)
    bundle = DashboardBundle.model_validate(source)
    revision = revision_template(bundle, revision_id="invalid-scene")
    assert (
        publish_revision(bundle, revision, tmp_path / "bad-scene-revisions")["save_state"]
        == "published"
    )
    directory = tmp_path / "bad-scene-revisions" / revision.id
    data = request.model_dump(mode="json")
    data.update(
        baseline=revision.baseline.model_dump(mode="json"),
        revision_id=revision.id,
        formats=["svg"],
        layers=[next(layer for layer in data["layers"] if layer["kind"] == kind)],
    )
    data["layers"][0]["required"] = True
    selected = DeliveryRequest.model_validate(data)
    with pytest.raises(ValueError, match="CRS|units|projected"):
        prepare_delivery(bundle, directory, selected)
    published = publish_delivery(bundle, directory, selected, tmp_path / "refused-deliveries")
    assert published["status"] == "error"
    assert not (tmp_path / "refused-deliveries").exists()


def test_request_supplied_selected_scene_is_validated_before_publication(tmp_path):
    from mp_models.plot import PlotPlacement
    from mp_verify.dashboard import _hash

    bundle, directory, request = _placed_case(tmp_path)
    data = request.model_dump(mode="json")
    data["formats"] = ["svg", "dxf"]
    data["scenes"] = [
        {
            "id": "false-metric",
            "name": "False projected scene",
            "kind": "projected",
            "crs": "EPSG:4326",
            "units": "m",
            "basis": "grid",
        }
    ]
    data["scene_id"] = "false-metric"
    data["placements"][0]["scene_id"] = "false-metric"
    data["layers"] = [next(layer for layer in data["layers"] if layer["kind"] == "calculation")]
    data["layers"][0]["placement_sha256"] = _hash(
        PlotPlacement.model_validate(data["placements"][0]).model_dump(mode="json")
    )
    result = publish_delivery(
        bundle, directory, DeliveryRequest.model_validate(data), tmp_path / "refused"
    )
    assert result["status"] == "error"
    assert not (tmp_path / "refused").exists()


@pytest.mark.parametrize(
    "drawing_geometry,drawing_distance", [("recorded", 100), ("scenario", 101)]
)
def test_revision_evidence_sidecar_is_distinct_from_actual_drawing_inputs(
    setup, tmp_path, drawing_geometry, drawing_distance
):
    bundle, directory, request = setup
    revision = revision_template(bundle, revision_id="alternative-evidence").model_dump(mode="json")
    revision["edits"] = [
        {
            "call_id": "call-one",
            "occurrence_id": "occ-one",
            "tract_id": "parcel-one",
            "document_id": "doc-one",
            "raw_fields": {"distance_ft": "101"},
            "rationale": "Hypothetical one-foot difference",
        }
    ]
    assert publish_revision(bundle, revision, directory.parent)["save_state"] == "published"
    selected = request.model_copy(
        update={"revision_id": revision["id"], "geometry": drawing_geometry, "formats": ("svg",)}
    )
    root = tmp_path / "evidence-export"
    assert (
        publish_delivery(bundle, directory.parent / revision["id"], selected, root)["save_state"]
        == "published"
    )
    output = root / selected.id
    actual = json.loads((output / "calls.json").read_bytes())
    evidence = json.loads((output / "revision-calls.json").read_bytes())
    assert actual[0]["calls"][0]["call"]["distance_ft"] == drawing_distance
    assert evidence["purpose"] == "selected_revision_evidence"
    assert evidence["drawing_geometry"] == drawing_geometry
    assert evidence["revision_id"] == revision["id"] and evidence["generation"] == 0
    assert evidence["calls"][0]["call"]["distance_ft"] == 101
    assert evidence["calls"][0]["source_status"] == "hypothetical"
    assert evidence["calls"][0]["original_source"]["call"]["distance_ft"] == 100
    loaded = load_delivery(bundle, directory.parent / revision["id"], output)
    assert loaded.items[0].primitives[0].selected_distance_ft == drawing_distance

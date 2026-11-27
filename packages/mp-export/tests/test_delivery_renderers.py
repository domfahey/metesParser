"""Independent readers verify analytic arcs and presentation-only rotation."""

import io
import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from mp_export.delivery import render_delivery_dxf, render_delivery_pdf, render_delivery_svg
from mp_models.delivery import DeliveryItem, DeliveryPrimitive, DeliveryRequest, DeliverySnapshot


def snapshot(rotation=0.0):
    request = DeliveryRequest(
        id="arc-package",
        baseline={"id": "baseline", "bundle_sha256": "0" * 64},
        revision_id="published",
        revision_generation=0,
        geometry="scenario",
        coordinate_mode="local",
        units="international_ft",
        formats=["svg", "pdf", "dxf"],
        labels=["course", "bearing", "distance"],
        layers=[
            {
                "id": "arc-layer",
                "kind": "calculation",
                "visible": True,
                "opacity": 0,
                "required": True,
            }
        ],
        presentation_rotation_deg=rotation,
    )
    arc = DeliveryPrimitive(
        kind="arc",
        call_id="arc-course",
        layer_id="arc-layer",
        start=(30.0, 0.0),
        end=(0.0, -30.0),
        center=(0.0, 0.0),
        radius=30.0,
        sweep_deg=270.0,
        curve_dir="left",
        length=45 * math.pi,
        recorded_bearing_deg=0.0,
        recorded_distance_ft=45 * math.pi,
    )
    return DeliverySnapshot(
        request=request,
        request_sha256="a" * 64,
        revision_sha256="b" * 64,
        items=[DeliveryItem(selection=request.layers[0], primitives=[arc])],
        metrics=[],
    )


def test_true_major_arc_dxf_independent_reader_and_presentation_rotation():
    import ezdxf

    one, two = snapshot(), snapshot(47.0)
    document = ezdxf.read(io.StringIO(render_delivery_dxf(one).decode()))
    rotated = ezdxf.read(io.StringIO(render_delivery_dxf(two).decode()))
    entity = list(document.modelspace())[0]
    assert entity.dxftype() == "ARC"
    assert entity.dxf.radius == 30
    assert entity.dxf.center == (0, 0, 0)
    assert (entity.dxf.end_angle - entity.dxf.start_angle) % 360 == 270
    assert entity.start_point.isclose((30, 0, 0))
    assert entity.end_point.isclose((0, -30, 0))
    assert document.header["$INSUNITS"] == 2
    assert entity.transparency == 1
    assert entity.get_xdata("METESPARSER")[0].value == "arc-course"
    assert list(rotated.modelspace())[0].dxf.start_angle == entity.dxf.start_angle
    assert render_delivery_dxf(one) == render_delivery_dxf(one)
    assert not document.audit().has_errors


def test_pdf_reader_svg_arc_and_deterministic_publication():
    from pypdf import PdfReader

    result = render_delivery_pdf(snapshot(33.0))
    assert result == render_delivery_pdf(snapshot(33.0))
    reader = PdfReader(io.BytesIO(result))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "published" in text and "verification not requested" in text
    assert "arc-course" in text and "recorded" in text
    source = render_delivery_svg(snapshot(33.0))
    root = ET.fromstring(source)
    paths = root.findall(".//{http://www.w3.org/2000/svg}path")
    assert " A " in paths[0].attrib["d"] and "0 1 0" in paths[0].attrib["d"]
    assert source != render_delivery_svg(snapshot())


def test_hypothetical_missing_bearing_never_falls_back_to_original_record():
    value = snapshot()
    primitive = (
        value.items[0]
        .primitives[0]
        .model_copy(
            update={
                "input_status": "hypothetical",
                "selected_bearing_deg": None,
                "selected_distance_ft": 10 * math.pi,
            }
        )
    )
    value = value.model_copy(
        update={"items": (value.items[0].model_copy(update={"primitives": (primitive,)}),)}
    )
    root = ET.fromstring(render_delivery_svg(value))
    texts = [el.text or "" for el in root.findall(".//{http://www.w3.org/2000/svg}text")]
    label = next(t for t in texts if t.startswith("arc-course | "))
    assert "bearing unavailable" in label
    assert "0.000000 deg" not in label
    selected = next(t for t in texts if "hypothetical input:" in t)
    assert "bearing unavailable" in selected
    assert "0.000000 deg" not in selected
    assert any("Original recorded input: 0.000000 deg" in t for t in texts)


def test_dxf_is_identical_across_fresh_process_hash_seeds():
    script = (
        "import sys; from mp_models.delivery import DeliverySnapshot; "
        "from mp_export.delivery import render_delivery_dxf; "
        "sys.stdout.buffer.write(render_delivery_dxf(DeliverySnapshot.model_validate_json(sys.stdin.buffer.read())))"
    )
    payload = snapshot().model_dump_json().encode()
    outputs = []
    for seed in ("0", "1", "2", "42", "99"):
        process = subprocess.run(
            [sys.executable, "-c", script],
            input=payload,
            capture_output=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
        )
        outputs.append(process.stdout)
    assert len(set(outputs)) == 1, "DXF bytes must replay identically in a fresh process"


def _oriented_raster_snapshot(orientation):
    import base64
    import hashlib

    from mp_models.raster import RasterLayer, RasterRegistration
    from PIL import Image

    image = Image.new("RGB", (10, 20))
    exif = Image.Exif()
    exif[274] = orientation
    stream = io.BytesIO()
    image.save(stream, format="JPEG", exif=exif.tobytes())
    data = stream.getvalue()
    layer = RasterLayer(
        id="old-raster",
        label="old.jpg",
        source_id="src",
        scene_id="scene",
        mime_type="image/jpeg",
        width=10,
        height=20,
        sha256=hashlib.sha256(data).hexdigest(),
        data_base64=base64.b64encode(data).decode(),
        registration=RasterRegistration(method="supplied_affine", matrix=(1, 0, 0, 0, 1, 0)),
    )
    base = snapshot()
    selection = base.items[0].selection.model_copy(update={"id": "raster-layer", "kind": "raster"})
    return base.model_copy(update={"items": [DeliveryItem(selection=selection, raster=layer)]})


def test_delivery_svg_and_pdf_refuse_exif_oriented_raster():
    import pytest

    oriented = _oriented_raster_snapshot(6)
    with pytest.raises(ValueError, match="orientation"):
        render_delivery_svg(oriented)
    with pytest.raises(ValueError, match="orientation"):
        render_delivery_pdf(oriented)


def test_delivery_svg_and_pdf_embed_upright_raster():
    upright = _oriented_raster_snapshot(1)
    assert "data:image/jpeg;base64," in render_delivery_svg(upright)
    assert render_delivery_pdf(upright).startswith(b"%PDF")


def test_delivery_full_circle_lines_vectors_hidden_layers_metrics_and_multipage_pdf():
    import ezdxf
    import pytest
    from mp_models.delivery import DeliveryMetric
    from mp_models.plot import VectorLayer
    from pypdf import PdfReader

    base = snapshot()
    hidden_sel = base.items[0].selection.model_copy(update={"id": "hidden-layer", "visible": False})
    line_sel = base.items[0].selection.model_copy(
        update={"id": "line-and-circle", "visible": True, "opacity": 0.8}
    )
    vec_sel = base.items[0].selection.model_copy(
        update={"id": "vector-layer", "kind": "vector", "visible": True, "opacity": 0.5}
    )
    line_prim = DeliveryPrimitive(
        kind="line",
        call_id="line-1",
        layer_id="line-and-circle",
        start=(0.0, 0.0),
        end=(40.0, 0.0),
        length=40.0,
        recorded_bearing_deg=90.0,
        recorded_distance_ft=40.0,
    )
    full_circle = DeliveryPrimitive(
        kind="arc",
        call_id="circle-1",
        layer_id="line-and-circle",
        start=(10.0, 0.0),
        end=(10.0, 0.0),
        center=(0.0, 0.0),
        radius=10.0,
        sweep_deg=360.0,
        curve_dir="right",
        length=20.0 * math.pi,
        recorded_bearing_deg=180.0,
        recorded_distance_ft=20.0 * math.pi,
    )
    polygon = VectorLayer(
        id="poly-1",
        label="Parcel context",
        source_id="src",
        scene_id="scene",
        geometry_type="Polygon",
        coordinates=(((0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0), (0.0, 0.0)),),
    )
    multipolygon = VectorLayer(
        id="mpoly-1",
        label="Multi context",
        source_id="src",
        scene_id="scene",
        geometry_type="MultiPolygon",
        coordinates=((((60.0, 0.0), (70.0, 0.0), (70.0, 10.0), (60.0, 10.0), (60.0, 0.0)),),),
    )
    # Include enough metrics (both single-line and wrapped long calculation_ids) to trigger
    # between-row and mid-row PDF pagination across multiple pages.
    many_metrics = [
        DeliveryMetric(
            calculation_id=("long-calc-" + "x" * 180) if i in {6, 40} else f"calc-{i}",
            misclosure_ft=0.001 * i if i % 2 == 0 else None,
            area_sq_ft=1000.0 + i if i % 2 == 0 else None,
            perimeter_ft=100.0,
        )
        for i in range(45)
    ]
    rich = base.model_copy(
        update={
            "scene_units": "m",
            "items": (
                DeliveryItem(selection=hidden_sel, primitives=(line_prim,)),
                DeliveryItem(selection=line_sel, primitives=(line_prim, full_circle)),
                DeliveryItem(selection=vec_sel, vector=polygon),
                DeliveryItem(
                    selection=vec_sel.model_copy(update={"id": "multi-vector-layer"}),
                    vector=multipolygon,
                ),
            ),
            "metrics": tuple(many_metrics),
        }
    )

    svg = render_delivery_svg(rich)
    assert 'data-layer-id="hidden-layer"' not in svg
    assert 'data-call-id="line-1"' in svg
    assert 'data-call-id="circle-1"' in svg
    assert "calc-0 | misclosure 0.0 ft | area 1000.0 sq ft" in svg
    assert "misclosure unavailable ft | area unavailable sq ft" in svg
    # Full circle splits into two SVG arcs.
    root = ET.fromstring(svg)
    circle_path = next(
        el.attrib["d"]
        for el in root.findall(".//{http://www.w3.org/2000/svg}path")
        if el.attrib.get("data-call-id") == "circle-1"
    )
    assert circle_path.count(" A ") == 2

    pdf_bytes = render_delivery_pdf(rich)
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 3
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "line-1" in full_text and "circle-1" in full_text

    dxf_doc = ezdxf.read(io.StringIO(render_delivery_dxf(rich).decode()))
    types = [e.dxftype() for e in dxf_doc.modelspace()]
    assert "LINE" in types
    assert "CIRCLE" in types
    assert "LWPOLYLINE" in types
    assert not any(e.dxf.layer.endswith("hidden-layer") for e in dxf_doc.modelspace())

    # All-hidden snapshot has no drawing bounds and raises ValueError.
    empty = base.model_copy(
        update={"items": (DeliveryItem(selection=hidden_sel, primitives=(line_prim,)),)}
    )
    with pytest.raises(ValueError, match="No drawing bounds"):
        render_delivery_svg(empty)

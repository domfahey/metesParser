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
    from mp_export.delivery import _label, _rows

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
    assert "bearing unavailable" in _label(value, primitive)
    selected = next(row for row in _rows(value) if "hypothetical input:" in row)
    assert "bearing unavailable" in selected
    assert "0.000000 deg" not in selected
    assert any("Original recorded input: 0.000000 deg" in row for row in _rows(value))


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

"""SVG, mature-library PDF and analytic CAD from one frozen review snapshot."""

from __future__ import annotations

import base64
import io
import math
import threading
from html import escape
from typing import Any

from mp_models.delivery import DeliveryPrimitive, DeliverySnapshot
from mp_models.plot import XY
from mp_verify.plot import unit_factor


def _presentation(snapshot: DeliverySnapshot, p: XY) -> XY:
    angle = math.radians(snapshot.request.presentation_rotation_deg)
    ox, oy = snapshot.request.presentation_pivot
    x, y = p[0] - ox, p[1] - oy
    return ox + x * math.cos(angle) + y * math.sin(angle), oy - x * math.sin(angle) + y * math.cos(
        angle
    )


def _context_factor(snapshot: DeliverySnapshot) -> float:
    native = snapshot.scene_units
    return (
        1.0
        if native is None or native == snapshot.request.units
        else float(unit_factor(native, snapshot.request.units))
    )


def _vector_rings(snapshot: DeliverySnapshot, vector: Any) -> list[tuple[XY, ...]]:
    factor = _context_factor(snapshot)
    polygons = (vector.coordinates,) if vector.geometry_type == "Polygon" else vector.coordinates
    return [
        tuple((p[0] * factor, p[1] * factor) for p in ring)
        for polygon in polygons
        for ring in polygon
    ]


def _raster_point(snapshot: DeliverySnapshot, raster: Any, pixel: XY) -> XY:
    a, b, c, d, e, f = raster.registration.matrix
    factor = _context_factor(snapshot)
    return (a * pixel[0] + b * pixel[1] + c) * factor, (d * pixel[0] + e * pixel[1] + f) * factor


def _bounds(snapshot: DeliverySnapshot) -> tuple[float, float, float, float]:
    points: list[XY] = []
    for item in snapshot.items:
        if not item.selection.visible:
            continue
        for primitive in item.primitives:
            points.extend(
                (_presentation(snapshot, primitive.start), _presentation(snapshot, primitive.end))
            )
            if primitive.center and primitive.radius:
                cx, cy = _presentation(snapshot, primitive.center)
                points.extend(
                    (
                        (cx - primitive.radius, cy - primitive.radius),
                        (cx + primitive.radius, cy + primitive.radius),
                    )
                )
        if item.vector:
            points.extend(
                _presentation(snapshot, p)
                for ring in _vector_rings(snapshot, item.vector)
                for p in ring
            )
        if item.raster:
            raster = item.raster
            points.extend(
                _presentation(snapshot, _raster_point(snapshot, raster, p))
                for p in (
                    (-0.5, -0.5),
                    (raster.width - 0.5, -0.5),
                    (raster.width - 0.5, raster.height - 0.5),
                    (-0.5, raster.height - 0.5),
                )
            )
    if not points:
        raise ValueError("No drawing bounds")
    lo_x, hi_x = min(p[0] for p in points), max(p[0] for p in points)
    lo_y, hi_y = min(p[1] for p in points), max(p[1] for p in points)
    pad = max(hi_x - lo_x, hi_y - lo_y, 1.0) * (0.4 if snapshot.request.labels else 0.12)
    return lo_x - pad, lo_y - pad, max(hi_x - lo_x, 1.0) + 2 * pad, max(hi_y - lo_y, 1.0) + 2 * pad


def _selected_values(p: DeliveryPrimitive) -> tuple[float | None, float | None]:
    bearing, distance = p.selected_bearing_deg, p.selected_distance_ft
    if p.input_status == "recorded":
        bearing = p.recorded_bearing_deg if bearing is None else bearing
        distance = p.recorded_distance_ft if distance is None else distance
    return bearing, distance


def _label(snapshot: DeliverySnapshot, p: DeliveryPrimitive) -> str:
    bearing, distance = _selected_values(p)
    values = []
    for field in snapshot.request.labels:
        if field == "course":
            values.append(p.call_id)
        elif field == "bearing":
            values.append(
                "bearing unavailable" if bearing is None else f"{bearing:.6f} deg {p.input_status}"
            )
        else:
            values.append(
                "distance unavailable" if distance is None else f"{distance:g} ft {p.input_status}"
            )
    return " | ".join(values)


def _rows(snapshot: DeliverySnapshot) -> list[str]:
    rows = []
    for item in snapshot.items:
        for p in item.primitives:
            selected_bearing_value, selected_distance_value = _selected_values(p)
            bearing = (
                "unavailable"
                if p.recorded_bearing_deg is None
                else f"{p.recorded_bearing_deg:.6f} deg"
            )
            distance = (
                "unavailable"
                if p.recorded_distance_ft is None
                else f"{p.recorded_distance_ft:g} ft"
            )
            selected_bearing = (
                f"{selected_bearing_value:.6f} deg"
                if selected_bearing_value is not None
                else "bearing unavailable"
            )
            selected_distance = (
                f"{selected_distance_value:g} ft"
                if selected_distance_value is not None
                else "distance unavailable"
            )
            rows.append(
                f"{item.selection.id} / {p.call_id}  {p.kind}  {p.input_status} input: {selected_bearing}; {selected_distance}"
            )
            if p.input_status != "recorded":
                rows.append(f"  Original recorded input: {bearing}; {distance}")
    return rows


def _path(snapshot: DeliverySnapshot, primitive: DeliveryPrimitive) -> str:
    start, end = _presentation(snapshot, primitive.start), _presentation(snapshot, primitive.end)
    output = f"M {start[0]:.17g} {-start[1]:.17g} "
    if primitive.kind == "line":
        return output + f"L {end[0]:.17g} {-end[1]:.17g}"
    assert primitive.radius is not None and primitive.sweep_deg is not None and primitive.center
    sweep = int(primitive.curve_dir == "right")
    if primitive.sweep_deg == 360:
        center = _presentation(snapshot, primitive.center)
        middle = 2 * center[0] - start[0], 2 * center[1] - start[1]
        output += f"A {primitive.radius:.17g} {primitive.radius:.17g} 0 0 {sweep} {middle[0]:.17g} {-middle[1]:.17g} "
    return (
        output
        + f"A {primitive.radius:.17g} {primitive.radius:.17g} 0 {int(primitive.sweep_deg > 180 and primitive.sweep_deg != 360)} {sweep} {end[0]:.17g} {-end[1]:.17g}"
    )


def render_delivery_svg(snapshot: DeliverySnapshot) -> str:
    x, y, width, height = _bounds(snapshot)
    rows = _rows(snapshot)
    drawing_height = 520
    total_height = 650 + 22 * len(rows) + 22 * len(snapshot.metrics)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="{total_height}" viewBox="0 0 1100 {total_height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f"<title>Review package {escape(snapshot.request.id)} - {escape(snapshot.request.revision_id)}</title>",
        f'<text x="30" y="30" font-size="20">{escape(snapshot.request.id)} | revision {escape(snapshot.request.revision_id)}</text>',
        f'<text x="30" y="53" font-size="12">{snapshot.request.geometry} | {snapshot.request.coordinate_mode} | {snapshot.request.units} | advisory; verification not requested</text>',
        f'<svg x="30" y="70" width="1040" height="{drawing_height}" viewBox="{x:.17g} {-y - height:.17g} {width:.17g} {height:.17g}" preserveAspectRatio="xMidYMid meet">',
    ]
    font = max(width, height) / 120
    stroke = max(width, height) / 700
    for item in snapshot.items:
        if not item.selection.visible:
            continue
        out.append(
            f'<g data-layer-id="{escape(item.selection.id)}" opacity="{item.selection.opacity:g}">'
        )
        if item.raster:
            r = item.raster
            a = _presentation(snapshot, _raster_point(snapshot, r, (-0.5, -0.5)))
            b = _presentation(snapshot, _raster_point(snapshot, r, (0.5, -0.5)))
            c = _presentation(snapshot, _raster_point(snapshot, r, (-0.5, 0.5)))
            out.append(
                f'<image width="{r.width}" height="{r.height}" href="data:{r.mime_type};base64,{r.data_base64}" transform="matrix({b[0] - a[0]:.17g} {a[1] - b[1]:.17g} {c[0] - a[0]:.17g} {a[1] - c[1]:.17g} {a[0]:.17g} {-a[1]:.17g})"/>'
            )
        if item.vector:
            for ring in _vector_rings(snapshot, item.vector):
                points = [_presentation(snapshot, p) for p in ring]
                out.append(
                    '<path fill="none" stroke="#6b7280" stroke-width="'
                    + str(stroke)
                    + '" d="M '
                    + " L ".join(f"{p[0]:.17g} {-p[1]:.17g}" for p in points)
                    + ' Z"/>'
                )
        for p in item.primitives:
            out.append(
                f'<path data-call-id="{escape(p.call_id)}" d="{_path(snapshot, p)}" fill="none" stroke="#17556e" stroke-width="{stroke:g}"/>'
            )
            if snapshot.request.labels:
                position = _presentation(
                    snapshot, ((p.start[0] + p.end[0]) / 2, (p.start[1] + p.end[1]) / 2)
                )
                out.append(
                    f'<text x="{position[0]:.17g}" y="{-position[1]:.17g}" font-size="{font:g}" text-anchor="middle" fill="#172f3c">{escape(_label(snapshot, p))}</text>'
                )
        out.append("</g>")
    out.append("</svg>")
    top = 620
    for row in rows:
        out.append(f'<text x="30" y="{top}" font-size="12">{escape(row)}</text>')
        top += 22
    for metric in snapshot.metrics:
        out.append(
            f'<text x="30" y="{top}" font-size="12">{escape(metric.calculation_id)} | misclosure {metric.misclosure_ft if metric.misclosure_ft is not None else "unavailable"} ft | area {metric.area_sq_ft if metric.area_sq_ft is not None else "unavailable"} sq ft</text>'
        )
        top += 22
    out.append("</svg>")
    return "\n".join(out)


def render_delivery_pdf(snapshot: DeliverySnapshot) -> bytes:
    from reportlab.lib.utils import ImageReader, simpleSplit  # type: ignore[import-untyped]
    from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]

    stream = io.BytesIO()
    canvas = Canvas(stream, pagesize=(792, 612), invariant=1, pageCompression=1)
    canvas.setTitle(f"Review {snapshot.request.id} - {snapshot.request.revision_id}")
    canvas.setAuthor("MetesParser deterministic review delivery")

    def header() -> None:
        canvas.setFillColorRGB(0.08, 0.16, 0.22)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawString(
            30, 580, f"{snapshot.request.id} | revision {snapshot.request.revision_id}"
        )
        canvas.setFont("Helvetica", 9)
        canvas.drawString(
            30,
            562,
            f"{snapshot.request.geometry} | {snapshot.request.coordinate_mode} | {snapshot.request.units} | advisory - verification not requested",
        )
        canvas.drawString(
            30, 18, f"Request {snapshot.request_sha256[:32]} | page {canvas.getPageNumber()}"
        )

    header()
    x, y, width, height = _bounds(snapshot)
    scale = min(732 / width, 350 / height)
    canvas.saveState()
    canvas.translate(30 + (732 - width * scale) / 2, 205 + (350 - height * scale) / 2)
    canvas.scale(scale, scale)
    canvas.translate(-x, -y)
    for item in snapshot.items:
        if not item.selection.visible:
            continue
        canvas.saveState()
        canvas.setStrokeAlpha(item.selection.opacity)
        canvas.setFillAlpha(item.selection.opacity)
        canvas.setLineWidth(1 / scale)
        if item.raster:
            r = item.raster
            a = _presentation(snapshot, _raster_point(snapshot, r, (-0.5, r.height - 0.5)))
            b = _presentation(snapshot, _raster_point(snapshot, r, (r.width - 0.5, r.height - 0.5)))
            c = _presentation(snapshot, _raster_point(snapshot, r, (-0.5, -0.5)))
            canvas.saveState()
            canvas.transform(b[0] - a[0], b[1] - a[1], c[0] - a[0], c[1] - a[1], a[0], a[1])
            canvas.drawImage(
                ImageReader(io.BytesIO(base64.b64decode(r.data_base64))),
                0,
                0,
                width=1,
                height=1,
                mask="auto",
            )
            canvas.restoreState()
        if item.vector:
            canvas.setStrokeColorRGB(0.42, 0.45, 0.49)
            for ring in _vector_rings(snapshot, item.vector):
                path = canvas.beginPath()
                for index, point in enumerate(ring):
                    vertex = _presentation(snapshot, point)
                    (path.moveTo if index == 0 else path.lineTo)(*vertex)
                path.close()
                canvas.drawPath(path, stroke=1, fill=0)
        canvas.setStrokeColorRGB(0.09, 0.33, 0.43)
        for p in item.primitives:
            a, b = _presentation(snapshot, p.start), _presentation(snapshot, p.end)
            if p.kind == "line":
                canvas.line(*a, *b)
            else:
                assert p.center and p.radius and p.sweep_deg
                center = _presentation(snapshot, p.center)
                start_angle = math.degrees(math.atan2(a[1] - center[1], a[0] - center[0]))
                extent = p.sweep_deg if p.curve_dir == "left" else -p.sweep_deg
                canvas.arc(
                    center[0] - p.radius,
                    center[1] - p.radius,
                    center[0] + p.radius,
                    center[1] + p.radius,
                    startAng=start_angle,
                    extent=extent,
                )
            if snapshot.request.labels:
                canvas.setFont("Helvetica", 6 / scale)
                canvas.drawCentredString((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, _label(snapshot, p))
        canvas.restoreState()
    canvas.restoreState()
    top = 187
    for row in _rows(snapshot) + [
        f"{m.calculation_id}: misclosure {m.misclosure_ft if m.misclosure_ft is not None else 'unavailable'} ft; area {m.area_sq_ft if m.area_sq_ft is not None else 'unavailable'} sq ft"
        for m in snapshot.metrics
    ]:
        if top < 40:
            canvas.showPage()
            header()
            top = 540
        canvas.setFont("Helvetica", 8)
        for line in simpleSplit(row, "Helvetica", 8, 732):
            if top < 40:
                canvas.showPage()
                header()
                top = 540
                canvas.setFont("Helvetica", 8)
            canvas.drawString(30, top, line)
            top -= 15
    canvas.save()
    return stream.getvalue()


def _render_delivery_dxf(snapshot: DeliverySnapshot) -> bytes:
    import ezdxf

    document = ezdxf.new("R2010")  # type: ignore[attr-defined]
    document.header["$INSUNITS"] = {
        "m": 6,
        "international_ft": 2,
        "us_survey_ft": 21,
        "unknown_ft": 0,
    }[snapshot.request.units]
    document.header["$MEASUREMENT"] = int(snapshot.request.units == "m")
    document.header["$TDCREATE"] = 2451545.0
    document.header["$TDUPDATE"] = 2451545.0
    document.header["$FINGERPRINTGUID"] = "{" + snapshot.request_sha256[:32].upper() + "}"
    document.header["$VERSIONGUID"] = "{" + snapshot.request_sha256[32:].upper() + "}"
    document.appids.new("METESPARSER")
    model = document.modelspace()
    for index, item in enumerate(snapshot.items):
        if not item.selection.visible:
            continue
        name = f"L{index:03d}_{item.selection.id.replace(':', '_')}"
        document.layers.new(name, dxfattribs={"color": 7})

        def identify(entity: Any, call_id: str, selected: Any = item.selection) -> None:
            entity.set_xdata(
                "METESPARSER",
                [
                    (1000, call_id),
                    (1000, selected.id),
                    (1000, snapshot.request.revision_id),
                    (1000, snapshot.request_sha256),
                ],
            )
            entity.transparency = 1 - selected.opacity

        entity: Any
        for p in item.primitives:
            attributes = {"layer": name}
            if p.kind == "line":
                entity = model.add_line(p.start, p.end, dxfattribs=attributes)
            else:
                assert p.center and p.radius and p.sweep_deg
                if p.sweep_deg == 360:
                    entity = model.add_circle(p.center, p.radius, dxfattribs=attributes)
                else:
                    a, b = (p.start, p.end) if p.curve_dir == "left" else (p.end, p.start)
                    angles = [
                        math.degrees(math.atan2(q[1] - p.center[1], q[0] - p.center[0])) % 360
                        for q in (a, b)
                    ]
                    entity = model.add_arc(
                        p.center,
                        p.radius,
                        start_angle=angles[0],
                        end_angle=angles[1],
                        dxfattribs=attributes,
                    )
            identify(entity, p.call_id)
            entity.set_xdata(
                "METESPARSER",
                entity.get_xdata("METESPARSER")
                + [(1000, p.curve_dir or "line"), (1000, p.input_status)]
                + (
                    [(1000, "original_recorded_bearing_deg"), (1040, p.recorded_bearing_deg)]
                    if p.recorded_bearing_deg is not None
                    else []
                )
                + (
                    [(1000, "selected_bearing_deg"), (1040, p.selected_bearing_deg)]
                    if p.selected_bearing_deg is not None
                    else []
                )
                + (
                    [(1000, "original_recorded_distance_ft"), (1040, p.recorded_distance_ft)]
                    if p.recorded_distance_ft is not None
                    else []
                )
                + (
                    [(1000, "selected_distance_ft"), (1040, p.selected_distance_ft)]
                    if p.selected_distance_ft is not None
                    else []
                ),
            )
        if item.vector:
            for ring in _vector_rings(snapshot, item.vector):
                entity = model.add_lwpolyline(ring[:-1], close=True, dxfattribs={"layer": name})
                identify(entity, item.vector.id)
    # The writer discovers classes by iterating a set of entity types. Register
    # them in a stable order first so publication can replay in another process.
    for entity_type in sorted(document.entitydb.dxf_types_in_use()):
        document.classes.add_class(entity_type)
    output = io.StringIO()
    document.write(output)
    return output.getvalue().encode("utf-8")


_DXF_LOCK = threading.RLock()


def render_delivery_dxf(snapshot: DeliverySnapshot) -> bytes:
    # ezdxf's documented option suppresses volatile GUID/time metadata. Serialize
    # this short option scope and restore it even when output generation fails.

    from ezdxf._options import options

    with _DXF_LOCK:
        original = options.write_fixed_meta_data_for_testing
        options.write_fixed_meta_data_for_testing = True
        try:
            return _render_delivery_dxf(snapshot)
        finally:
            options.write_fixed_meta_data_for_testing = original

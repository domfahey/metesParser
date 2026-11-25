"""Ground truth review packet generator.

Produces self-contained HTML review worksheets from ground truth JSON files
so attorneys or surveyors can verify parsed data against source deed PDFs.
"""

from __future__ import annotations

import html as html_mod
import json
import math
from pathlib import Path
from typing import Any

# Ground truth data is unstructured JSON — use a type alias for clarity.
GroundTruth = dict[str, Any]

_REQUIRED_KEYS = {
    "deed_info",
    "expected_calls",
    "expected_closure",
    "expected_legal_description",
    "expected_pob",
    "raw_ocr_text",
}


def load_ground_truth(path: Path) -> GroundTruth:
    """Load and validate a ground truth JSON file.

    Args:
        path: Path to a .ground_truth.json file.

    Returns:
        Parsed ground truth dict.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the JSON is malformed or missing required keys.
    """
    if not path.exists():
        raise FileNotFoundError(f"Ground truth file not found: {path}")

    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Ground truth JSON in {path} must be an object, got {type(data).__name__}"
        )

    missing = _REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys in {path}: {sorted(missing)}")

    result: GroundTruth = data
    return result


def _esc(value: object) -> str:
    """HTML-escape a value, converting None to empty string."""
    if value is None:
        return ""
    return html_mod.escape(str(value))


def build_metadata_section(gt: GroundTruth, source_pdf: str) -> str:
    """Build HTML metadata header from ground truth deed_info.

    Args:
        gt: Parsed ground truth dict.
        source_pdf: Filename of the source PDF.

    Returns:
        HTML string for the metadata section.
    """
    raw_info = gt.get("deed_info")
    info = raw_info if isinstance(raw_info, dict) else {}
    parts: list[str] = []
    parts.append("<div class='metadata'>")
    parts.append(f"<h1>{_esc(info.get('address') or 'Unknown Address')}</h1>")
    parts.append("<table class='meta-table'>")
    parts.append(f"<tr><th>Source PDF</th><td>{_esc(source_pdf)}</td></tr>")
    parts.append(
        f"<tr><th>Book / Page</th><td>{_esc(info.get('book'))} / {_esc(info.get('page'))}</td></tr>"
    )
    parts.append(
        f"<tr><th>Location</th><td>{_esc(info.get('city'))}, {_esc(info.get('state'))}</td></tr>"
    )
    if info.get("parcel_shape"):
        parts.append(f"<tr><th>Parcel Shape</th><td>{_esc(info['parcel_shape'])}</td></tr>")
    if info.get("dimensions"):
        parts.append(f"<tr><th>Dimensions</th><td>{_esc(info['dimensions'])}</td></tr>")
    parts.append("</table>")
    parts.append("</div>")
    return "\n".join(parts)


# Column definitions for the call review table.
_CALL_COLUMNS = [
    ("Course", "course"),
    ("Direction Text", "direction_text"),
    ("Bearing Quadrant", "bearing_quadrant"),
    ("Azimuth", "bearing_azimuth_deg_from_north"),
    ("Distance (ft)", "distance_ft"),
    ("Curve Dir", "curve_dir"),
    ("Radius (ft)", "radius_ft"),
    ("Delta (deg)", "delta_deg"),
    ("Arc Length (ft)", "arc_length_ft"),
    ("Along", "along"),
    ("To", "to"),
    ("Monument", "monument_type"),
    ("Notes", "notes"),
    ("Chord Bearing", "chord_bearing"),
    ("Chord Length (ft)", "chord_length_ft"),
    ("Curve Type", "curve_type"),
    ("Radial Bearing", "radial_bearing"),
    ("Non-Tangent", "non_tangent"),
    ("Monument Status", "monument_status"),
    ("Exception", "is_exception"),
    ("Meander", "is_meander"),
    ("Tie-In", "is_tie_in"),
]


def build_call_table(gt: GroundTruth) -> str:
    """Build HTML review table for expected calls.

    Includes reviewer columns (Correct?, Reviewer Notes) for marking
    during professional audit.

    Args:
        gt: Parsed ground truth dict.

    Returns:
        HTML string for the call table section.
    """
    calls = gt.get("expected_calls") or []
    parts: list[str] = []
    parts.append("<div class='call-table-section'>")
    parts.append("<h2>Call-by-Call Review</h2>")
    parts.append("<table class='call-table'>")

    # Header row
    parts.append("<tr>")
    for label, _ in _CALL_COLUMNS:
        parts.append(f"<th>{label}</th>")
    parts.append("<th>Correct?</th>")
    parts.append("<th>Reviewer Notes</th>")
    parts.append("</tr>")

    # Data rows
    for call in calls:
        parts.append("<tr>")
        for _, key in _CALL_COLUMNS:
            val = call.get(key)
            parts.append(f"<td>{_esc(val)}</td>")
        parts.append("<td></td>")  # Correct? — blank for reviewer
        parts.append("<td></td>")  # Reviewer Notes — blank for reviewer
        parts.append("</tr>")

    parts.append("</table>")
    parts.append("</div>")
    return "\n".join(parts)


def build_closure_section(gt: GroundTruth) -> str:
    """Build HTML section for closure/verification data.

    Args:
        gt: Parsed ground truth dict.

    Returns:
        HTML string for the closure section.
    """
    closure = gt.get("expected_closure") or {}
    assertions = gt.get("critical_assertions") or {}
    parts: list[str] = []
    parts.append("<div class='closure-section'>")
    parts.append("<h2>Closure Verification</h2>")
    parts.append("<table class='closure-table'>")

    # Status row
    passed = closure.get("closure_passed")
    if passed is True:
        status_label, status_css = "PASS", "pass"
    elif passed is False:
        status_label, status_css = "FAIL", "fail"
    else:
        status_label, status_css = "N/A", "na"
    parts.append(
        f"<tr><th>Closure Status</th>"
        f"<td class='{status_css}'><strong>{status_label}</strong></td>"
        f"<td>Correct?</td><td></td></tr>"
    )

    # Metric rows
    _closure_fields = [
        ("Misclosure (ft)", "misclosure_ft"),
        ("Area (sq ft)", "area_sq_ft"),
        ("Area (acres)", "area_acres"),
        ("Perimeter (ft)", "perimeter_ft"),
    ]
    for label, key in _closure_fields:
        val = closure.get(key)
        if (
            (key == "misclosure_ft" and closure.get("misclosure_available") is False)
            or (key == "perimeter_ft" and closure.get("perimeter_available") is False)
            or (key in ("area_sq_ft", "area_acres") and closure.get("area_available") is False)
        ):
            display = "not determined"
        else:
            display = _esc(val) if val is not None else "N/A"
        parts.append(f"<tr><th>{label}</th><td>{display}</td><td>Correct?</td><td></td></tr>")

    parts.append("</table>")

    # Critical assertions
    if assertions:
        parts.append("<h3>Critical Assertions</h3>")
        parts.append("<table class='assertions-table'>")
        parts.append("<tr><th>Assertion</th><th>Expected</th><th>Description</th></tr>")
        for name, assertion in assertions.items():
            if isinstance(assertion, dict):
                expected = assertion.get("expected")
                desc = assertion.get("description", "")
            else:
                expected = assertion
                desc = ""
            parts.append(
                f"<tr><td>{_esc(name)}</td><td>{_esc(expected)}</td><td>{_esc(desc)}</td></tr>"
            )
        parts.append("</table>")

    parts.append("</div>")
    return "\n".join(parts)


def build_text_comparison(gt: GroundTruth) -> str:
    """Build HTML section for side-by-side text comparison.

    Shows raw OCR text, expected legal description, and normalized text
    for reviewer to verify faithful transcription.

    Args:
        gt: Parsed ground truth dict.

    Returns:
        HTML string for the text comparison section.
    """
    parts: list[str] = []
    parts.append("<div class='text-comparison'>")
    parts.append("<h2>Text Comparison</h2>")

    # POB / POC
    poc = gt.get("expected_poc")
    pob = gt.get("expected_pob")
    parts.append("<div class='pob-section'>")
    if poc:
        parts.append(f"<p><strong>Point of Commencement:</strong> {_esc(poc)}</p>")
    parts.append(f"<p><strong>Point of Beginning:</strong> {_esc(pob)}</p>")
    parts.append("</div>")

    # Side-by-side panels
    parts.append("<div class='text-panels'>")

    # Raw OCR
    parts.append("<div class='text-panel'>")
    parts.append("<h3>Raw OCR Text</h3>")
    parts.append(f"<pre class='text-block'>{_esc(gt.get('raw_ocr_text'))}</pre>")
    parts.append("</div>")

    # Expected legal description
    parts.append("<div class='text-panel'>")
    parts.append("<h3>Expected Legal Description</h3>")
    parts.append(f"<pre class='text-block'>{_esc(gt.get('expected_legal_description'))}</pre>")
    parts.append("</div>")

    # Normalized text
    normalized = gt.get("expected_normalized_text")
    parts.append("<div class='text-panel'>")
    parts.append("<h3>Normalized Text</h3>")
    if normalized:
        parts.append(f"<pre class='text-block'>{_esc(normalized)}</pre>")
    else:
        parts.append("<p class='na'>N/A</p>")
    parts.append("</div>")

    parts.append("</div>")  # text-panels
    parts.append("</div>")  # text-comparison
    return "\n".join(parts)


def _as_bool(value: Any) -> bool:
    """Coerce JSON boolean or string-encoded boolean values to bool."""
    from mp_models import coerce_bool_field

    try:
        return coerce_bool_field(value)
    except ValueError as exc:
        raise ValueError(f"Invalid boolean value: {value!r}") from exc


def _is_curve_call(call: dict[str, Any]) -> bool:
    """Return True if a call dictionary carries curve-specific fields."""
    return any(
        call.get(key) is not None
        for key in (
            "curve_dir",
            "radius_ft",
            "delta_deg",
            "arc_length_ft",
            "chord_bearing",
            "chord_length_ft",
            "curve_type",
            "radial_bearing",
        )
    ) or _as_bool(call.get("non_tangent"))


def generate_traverse_plot(gt: GroundTruth) -> str:
    """Generate an SVG traverse plot from ground truth calls.

    Produces a pure-SVG diagram (no external dependencies) showing the
    closed traverse with labeled course numbers. Includes a north arrow.

    Args:
        gt: Parsed ground truth dict.

    Returns:
        SVG string if plottable calls exist, otherwise an HTML message.
    """
    from mp_models import DeedCall, Point
    from mp_verify.tangents import curve_sweep, entry_azimuth
    from mp_verify.traverse import analyze_courses
    from pydantic import ValidationError

    calls = gt.get("expected_calls") or []
    # A boundary call without usable geometry (or with an invalid boolean flag)
    # breaks the traverse. Dropping it would falsely connect the calls on either
    # side of the gap.
    boundary_calls: list[dict[str, Any]] = []
    invalid_courses: list[str] = []
    for raw_index, c in enumerate(calls, start=1):
        course_label = str(c.get("course", raw_index))
        try:
            is_tie_in = _as_bool(c.get("is_tie_in"))
            is_exception = _as_bool(c.get("is_exception"))
        except ValueError:
            invalid_courses.append(course_label)
            continue
        if not is_tie_in and not is_exception:
            boundary_calls.append(c)

    if not boundary_calls and not invalid_courses:
        return "<p class='na'>No plottable calls (cannot generate traverse plot).</p>"

    # (dx, dy, svg_cmd, dist_label, label_offset, arc_bbox_offsets, mid_offset)
    segments: list[
        tuple[
            float,
            float,
            str,
            float,
            tuple[float, float] | None,
            list[tuple[float, float]],
            tuple[float, float] | None,
        ]
    ] = []
    origin = Point(x=0.0, y=0.0)

    for index, call in enumerate(boundary_calls, start=1):
        course_label = str(call.get("course", index))
        try:
            is_curve = _is_curve_call(call)
        except ValueError:
            invalid_courses.append(course_label)
            continue
        if is_curve:
            try:
                deed_call = DeedCall(
                    course=index,
                    direction_text=str(call.get("direction_text") or "curve"),
                    bearing_quadrant=call.get("bearing_quadrant"),
                    bearing_azimuth_deg_from_north=call.get("bearing_azimuth_deg_from_north"),
                    distance_ft=call.get("distance_ft"),
                    curve_dir=call.get("curve_dir"),
                    radius_ft=call.get("radius_ft"),
                    delta_deg=call.get("delta_deg"),
                    arc_length_ft=call.get("arc_length_ft"),
                    chord_bearing=call.get("chord_bearing"),
                    chord_length_ft=call.get("chord_length_ft"),
                    non_tangent=_as_bool(call.get("non_tangent", False)),
                    radial_bearing=call.get("radial_bearing"),
                    curve_type=call.get("curve_type"),
                )
            except (ValidationError, ValueError, TypeError):
                invalid_courses.append(course_label)
                continue

            pts, records = analyze_courses([deed_call], start_point=origin)
            record = records[0]
            if not record.positioned or len(pts) < 2:
                invalid_courses.append(course_label)
                continue

            dx = pts[1].x
            dy = -pts[1].y  # negate for SVG y-axis
            sweep_deg = curve_sweep(deed_call)
            if (
                not record.arc_undetermined
                and sweep_deg is not None
                and deed_call.radius_ft is not None
                and deed_call.curve_dir in ("left", "right")
                and deed_call.curve_type != "spiral"
            ):
                radius = deed_call.radius_ft
                dir_sign = 1.0 if deed_call.curve_dir == "right" else -1.0
                sweep_flag = 1 if dir_sign > 0 else 0
                sweep_rad = math.radians(sweep_deg)
                dist_label = deed_call.arc_length_ft or (radius * sweep_rad)
                chord = math.hypot(dx, dy)
                arc_offsets: list[tuple[float, float]] = []
                label_offset: tuple[float, float] | None = None
                mid_offset: tuple[float, float] | None = None
                split_arc = sweep_deg >= 360.0 - 1e-6 or (sweep_deg > 180.0 and chord < 0.05)
                center: tuple[float, float] | None = None
                if split_arc:
                    t_deg = entry_azimuth(deed_call)
                    if t_deg is None:
                        invalid_courses.append(course_label)
                        continue
                    t_rad = math.radians(t_deg)
                    center = (
                        dir_sign * radius * math.cos(t_rad),
                        dir_sign * radius * math.sin(t_rad),
                    )
                    cmd = f"A {radius:.2f},{radius:.2f} 0 0,{sweep_flag}"
                else:
                    large_arc = 1 if sweep_deg > 180.0 else 0
                    cmd = f"A {radius:.2f},{radius:.2f} 0 {large_arc},{sweep_flag}"
                    if chord > 1e-9:
                        # SVG y-down coordinates: left-hand normal to (dx, dy) is (dy/c, -dx/c).
                        # For sweep_flag=1 ("right", clockwise in SVG), center is on the right side
                        # (-nx, -ny) for minor arcs and switches sign via cos(sweep/2) for major arcs.
                        h = radius * math.cos(sweep_rad / 2.0)
                        center = (
                            dx / 2.0 - dir_sign * (dy / chord) * h,
                            dy / 2.0 + dir_sign * (dx / chord) * h,
                        )
                if center is not None:
                    cx, cy = center
                    start_angle = math.atan2(-cy, -cx)
                    mid_angle = start_angle + dir_sign * (sweep_rad / 2.0)
                    label_offset = (
                        cx + radius * math.cos(mid_angle),
                        cy + radius * math.sin(mid_angle),
                    )
                    if split_arc:
                        mid_offset = label_offset
                    arc_offsets.append(label_offset)
                    # Include every cardinal extremum angle traversed by the rendered arc
                    lo = min(start_angle, start_angle + dir_sign * sweep_rad)
                    hi = max(start_angle, start_angle + dir_sign * sweep_rad)
                    k_start = math.ceil(lo / (math.pi / 2.0))
                    k_end = math.floor(hi / (math.pi / 2.0))
                    for k in range(k_start, k_end + 1):
                        theta = k * (math.pi / 2.0)
                        arc_offsets.append(
                            (cx + radius * math.cos(theta), cy + radius * math.sin(theta))
                        )
                segments.append((dx, dy, cmd, dist_label, label_offset, arc_offsets, mid_offset))
            else:
                dist_label = deed_call.chord_length_ft or math.hypot(dx, dy)
                segments.append((dx, dy, "L", dist_label, None, [], None))
            continue

        azimuth = call.get("bearing_azimuth_deg_from_north")
        distance = call.get("distance_ft")
        if (
            not isinstance(azimuth, (int, float))
            or isinstance(azimuth, bool)
            or not math.isfinite(azimuth)
            or not (0 <= azimuth <= 360)
            or not isinstance(distance, (int, float))
            or isinstance(distance, bool)
            or not math.isfinite(distance)
            or distance < 0
        ):
            invalid_courses.append(course_label)
            continue
        azimuth_rad = math.radians(azimuth)
        dx = distance * math.sin(azimuth_rad)
        dy = -distance * math.cos(azimuth_rad)  # negate for SVG y-axis
        segments.append((dx, dy, "L", float(distance), None, [], None))

    if invalid_courses:
        courses = ", ".join(_esc(course) for course in invalid_courses)
        return (
            "<p class='na'>Incomplete traverse plot (cannot generate plot): "
            "missing or invalid geometry "
            f"for course(s) {courses}.</p>"
        )

    # Compute traverse points (azimuth is clockwise from north)
    # SVG: x = east, y = south (so we negate y for north-up)
    points: list[tuple[float, float]] = [(0.0, 0.0)]
    bbox_points: list[tuple[float, float]] = [(0.0, 0.0)]
    for dx, dy, _, _, _, arc_offsets, _ in segments:
        last = points[-1]
        for ox, oy in arc_offsets:
            bbox_points.append((last[0] + ox, last[1] + oy))
        nxt = (last[0] + dx, last[1] + dy)
        points.append(nxt)
        bbox_points.append(nxt)

    # Compute bounding box with padding
    xs = [p[0] for p in bbox_points]
    ys = [p[1] for p in bbox_points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max_x - min_x
    span_y = max_y - min_y
    width = span_x if span_x > 1e-6 else 1.0
    height = span_y if span_y > 1e-6 else 1.0
    pad = max(width, height) * 0.15
    vb_x = min_x - pad
    vb_y = min_y - pad
    vb_w = width + 2 * pad
    vb_h = height + 2 * pad

    parts: list[str] = []
    parts.append(
        f"<svg xmlns='http://www.w3.org/2000/svg' "
        f"viewBox='{vb_x:.2f} {vb_y:.2f} {vb_w:.2f} {vb_h:.2f}' "
        f"width='600' height='500' "
        f"style='background:#fafafa;border:1px solid #dee2e6;border-radius:8px'>"
    )

    # Traverse path
    path_parts = [f"M {points[0][0]:.2f},{points[0][1]:.2f}"]
    for i, (_, _, cmd, _, _, _, mid_offset) in enumerate(segments):
        p = points[i + 1]
        if mid_offset is not None:
            mx = points[i][0] + mid_offset[0]
            my = points[i][1] + mid_offset[1]
            path_parts.append(f"{cmd} {mx:.2f},{my:.2f} {cmd} {p[0]:.2f},{p[1]:.2f}")
        else:
            path_parts.append(f"{cmd} {p[0]:.2f},{p[1]:.2f}")
    closed = math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1]) < 0.01
    if closed:
        path_parts.append("Z")
    path_d = " ".join(path_parts)
    fill = "#e8f4f8" if closed else "none"
    parts.append(
        f"<path d='{path_d}' fill='{fill}' stroke='#2c3e50' "
        f"stroke-width='{max(vb_w, vb_h) * 0.005:.2f}'/>"
    )

    # Course labels at midpoints
    font_size = max(vb_w, vb_h) * 0.035
    for i, call in enumerate(boundary_calls):
        bulge = segments[i][4]
        if bulge is not None:
            mid_x = points[i][0] + bulge[0]
            mid_y = points[i][1] + bulge[1]
        else:
            mid_x = (points[i][0] + points[i + 1][0]) / 2
            mid_y = (points[i][1] + points[i + 1][1]) / 2
        label = _esc(f"#{call.get('course', i + 1)}")
        distance_text = f"{segments[i][3]:.1f}'"
        parts.append(
            f"<text x='{mid_x:.2f}' y='{mid_y:.2f}' "
            f"font-size='{font_size:.1f}' text-anchor='middle' "
            f"fill='#2c3e50' font-family='sans-serif'>"
            f"{label} {distance_text}</text>"
        )

    # Point markers
    r = max(vb_w, vb_h) * 0.008
    for p in points:
        parts.append(f"<circle cx='{p[0]:.2f}' cy='{p[1]:.2f}' r='{r:.2f}' fill='#e74c3c'/>")

    # POB label
    parts.append(
        f"<text x='{points[0][0]:.2f}' y='{points[0][1] - font_size:.2f}' "
        f"font-size='{font_size:.1f}' text-anchor='middle' "
        f"fill='#e74c3c' font-weight='bold' font-family='sans-serif'>POB</text>"
    )

    # North arrow (top-right corner)
    na_x = max_x + pad * 0.5
    na_y = min_y - pad * 0.3
    arrow_len = max(vb_w, vb_h) * 0.08
    parts.append(
        f"<line x1='{na_x:.2f}' y1='{na_y + arrow_len:.2f}' "
        f"x2='{na_x:.2f}' y2='{na_y:.2f}' "
        f"stroke='#333' stroke-width='{max(vb_w, vb_h) * 0.004:.2f}' "
        f"marker-end='url(#arrowhead)'/>"
    )
    parts.append(
        f"<text x='{na_x:.2f}' y='{na_y - font_size * 0.3:.2f}' "
        f"font-size='{font_size * 1.2:.1f}' text-anchor='middle' "
        f"fill='#333' font-weight='bold' font-family='sans-serif'>N</text>"
    )

    # Arrowhead marker definition
    parts.append(
        "<defs><marker id='arrowhead' markerWidth='10' markerHeight='7' "
        "refX='10' refY='3.5' orient='auto'>"
        "<polygon points='0 0, 10 3.5, 0 7' fill='#333'/>"
        "</marker></defs>"
    )

    parts.append("</svg>")
    return "\n".join(parts)


def _review_css() -> str:
    """Return embedded CSS for review packet HTML."""
    return (
        "body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; "
        "max-width: 1200px; margin: 0 auto; padding: 20px; background: #f8f9fa; color: #333; }\n"
        ".metadata { background: #2c3e50; color: white; padding: 20px; "
        "border-radius: 8px; margin-bottom: 20px; }\n"
        ".metadata h1 { margin: 0 0 12px 0; }\n"
        ".meta-table { width: auto; border-collapse: collapse; }\n"
        ".meta-table th { text-align: right; padding: 4px 12px 4px 0; color: #adb5bd; }\n"
        ".meta-table td { padding: 4px 0; }\n"
        "h2 { color: #2c3e50; border-bottom: 2px solid #dee2e6; padding-bottom: 8px; }\n"
        "h3 { color: #495057; }\n"
        ".call-table-section, .closure-section, .text-comparison, .plot-section "
        "{ background: white; border: 1px solid #dee2e6; border-radius: 8px; "
        "margin-bottom: 16px; padding: 16px; }\n"
        "table { width: 100%; border-collapse: collapse; margin-top: 8px; }\n"
        "th, td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #dee2e6; "
        "font-size: 0.9em; }\n"
        "th { background: #f8f9fa; font-weight: 600; }\n"
        ".call-table { font-size: 0.85em; }\n"
        ".call-table td, .call-table th { padding: 4px 6px; white-space: nowrap; }\n"
        ".call-table td:nth-child(10), .call-table td:nth-child(11), .call-table td:nth-child(13) "
        "{ white-space: normal; max-width: 200px; }\n"
        ".pass { color: #2d6a4f; font-weight: bold; }\n"
        ".fail { color: #842029; font-weight: bold; }\n"
        ".na { color: #6c757d; font-style: italic; }\n"
        ".text-panels { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }\n"
        ".text-panel h3 { margin-top: 0; font-size: 0.95em; }\n"
        ".text-block { background: #f8f9fa; padding: 12px; border-radius: 4px; "
        "white-space: pre-wrap; font-size: 0.8em; max-height: 400px; overflow-y: auto; "
        "border: 1px solid #dee2e6; }\n"
        ".pob-section { background: #fff3cd; padding: 12px; border-radius: 4px; "
        "margin-bottom: 12px; border-left: 4px solid #ffc107; }\n"
        ".plot-section svg { display: block; margin: 0 auto; }\n"
        "@media print { "
        "body { background: white; padding: 0; } "
        ".metadata { background: #333; } "
        ".text-panels { grid-template-columns: 1fr; } "
        ".text-block { max-height: none; overflow: visible; } "
        "table { page-break-inside: avoid; } "
        "}\n"
    )


def generate_review_html(gt: GroundTruth, source_pdf: str) -> str:
    """Generate a complete self-contained HTML review packet.

    Assembles all sections (metadata, text comparison, call table,
    closure, traverse plot) into a single printable HTML document.

    Args:
        gt: Parsed ground truth dict.
        source_pdf: Filename of the source PDF.

    Returns:
        Complete HTML document as string.
    """
    raw_info = gt.get("deed_info")
    info = raw_info if isinstance(raw_info, dict) else {}
    address = info.get("address") or "Unknown"
    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append("<html lang='en'>")
    parts.append("<head>")
    parts.append("<meta charset='utf-8'>")
    parts.append("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    parts.append(f"<title>Review Packet &mdash; {_esc(address)}</title>")
    parts.append("<style>")
    parts.append(_review_css())
    parts.append("</style>")
    parts.append("</head>")
    parts.append("<body>")

    parts.append(build_metadata_section(gt, source_pdf))
    parts.append(build_text_comparison(gt))
    parts.append(build_call_table(gt))
    parts.append(build_closure_section(gt))

    # Traverse plot
    parts.append("<div class='plot-section'>")
    parts.append("<h2>Traverse Plot</h2>")
    parts.append(generate_traverse_plot(gt))
    parts.append("</div>")

    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)


def generate_all_packets(source_dir: Path, output_dir: Path) -> list[Path]:
    """Generate review packets for all ground truth files in a directory.

    Args:
        source_dir: Directory containing .ground_truth.json files.
        output_dir: Directory to write HTML review packets to.

    Returns:
        List of paths to generated HTML files.
    """
    gt_files = sorted(source_dir.glob("*.ground_truth.json"))
    if not gt_files:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []
    for gt_path in gt_files:
        gt = load_ground_truth(gt_path)
        stem = gt_path.name.removesuffix(".ground_truth.json")
        # Derive source PDF name from GT filename
        source_pdf = f"{stem}.pdf"
        html_content = generate_review_html(gt, source_pdf)

        out_name = f"{stem}_review.html"
        out_path = output_dir / out_name
        out_path.write_text(html_content, encoding="utf-8")
        generated.append(out_path)

    return generated

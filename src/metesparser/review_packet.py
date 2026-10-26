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
    info = gt.get("deed_info", {})
    parts: list[str] = []
    parts.append("<div class='metadata'>")
    parts.append(f"<h1>{_esc(info.get('address', 'Unknown Address'))}</h1>")
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
    calls = gt.get("expected_calls", [])
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
    closure = gt.get("expected_closure", {})
    assertions = gt.get("critical_assertions", {})
    parts: list[str] = []
    parts.append("<div class='closure-section'>")
    parts.append("<h2>Closure Verification</h2>")
    parts.append("<table class='closure-table'>")

    # Status row
    passed = closure.get("closure_passed")
    status_label = "PASS" if passed else "FAIL"
    status_css = "pass" if passed else "fail"
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


def generate_traverse_plot(gt: GroundTruth) -> str:
    """Generate an SVG traverse plot from ground truth calls.

    Produces a pure-SVG diagram (no external dependencies) showing the
    closed traverse with labeled course numbers. Includes a north arrow.

    Args:
        gt: Parsed ground truth dict.

    Returns:
        SVG string if plottable calls exist, otherwise an HTML message.
    """
    calls = gt.get("expected_calls", [])

    if not calls:
        return "<p class='na'>No plottable calls (cannot generate traverse plot).</p>"

    # A boundary call without usable geometry breaks the traverse. Dropping it
    # would falsely connect the calls on either side of the gap.
    invalid_courses: list[str] = []
    for index, call in enumerate(calls, start=1):
        azimuth = call.get("bearing_azimuth_deg_from_north")
        distance = call.get("distance_ft")
        valid_azimuth = (
            isinstance(azimuth, (int, float))
            and not isinstance(azimuth, bool)
            and math.isfinite(azimuth)
            and 0 <= azimuth <= 360
        )
        valid_distance = (
            isinstance(distance, (int, float))
            and not isinstance(distance, bool)
            and math.isfinite(distance)
            and distance >= 0
        )
        if not (valid_azimuth and valid_distance):
            invalid_courses.append(str(call.get("course", index)))

    if invalid_courses:
        courses = ", ".join(_esc(course) for course in invalid_courses)
        return (
            "<p class='na'>Incomplete traverse plot (cannot generate plot): "
            "missing or invalid geometry "
            f"for course(s) {courses}.</p>"
        )

    plottable = calls

    # Compute traverse points (azimuth is clockwise from north)
    # SVG: x = east, y = south (so we negate y for north-up)
    points: list[tuple[float, float]] = [(0.0, 0.0)]
    for call in plottable:
        azimuth_rad = math.radians(call["bearing_azimuth_deg_from_north"])
        dist = call["distance_ft"]
        dx = dist * math.sin(azimuth_rad)
        dy = -dist * math.cos(azimuth_rad)  # negate for SVG y-axis
        last = points[-1]
        points.append((last[0] + dx, last[1] + dy))

    # Compute bounding box with padding
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = max_x - min_x or 1.0
    height = max_y - min_y or 1.0
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
    path_d = f"M {points[0][0]:.2f},{points[0][1]:.2f}"
    for p in points[1:]:
        path_d += f" L {p[0]:.2f},{p[1]:.2f}"
    closed = math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1]) < 0.01
    if closed:
        path_d += " Z"
    fill = "#e8f4f8" if closed else "none"
    parts.append(
        f"<path d='{path_d}' fill='{fill}' stroke='#2c3e50' "
        f"stroke-width='{max(vb_w, vb_h) * 0.005:.2f}'/>"
    )

    # Course labels at midpoints
    font_size = max(vb_w, vb_h) * 0.035
    for i, call in enumerate(plottable):
        mid_x = (points[i][0] + points[i + 1][0]) / 2
        mid_y = (points[i][1] + points[i + 1][1]) / 2
        label = _esc(f"#{call.get('course', i + 1)}")
        dist_label = f"{call.get('distance_ft', 0):.1f}'"
        parts.append(
            f"<text x='{mid_x:.2f}' y='{mid_y:.2f}' "
            f"font-size='{font_size:.1f}' text-anchor='middle' "
            f"fill='#2c3e50' font-family='sans-serif'>"
            f"{label} {dist_label}</text>"
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
        ".call-table td:nth-child(10), .call-table td:nth-child(11) "
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
    address = gt.get("deed_info", {}).get("address", "Unknown")
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
        # Derive source PDF name from GT filename
        source_pdf = gt_path.name.replace(".ground_truth.json", ".pdf")
        html_content = generate_review_html(gt, source_pdf)

        out_name = gt_path.stem.replace(".ground_truth", "") + "_review.html"
        out_path = output_dir / out_name
        out_path.write_text(html_content, encoding="utf-8")
        generated.append(out_path)

    return generated

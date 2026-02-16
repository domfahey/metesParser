"""Tests for the ground truth review packet generator."""

import json
from pathlib import Path

import pytest

from metesparser.review_packet import (
    build_call_table,
    build_closure_section,
    build_metadata_section,
    build_text_comparison,
    generate_all_packets,
    generate_review_html,
    generate_traverse_plot,
    load_ground_truth,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_GT = {
    "deed_info": {
        "address": "18 Pennbrook Drive",
        "city": "Haddonfield",
        "state": "NJ",
        "book": "11985",
        "page": "00829",
        "parcel_shape": "Rectangle",
        "dimensions": "60 ft × 125 ft",
    },
    "raw_ocr_text": "LAND AND PREMISES situate in the Borough...",
    "expected_legal_description": "BEGINNING at a point...",
    "expected_normalized_text": "BEGINNING at a point...",
    "expected_pob": "a point at the southwesterly corner",
    "expected_calls": [
        {
            "course": 1,
            "direction_text": "S 33°20'00\" E",
            "bearing_quadrant": "S 33°20' E",
            "bearing_azimuth_deg_from_north": 146.666667,
            "distance_ft": 60.0,
            "along": "southwesterly line of Concord Drive",
            "to": "a point in the division line",
            "notes": None,
        },
        {
            "course": 2,
            "direction_text": "S 56°40'00\" W",
            "bearing_quadrant": "S 56°40' W",
            "bearing_azimuth_deg_from_north": 236.666667,
            "distance_ft": 125.0,
            "along": "said division line",
            "to": "point corner to Lot 50",
            "notes": None,
        },
    ],
    "expected_closure": {
        "misclosure_ft": 0.0,
        "area_sq_ft": 7500.0,
        "area_acres": 0.172,
        "perimeter_ft": 370.0,
        "closure_passed": True,
    },
}

CARDINAL_ONLY_GT = {
    "deed_info": {
        "address": "38 Birchall Drive",
        "city": "Haddonfield",
        "state": "NJ",
        "book": "12673",
        "page": "00546",
    },
    "raw_ocr_text": "ALL THAT certain tract...",
    "expected_legal_description": "BEGINNING at a point...",
    "expected_normalized_text": None,
    "expected_pob": "a point in the Westerly line",
    "expected_calls": [
        {
            "course": 1,
            "direction_text": "Northwardly",
            "bearing_quadrant": None,
            "bearing_azimuth_deg_from_north": None,
            "distance_ft": 95.0,
            "along": "the Westerly line of Birchall Drive",
            "to": "a point in the division line",
            "notes": "incomplete bearing - cardinal only",
        },
    ],
    "expected_closure": {
        "misclosure_ft": None,
        "closure_passed": False,
    },
}


class TestLoadGroundTruth:
    """Tests for load_ground_truth()."""

    def test_loads_valid_json(self, tmp_path: Path) -> None:
        """Load a well-formed GT JSON and return the dict."""
        gt_file = tmp_path / "test.ground_truth.json"
        gt_file.write_text(json.dumps(SIMPLE_GT))

        result = load_ground_truth(gt_file)

        assert result["deed_info"]["address"] == "18 Pennbrook Drive"
        assert len(result["expected_calls"]) == 2
        assert result["expected_closure"]["closure_passed"] is True

    def test_returns_all_top_level_keys(self, tmp_path: Path) -> None:
        """Returned dict has all expected top-level keys."""
        gt_file = tmp_path / "test.ground_truth.json"
        gt_file.write_text(json.dumps(SIMPLE_GT))

        result = load_ground_truth(gt_file)

        expected_keys = {
            "deed_info",
            "raw_ocr_text",
            "expected_legal_description",
            "expected_normalized_text",
            "expected_pob",
            "expected_calls",
            "expected_closure",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_handles_cardinal_only_deed(self, tmp_path: Path) -> None:
        """Load GT with cardinal-only bearings (null azimuths)."""
        gt_file = tmp_path / "test.ground_truth.json"
        gt_file.write_text(json.dumps(CARDINAL_ONLY_GT))

        result = load_ground_truth(gt_file)

        call = result["expected_calls"][0]
        assert call["bearing_azimuth_deg_from_north"] is None
        assert call["notes"] == "incomplete bearing - cardinal only"

    def test_raises_on_missing_file(self) -> None:
        """Raise FileNotFoundError for nonexistent path."""
        with pytest.raises(FileNotFoundError):
            load_ground_truth(Path("/nonexistent/file.json"))

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        """Raise ValueError on malformed JSON."""
        gt_file = tmp_path / "bad.ground_truth.json"
        gt_file.write_text("not valid json {{{")

        with pytest.raises(ValueError, match="Invalid JSON"):
            load_ground_truth(gt_file)

    def test_raises_on_missing_required_keys(self, tmp_path: Path) -> None:
        """Raise ValueError when required keys are missing."""
        gt_file = tmp_path / "incomplete.ground_truth.json"
        gt_file.write_text(json.dumps({"deed_info": {}}))

        with pytest.raises(ValueError, match="Missing required"):
            load_ground_truth(gt_file)


class TestBuildMetadataSection:
    """Tests for build_metadata_section()."""

    def test_contains_address(self) -> None:
        """Output includes the deed address."""
        html = build_metadata_section(SIMPLE_GT, "test_deed.pdf")
        assert "18 Pennbrook Drive" in html

    def test_contains_book_and_page(self) -> None:
        """Output includes book and page numbers."""
        html = build_metadata_section(SIMPLE_GT, "test_deed.pdf")
        assert "11985" in html
        assert "00829" in html

    def test_contains_parcel_shape(self) -> None:
        """Output includes parcel shape and dimensions."""
        html = build_metadata_section(SIMPLE_GT, "test_deed.pdf")
        assert "Rectangle" in html

    def test_contains_source_pdf_filename(self) -> None:
        """Output includes source PDF filename."""
        html = build_metadata_section(SIMPLE_GT, "18 Pennbrook Dr - Deed.pdf")
        assert "18 Pennbrook Dr - Deed.pdf" in html

    def test_escapes_html_in_address(self) -> None:
        """HTML-special chars in deed_info are escaped."""
        gt_with_html = {
            **SIMPLE_GT,
            "deed_info": {**SIMPLE_GT["deed_info"], "address": '<script>alert("xss")</script>'},
        }
        html = build_metadata_section(gt_with_html, "test.pdf")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_handles_missing_optional_fields(self) -> None:
        """Works when parcel_shape/dimensions are absent."""
        html = build_metadata_section(CARDINAL_ONLY_GT, "test.pdf")
        assert "38 Birchall Drive" in html


# Fixture with curve data for call table tests
CURVE_GT = {
    **SIMPLE_GT,
    "expected_calls": [
        {
            "course": 1,
            "direction_text": "S 33°20'00\" E",
            "bearing_quadrant": "S 33°20' E",
            "bearing_azimuth_deg_from_north": 146.666667,
            "distance_ft": 60.0,
            "curve_dir": None,
            "radius_ft": None,
            "delta_deg": None,
            "arc_length_ft": None,
            "along": "southwesterly line of Concord Drive",
            "to": "a point in the division line",
            "monument_type": None,
            "notes": None,
        },
        {
            "course": 2,
            "direction_text": "along a curve to the right",
            "bearing_quadrant": None,
            "bearing_azimuth_deg_from_north": None,
            "distance_ft": None,
            "curve_dir": "right",
            "radius_ft": 175.0,
            "delta_deg": 22.5,
            "arc_length_ft": 68.72,
            "along": "the northerly line of Oak Road",
            "to": "a point",
            "monument_type": "iron_pipe",
            "notes": None,
        },
    ],
}


class TestBuildCallTable:
    """Tests for build_call_table()."""

    def test_contains_table_element(self) -> None:
        """Output contains an HTML table."""
        html = build_call_table(SIMPLE_GT)
        assert "<table" in html
        assert "</table>" in html

    def test_has_header_row_with_review_columns(self) -> None:
        """Table header includes Correct? and Reviewer Notes columns."""
        html = build_call_table(SIMPLE_GT)
        assert "Correct?" in html
        assert "Reviewer Notes" in html

    def test_one_row_per_call(self) -> None:
        """Table body has one <tr> per call."""
        html = build_call_table(SIMPLE_GT)
        # 2 calls + 1 header row = 3 <tr> tags
        assert html.count("<tr>") == 3

    def test_displays_course_number(self) -> None:
        """Each row shows the course number."""
        html = build_call_table(SIMPLE_GT)
        assert ">1<" in html
        assert ">2<" in html

    def test_displays_bearing_and_distance(self) -> None:
        """Each row shows direction text and distance."""
        html = build_call_table(SIMPLE_GT)
        assert "S 33" in html
        assert "60.0" in html
        assert "125.0" in html

    def test_displays_along_and_to(self) -> None:
        """Each row shows along and to fields."""
        html = build_call_table(SIMPLE_GT)
        assert "southwesterly line of Concord Drive" in html
        assert "a point in the division line" in html

    def test_handles_null_values(self) -> None:
        """Null values render as empty cells, not 'None'."""
        html = build_call_table(CARDINAL_ONLY_GT)
        assert "None" not in html

    def test_displays_curve_data(self) -> None:
        """Curve fields (radius, delta, arc) shown when present."""
        html = build_call_table(CURVE_GT)
        assert "175.0" in html
        assert "22.5" in html
        assert "68.72" in html
        assert "right" in html

    def test_displays_monument_type(self) -> None:
        """Monument type column populated when present."""
        html = build_call_table(CURVE_GT)
        assert "iron_pipe" in html

    def test_displays_notes(self) -> None:
        """Notes column populated when present."""
        html = build_call_table(CARDINAL_ONLY_GT)
        assert "incomplete bearing - cardinal only" in html

    def test_escapes_html_in_along_field(self) -> None:
        """HTML in along/to fields is escaped."""
        gt_with_html = {
            **SIMPLE_GT,
            "expected_calls": [
                {
                    **SIMPLE_GT["expected_calls"][0],
                    "along": '<img src=x onerror="alert(1)">',
                },
            ],
        }
        html = build_call_table(gt_with_html)
        assert "<img" not in html
        assert "&lt;img" in html


class TestBuildClosureSection:
    """Tests for build_closure_section()."""

    def test_displays_misclosure(self) -> None:
        """Output includes misclosure value."""
        html = build_closure_section(SIMPLE_GT)
        assert "0.0" in html

    def test_displays_area(self) -> None:
        """Output includes area in sq ft and acres."""
        html = build_closure_section(SIMPLE_GT)
        assert "7500.0" in html or "7,500" in html
        assert "0.172" in html

    def test_displays_perimeter(self) -> None:
        """Output includes perimeter."""
        html = build_closure_section(SIMPLE_GT)
        assert "370.0" in html

    def test_displays_pass_status(self) -> None:
        """Output shows PASS for successful closure."""
        html = build_closure_section(SIMPLE_GT)
        assert "PASS" in html

    def test_displays_fail_status(self) -> None:
        """Output shows FAIL for unsuccessful closure."""
        html = build_closure_section(CARDINAL_ONLY_GT)
        assert "FAIL" in html

    def test_handles_null_misclosure(self) -> None:
        """Handles null misclosure (cardinal-only deed) gracefully."""
        html = build_closure_section(CARDINAL_ONLY_GT)
        # Should not crash and should show something meaningful
        assert "None" not in html
        assert "closure" in html.lower() or "Closure" in html

    def test_displays_critical_assertions(self) -> None:
        """Shows critical assertions when present in GT."""
        gt_with_assertions = {
            **SIMPLE_GT,
            "critical_assertions": {
                "num_calls": {
                    "expected": 4,
                    "operator": "==",
                    "description": "MUST extract exactly 4 calls",
                },
            },
        }
        html = build_closure_section(gt_with_assertions)
        assert "MUST extract exactly 4 calls" in html

    def test_handles_scalar_assertions(self) -> None:
        """Handles scalar (non-dict) assertion values like total_calls=4."""
        gt_scalar = {
            **SIMPLE_GT,
            "critical_assertions": {
                "total_calls": 4,
                "has_curves": False,
            },
        }
        html = build_closure_section(gt_scalar)
        assert "total_calls" in html
        assert "4" in html

    def test_includes_reviewer_fields(self) -> None:
        """Closure section has Correct? and Notes fields for reviewer."""
        html = build_closure_section(SIMPLE_GT)
        assert "Correct?" in html


class TestBuildTextComparison:
    """Tests for build_text_comparison()."""

    def test_displays_raw_ocr_text(self) -> None:
        """Output includes the raw OCR text."""
        html = build_text_comparison(SIMPLE_GT)
        assert "LAND AND PREMISES" in html

    def test_displays_legal_description(self) -> None:
        """Output includes the expected legal description."""
        html = build_text_comparison(SIMPLE_GT)
        assert "BEGINNING at a point" in html

    def test_displays_pob(self) -> None:
        """Output includes the point of beginning."""
        html = build_text_comparison(SIMPLE_GT)
        assert "a point at the southwesterly corner" in html

    def test_handles_null_normalized_text(self) -> None:
        """Works when expected_normalized_text is None."""
        html = build_text_comparison(CARDINAL_ONLY_GT)
        assert "N/A" in html or "Not available" in html

    def test_handles_null_poc(self) -> None:
        """Works when expected_poc is absent."""
        html = build_text_comparison(SIMPLE_GT)
        # Should not crash, SIMPLE_GT has no expected_poc key
        assert "<div" in html

    def test_displays_poc_when_present(self) -> None:
        """Shows POC when the GT has one."""
        gt_with_poc = {**SIMPLE_GT, "expected_poc": "a point on the center line"}
        html = build_text_comparison(gt_with_poc)
        assert "a point on the center line" in html

    def test_escapes_html_in_text(self) -> None:
        """HTML in text fields is escaped."""
        gt_with_html = {
            **SIMPLE_GT,
            "raw_ocr_text": '<b>bold</b> & "quoted"',
        }
        html = build_text_comparison(gt_with_html)
        assert "<b>" not in html
        assert "&lt;b&gt;" in html


# 4-call rectangle for traverse plot tests (all azimuths present)
RECTANGLE_GT = {
    **SIMPLE_GT,
    "expected_calls": [
        {
            "course": 1,
            "bearing_azimuth_deg_from_north": 146.666667,
            "distance_ft": 60.0,
            "direction_text": "S 33°20' E",
        },
        {
            "course": 2,
            "bearing_azimuth_deg_from_north": 236.666667,
            "distance_ft": 125.0,
            "direction_text": "S 56°40' W",
        },
        {
            "course": 3,
            "bearing_azimuth_deg_from_north": 326.666667,
            "distance_ft": 60.0,
            "direction_text": "N 33°20' W",
        },
        {
            "course": 4,
            "bearing_azimuth_deg_from_north": 56.666667,
            "distance_ft": 125.0,
            "direction_text": "N 56°40' E",
        },
    ],
}


class TestGenerateTraversePlot:
    """Tests for generate_traverse_plot()."""

    def test_returns_svg_string(self) -> None:
        """Returns an SVG string for a deed with azimuths."""
        svg = generate_traverse_plot(RECTANGLE_GT)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_contains_course_labels(self) -> None:
        """SVG contains course number labels."""
        svg = generate_traverse_plot(RECTANGLE_GT)
        assert "#1" in svg or "C1" in svg or ">1<" in svg

    def test_returns_message_for_cardinal_only(self) -> None:
        """Returns a 'cannot plot' message when all bearings are cardinal-only."""
        result = generate_traverse_plot(CARDINAL_ONLY_GT)
        assert "cannot" in result.lower() or "no plottable" in result.lower()

    def test_handles_empty_calls(self) -> None:
        """Returns graceful message for empty call list."""
        gt_empty = {**SIMPLE_GT, "expected_calls": []}
        result = generate_traverse_plot(gt_empty)
        assert "no" in result.lower()

    def test_svg_has_viewbox(self) -> None:
        """SVG has a viewBox attribute for proper scaling."""
        svg = generate_traverse_plot(RECTANGLE_GT)
        assert "viewBox" in svg

    def test_contains_north_arrow(self) -> None:
        """SVG contains a north arrow indicator."""
        svg = generate_traverse_plot(RECTANGLE_GT)
        assert "N" in svg  # North label


class TestGenerateReviewHtml:
    """Tests for generate_review_html()."""

    def test_returns_complete_html_document(self) -> None:
        """Output is a complete HTML document with doctype, head, body."""
        html = generate_review_html(SIMPLE_GT, "test.pdf")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "<body>" in html

    def test_has_embedded_css(self) -> None:
        """Output contains embedded <style> tag."""
        html = generate_review_html(SIMPLE_GT, "test.pdf")
        assert "<style>" in html

    def test_contains_metadata_section(self) -> None:
        """Output includes the metadata section."""
        html = generate_review_html(SIMPLE_GT, "test.pdf")
        assert "18 Pennbrook Drive" in html
        assert "11985" in html

    def test_contains_call_table(self) -> None:
        """Output includes the call review table."""
        html = generate_review_html(SIMPLE_GT, "test.pdf")
        assert "Call-by-Call Review" in html
        assert "Correct?" in html

    def test_contains_closure_section(self) -> None:
        """Output includes closure verification."""
        html = generate_review_html(SIMPLE_GT, "test.pdf")
        assert "Closure Verification" in html

    def test_contains_text_comparison(self) -> None:
        """Output includes text comparison."""
        html = generate_review_html(SIMPLE_GT, "test.pdf")
        assert "Text Comparison" in html

    def test_contains_traverse_plot_for_plottable(self) -> None:
        """Output includes SVG plot for deeds with azimuths."""
        html = generate_review_html(RECTANGLE_GT, "test.pdf")
        assert "<svg" in html

    def test_is_print_friendly(self) -> None:
        """CSS includes print media query."""
        html = generate_review_html(SIMPLE_GT, "test.pdf")
        assert "@media print" in html

    def test_title_includes_address(self) -> None:
        """HTML <title> includes the deed address."""
        html = generate_review_html(SIMPLE_GT, "test.pdf")
        assert "<title>" in html
        assert "18 Pennbrook Drive" in html


class TestGenerateAllPackets:
    """Tests for generate_all_packets()."""

    def _write_gt_files(self, d: Path) -> None:
        """Helper: write two GT JSON files into directory d."""
        (d / "deed_a.ground_truth.json").write_text(json.dumps(SIMPLE_GT))
        (d / "deed_b.ground_truth.json").write_text(json.dumps(CARDINAL_ONLY_GT))

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        """Creates output dir if it doesn't exist."""
        src = tmp_path / "deeds"
        src.mkdir()
        self._write_gt_files(src)
        out = tmp_path / "packets"

        generate_all_packets(src, out)

        assert out.is_dir()

    def test_generates_one_html_per_gt(self, tmp_path: Path) -> None:
        """One HTML file per ground truth JSON."""
        src = tmp_path / "deeds"
        src.mkdir()
        self._write_gt_files(src)
        out = tmp_path / "packets"

        paths = generate_all_packets(src, out)

        assert len(paths) == 2
        for p in paths:
            assert p.suffix == ".html"
            assert p.exists()

    def test_html_files_are_valid(self, tmp_path: Path) -> None:
        """Generated HTML files contain expected structure."""
        src = tmp_path / "deeds"
        src.mkdir()
        self._write_gt_files(src)
        out = tmp_path / "packets"

        paths = generate_all_packets(src, out)

        for p in paths:
            content = p.read_text()
            assert "<!DOCTYPE html>" in content
            assert "Call-by-Call Review" in content

    def test_returns_empty_for_no_gt_files(self, tmp_path: Path) -> None:
        """Returns empty list when no GT files exist."""
        src = tmp_path / "empty"
        src.mkdir()
        out = tmp_path / "packets"

        paths = generate_all_packets(src, out)

        assert paths == []

    def test_skips_non_gt_json_files(self, tmp_path: Path) -> None:
        """Ignores JSON files that aren't *.ground_truth.json."""
        src = tmp_path / "deeds"
        src.mkdir()
        (src / "config.json").write_text("{}")
        (src / "deed_a.ground_truth.json").write_text(json.dumps(SIMPLE_GT))
        out = tmp_path / "packets"

        paths = generate_all_packets(src, out)

        assert len(paths) == 1

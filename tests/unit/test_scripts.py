"""Tests for standalone utility scripts."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


def _load_audit_module():
    """Import the audit_gt_vs_md script as a module."""
    spec = importlib.util.spec_from_file_location(
        "audit_gt_vs_md",
        Path(__file__).parent.parent.parent / "scripts" / "audit_gt_vs_md.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestAuditGtVsMdCardinalPattern:
    """The audit script's CARDINAL_ONLY_PATTERN should match the canonical
    pattern from call_extractor.py for consistency."""

    def test_canonical_pattern_matches_wardly_compounds(self) -> None:
        """The canonical _CARDINAL_ONLY_PATTERN handles 'wardly' suffix on
        compound directions."""
        from metesparser.call_extractor import _CARDINAL_ONLY_PATTERN

        assert _CARDINAL_ONLY_PATTERN.fullmatch("northeastwardly")
        assert _CARDINAL_ONLY_PATTERN.fullmatch("southwestwardly")
        assert _CARDINAL_ONLY_PATTERN.fullmatch("northwestwardly")
        assert _CARDINAL_ONLY_PATTERN.fullmatch("southeastwardly")

    def test_audit_script_pattern_matches_wardly_compounds(self) -> None:
        """The audit script's CARDINAL_ONLY_PATTERN should also match
        compound+wardly forms for consistency with canonical pattern."""
        mod = _load_audit_module()
        pattern: re.Pattern[str] = mod.CARDINAL_ONLY_PATTERN

        assert pattern.search("Northeastwardly")
        assert pattern.search("Southwestwardly")
        assert pattern.search("Northwestwardly")
        assert pattern.search("Southeastwardly")

    def test_audit_script_pattern_matches_all_canonical_forms(self) -> None:
        """Every form matched by the canonical pattern should also be matched
        by the audit script's pattern."""
        mod = _load_audit_module()
        audit_pattern: re.Pattern[str] = mod.CARDINAL_ONLY_PATTERN

        all_forms = [
            "north",
            "south",
            "east",
            "west",
            "northeast",
            "northwest",
            "southeast",
            "southwest",
            "northerly",
            "southerly",
            "easterly",
            "westerly",
            "northeasterly",
            "northwesterly",
            "southeasterly",
            "southwesterly",
            "northwardly",
            "southwardly",
            "eastwardly",
            "westwardly",
            "northeastwardly",
            "northwestwardly",
            "southeastwardly",
            "southwestwardly",
        ]

        for form in all_forms:
            assert audit_pattern.search(form), f"Audit pattern should match '{form}'"


class TestAuditFallbackExtraction:
    """Tests for the Step 2b fallback when BEGINNING is garbled/missing."""

    def test_fallback_extracts_calls_without_beginning(self) -> None:
        """When BEGINNING is garbled but closure language and thence exist,
        the fallback should extract calls via thence-splitting."""
        mod = _load_audit_module()
        md_text = (
            "Some preamble text.\n"
            "BEGINNiNn at a garbled point;\n"
            "thence North 45 degrees 00 minutes East 100.00 feet to a stake;\n"
            "thence South 45 degrees 00 minutes East 100.00 feet to a stake;\n"
            "thence South 45 degrees 00 minutes West 100.00 feet to a stake;\n"
            "thence North 45 degrees 00 minutes West 100.00 feet to the place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert len(calls) == 4
        assert calls[0]["distance_ft"] == 100.00

    def test_fallback_excludes_preamble(self) -> None:
        """The fallback should anchor to the first thence, not include
        preamble text that could produce false bearing matches."""
        mod = _load_audit_module()
        md_text = (
            "North 10 degrees 00 minutes East 999.00 feet preamble text.\n"
            "BEGINNiNn at a garbled point;\n"
            "thence South 30 degrees 00 minutes West 50.00 feet to a stake;\n"
            "thence North 30 degrees 00 minutes East 50.00 feet to the point of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert len(calls) == 2
        # Should NOT include the preamble bearing/distance
        assert calls[0]["distance_ft"] == 50.00

    def test_no_fallback_when_no_closure_language(self) -> None:
        """When neither BEGINNING nor closure language exists,
        return empty list."""
        mod = _load_audit_module()
        md_text = "Just some random deed text with no legal description."
        calls = mod.extract_calls_from_md(md_text)
        assert calls == []

    def test_markdown_bold_beginning_matched(self) -> None:
        """BEGINNING_PATTERN should match **BEGINNING** (bold) and
        *BEGINNING* (italic) markdown markers."""
        mod = _load_audit_module()
        assert mod.BEGINNING_PATTERN.search("**BEGINNING** at a stone")
        assert mod.BEGINNING_PATTERN.search("**BEGINNING** in the Northwesterly line")
        # Italic markdown (single asterisk)
        assert mod.BEGINNING_PATTERN.search("*BEGINNING* at a stone")
        # Still matches without any markers
        assert mod.BEGINNING_PATTERN.search("BEGINNING at a stone")

    def test_page_wrap_extracts_all_calls(self) -> None:
        """When BEGINNING is after closure in the file (reversed page order),
        the extraction should wrap around and find all calls."""
        mod = _load_audit_module()
        # Simulate reversed-page MD: calls 2-3 + closure at top, BEGINNING + call 1 at bottom
        md_text = (
            "(2) Westwardly along said line 112.96 feet to a point; thence\n"
            "(3) Southwardly along said boundary 95.00 feet to the place of beginning.\n"
            "\n"
            "Some deed boilerplate text in the middle.\n"
            "\n"
            "**BEGINNING** at a point in the Westerly line; thence\n"
            "(1) Northwardly along the line 95.00 feet to a point; thence\n"
        )
        calls = mod.extract_calls_from_md(md_text)
        assert len(calls) == 3
        # Verify correct order: call 1 first (from BEGINNING section), then 2, then 3
        assert calls[0]["distance_ft"] == 95.00
        assert calls[1]["distance_ft"] == 112.96
        assert calls[2]["distance_ft"] == 95.00

    def test_page_wrap_uses_last_closure_before_beginning(self) -> None:
        """When multiple closures exist before BEGINNING in reversed-page text,
        the page wrap should use the LAST closure (closest to BEGINNING),
        not the first one."""
        mod = _load_audit_module()
        # Two POB_CLOSE matches before BEGINNING — the page wrap should use
        # the second (closest to BEGINNING), not the first.
        md_text = (
            "said property returns to the point of beginning.\n"
            "\n"
            "(2) Eastwardly along said line 50.00 feet to a point; thence\n"
            "(3) Southwardly 75.00 feet to the place of beginning.\n"
            "\n"
            "**BEGINNING** at a stake; thence\n"
            "(1) Northwardly 75.00 feet to a point; thence\n"
        )
        calls = mod.extract_calls_from_md(md_text)
        assert len(calls) == 3
        assert calls[0]["distance_ft"] == 75.00
        assert calls[1]["distance_ft"] == 50.00
        assert calls[2]["distance_ft"] == 75.00

    def test_no_beginning_not_flagged_when_fallback_recovers_calls(self) -> None:
        """The NO_BEGINNING issue should NOT be raised when the fallback
        successfully extracted calls (n_md > 0)."""
        mod = _load_audit_module()
        # The audit_deed function needs GT and MD files, so test the logic
        # directly: when n_gt > 0 and n_md > 0, NO_BEGINNING should not fire
        md_text = (
            "BEGINNiNn garbled;\n"
            "thence North 45 degrees 00 minutes East 100.00 feet;\n"
            "thence South 45 degrees 00 minutes West 100.00 feet to the place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        # Fallback should find calls
        assert len(calls) > 0
        # BEGINNING_PATTERN should NOT match the garbled text
        assert not mod.BEGINNING_PATTERN.search(md_text)


class TestAuditTotalDistance:
    """A course that passes a monument records the full course length as its distance."""

    def test_total_distance_beats_intermediate_distance(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "BEGINNING at a stone; thence "
            "North 53 degrees 41 minutes 15 seconds East, passing over stone 292.51 feet "
            "from Haddon Avenue and continuing said course a total distance of 307.52 feet "
            "to a stake; thence "
            "South 53 degrees 41 minutes 15 seconds West, passing over stone 15.83 feet "
            "from beginning of this course total distance of 336.25 feet "
            "to place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [307.52, 336.25]


class TestAuditMultiTract:
    """101-111 Kings Highway E: marked tracts, exceptions, tie lines and mixed bearings."""

    def test_comma_separated_dms_bearing(self) -> None:
        mod = _load_audit_module()
        match = mod.BEARING_PATTERN.search("North 29 degrees, 23 minutes, 50 seconds West")
        assert match is not None
        assert match.groups() == ("N", "29", "23", "50", "W")

    def test_distance_includes_inches_and_skips_widths_and_offsets(self) -> None:
        mod = _load_audit_module()
        assert mod.extract_distance("Southeastwardly 92 feet, 4 inches to a point") == (92 + 4 / 12)
        assert mod.extract_distance(
            "along the aforesaid 10 feet wide alley, a distance of 148.10 feet"
        ) == (148.10)
        assert mod.extract_distance(
            "distant 10 feet Northeastwardly therefrom measured at right angles thereto "
            "158 feet 8 inches, more or less"
        ) == (158 + 8 / 12)

    def test_restated_place_of_beginning_does_not_close_the_block(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "STARTING at a point; thence in a Northwesterly direction a distance of 148.10 "
            "feet to a point which last mentioned point is the place of beginning on the lands "
            "hereby being described; and continuing thence in a Northwesterly direction a "
            "distance of 12 feet; thence in a Northeasterly direction a distance of 50 feet "
            "to the place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [148.10, 12, 50]

    def test_marked_tracts_keep_cardinal_only_blocks_and_exceptions(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "TRACT #1: BEGINNING at a point; thence (1) North 29 degrees, 23 minutes West "
            "72.64 feet; thence (2) Southwestwardly 107.03 feet to the place of beginning.\n"
            "TRACT #2: BEGINNING at a point; thence Southwestwardly 117.61 feet; thence "
            "Northwestwardly 138.43 feet to the place of beginning.\n"
            "EXCEPTING THEREOUT: BEGINNING on the Northwesterly side of Main Street; thence "
            "South 61 degrees 5 minutes West 50 feet; thence Northwardly 147.60 feet to "
            "beginning."
        )
        calls = mod.extract_calls_from_md(md_text, n_gt=7)
        assert [call["distance_ft"] for call in calls] == [
            72.64,
            107.03,
            117.61,
            138.43,
            50,
            147.60,
        ]

    def test_place_of_beginning_on_the_lands_is_not_a_block_start(self) -> None:
        mod = _load_audit_module()
        assert not mod.BLOCK_START_PATTERN.search("is the place of beginning on the lands")
        assert mod.BLOCK_START_PATTERN.search("BEGINNING on the Northwesterly side")


class TestAuditMain:
    def test_main_reports_skipped_deeds(self, tmp_path, monkeypatch, capsys) -> None:
        """A PDF without its md/ground-truth pair is reported as SKIP, not a crash."""
        mod = _load_audit_module()
        (tmp_path / "1 Main St - Deed Image (1 - 1).pdf").write_bytes(b"")
        monkeypatch.setattr(mod, "SAMPLE_DIR", tmp_path)

        mod.main()

        out = capsys.readouterr().out
        assert "GT AUDIT: 0 PASS / 0 FAIL / 1 SKIP out of 1" in out
        assert "1 Main St: 0/1 pass (0%) | 0 fail | 1 skip" in out


class TestAuditEmptyGroundTruth:
    MD = (
        "BEGINNING at a point; thence North 10 degrees 00 minutes 00 seconds East 100 feet; "
        "thence South 10 degrees 00 minutes 00 seconds West 100 feet to the point of beginning."
    )

    def _write(self, tmp_path, md_text: str, calls: list[dict[str, object]]) -> str:
        base = "1 Main St - Deed Image (1 - 1)"
        (tmp_path / f"{base}.md").write_text(md_text)
        (tmp_path / f"{base}.ground_truth.json").write_text(json.dumps({"expected_calls": calls}))
        return base

    def test_empty_ground_truth_with_md_courses_fails(self, tmp_path, monkeypatch) -> None:
        mod = _load_audit_module()
        monkeypatch.setattr(mod, "SAMPLE_DIR", tmp_path)
        result = mod.audit_deed(self._write(tmp_path, self.MD, []))
        assert result["status"] == "FAIL"
        assert result["issues"] == ["EMPTY_GT: GT has no calls but MD extracted=2"]

    def test_empty_ground_truth_without_md_courses_passes(self, tmp_path, monkeypatch) -> None:
        mod = _load_audit_module()
        monkeypatch.setattr(mod, "SAMPLE_DIR", tmp_path)
        result = mod.audit_deed(self._write(tmp_path, "See Schedule A attached hereto", []))
        assert result["status"] == "PASS"

    def test_description_recorded_with_another_deed_uses_that_markdown(
        self, tmp_path, monkeypatch
    ) -> None:
        """8 Kings Highway W 7535-933: its Schedule C is recorded in the 7535-929 scan."""
        mod = _load_audit_module()
        monkeypatch.setattr(mod, "SAMPLE_DIR", tmp_path)
        (tmp_path / "other.md").write_text(self.MD)
        base = "1 Main St - Deed Image (1 - 1)"
        (tmp_path / f"{base}.md").write_text("SEE Schedule C attached.")
        calls = mod.extract_calls_from_md(self.MD)
        gt = {
            "legal_description_markdown": "other.md",
            "expected_calls": [
                {"distance_ft": c["distance_ft"], "bearing_azimuth_deg_from_north": c["azimuth"]}
                for c in calls
            ],
        }
        (tmp_path / f"{base}.ground_truth.json").write_text(json.dumps(gt))
        result = mod.audit_deed(base)
        assert result["status"] == "PASS"
        assert result["n_md"] == len(calls) == 2


class TestAuditSchedules:
    """219 Berlin Rd 12799-00118: schedule attachments and trailing-thence courses."""

    def test_schedule_city_is_not_a_schedule_c_section(self) -> None:
        mod = _load_audit_module()
        assert not mod.EXHIBIT_PATTERN.search("SEE ATTACHED SCHEDULE\n    City, Town")
        assert mod.EXHIBIT_PATTERN.search("SCHEDULE C")
        assert mod.EXHIBIT_PATTERN.search('EXHIBIT "A"')

    def test_said_point_of_beginning_in_preamble_does_not_close_the_block(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "BEGINNING at a point, said point of beginning being also distant 24.75 feet "
            "from the center line, and from said point of beginning, proceeding thence "
            "North 50 degrees 45 minutes 00 seconds East, a distance of 416.57 feet; thence "
            "South 32 degrees 36 minutes 00 seconds East, a distance of 300.07 feet to said "
            "point of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [416.57, 300.07]

    def test_course_ending_in_thence_after_preamble_is_kept(self) -> None:
        mod = _load_audit_module()
        md_text = (
            "Beginning at a point said point being the following two courses and distances "
            "from the intersection of White Horse Road with Burnt Mill Road.\n\n"
            "North 40 Degrees 41 Minutes 31 Seconds East a distance of 483.13 feet to a point "
            "thence;\n\n"
            "North 59 Degrees 29 Minutes 19 Seconds West a distance of 17.78 feet to a point "
            "thence;\n\n"
            "South 59 Degrees 29 Minutes 19 Seconds East a distance of 250.44 feet to point "
            "and place of beginning."
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [483.13, 17.78, 250.44]


class TestAuditLetteredTieCourses:
    """36 Kresson: tie courses (A) and (B) reach a point of beginning that more courses follow."""

    EXCEPTION = (
        "BEGINNING at a point along a line common with Lot 13A, said point being the following "
        "courses and distances from the intersection of Willard Avenue with Kresson Road\n\n"
        "(A) Along the said row line of Kresson Road North 73 degrees 30 minutes 00 seconds West "
        "a distance of 509.1 feet to a point common to said Lots 13 and 13B, thence;\n\n"
        "(B) Along line common to said Lots 13 and 13A South 16 degrees 30 minutes 00 seconds "
        "West a distance of 27.00 feet to a point and place of beginning{after_b}\n\n"
        "(1) South 73 degrees 30 minutes 00 seconds East a distance of 10.00 feet to a point, "
        "thence;\n\n"
        "(2) North 16 degrees 30 minutes 00 seconds East a distance of 47.00 feet to a point and "
        "place of BEGINNING.\n\nNOTE: Lot and Block shown for informational purposes only."
    )

    def test_lettered_tie_courses_and_following_courses_are_extracted(self) -> None:
        mod = _load_audit_module()
        for after_b in (", thence;", "."):
            calls = mod.extract_calls_from_md(self.EXCEPTION.format(after_b=after_b))
            assert [call["distance_ft"] for call in calls] == [509.1, 27.0, 10.0, 47.0], after_b

    def test_lot_s_mid_line_is_not_a_course_marker(self) -> None:
        mod = _load_audit_module()
        assert not mod.CALL_NUM_PATTERN.search("NOTE: Being Lot(s) 4, Block: 423.01")
        assert mod.CALL_NUM_PATTERN.search("\n(A) Along the said row line")


class TestAuditRepeatedDescriptions:
    def test_repeated_description_is_counted_once(self) -> None:
        """2 Walnut 10239-1279: an attached certification repeats Exhibit A word for word."""
        mod = _load_audit_module()
        lot = (
            "BEGINNING at a point in the Westerly line of Walnut Street; thence Westerly 51.00 "
            "feet; thence Southerly 177.97 feet to the point and place of beginning."
        )
        md_text = f"# EXHIBIT A\n\n{lot}\n\n# Exhibit B\nCertification of Trust\n\n{lot}\n"
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [51.0, 177.97]


class TestAuditExhibitReferences:
    """One Centennial Square: the deed body refers to Exhibit A and to a recording page."""

    MD = (
        'SEE EXHIBIT "A" ATTACHED HERETO AND MADE A PART HEREOF.\n\n'
        "BEING the same premises recorded in Deed Book 4795, beginning at page 618.\n\n"
        'EXHIBIT "A"\n\n'
        "BEGINNING at a point in the Northwesterly line of Euclid Avenue; thence\n"
        "(1) North 49 degrees 06 minutes 30 seconds East a distance of 213.26 feet; thence\n"
        "(2) Along lands of the Port Authority curving to the right with a radius of 5933.53 "
        "feet, an arc distance of 344.93 feet to a point; thence\n"
        "(3) South 21 degrees 01 minutes 53 seconds East a distance of 285.44 feet to the "
        "point and place of beginning."
    )

    def test_exhibit_reference_and_recording_page_are_skipped(self) -> None:
        mod = _load_audit_module()
        assert mod.find_preferred_text(self.MD).startswith('EXHIBIT "A"\n')
        assert not mod.BLOCK_START_PATTERN.search("Deed Book 4795, beginning at page 618")

    def test_curve_length_is_its_arc(self) -> None:
        mod = _load_audit_module()
        calls = mod.extract_calls_from_md(self.MD)
        assert [call["distance_ft"] for call in calls] == [213.26, 344.93, 285.44]


class TestAuditPrintedValues:
    """A misprinted course records its intended value and the printed value the markdown shows."""

    MD = (
        "BEGINNING at a point; thence South 64 degrees 22 minutes 25 seconds West, 229.89 feet "
        "to a point; thence North 46 degrees 46 minutes 25 seconds West, 59.30 feet to the point "
        "and place of beginning."
    )

    def _audit(self, tmp_path, monkeypatch, first_call: dict[str, object]) -> dict[str, object]:
        mod = _load_audit_module()
        monkeypatch.setattr(mod, "SAMPLE_DIR", tmp_path)
        base = "26 Chews Landing Rd - Deed Image (1 - 1)"
        calls = [first_call, {"bearing_azimuth_deg_from_north": 313.2264, "distance_ft": 59.30}]
        (tmp_path / f"{base}.md").write_text(self.MD)
        (tmp_path / f"{base}.ground_truth.json").write_text(json.dumps({"expected_calls": calls}))
        return mod.audit_deed(base)

    def test_printed_value_is_compared_with_the_markdown(self, tmp_path, monkeypatch) -> None:
        result = self._audit(
            tmp_path,
            monkeypatch,
            {
                "bearing_azimuth_deg_from_north": 244.3736,
                "distance_ft": 299.89,
                "printed_distance_ft": 229.89,
            },
        )
        assert result["status"] == "PASS", result["issues"]

    def test_intended_value_without_printed_value_fails(self, tmp_path, monkeypatch) -> None:
        result = self._audit(
            tmp_path,
            monkeypatch,
            {"bearing_azimuth_deg_from_north": 244.3736, "distance_ft": 299.89},
        )
        assert result["issues"] == ["DISTANCE_C1: GT=299.89ft, MD=229.89ft (diff=70.00ft)"]


class TestAuditTractReferences:
    def test_tract_reference_does_not_cut_an_unclosed_description(self) -> None:
        """89 Haddon 4455-174: "boundary line of Tract #1 of Haddonfield Estates" is a reference."""
        mod = _load_audit_module()
        md_text = (
            "BEGINNING at a point in the former Southeasterly boundary line of Tract #1 of "
            "Haddonfield Estates; running thence (1) North 54 degrees 44 minutes 05 seconds East, "
            "a distance of 141.73 feet to a point; thence (2) South 19 degrees 58 minutes 30 "
            "seconds West, a distance of 146.44 feet to a found field stone [page unreadable]\n\n"
            "TRACT #2: other land"
        )
        calls = mod.extract_calls_from_md(md_text)
        assert [call["distance_ft"] for call in calls] == [141.73, 146.44]


class TestAuditNearRepeatedDescriptions:
    LOT = (
        "BEGINNING at a corner formed by the intersection of the Southwest line of {street} Street "
        "(66 feet wide) with the Northwesterly line of Walnut Street (60 feet wide), which corner "
        "forms an interior angle of 90 degrees; and extending thence in a northwesterly direction "
        "along the Southwesterly line of {street} Street a distance of {d1} feet to a point corner "
        "to lands now or late of Henry E. Uber and wife; thence in a Southwesterly direction and at "
        "right angles to Ellis Street and along the line of lands now or late of Uber a distance of "
        "125 feet; thence in a Northwesterly direction and at right angles to the last course and "
        "along the line of lands now or late of Uber a distance of 42.79 feet to a point corner to "
        "lands now or late of Isaac Nicholson; thence in a Southwesterly direction and at right "
        "angles to the last course a distance of 172 feet to a point; thence in a Southeasterly "
        "direction and at right angles to the last course a distance of {d5} feet; thence in a "
        "Northeasterly direction along the Northwesterly line of Walnut Street a distance of "
        "248.31 feet to the place of beginning."
    )

    def test_ocr_noisy_repeat_is_counted_once(self) -> None:
        """2 Walnut 10239-1268: the certification's copy reads "Elis" and "81 52"."""
        mod = _load_audit_module()
        first = self.LOT.format(street="Ellis", d1="265.21", d5="81.52")
        copy = self.LOT.format(street="Elis", d1="265.21", d5="81 52")
        calls = mod.extract_calls_from_md(f"{first}\n\nCertification of Trust\n\n{copy}")
        assert [call["distance_ft"] for call in calls] == [
            265.21,
            125.0,
            42.79,
            172.0,
            81.52,
            248.31,
        ]

    def test_similar_parcels_with_different_distances_are_kept(self) -> None:
        mod = _load_audit_module()
        lot_a = self.LOT.format(street="Ellis", d1="265.21", d5="81.52")
        lot_b = self.LOT.format(street="Ellis", d1="200.00", d5="60.00")
        calls = mod.extract_calls_from_md(f"{lot_a}\n\n{lot_b}")
        assert len(calls) == 12


class TestAuditDecimalCommas:
    def test_two_digit_comma_is_a_decimal_point(self) -> None:
        """219 Berlin 12799-00118 prints "a distance of 300,07 feet"."""
        mod = _load_audit_module()
        assert mod.extract_distance("South 32 degrees East, a distance of 300,07 feet") == 300.07
        assert mod.extract_distance("a distance of 35,00 feet to the point") == 35.0

    def test_three_digit_comma_is_not_a_decimal_point(self) -> None:
        mod = _load_audit_module()
        assert mod.to_float("300,07") == 300.07
        assert not mod.re.fullmatch(mod.NUMBER, "1,140")


class TestAuditMiwaynForms:
    """Wording from the Wayne County (MIWAYN) deeds."""

    def test_due_cardinal_is_an_exact_bearing(self) -> None:
        mod = _load_audit_module()
        calls = mod.extract_calls_from_md(
            "BEGINNING at a point; thence South 00°44'00\" West 213.00 feet; thence due west "
            "130.00 feet; thence North 00°44'00\" East 213.00 feet; thence due East 130.00 feet "
            "to the point of beginning."
        )
        assert [call["azimuth"] for call in calls][1::2] == [270.0, 90.0]

    def test_stray_period_after_minutes(self) -> None:
        mod = _load_audit_module()
        match = mod.BEARING_PATTERN.search("South 00 degrees 15. minutes 50 seconds West")
        assert match is not None and match.groups() == ("S", "00", "15", "50", "W")

    def test_commencing_opens_a_description_with_its_tie_course(self) -> None:
        mod = _load_audit_module()
        calls = mod.extract_calls_from_md(
            "described as: Commencing at the Northwest corner of Lot 15; Thence South 26 deg. 00' "
            '41" East, 120.00 feet for the point of beginning; Thence North 58 deg. 14\' 00" East '
            "232.17 feet; Thence South 26 deg. 00' 41\" East 120.00 feet to the point of beginning."
        )
        assert [call["distance_ft"] for call in calls] == [120.0, 232.17, 120.0]

    def test_comma_joined_courses_are_split(self) -> None:
        mod = _load_audit_module()
        calls = mod.extract_calls_from_md(
            "beginning at a point; thence South 16 degrees, 54 minutes, 36 seconds West, 85.33 feet, "
            "North 73 degrees, 05 minutes, 24 seconds West, 128.00 feet; thence North 16 degrees, "
            "54 minutes, 36 seconds East, 85.33 feet to the point of beginning."
        )
        assert [call["distance_ft"] for call in calls] == [85.33, 128.0, 85.33]

    def test_excepted_parcel_conveyed_again_is_not_a_repeat(self) -> None:
        """MIWAYN-50306-00349: Parcel 1 excepts a parcel that Parcel 2 then conveys."""
        mod = _load_audit_module()
        parcel = (
            "beginning at a point; thence South 16 degrees 54 minutes 36 seconds West 85.33 feet; "
            "thence North 73 degrees 05 minutes 24 seconds West 128.00 feet to the point of beginning."
        )
        md_text = f"Parcel 1: Lot 13, EXCEPT that part described as {parcel}\n\nParcel 2: {parcel}"
        assert len(mod.extract_calls_from_md(md_text)) == 4

    def test_note_between_number_and_feet(self) -> None:
        mod = _load_audit_module()
        assert (
            mod.extract_distance("North 1 degrees West, 704.61 (surveyed as 704.60) feet") == 704.61
        )

    def test_assessor_shorthand_description(self) -> None:
        """MIWAYN-50062-01403: BEG ... TH <bearing> <distance>FT ... POB."""
        mod = _load_audit_module()
        calls = mod.extract_calls_from_md(
            "PT OF NE 1/4 SEC 36 T2S R8E BEG S0DEG 32M 50S W 401.55FT FROM NE COR SEC 36 "
            "TH S0DEG 49M 20S W 175FT TH N89DEG 10M 40S W 61.23FT TH N0DEG 49M E 175FT "
            "TH S89DEG 10M 40S E 61.26FT POB 0.25 AC"
        )
        assert [call["distance_ft"] for call in calls] == [175.0, 61.23, 175.0, 61.26]
        assert round(calls[2]["azimuth"], 4) == 0.8167

    def test_assessor_d_m_sec_units(self) -> None:
        mod = _load_audit_module()
        match = mod.BEARING_PATTERN.search("TH N 89D 05M 3SEC W 318.12 FT")
        assert match is not None and match.groups() == ("N", "89", "05", "3", "W")

    def test_bare_cardinal_letter_and_joined_courses(self) -> None:
        """MIWAYN-50058-00465: "th. S 289.81 ft." and courses joined by "and" / "&"."""
        mod = _load_audit_module()
        calls = mod.extract_calls_from_md(
            "Commencing at the NE corner of Lot 13 and proceeding th. S 69° 53' 23\" W 82.00 ft. "
            "to the POB, proceeding th. S 289.81 ft. th. W 199.44 ft. to a point on the easterly "
            "line th. along said line N 15° 21' 23\" E 49.18 ft. and N 48° 03' 44\" E. 113.41 ft. "
            "& N 69° 53' 23\" E 109.98 feet to the point of beginning."
        )
        assert [call["distance_ft"] for call in calls] == [
            82.0,
            289.81,
            199.44,
            49.18,
            113.41,
            109.98,
        ]
        assert [call["azimuth"] for call in calls][1:3] == [180.0, 270.0]

    def test_excluded_part_with_a_point_of_beginning_being(self) -> None:
        """MIWAYN-50428-01001: the excluded triangle is the only described figure."""
        mod = _load_audit_module()
        calls = mod.extract_calls_from_md(
            "LOT 48 EXCLUDING THAT PART DESCRIBED AS TRIANGULAR PORTION HAVING A POINT OF BEGINNING "
            "BEING THE NORTHWEST CORNER OF SAID LOT 48: THENCE SOUTH 89 DEGREES 39 MINUTES 00 SECONDS "
            "EAST 20.00 FEET; THENCE SOUTH 22 DEGREES 53 MINUTES 15 SECONDS WEST 50.20 FEET; THENCE "
            "NORTH 00 DEGREES 35 MINUTES 20 SECONDS WEST 46.37 FEET TO THE POINT OF BEGINNING"
        )
        assert [call["distance_ft"] for call in calls] == [20.0, 50.2, 46.37]


class TestAuditSentenceJoinedCourses:
    """1 Walnut St 12420-00902 Tract No. 3: "122.55 feet to a point. South 18 degrees ..."."""

    def test_tie_courses_joined_by_a_sentence_break_are_split(self) -> None:
        mod = _load_audit_module()
        calls = mod.extract_calls_from_md(
            "BEGINNING at a point which is located at the following two courses and distances "
            "from the intersection; thence\n\nSouth 71 degrees 54 minutes 50 seconds East along "
            "Ellis Street 122.55 feet to a point. South 18 degrees 05 minutes 10 seconds West "
            "123.00 feet to the point and place of beginning; thence\n\n(1) South 18 degrees 05 "
            "minutes 10 seconds West 82.00 feet to a point; thence\n\n(2) North 71 degrees 54 "
            "minutes 50 seconds West 53.36 feet to the point and place of beginning."
        )
        assert [call["distance_ft"] for call in calls] == [122.55, 123.0, 82.0, 53.36]

"""Tests for standalone utility scripts."""

from __future__ import annotations

import importlib.util
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

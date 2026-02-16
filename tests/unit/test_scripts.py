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

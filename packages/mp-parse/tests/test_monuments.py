"""Tests for mp_parse.monuments -- monument classification functions."""

from __future__ import annotations


class TestClassifyMonument:
    def test_iron_pin(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("an iron pin found")
        assert result == "iron_pin"

    def test_iron_rod(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("iron rod set in concrete")
        assert result == "iron_rod"

    def test_iron_pipe(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("iron pipe")
        assert result == "iron_pipe"

    def test_capped_rod(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("capped iron rod")
        assert result == "capped_rod"

    def test_capped_pin(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("capped iron pin")
        assert result == "capped_pin"

    def test_capped_rebar(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("capped rebar")
        assert result == "capped_rod"

    def test_rebar(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("rebar found")
        assert result == "rebar"

    def test_pk_nail(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("pk nail set")
        assert result == "pk_nail"

    def test_nail(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("nail in pavement")
        assert result == "nail"

    def test_magnetic_nail(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("magnetic nail")
        assert result == "nail"

    def test_hub_and_tack(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("hub and tack")
        assert result == "hub_and_tack"

    def test_railroad_spike(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("railroad spike")
        assert result == "railroad_spike"

    def test_stone(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("stone monument")
        assert result == "stone"

    def test_stone_bare(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("a stone")
        assert result == "stone"

    def test_concrete(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("concrete monument")
        assert result == "concrete"

    def test_brass_cap(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("brass cap marker")
        assert result == "brass_cap"

    def test_wooden_post(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("wooden post")
        assert result == "wooden_post"

    def test_tree(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("an oak tree")
        assert result == "tree"

    def test_rock(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("a large rock")
        assert result == "rock"

    def test_natural_feature(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("the creek bank")
        assert result == "natural_feature"

    def test_generic_monument(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("a monument")
        assert result == "other"

    def test_txdot_monument(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("TxDOT monument found")
        assert result == "txdot_monument"

    def test_monitoring_well(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("monitoring well")
        assert result == "monitoring_well"

    def test_empty_string_returns_none(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("")
        assert result is None

    def test_no_match_returns_none(self) -> None:
        from mp_parse.monuments import classify_monument

        result = classify_monument("the property line")
        assert result is None

    def test_specificity_ordering(self) -> None:
        """Capped iron rod should beat plain iron rod."""
        from mp_parse.monuments import classify_monument

        result = classify_monument("capped iron rod found")
        assert result == "capped_rod"


class TestClassifyMonumentStatus:
    def test_found(self) -> None:
        from mp_parse.monuments import classify_monument_status

        assert classify_monument_status("iron pin found") == "found"

    def test_set(self) -> None:
        from mp_parse.monuments import classify_monument_status

        assert classify_monument_status("iron pin set") == "set"

    def test_fd_abbreviation(self) -> None:
        from mp_parse.monuments import classify_monument_status

        assert classify_monument_status("iron rod FD") == "found"

    def test_fnd_abbreviation(self) -> None:
        from mp_parse.monuments import classify_monument_status

        assert classify_monument_status("iron rod FND") == "found"

    def test_placed(self) -> None:
        from mp_parse.monuments import classify_monument_status

        assert classify_monument_status("iron pin placed") == "set"

    def test_no_status_returns_none(self) -> None:
        from mp_parse.monuments import classify_monument_status

        assert classify_monument_status("iron pin") is None

    def test_empty_returns_none(self) -> None:
        from mp_parse.monuments import classify_monument_status

        assert classify_monument_status("") is None

    def test_none_returns_none(self) -> None:
        from mp_parse.monuments import classify_monument_status

        assert classify_monument_status(None) is None


class TestMonumentPatterns:
    def test_patterns_list_available(self) -> None:
        from mp_parse.monuments import MONUMENT_PATTERNS

        assert len(MONUMENT_PATTERNS) > 20

    def test_status_patterns_available(self) -> None:
        from mp_parse.monuments import MONUMENT_STATUS_PATTERNS

        assert len(MONUMENT_STATUS_PATTERNS) >= 5

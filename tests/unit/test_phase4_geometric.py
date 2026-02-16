"""Phase 4: Geometric Completeness tests.

Covers:
- Meander/water boundary detection
- Compound/reverse curve detection
- Missing curve element calculation
- Tie-in call separation
- Indefinite call flagging
"""

from pathlib import Path

import pytest

from metesparser.csv_builder import CSVBuilder
from metesparser.models import DeedCall


class TestDeedCallPhase4Fields:
    """Tests for new Phase 4 fields on DeedCall."""

    def test_is_meander_default_false(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.is_meander is False

    def test_is_meander_set_true(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, is_meander=True)
        assert call.is_meander is True

    def test_is_tie_in_default_false(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.is_tie_in is False

    def test_is_tie_in_set_true(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0, is_tie_in=True)
        assert call.is_tie_in is True

    def test_is_indefinite_default_false(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.is_indefinite is False

    def test_is_indefinite_set_true(self) -> None:
        call = DeedCall(course=1, direction_text="southwesterly", distance_ft=100.0, is_indefinite=True)
        assert call.is_indefinite is True

    def test_curve_type_default_none(self) -> None:
        call = DeedCall(course=1, direction_text="N 45° E", distance_ft=100.0)
        assert call.curve_type is None

    def test_curve_type_simple(self) -> None:
        call = DeedCall(
            course=1, direction_text="N 45° E", distance_ft=100.0,
            curve_dir="left", radius_ft=200.0, delta_deg=30.0, curve_type="simple",
        )
        assert call.curve_type == "simple"

    def test_curve_type_compound(self) -> None:
        call = DeedCall(
            course=1, direction_text="N 45° E", distance_ft=100.0,
            curve_dir="left", radius_ft=200.0, delta_deg=30.0, curve_type="compound",
        )
        assert call.curve_type == "compound"

    def test_curve_type_reverse(self) -> None:
        call = DeedCall(
            course=1, direction_text="N 45° E", distance_ft=100.0,
            curve_dir="right", radius_ft=200.0, delta_deg=30.0, curve_type="reverse",
        )
        assert call.curve_type == "reverse"

    def test_curve_type_invalid_rejected(self) -> None:
        with pytest.raises(ValueError):
            DeedCall(
                course=1, direction_text="N 45° E", distance_ft=100.0,
                curve_dir="left", radius_ft=200.0, delta_deg=30.0, curve_type="spiral",
            )


class TestPhase4CSVSchema:
    """Tests for Phase 4 CSV schema changes."""

    def test_fieldnames_count_21(self) -> None:
        assert len(CSVBuilder.FIELDNAMES) == 21

    def test_is_meander_in_fieldnames(self) -> None:
        assert "is_meander" in CSVBuilder.FIELDNAMES

    def test_is_tie_in_in_fieldnames(self) -> None:
        assert "is_tie_in" in CSVBuilder.FIELDNAMES

    def test_is_meander_after_is_exception(self) -> None:
        exc_idx = CSVBuilder.FIELDNAMES.index("is_exception")
        meander_idx = CSVBuilder.FIELDNAMES.index("is_meander")
        assert meander_idx == exc_idx + 1

    def test_is_tie_in_after_is_meander(self) -> None:
        meander_idx = CSVBuilder.FIELDNAMES.index("is_meander")
        tie_in_idx = CSVBuilder.FIELDNAMES.index("is_tie_in")
        assert tie_in_idx == meander_idx + 1

    def test_csv_round_trip_meander(self, tmp_path: Path) -> None:
        output_path = tmp_path / "meander.csv"
        calls = [
            DeedCall(course=1, direction_text="northerly", distance_ft=100.0, is_meander=True),
        ]
        CSVBuilder.calls_to_csv(calls, str(output_path))
        loaded = CSVBuilder.csv_to_calls(str(output_path))
        assert len(loaded) == 1
        assert loaded[0].is_meander is True

    def test_csv_round_trip_tie_in(self, tmp_path: Path) -> None:
        output_path = tmp_path / "tie_in.csv"
        calls = [
            DeedCall(course=1, direction_text="N 45° E", distance_ft=200.0, is_tie_in=True),
        ]
        CSVBuilder.calls_to_csv(calls, str(output_path))
        loaded = CSVBuilder.csv_to_calls(str(output_path))
        assert len(loaded) == 1
        assert loaded[0].is_tie_in is True

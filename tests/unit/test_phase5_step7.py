"""Phase 5 Step 7: Subdivision Lot/Block + TPOB/RPOB tests."""

from metesparser.text_parser import TextParser


class TestSubdivisionReference:
    """Tests for subdivision lot/block extraction."""

    def test_full_subdivision_reference(self) -> None:
        text = "Lot 15, Block 3, PENNBROOK ESTATES, as recorded in Plat Book 14, Page 22"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is not None
        assert ref.lot == "15"
        assert ref.block == "3"
        assert ref.subdivision_name == "PENNBROOK ESTATES"
        assert ref.plat_book == "14"
        assert ref.plat_page == "22"

    def test_lot_only(self) -> None:
        text = "Lot 5, OAKDALE SUBDIVISION"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is not None
        assert ref.lot == "5"
        assert ref.block is None

    def test_lot_and_block_no_plat(self) -> None:
        text = "Lot 12, Block 7, SUNSET HILLS"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is not None
        assert ref.lot == "12"
        assert ref.block == "7"
        assert ref.subdivision_name == "SUNSET HILLS"

    def test_no_subdivision_returns_none(self) -> None:
        text = "BEGINNING at an iron pin, thence N 45° E 100 feet"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is None

    def test_plat_book_and_page(self) -> None:
        text = "recorded in Plat Book 23, Page 45 of the County Records"
        ref = TextParser.extract_subdivision_reference(text)
        assert ref is not None
        assert ref.plat_book == "23"
        assert ref.plat_page == "45"


class TestTPOBRecognition:
    """Tests for True/Remote Point of Beginning recognition."""

    def test_tpob_recognized_as_pob(self) -> None:
        assert TextParser.is_closure_to_pob("to the TRUE POINT OF BEGINNING") is True

    def test_tpob_abbreviation(self) -> None:
        assert TextParser.is_closure_to_pob("to the TPOB") is True

    def test_tpob_dotted(self) -> None:
        assert TextParser.is_closure_to_pob("to the T.P.O.B.") is True

    def test_rpob_recognized_as_pob(self) -> None:
        assert TextParser.is_closure_to_pob("to the REMOTE POINT OF BEGINNING") is True

    def test_rpob_abbreviation(self) -> None:
        assert TextParser.is_closure_to_pob("to the RPOB") is True

    def test_rpob_dotted(self) -> None:
        assert TextParser.is_closure_to_pob("to the R.P.O.B.") is True

    def test_extract_pob_with_tpob(self) -> None:
        text = "TRUE POINT OF BEGINNING at the corner of Lot 5; THENCE N 45° E"
        pob = TextParser.extract_pob(text)
        assert "corner of Lot 5" in pob

    def test_extract_pob_with_tpob_abbreviation(self) -> None:
        text = "TPOB at an iron pin found; THENCE S 30° W"
        pob = TextParser.extract_pob(text)
        assert "iron pin" in pob

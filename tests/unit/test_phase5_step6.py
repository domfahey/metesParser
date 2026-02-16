"""Phase 5 Step 6: Clause Taxonomy tests."""

from metesparser.text_parser import TextParser


class TestClauseTaxonomy:
    """Tests for deed clause extraction."""

    def test_extract_reservation_clause(self) -> None:
        text = "RESERVING unto the Grantor a right of way 20 feet wide along the northern boundary."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "reservation"
        assert "RESERVING" in clauses[0].text

    def test_extract_subject_to_clause(self) -> None:
        text = "SUBJECT TO existing easements of record and all applicable zoning ordinances."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "subject_to"
        assert "SUBJECT TO" in clauses[0].text

    def test_extract_together_with_clause(self) -> None:
        text = "TOGETHER WITH a right of ingress and egress over the private road."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "together_with"
        assert "TOGETHER WITH" in clauses[0].text

    def test_extract_multiple_clauses(self) -> None:
        text = (
            "RESERVING unto the Grantor mineral rights. "
            "SUBJECT TO existing utility easements. "
            "TOGETHER WITH appurtenant water rights."
        )
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 3
        types = {c.clause_type for c in clauses}
        assert types == {"reservation", "subject_to", "together_with"}

    def test_no_clauses_returns_empty(self) -> None:
        text = "BEGINNING at an iron pin, thence N 45° E 100 feet to a point."
        clauses = TextParser.extract_deed_clauses(text)
        assert clauses == []

    def test_reserving_variant_spelling(self) -> None:
        text = "RESERVING UNTO the grantor and his heirs all oil and gas rights."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "reservation"

    def test_subject_to_covenants(self) -> None:
        text = "Subject to covenants, conditions, and restrictions of record."
        clauses = TextParser.extract_deed_clauses(text)
        assert len(clauses) == 1
        assert clauses[0].clause_type == "subject_to"

"""Phase 5 Step 8: Witness Trees tests."""

from metesparser.text_parser import TextParser


class TestWitnessTrees:
    """Tests for witness tree / reference mark extraction."""

    def test_extract_single_witness_tree(self) -> None:
        text = "a white oak, 14 inches diameter, bears N 35\u00b0 W, 12 links distant"
        trees = TextParser.extract_witness_trees(text)
        assert len(trees) == 1
        assert "white oak" in trees[0]
        assert "14 inches" in trees[0]

    def test_extract_multiple_witness_trees(self) -> None:
        text = (
            "a white oak, 14 inches diameter, bears N 35\u00b0 W, 12 links distant; "
            "a hickory, 10 inches diameter, bears S 60\u00b0 E, 8 links distant"
        )
        trees = TextParser.extract_witness_trees(text)
        assert len(trees) == 2

    def test_extract_witness_tree_with_bears(self) -> None:
        text = "a post oak 12 in dia bears N 22\u00b030' E 15 links dist"
        trees = TextParser.extract_witness_trees(text)
        assert len(trees) == 1

    def test_no_witness_trees(self) -> None:
        text = "thence N 45\u00b0 E 100 feet to an iron pin found"
        trees = TextParser.extract_witness_trees(text)
        assert trees == []

    def test_witness_tree_preserves_verbatim(self) -> None:
        original = "a black walnut, 18 inches diameter, bears S 15\u00b0 W, 20 links distant"
        trees = TextParser.extract_witness_trees(original)
        assert len(trees) == 1
        assert trees[0] == original.strip()

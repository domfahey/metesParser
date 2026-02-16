"""Phase 5 Step 4: Natural Monument Classification tests."""

from metesparser.call_extractor import MonumentClassifier


class TestNaturalMonumentClassification:
    """Tests for natural monument classification."""

    # Tree patterns
    def test_classify_oak_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a white oak tree") == "tree"

    def test_classify_hickory_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a hickory tree, 14 inches diameter") == "tree"

    def test_classify_pine_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a pine tree") == "tree"

    def test_classify_elm_tree(self) -> None:
        assert MonumentClassifier.classify_monument("an elm tree") == "tree"

    def test_classify_walnut_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a black walnut") == "tree"

    def test_classify_sycamore_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a sycamore tree") == "tree"

    def test_classify_generic_tree(self) -> None:
        assert MonumentClassifier.classify_monument("a marked tree") == "tree"

    # Rock patterns
    def test_classify_rock_outcrop(self) -> None:
        assert MonumentClassifier.classify_monument("a rock outcrop") == "rock"

    def test_classify_standing_rock(self) -> None:
        assert MonumentClassifier.classify_monument("a standing rock") == "rock"

    def test_classify_large_rock(self) -> None:
        assert MonumentClassifier.classify_monument("a large rock") == "rock"

    def test_classify_boulder(self) -> None:
        assert MonumentClassifier.classify_monument("a boulder") == "rock"

    # Natural feature patterns
    def test_classify_stream(self) -> None:
        assert MonumentClassifier.classify_monument("center of the stream") == "natural_feature"

    def test_classify_creek(self) -> None:
        assert MonumentClassifier.classify_monument("bank of Bear Creek") == "natural_feature"

    def test_classify_river(self) -> None:
        assert MonumentClassifier.classify_monument("edge of the river") == "natural_feature"

    def test_classify_ridge(self) -> None:
        assert MonumentClassifier.classify_monument("top of the ridge") == "natural_feature"

    def test_classify_shoreline(self) -> None:
        assert MonumentClassifier.classify_monument("the shoreline") == "natural_feature"

    # Priority: artificial monuments should still match first
    def test_stone_monument_still_matches_stone(self) -> None:
        assert MonumentClassifier.classify_monument("a stone monument") == "stone"

    def test_iron_pin_still_matches(self) -> None:
        assert MonumentClassifier.classify_monument("iron pin found") == "iron_pin"

    def test_no_monument_returns_none(self) -> None:
        assert MonumentClassifier.classify_monument("to a point on the boundary") is None

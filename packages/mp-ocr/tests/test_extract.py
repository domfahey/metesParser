"""Verify PDF processor extraction logic."""


def test_compute_llm_confidence_high():
    from mp_ocr.extract import compute_llm_confidence

    text = (
        "BEGINNING at an iron pin found in the Southerly line of Elm Street; "
        "thence South 56 degrees 40 minutes East, a distance of 150.00 feet; "
        "thence North 33 degrees 20 minutes East, 125.00 feet; "
        "thence North 56 degrees 40 minutes West, 150.00 feet; "
        "to the POINT OF BEGINNING. "
        "Section 12, Township 3N, Range 2W. "
        "CONTAINING 0.43 acres more or less."
    )
    confidence, signals = compute_llm_confidence(text)
    assert confidence > 0.7
    assert signals["has_pob"] is True
    assert signals["has_bearing_calls"] is True


def test_compute_llm_confidence_low():
    from mp_ocr.extract import compute_llm_confidence

    confidence, signals = compute_llm_confidence("This is not a legal description at all.")
    assert confidence < 0.3

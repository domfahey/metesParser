"""PR #60 round 7: the review packet never shows an undetermined perimeter as a value."""

from metesparser.review_packet import build_closure_section


def test_review_packet_reports_undetermined_perimeter():
    gt = {"expected_closure": {"perimeter_ft": 0.0, "perimeter_available": False}}
    html = build_closure_section(gt)
    assert "<th>Perimeter (ft)</th><td>not determined</td>" in html


def test_review_packet_keeps_available_perimeter():
    gt = {"expected_closure": {"perimeter_ft": 400.0}}
    assert "<th>Perimeter (ft)</th><td>400.0</td>" in build_closure_section(gt)

"""The validator and producer share one finite-only bounds implementation."""

import math

from mp_review import webmap as review_webmap
from mp_verify import webmap as verify_webmap


def test_bounds_of_is_shared():
    assert review_webmap.bounds_of is verify_webmap.bounds_of


def test_bounds_of_drops_non_finite_points():
    points = [(0.0, 1.0), (math.nan, 5.0), (2.0, math.inf), (3.0, 4.0)]
    assert verify_webmap.bounds_of(points) == (0.0, 1.0, 3.0, 4.0)
    assert verify_webmap.bounds_of([(math.nan, 0.0)]) is None
    assert verify_webmap.bounds_of([]) is None

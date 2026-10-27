"""Validate declared projected scene semantics without a mandatory GIS dependency.

Local/deed-only dashboards never import pyproj. Projected scenes require the geo
extra even when supplied directly instead of through the overlay importer.
"""

from __future__ import annotations

import math
from typing import Any

from mp_models.plot import LinearUnit, PlotScene

_FACTORS: dict[LinearUnit, float] = {
    "m": 1.0,
    "international_ft": 0.3048,
    "us_survey_ft": 1200 / 3937,
}


def projected_crs_unit(crs: Any) -> LinearUnit:
    """Require two projected linear axes with one supported exact unit definition."""
    if not crs.is_projected or len(crs.axis_info) != 2:
        raise ValueError(
            "Scene CRS must have two projected linear axes; geographic degrees are not linear units"
        )
    factors = tuple(axis.unit_conversion_factor for axis in crs.axis_info)
    if any(not math.isfinite(factor) or factor <= 0 for factor in factors):
        raise ValueError("Scene CRS has unavailable or invalid linear units")
    for unit, expected in _FACTORS.items():
        if all(math.isclose(factor, expected, rel_tol=1e-12, abs_tol=1e-15) for factor in factors):
            return unit
    raise ValueError("Scene CRS has unsupported, ambiguous, or differing axis units")


def validate_scene(scene: PlotScene) -> None:
    """Check metadata against the CRS, rather than trusting its declared label."""
    if scene.axis_order != "xy":
        raise ValueError("Scene coordinates must use explicit normalized XY axis order")
    if scene.kind == "local":
        if scene.crs is not None:
            raise ValueError("Local scenes cannot declare a geographic/projected CRS")
        return
    try:
        from pyproj import CRS
    except ImportError as exc:
        raise ValueError("Install mp-review[geo] to validate supplied projected scenes.") from exc
    try:
        crs = CRS.from_user_input(scene.crs)
        native_unit = projected_crs_unit(crs)
    except Exception as exc:
        raise ValueError(f"Invalid projected scene CRS: {exc}") from exc
    if native_unit != scene.units:
        raise ValueError(
            f"Scene units {scene.units!r} conflict with CRS linear units {native_unit!r}"
        )

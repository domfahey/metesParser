"""Shared analytic SVG primitives and local viewport fitting (no browser math)."""

from collections.abc import Callable, Sequence
from math import hypot

from mp_models.plot import XY, PlotPrimitive
from mp_verify.plot import arc_point


def _identity(value: XY) -> XY:
    return value


def primitive_svg_path(
    primitive: PlotPrimitive, point: Callable[[XY], XY] = _identity
) -> tuple[str, tuple[XY, ...]]:
    """Project one analytic course into SVG's inverted Y axis.

    Arc bounds conservatively include the circle, including transformed placements.
    Full circles use two arcs because coincident SVG endpoints draw no single arc.
    """
    start, end = point(primitive.start), point(primitive.end)
    bounds = [start, end]
    path = f"M {start[0]:.17g} {-start[1]:.17g} "
    if primitive.kind == "arc":
        assert primitive.center is not None and primitive.sweep_deg is not None
        center = point(primitive.center)
        radius = hypot(start[0] - center[0], start[1] - center[1])
        bounds.extend(
            ((center[0] - radius, center[1] - radius), (center[0] + radius, center[1] + radius))
        )
        sweep = int(primitive.curve_dir == "right")
        if primitive.sweep_deg == 360:
            middle = point(arc_point(primitive, 0.5))
            path += f"A {radius:.17g} {radius:.17g} 0 0 {sweep} {middle[0]:.17g} {-middle[1]:.17g} "
            path += f"A {radius:.17g} {radius:.17g} 0 0 {sweep} {end[0]:.17g} {-end[1]:.17g}"
        else:
            path += f"A {radius:.17g} {radius:.17g} 0 {int(primitive.sweep_deg > 180)} {sweep} {end[0]:.17g} {-end[1]:.17g}"
    else:
        path += f"L {end[0]:.17g} {-end[1]:.17g}"
    return path, tuple(bounds)


def fitted_viewbox(bounds: Sequence[XY]) -> tuple[str, float, float]:
    """Return a padded SVG viewBox and nonzero native width and height."""
    points = bounds or [(0.0, 0.0), (100.0, 100.0)]
    min_x, max_x = min(p[0] for p in points), max(p[0] for p in points)
    min_y, max_y = min(p[1] for p in points), max(p[1] for p in points)
    width, height = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
    pad = max(width, height) * 0.14
    return (
        f"{min_x - pad:.17g} {-max_y - pad:.17g} {width + 2 * pad:.17g} {height + 2 * pad:.17g}",
        width,
        height,
    )

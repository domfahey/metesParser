"""The backward-compatible package exposes the deterministic plot implementation."""


def test_plot_facade_uses_package_geometry():
    from mp_verify import plot

    from metesparser.plot import build_dashboard_plots, compare_points, transform_point

    assert build_dashboard_plots is plot.build_dashboard_plots
    assert compare_points is plot.compare_points
    assert transform_point is plot.transform_point

"""The backward-compatible package exposes the deterministic plot implementation."""


def test_plot_facade_uses_package_geometry():
    from mp_verify import plot

    from metesparser.plot import build_dashboard_plots, compare_points, transform_point

    assert build_dashboard_plots is plot.build_dashboard_plots
    assert compare_points is plot.compare_points
    assert transform_point is plot.transform_point


def test_standalone_plot_facade_uses_shared_package_implementation():
    from mp_models.plot_request import PlotRequest
    from mp_review.plot import plot_file
    from mp_verify.plot import prepare_plot, validate_prepared_plot

    from metesparser import plot

    assert plot.PlotRequest is PlotRequest
    assert plot.plot_file is plot_file
    assert plot.prepare_plot is prepare_plot
    assert plot.validate_prepared_plot is validate_prepared_plot

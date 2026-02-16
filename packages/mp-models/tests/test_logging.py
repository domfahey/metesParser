"""Verify logging config is importable from mp_models."""

import io


def test_configure_logging_importable():
    from mp_models.logging import configure_logging, get_log_format

    buf = io.StringIO()
    configure_logging(level="WARNING", log_format="console", stream=buf)
    assert get_log_format() == "console"

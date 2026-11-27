"""Behavioral tests for mp_models structured logging configuration."""

from __future__ import annotations

import io
import json
import logging

import mp_models.logging as mp_logging
import pytest
import structlog
from mp_models.logging import configure_logging, get_log_format


@pytest.fixture(autouse=True)
def _restore_logging_state():
    root_logger = logging.getLogger()
    orig_root_handlers = list(root_logger.handlers)
    orig_root_level = root_logger.level
    orig_pkg_state = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in mp_logging._PACKAGE_LOGGER_NAMES
    }
    orig_structlog_config = dict(structlog.get_config())
    orig_format = mp_logging._CURRENT_FORMAT
    orig_owns_warnings = mp_logging._OWNS_WARNING_CAPTURE
    orig_warnings_captured = getattr(logging, "_warnings_showwarning", None) is not None
    try:
        yield
    finally:
        for h in list(root_logger.handlers):
            root_logger.removeHandler(h)
            if h not in orig_root_handlers:
                h.close()
        for h in orig_root_handlers:
            root_logger.addHandler(h)
        root_logger.setLevel(orig_root_level)
        for name, (handlers, level, propagate) in orig_pkg_state.items():
            pkg_logger = logging.getLogger(name)
            for h in list(pkg_logger.handlers):
                pkg_logger.removeHandler(h)
                if h not in handlers:
                    h.close()
            for h in handlers:
                pkg_logger.addHandler(h)
            pkg_logger.setLevel(level)
            pkg_logger.propagate = propagate
        structlog.configure(**orig_structlog_config)
        mp_logging._CURRENT_FORMAT = orig_format
        mp_logging._OWNS_WARNING_CAPTURE = orig_owns_warnings
        logging.captureWarnings(orig_warnings_captured)


def test_configure_logging_console_and_json_formats_and_env(monkeypatch):
    monkeypatch.setenv("METESPARSER_LOG_LEVEL", "INFO")
    monkeypatch.setenv("METESPARSER_LOG_FORMAT", "json")

    buf = io.StringIO()
    configure_logging(stream=buf)
    assert get_log_format() == "json"

    log = structlog.get_logger("mp_models.test_json")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        log.exception("failed_step", course=2)

    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "failed_step"
    assert payload["course"] == 2
    assert payload["level"] == "error"
    assert "exception" in payload

    # Reconfiguring replaces handlers cleanly without duplicate output.
    buf2 = io.StringIO()
    configure_logging(level="WARNING", log_format="console", stream=buf2)
    assert get_log_format() == "console"
    structlog.get_logger("mp_models.test_console").info("filtered_out")
    structlog.get_logger("mp_models.test_console").warning("visible_warning")
    output = buf2.getvalue()
    assert "filtered_out" not in output
    assert "visible_warning" in output


def test_configure_logging_debug_adds_callsite_and_rejects_invalid_inputs():
    buf = io.StringIO()
    configure_logging(level="WARNING", log_format="json", debug=True, stream=buf)
    structlog.get_logger("mp_models.test_debug").debug("trace_event")
    payload = json.loads(buf.getvalue().strip())
    assert payload["level"] == "debug"
    assert payload["filename"] == "test_logging.py"
    assert (
        payload["func_name"]
        == "test_configure_logging_debug_adds_callsite_and_rejects_invalid_inputs"
    )
    assert isinstance(payload["lineno"], int)

    with pytest.raises(ValueError, match="Invalid log level"):
        configure_logging(level="NOT_A_LEVEL", stream=buf)
    with pytest.raises(ValueError, match="Invalid log format"):
        configure_logging(log_format="xml", stream=buf)


def test_configure_logging_take_over_root_and_restore_package_scoped():
    root_logger = logging.getLogger()
    # Detach pytest's root handlers (e.g., --log-file) without closing them before take_over_root=True
    # clears root handlers; _restore_logging_state re-attaches them in teardown.
    root_logger.handlers.clear()
    buf = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=buf, take_over_root=True)
    assert root_logger.level == logging.INFO
    pkg_logger = logging.getLogger("mp_models")
    assert pkg_logger.handlers == []
    assert pkg_logger.propagate is True

    structlog.get_logger("mp_models.root_check").info("via_root")
    assert json.loads(buf.getvalue().strip())["event"] == "via_root"

    # Switching back to package-scoped disables root warning capture and stops propagation.
    buf2 = io.StringIO()
    configure_logging(level="WARNING", log_format="console", stream=buf2, take_over_root=False)
    assert pkg_logger.propagate is False
    assert len(pkg_logger.handlers) == 1


def test_logging_tests_do_not_break_caplog_propagation(caplog: pytest.LogCaptureFixture) -> None:
    """Package loggers must still propagate to root after configure_logging tests run."""
    assert logging.getLogger("mp_parse").propagate is True
    with caplog.at_level(logging.DEBUG, logger="mp_parse.calls"):
        logging.getLogger("mp_parse.calls").debug("probe_event")
    assert any(r.getMessage() == "probe_event" for r in caplog.records)

from __future__ import annotations

import io
import json
import logging
import warnings

import pytest
import structlog

from metesparser.logging_config import configure_logging, get_log_format

pytestmark = pytest.mark.usefixtures("isolate_logging_state")


def _json_lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_configure_logging_emits_structured_events_for_structlog_and_stdlib() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=stream)

    structlog.get_logger("metesparser.test").info("structured event", parcel_id="P-101")
    logging.getLogger("metesparser.stdlib").warning("stdlib warning")

    lines = _json_lines(stream)

    assert lines[0]["event"] == "structured event"
    assert lines[0]["level"] == "info"
    assert lines[0]["logger"] == "metesparser.test"
    assert lines[0]["parcel_id"] == "P-101"

    assert lines[1]["event"] == "stdlib warning"
    assert lines[1]["level"] == "warning"
    assert lines[1]["logger"] == "metesparser.stdlib"


def test_configure_logging_debug_adds_callsite_metadata() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", debug=True, stream=stream)

    structlog.get_logger("metesparser.debug").debug("debug event")

    line = _json_lines(stream)[0]

    assert line["event"] == "debug event"
    assert line["level"] == "debug"
    assert "filename" in line
    assert "func_name" in line
    assert "lineno" in line


def test_configure_logging_json_emits_structured_tracebacks() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=stream)

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.get_logger("metesparser.test").exception("operation failed")

    line = _json_lines(stream)[0]

    assert line["event"] == "operation failed"
    assert isinstance(line["exception"], list)
    assert line["exception"][0]["exc_type"] == "RuntimeError"


def test_configure_logging_closes_previous_root_handlers_when_taking_over_root() -> None:
    class TrackingHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.closed_called = False

        def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - noop
            return

        def close(self) -> None:
            self.closed_called = True
            super().close()

    root_logger = logging.getLogger()
    original_root_handlers = list(root_logger.handlers)
    previous = TrackingHandler()
    root_logger.handlers[:] = [previous]

    try:
        configure_logging(
            level="INFO",
            log_format="json",
            stream=io.StringIO(),
            take_over_root=True,
        )

        assert previous.closed_called is True
        assert previous not in root_logger.handlers
    finally:
        root_logger.handlers[:] = original_root_handlers


def test_configure_logging_default_mode_preserves_existing_root_handlers() -> None:
    class TrackingHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.closed_called = False

        def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - noop
            return

        def close(self) -> None:
            self.closed_called = True
            super().close()

    root_logger = logging.getLogger()
    original_root_handlers = list(root_logger.handlers)
    root_handler = TrackingHandler()
    root_logger.handlers[:] = [root_handler]

    package_logger = logging.getLogger("metesparser")
    original_package_handlers = list(package_logger.handlers)
    original_propagate = package_logger.propagate

    try:
        configure_logging(level="INFO", log_format="json", stream=io.StringIO())

        assert root_handler.closed_called is False
        assert root_handler in root_logger.handlers
    finally:
        root_logger.handlers[:] = original_root_handlers
        for handler in list(package_logger.handlers):
            package_logger.removeHandler(handler)
            if handler not in original_package_handlers:
                handler.close()
        package_logger.handlers[:] = original_package_handlers
        package_logger.propagate = original_propagate


def test_transition_from_package_mode_to_root_mode_routes_logs_to_root() -> None:
    package_stream = io.StringIO()
    root_stream = io.StringIO()

    root_logger = logging.getLogger()
    package_logger = logging.getLogger("metesparser")
    original_root_handlers = list(root_logger.handlers)
    original_package_handlers = list(package_logger.handlers)
    original_propagate = package_logger.propagate

    try:
        configure_logging(level="INFO", log_format="json", stream=package_stream)
        configure_logging(level="INFO", log_format="json", stream=root_stream, take_over_root=True)

        structlog.get_logger("metesparser.transition").info("transition event")

        package_lines = _json_lines(package_stream)
        root_lines = _json_lines(root_stream)

        assert not package_lines
        assert any(line.get("event") == "transition event" for line in root_lines)
    finally:
        logging.captureWarnings(False)
        root_logger.handlers[:] = original_root_handlers
        for handler in list(package_logger.handlers):
            package_logger.removeHandler(handler)
            if handler not in original_package_handlers:
                handler.close()
        package_logger.handlers[:] = original_package_handlers
        package_logger.propagate = original_propagate


def test_transition_from_root_mode_to_package_mode_stops_warning_capture() -> None:
    root_stream = io.StringIO()
    package_stream = io.StringIO()

    root_logger = logging.getLogger()
    package_logger = logging.getLogger("metesparser")
    original_root_handlers = list(root_logger.handlers)
    original_package_handlers = list(package_logger.handlers)
    original_propagate = package_logger.propagate

    try:
        configure_logging(level="INFO", log_format="json", stream=root_stream, take_over_root=True)
        configure_logging(level="INFO", log_format="json", stream=package_stream)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            warnings.warn("transition warning", UserWarning, stacklevel=2)

        assert len(caught) == 1
        assert not _json_lines(root_stream)
        assert not _json_lines(package_stream)
    finally:
        logging.captureWarnings(False)
        root_logger.handlers[:] = original_root_handlers
        for handler in list(package_logger.handlers):
            package_logger.removeHandler(handler)
            if handler not in original_package_handlers:
                handler.close()
        package_logger.handlers[:] = original_package_handlers
        package_logger.propagate = original_propagate


def test_get_log_format_reflects_latest_configuration() -> None:
    configure_logging(level="INFO", log_format="json", stream=io.StringIO())
    assert get_log_format() == "json"

    configure_logging(level="INFO", log_format="console", stream=io.StringIO())
    assert get_log_format() == "console"


def test_configure_logging_rejects_invalid_settings() -> None:
    with pytest.raises(ValueError, match="Invalid log level"):
        configure_logging(level="VERBOSE", stream=io.StringIO())

    with pytest.raises(ValueError, match="Invalid log format"):
        configure_logging(log_format="yaml", stream=io.StringIO())


_PACKAGE_LOGGER_NAMES = (
    "mp_models",
    "mp_bearing",
    "mp_ocr",
    "mp_parse",
    "mp_verify",
    "mp_export",
    "mp_review",
)


def test_library_mode_routes_package_warnings_to_configured_handler() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=stream)

    structlog.get_logger("mp_parse.calls").warning("Skipping malformed call", course=3)

    lines = _json_lines(stream)

    assert lines[0]["event"] == "Skipping malformed call"
    assert lines[0]["level"] == "warning"
    assert lines[0]["logger"] == "mp_parse.calls"
    assert lines[0]["course"] == 3


def test_library_mode_reconfigure_does_not_duplicate_package_output() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=stream)
    configure_logging(level="INFO", log_format="json", stream=stream)

    structlog.get_logger("mp_verify.closure").warning("closure warning")

    assert [line["event"] for line in _json_lines(stream)] == ["closure warning"]
    for name in _PACKAGE_LOGGER_NAMES:
        assert len(logging.getLogger(name).handlers) == 1

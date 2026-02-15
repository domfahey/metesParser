from __future__ import annotations

import io
import json
import logging

import pytest
import structlog

from metesparser.logging_config import configure_logging


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


def test_configure_logging_rejects_invalid_settings() -> None:
    with pytest.raises(ValueError, match="Invalid log level"):
        configure_logging(level="VERBOSE", stream=io.StringIO())

    with pytest.raises(ValueError, match="Invalid log format"):
        configure_logging(log_format="yaml", stream=io.StringIO())

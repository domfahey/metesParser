"""Centralized structlog + stdlib logging configuration."""

from __future__ import annotations

import logging
import os
import sys
from typing import TextIO

import structlog
from structlog.processors import CallsiteParameter, CallsiteParameterAdder

_DEFAULT_LEVEL = "INFO"
_DEFAULT_FORMAT = "console"
_VALID_FORMATS = {"console", "json"}


def _normalize_level(level: str) -> str:
    normalized = level.strip().upper()
    if normalized not in logging.getLevelNamesMapping():
        raise ValueError(
            f"Invalid log level '{level}'. Use standard levels like DEBUG/INFO/WARNING."
        )
    return normalized


def _normalize_format(log_format: str) -> str:
    normalized = log_format.strip().lower()
    if normalized not in _VALID_FORMATS:
        raise ValueError(f"Invalid log format '{log_format}'. Use one of: console, json.")
    return normalized


def configure_logging(
    level: str | None = None,
    *,
    log_format: str | None = None,
    debug: bool = False,
    stream: TextIO | None = None,
) -> None:
    """Configure structured logging for CLI and library code.

    Args:
        level: Standard Python logging level name.
        log_format: Output format (`console` or `json`).
        debug: Enable debug-friendly options (DEBUG level + callsite metadata).
        stream: Optional stream override for tests.
    """
    resolved_level = _normalize_level(level or os.getenv("METESPARSER_LOG_LEVEL", _DEFAULT_LEVEL))
    resolved_format = _normalize_format(
        log_format or os.getenv("METESPARSER_LOG_FORMAT", _DEFAULT_FORMAT)
    )

    if debug:
        resolved_level = "DEBUG"

    level_num = logging.getLevelNamesMapping()[resolved_level]
    include_callsite = debug or resolved_level == "DEBUG"

    shared_processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    if include_callsite:
        shared_processors.append(
            CallsiteParameterAdder(
                {
                    CallsiteParameter.FILENAME,
                    CallsiteParameter.FUNC_NAME,
                    CallsiteParameter.LINENO,
                }
            )
        )

    shared_processors.extend(
        [
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
        ]
    )

    renderer: structlog.typing.Processor
    if resolved_format == "json":
        renderer = structlog.processors.JSONRenderer(sort_keys=True)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers[:] = [handler]
    root_logger.setLevel(level_num)

    logging.captureWarnings(True)
    structlog.contextvars.clear_contextvars()

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

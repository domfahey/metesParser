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
_CURRENT_FORMAT = _DEFAULT_FORMAT
_OWNS_WARNING_CAPTURE = False
# Composable packages log via structlog with stdlib logger names (e.g. mp_parse.calls).
_PACKAGE_LOGGER_NAMES = (
    "mp_models",
    "mp_bearing",
    "mp_ocr",
    "mp_parse",
    "mp_verify",
    "mp_export",
    "mp_review",
)


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


def get_log_format() -> str:
    """Return currently configured logging format (`console` or `json`)."""
    return _CURRENT_FORMAT


def _clear_handlers(target_logger: logging.Logger) -> None:
    previous_handlers = list(target_logger.handlers)
    for previous_handler in previous_handlers:
        target_logger.removeHandler(previous_handler)
        previous_handler.close()


def _replace_handlers(target_logger: logging.Logger, handler: logging.Handler) -> None:
    _clear_handlers(target_logger)
    target_logger.addHandler(handler)


def configure_logging(
    level: str | None = None,
    *,
    log_format: str | None = None,
    debug: bool = False,
    stream: TextIO | None = None,
    take_over_root: bool = False,
) -> None:
    """Configure structured logging for CLI and library code.

    Args:
        level: Standard Python logging level name.
        log_format: Output format (`console` or `json`).
        debug: Enable debug-friendly options (DEBUG level + callsite metadata).
        stream: Optional stream override for tests.
        take_over_root: Replace root logger handlers (preferred for CLI entrypoints).
    """
    resolved_level_value: str | None = level or os.getenv("METESPARSER_LOG_LEVEL")
    resolved_level = _normalize_level(resolved_level_value or _DEFAULT_LEVEL)
    resolved_format = _normalize_format(
        (log_format or os.getenv("METESPARSER_LOG_FORMAT")) or _DEFAULT_FORMAT
    )

    if debug:
        resolved_level = "DEBUG"

    level_num = logging.getLevelNamesMapping()[resolved_level]
    include_callsite = debug or resolved_level == "DEBUG"

    exception_processor: structlog.typing.Processor
    renderer: structlog.typing.Processor
    if resolved_format == "json":
        exception_processor = structlog.processors.dict_tracebacks
        renderer = structlog.processors.JSONRenderer(sort_keys=True)
    else:
        exception_processor = structlog.processors.format_exc_info
        renderer = structlog.dev.ConsoleRenderer(colors=False)

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
            exception_processor,
            structlog.processors.UnicodeDecoder(),
        ]
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(formatter)

    package_logger = logging.getLogger("metesparser")

    global _CURRENT_FORMAT
    global _OWNS_WARNING_CAPTURE

    if take_over_root:
        root_logger = logging.getLogger()
        _replace_handlers(root_logger, handler)
        root_logger.setLevel(level_num)

        # Remove stale package handlers from prior non-root configuration.
        _clear_handlers(package_logger)
        package_logger.setLevel(logging.NOTSET)
        package_logger.propagate = True
        for package_name in _PACKAGE_LOGGER_NAMES:
            stale_logger = logging.getLogger(package_name)
            _clear_handlers(stale_logger)
            stale_logger.setLevel(logging.NOTSET)
            stale_logger.propagate = True

        logging.captureWarnings(True)
        _OWNS_WARNING_CAPTURE = True
    else:
        _replace_handlers(package_logger, handler)
        package_logger.setLevel(level_num)
        package_logger.propagate = False
        for package_name in _PACKAGE_LOGGER_NAMES:
            # Package loggers are not children of 'metesparser'; attach the same handler.
            package_scoped_logger = logging.getLogger(package_name)
            _replace_handlers(package_scoped_logger, handler)
            package_scoped_logger.setLevel(level_num)
            package_scoped_logger.propagate = False

        # If root warning capture was enabled by this module, disable it when returning
        # to package-scoped logging.
        if _OWNS_WARNING_CAPTURE:
            logging.captureWarnings(False)
            _OWNS_WARNING_CAPTURE = False

    structlog.contextvars.clear_contextvars()

    _CURRENT_FORMAT = resolved_format

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

"""Single JSON-reading boundary for CLI-reachable inputs.

Every loader parses through ``parse_json``/``read_json_input`` so that recursion caused by
deeply nested input (the decoder or the finiteness walk that guards later validators) is
reported as ``InvalidInputJson``, while recursion elsewhere stays an internal failure.
"""

import contextlib
import json
import math
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any


class InvalidInputJson(Exception):
    """Input JSON is nested too deeply to load or validate."""


@contextlib.contextmanager
def input_boundary() -> Iterator[None]:
    """Input-loading phase: recursion inside it means the supplied JSON is too deep."""
    try:
        yield
    except RecursionError as exc:
        raise InvalidInputJson from exc


def finite_json(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite JSON number")
    if isinstance(value, dict):
        for item in value.values():
            finite_json(item)
    elif isinstance(value, list):
        for item in value:
            finite_json(item)


def parse_json(
    data: str | bytes,
    *,
    object_pairs_hook: Callable[[list[tuple[str, Any]]], Any] | None = None,
    parse_constant: Callable[[str], Any] | None = None,
) -> Any:
    """Decode and depth/finiteness-check JSON inside the input boundary; return the value."""
    with input_boundary():
        value = json.loads(data, object_pairs_hook=object_pairs_hook, parse_constant=parse_constant)
        finite_json(value)
    return value


def read_json_input(path: Path, **hooks: Any) -> Any:
    """Read a JSON file once and return its parsed value (see ``parse_json``)."""
    return parse_json(Path(path).read_bytes(), **hooks)

"""Rule-based parsing for metes and bounds legal descriptions."""

from .numbers import COMMA_NUMBER, parse_comma_number

__version__ = "1.0.0"

__all__ = [
    "COMMA_NUMBER",
    "parse_comma_number",
]

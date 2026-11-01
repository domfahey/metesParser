"""Shared numeric parsing utilities."""

import re

COMMA_NUMBER = r"\d[\d,]*(?:\.\d+)?"

# "300,07": a single comma followed by exactly two digits is a decimal point, as some
# deeds print it. Thousands separators are always followed by three digits.
_DECIMAL_COMMA = re.compile(r"\d+,\d{2}")


def parse_comma_number(s: str) -> float:
    """Parse a number string with optional commas. '1,200.50' -> 1200.5, '300,07' -> 300.07"""
    if _DECIMAL_COMMA.fullmatch(s):
        return float(s.replace(",", "."))
    return float(s.replace(",", ""))

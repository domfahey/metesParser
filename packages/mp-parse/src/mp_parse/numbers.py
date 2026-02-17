"""Shared numeric parsing utilities."""

COMMA_NUMBER = r"\d[\d,]*(?:\.\d+)?"


def parse_comma_number(s: str) -> float:
    """Parse a number string with optional commas. '1,200.50' -> 1200.5"""
    return float(s.replace(",", ""))

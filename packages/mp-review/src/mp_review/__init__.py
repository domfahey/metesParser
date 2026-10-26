"""Deterministic text-first deed review."""

from .api import ENGINE_VERSION, review_file, review_text, verify_file

__version__ = ENGINE_VERSION
__all__ = ["review_text", "review_file", "verify_file"]

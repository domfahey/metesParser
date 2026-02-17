"""Metes and Bounds Deed Parser.

Extract and parse legal descriptions from deed PDFs into structured CSV format.
"""

from .audit_reporter import AuditReporter
from .call_extractor import CallExtractor
from .closure_checker import ClosureChecker
from .csv_builder import CSVBuilder
from .models import AuditContext, LegalDescription
from .pdf_processor import PDFProcessor
from .pipeline import Pipeline
from .text_parser import TextParser

__version__ = "0.5.0"

__all__ = [
    "__version__",
    "AuditContext",
    "AuditReporter",
    "CallExtractor",
    "ClosureChecker",
    "CSVBuilder",
    "LegalDescription",
    "PDFProcessor",
    "Pipeline",
    "TextParser",
]

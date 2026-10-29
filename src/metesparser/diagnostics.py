"""Compatibility facade for deterministic advisory diagnostics operations."""

from mp_models.diagnostics import (
    CallSensitivity,
    ClosureDiagnosticRequest,
    ClosureDiagnostics,
    CurveParameterSensitivity,
    DiagnosticCall,
    DiagnosticFrame,
    DiagnosticResidual,
    DiagnosticSourceRef,
    DiagnosticVector,
    QuantizationAssumptions,
    QuantizationBound,
    diagnostic_input_hash,
)
from mp_review.diagnostics import diagnose_closure_file  # type: ignore[import-untyped]
from mp_verify.diagnostics import diagnose_closure

__all__ = [
    "CallSensitivity",
    "ClosureDiagnosticRequest",
    "ClosureDiagnostics",
    "CurveParameterSensitivity",
    "DiagnosticCall",
    "DiagnosticFrame",
    "DiagnosticResidual",
    "DiagnosticSourceRef",
    "DiagnosticVector",
    "QuantizationAssumptions",
    "QuantizationBound",
    "diagnostic_input_hash",
    "diagnose_closure_file",
    "diagnose_closure",
]

"""Validity: the check interface, shared types, check implementations, and composition."""

from finops_governor.validity.base import ValidityCheck
from finops_governor.validity.composition import resolve_verdict, summarize_findings
from finops_governor.validity.cost import CostCheck
from finops_governor.validity.models import (
    CheckContext,
    Finding,
    Severity,
    ValidityReport,
)

__all__ = [
    "CheckContext",
    "CostCheck",
    "Finding",
    "Severity",
    "ValidityCheck",
    "ValidityReport",
    "resolve_verdict",
    "summarize_findings",
]

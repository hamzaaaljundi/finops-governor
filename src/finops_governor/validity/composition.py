"""Composition precedence and audit summary (M3, Task 3.4).

Turns a ValidityReport (the findings from every axis) into a verdict and into a
human-readable audit line. Pure functions - no side effects - so the policy is testable
in isolation and stated in exactly one place.

Precedence (highest first):
  1. Any BLOCKING finding   -> BLOCK   (invalid/unsafe: do not run, do not modify)
  2. Any MODIFIABLE finding -> MODIFY  (recoverable: propose a fitting variant)
  3. Otherwise              -> APPROVE (clean, or warnings only)

BLOCKING dominates MODIFIABLE on purpose: if any axis says the job must not run, there is
no point proposing a cheaper variant of a fundamentally invalid job. Warnings are advisory
and never change the verdict, but - like all findings - they are recorded for audit.
"""

from finops_governor.gate.decision import Verdict
from finops_governor.validity.models import ValidityReport


def resolve_verdict(report: ValidityReport) -> Verdict:
    """Map a report to a verdict by severity precedence (see module docstring)."""
    if report.has_blocking:
        return Verdict.BLOCK
    if report.has_modifiable:
        return Verdict.MODIFY
    return Verdict.APPROVE


def summarize_findings(report: ValidityReport) -> str:
    """One audit line listing every finding as '[SEVERITY] check_name: reason'."""
    return " | ".join(f"[{f.severity.value}] {f.check_name}: {f.reason}" for f in report.findings)

# ADR 0001 — The LLM plans, but a deterministic gate decides

**Status:** Accepted

## Context

The system turns vague natural-language requests into expensive GPU jobs. An LLM
is well suited to the fuzzy decomposition step but is stochastic: the same prompt
can yield different plans, and it can hallucinate costs or validity.

## Decision

The LLM produces plans only. All go/no-go authority over spend lives in a
deterministic rules engine (cost thresholds + geometric checks) that returns
approve / modify / block. The LLM's output is advisory and is always validated
against a strict schema before the gate sees it.

## Consequences

- The gate is unit-testable: known plan + known budget → known verdict.
- Decisions are auditable and reproducible — a requirement for a FinOps control.
- The LLM can be swapped or fail without compromising spend safety.
- Cost: some flexibility is lost; "modify" logic must be authored explicitly
  rather than delegated to the model.
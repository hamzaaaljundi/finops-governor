# Architecture

## Trust boundary

Everything upstream of the gate is **advisory** (including the LLM). The gate is
the only component with authority to approve spend, and it is fully
deterministic: same plan + same budget + same scene → same verdict, every time.
This is what makes the governor testable and auditable.

## Stages

1. **Planning Agent (LLM)** — decomposes a natural-language request into a
   structured, schema-valid plan. Fuzzy, stochastic, *advisory only*.
2. **Cost Estimator** — deterministic: plan → GPU-hours → dollars.
3. **Budget Gate** — deterministic: compares cost to budget.
4. **Validity Gate (OpenUSD)** — deterministic: checks the scene graph for
   asset existence, bounds, collisions, plausible poses — pre-render.
5. **Verdict** — approve / modify / block. "Modify" loops back to re-plan.
6. **Execution stub** — fires only on approve.
7. **Audit log** — records every decision with its cost basis and reasoning.
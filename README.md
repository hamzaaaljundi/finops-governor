# FinOps Governor for Synthetic Data Pipelines

A control layer between a plain-English synthetic-data request and the GPU job
that fulfills it. An LLM plans the job; a **deterministic gate** decides whether
that plan is allowed to run. Nothing hits a GPU until it is proven both
**affordable** and **geometrically valid**.

## The core idea

The LLM does fuzzy planning. A deterministic rules engine makes the final
**approve / modify / block** decision. A stochastic model is never the last word
on budget or safety.

This governs **multimodal / digital-twin** synthetic data — rendered scenes,
depth, segmentation, poses — where jobs can quietly cost thousands in GPU time
and a scene can be geometrically invalid (e.g. a robot arm clipping the floor).

## How it works

​```mermaid
flowchart TD
    A[NL Request] --> B[Planning Agent · LLM]
    B --> C[Structured Plan]
    C --> D[Cost Estimator]
    D --> E{Deterministic Gate}
    E -->|approve| F[Execution Stub]
    E -->|modify| B
    E -->|block| G[Halt + Log]
    F --> H[Audit Log]
    G --> H
​```

The gate validates the **scene description** (the USD stage) *before* any render,
which preserves the "block before GPU spend" guarantee.

## Scope

**In scope:** NL → structured plan · pre-execution cost estimate ·
deterministic budget + geometric-validity gate · execution stub · audit trail.

**Out of scope:** running large-scale generation (execution is stubbed — the
*governance* is the product) · GPU autoscaling · downstream model training ·
validating rendered output images.

## What this is

A **pre-flight gate for training-value-per-GPU-dollar** in synthetic-data generation.
Before a single frame renders, it refuses jobs that are **over budget**, **geometrically
invalid**, or **predictably low training-value** - and tells you, in dollars, how much of
a job's spend would be wasted.

> _"scene 'floor': 50,000 variations across ~16 declared configurations (~3,125x
> oversampled, ~100% redundant); est. $373.18 of spend adds little training value."_

The three checks are one idea: each is a reason **not to spend GPU-hours on this job,
catchable before you spend**. An LLM proposes plans; a deterministic gate decides. The
headline axis - diversity/redundancy gating - catches the expensive failure no standard
tool catches pre-execution: spending on data that's affordable and renderable but teaches
the model almost nothing.

## Status

- **M1** (`v0.1-schema`): the `GenerationPlan` contract + randomization block.
- **M2** (`v0.2-deterministic-gate`): deterministic cost estimator + budget gate.
- **M3** (`v0.3-validity-gate`): the multi-axis Governor - checks composed into one decision.
- **M4** (`v0.4-diversity-gate`): **the diversity/redundancy gate** - a pre-execution
  estimate of wasted, low-training-value spend, quantified in dollars.
- **Next: M5 - the OpenUSD geometric-validity gate** (one more axis on the same seam).

See [docs/diversity-model.md](./docs/diversity-model.md) and [docs/adr/](./docs/adr/).

## Quickstart

​```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
​```
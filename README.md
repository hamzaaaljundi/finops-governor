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

## Status

Under active construction — see [ROADMAP.md](./ROADMAP.md). Architecture
rationale in [docs/adr/](./docs/adr/).

## Quickstart

​```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
​```
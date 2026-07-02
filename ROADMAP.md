# Roadmap — Agentic FinOps Governor for Synthetic Data Pipelines

> A control layer between a plain-English synthetic-data request and the GPU job that fulfills it.
> An LLM plans the job; a **deterministic gate** decides whether that plan is allowed to run.
> Nothing hits a GPU until it is proven both **affordable** and **geometrically valid**.

---

## Thesis (read this first)

The LLM does fuzzy planning. A deterministic rules engine makes the final **approve / modify / block** decision. A stochastic model is never the last word on budget or safety. This is the whole point of the project, and the build order below reflects it: **the deterministic, testable spine is built before the stochastic planner is bolted on.**

This is a **multimodal / digital-twin** synthetic-data project — rendered scenes, images, depth, segmentation, poses — not tabular data. The FinOps premise (jobs that quietly cost thousands in GPU time) and the geometric-validity premise (a robot arm clipping through a floor) only exist for visual/3D generation.

---

## Scope

**In scope**
- Natural-language request → structured multimodal generation plan
- Pre-execution GPU cost estimate for every job
- Deterministic quality-and-budget gate: **approve / modify / block**
- Geometric validity checks on the *scene description* (USD stage), pre-render
- Execution stub that only fires on approve, with a full audit trail

**Out of scope (deliberately)**
- Running large-scale synthetic data generation (GPU execution is stubbed — the *governance* is the product)
- Real-time GPU autoscaling, multi-cloud cost arbitrage, full FinOps dashboards
- Training downstream models on the generated data
- Validating rendered *output images* (would require rendering first, defeating "block before spend")

---

## Milestone sequencing

Two build orders are viable:

- **Strict:** `M0 → M1 → M2 → M3 → M4 → M5 → M6`
- **Recommended:** pull the **M3 USD spike** forward to sit right after **M0**, to retire the biggest technical unknown in week one.

For a portfolio piece where a late-discovered dead end is costly, the early spike is the safer call.

Every milestone ends in something **showable** — a tagged release, a README section, a green test suite, or a demo transcript. Map each to a GitHub Milestone with issues underneath. Tag releases at **M2, M3, and M6** at minimum.

```
Request (NL)
   → [M4] Planning Agent (LLM)  → structured plan
   → [M2] Cost Estimator        → estimated GPU-hours + $
   → [M2] Budget Gate ┐
   → [M3] Validity Gate ┘       → approve / modify / block
   → [M5] Execution stub (fires only on approve)
   → [M5] Audit log
```

---

## M0 — Foundation & architecture

Establish the thesis so no one mistakes the scope. Repo scaffolding, README, architecture diagram, and a decision log explaining *why* the LLM plans but a deterministic gate decides.

**Definition of done:** someone landing on the repo cold understands the thesis in 60 seconds.

**GitHub artifacts:** `README.md`, `/docs/architecture.md`, `/docs/adr/0001-deterministic-gate.md`

- [ ] Initialize repo, license, `.gitignore`, Python project scaffold
- [ ] README with the one-liner, thesis, and explicit in-scope / out-of-scope statement
- [ ] Architecture diagram: request → plan → estimate → gate → execute
- [ ] ADR: "LLM plans, deterministic gate decides" — the reasoning, written down
- [ ] ADR: "Multimodal digital-twin framing, not tabular data"
- [ ] Set up GitHub Milestones + issue templates

---

## M1 — The plan contract

The Pydantic schema representing a **multimodal** generation plan. Load-bearing: everything downstream validates against it.

**Definition of done:** a hand-authored valid plan JSON parses; an invalid one fails cleanly with a useful error.

**GitHub artifacts:** `schemas/` with models, example plans, and schema tests

- [ ] Pydantic models: scene(s), variation count, render settings, asset references
- [ ] Output modalities modeled explicitly (RGB, depth, segmentation, 2D/3D boxes, pose)
- [ ] Example valid plan JSON files committed as fixtures
- [ ] Example invalid plans (missing fields, bad types) as negative fixtures
- [ ] Tests: valid plans parse, invalid plans raise
- [ ] Tag: `v0.1-schema`

---

## M2 — Deterministic spine: cost estimator + budget gate

The star of the project, built with **no LLM in sight**. Estimator maps plan → GPU-hours → dollars via a $/GPU-hour lookup table. Gate returns approve / modify / block, where **modify** holds the interesting logic (trim variation count or resolution to fit budget).

**Definition of done:** a thorough unit-test suite drives known plans → known verdicts, deterministically. This is the CI green-badge section.

**GitHub artifacts:** estimator + gate modules with a visibly thorough test suite; CI workflow

- [ ] Pricing lookup table (AWS/Azure $/GPU-hour) as data, not hardcoded
- [ ] Cost estimator: plan → GPU-hours → dollars, accounting for per-modality render cost
- [ ] Budget gate: (plan, cost, budget) → `approve | modify | block`
- [ ] "Modify" logic: trim variations / resolution to land inside budget, surface the change
- [ ] Unit tests covering all three verdicts + boundary cases (exactly at budget, 10× over)
- [ ] GitHub Actions CI running the suite on every push
- [ ] Tag: `v0.2-deterministic-gate`

---

## M3 — Geometric validity gate (OpenUSD)

The Physical AI teeth. Validate the **scene description** — the USD stage — before any render. Runs on the 3D representation, not output pixels, preserving the "block before GPU spend" guarantee.

**Definition of done:** a deliberately broken scene (arm clipping the floor, missing asset) is caught and returns block/modify.

**⚠ Highest technical risk.** De-risk with a throwaway spike *before* committing the milestone: prove you can load a USD stage and read one bounds/collision check. If the spike hurts, you want to know in week one.

**GitHub artifacts:** validation module + intentionally-invalid USD fixtures

- [ ] **Spike:** load a USD stage, read a single bounds/collision check (throwaway, timeboxed)
- [ ] Asset-existence check (referenced assets actually resolve)
- [ ] Bounds check (objects within the scene envelope)
- [ ] Collision / clipping check (arm not through the floor)
- [ ] Plausibility checks (pose, camera placement)
- [ ] Invalid USD fixtures demonstrating each catch
- [ ] Wire verdicts into the gate: validity failures → block/modify
- [ ] Tag: `v0.3-validity-gate`

---

## M4 — The planning agent (LLM)

The fuzzy front end: natural language → structured plan, output constrained to strictly emit the M1 schema. Built *after* the spine so the LLM is tested against a known-good contract — a malformed plan means the model, not your validation.

**Definition of done:** "generate 500 variations of a robotic arm on an assembly floor" produces a valid, sensible plan that flows into M2/M3.

**GitHub artifacts:** agent module, prompt, NL-request → plan transcripts

- [ ] Planning prompt that emits strict JSON matching the M1 schema
- [ ] Constrained / validated decoding — reject or repair off-schema output
- [ ] Decomposition: one request → scenes, variations, modalities, render settings
- [ ] Example transcripts: NL request → generated plan
- [ ] Failure-mode notes: what the model gets wrong, how the contract catches it
- [ ] Tag: `v0.4-planner`

---

## M5 — Orchestration + audit trail (LangGraph)

Wire the pieces into one state machine: plan → estimate → gate → execute, with conditional edges for approve/modify/block and a loop back to re-plan on **modify**. Add the execution stub (mock GPU job, fires only on approve) and structured logging.

**Definition of done:** a single request runs end-to-end and every verdict leaves an auditable log entry.

**GitHub artifacts:** graph definition, execution stub, sample audit logs for all three paths

- [ ] LangGraph state machine: plan → estimate → gate → execute
- [ ] Conditional edges: approve → execute, block → halt, modify → re-plan loop
- [ ] Execution stub: mock GPU job that only fires on approve
- [ ] Structured logging: every decision with cost basis + reasoning
- [ ] Sample audit logs demonstrating approve, block, and modify paths
- [ ] Tag: `v0.5-orchestration`

---

## M6 — Service, packaging & demo

FastAPI endpoint, containerization, and the demo layer: curated transcripts showing an approve, a block (10× over budget), and a modify (trimmed to fit).

**Definition of done:** clone, run, hit the endpoint with a request, watch a verdict come back.

**GitHub artifacts:** service, Dockerfile, demo transcripts, tagged `v1.0` release

- [ ] FastAPI endpoint accepting an NL request, returning a verdict + plan + cost
- [ ] Dockerfile + container build
- [ ] Curated demo: approve / block / modify transcripts
- [ ] README walkthrough: clone → run → request → verdict
- [ ] Release notes summarizing the deterministic-spine-first story
- [ ] Tag: `v1.0`

---

## Release map

| Tag | Milestone | Proves |
|-----|-----------|--------|
| `v0.1-schema` | M1 | The contract everything leans on exists |
| `v0.2-deterministic-gate` | M2 | Budget decisions are deterministic + tested |
| `v0.3-validity-gate` | M3 | Geometric invalidity is caught pre-render |
| `v0.4-planner` | M4 | NL → valid plan works |
| `v0.5-orchestration` | M5 | End-to-end flow with audit trail |
| `v1.0` | M6 | Clone-and-run service + demo |

The commit history tells the argument on its own: **deterministic spine first, LLM last.** That ordering is the signal — it shows you know where *not* to put the LLM.

# Service Model - Design Specification

> The design-on-paper artifact for **M8, Task 8.1**. Defines the HTTP surface, its
> contracts, the error model, and the v1.0 definition of done. Implementation (Task 8.3)
> transcribes this spec; the profile advisor (Task 8.2) adds one endpoint to it.
>
> **Status:** Accepted - **Milestone:** M8 - **Consumed by:** the FastAPI app (8.3), the demo (8.5)

---

## 1. What the service is (and is not)

A thin HTTP skin over the existing, fully tested core: the Governor and the
Orchestrator. The service layer adds **transport, not behavior** - no logic lives in it
that does not already exist behind it. It is a local / trusted-network tool with **no
authentication**, stated plainly: a spend gate deployed for real would sit behind an
organization's existing auth (a reverse proxy, a service mesh); bolting a toy API key
onto v1.0 would be security theater, and pretending otherwise is worse than saying so.

## 2. The endpoints

| Method + path | Body | Response | Mirrors |
|---|---|---|---|
| `POST /evaluate` | a `GenerationPlan` (the M1 contract, verbatim) | `GateDecision` | CLI evaluate mode: ONE gate pass |
| `POST /pipeline` | `{request, budget_usd, profile?, geometry?}` | `PipelineState` (the full audit trail) | CLI plan mode: the M7 pipeline |
| `POST /advise` | a `GenerationPlan` | per-profile cost ranking + recommendation | Task 8.2 (the FinOps advisor) |
| `GET /profiles` | - | the hardware profiles (the data behind the cost model) | discoverability |
| `GET /health` | - | `{"status": "ok"}` | liveness |

Two design consequences worth naming:

- **The existing contracts ARE the API contracts.** `/evaluate`'s request body is the
  M1 `GenerationPlan`; `/pipeline`'s response is the M7 `PipelineState` - serialized
  verbatim, zero new response models for the core surface. Six milestones of frozen,
  JSON-round-trippable Pydantic models pay off here: the API schema was built before the
  API was conceived.
- **`/evaluate` options travel as query parameters** (`?profile=a10g&geometry=true`)
  because the body is the plan itself, owned by the M1 schema; mixing transport options
  into it would pollute a tagged contract.

## 3. The status-code model (locked)

**HTTP codes describe the HTTP transaction, never the verdict.**

| Situation | Code | Body |
|---|---|---|
| Plan evaluated - APPROVE / MODIFY / **BLOCK** | 200 | the `GateDecision` |
| Pipeline ran - EXECUTED / **BLOCKED** / **FAILED** (planner exhaustion) | 200 | the `PipelineState`, trail included |
| Body is not a valid `GenerationPlan` / bad request shape | 422 | pydantic error detail (FastAPI default) |
| Unknown hardware profile | 400 | `{"detail": "unknown hardware profile: ..."}` |
| Upstream model unreachable (missing key, network, auth) | 502 | `{"detail": "model call failed: ..."}` |

Rationale: a BLOCK is the gate *working*; a FAILED pipeline still produced its audit
trail, and the trail is the deliverable even in failure (orchestration-model.md,
section 4). Clients branch on `verdict` / `status` in the body, not on HTTP codes -
the same philosophy as the CLI's exit codes, translated to HTTP's semantics.

## 4. Construction and testability

- **App factory:** `create_app(planner_model: PlannerModel | None = None) -> FastAPI`.
  The planner seam threads through the service layer: tests inject the scripted fake
  and drive every endpoint through `TestClient` - no network, no keys, CI-hermetic,
  exactly as the CLI's `main(argv, planner_model=...)` already works.
- **Governor wiring per request:** `profile` and `geometry` are request options, so the
  governor is constructed per call (construction is microseconds; statefulness would
  buy nothing and cost the option surface).
- **The live planner is constructed lazily** on the first `/pipeline` call without an
  injected model - same deferred-SDK discipline as the CLI.

## 5. Scope exclusions (the ADR 0008 discipline, applied to HTTP)

Deliberately absent from v1.0, each a named non-goal rather than an omission:

1. **No async job queue / no job IDs.** The pipeline completes in seconds (the LLM call
   dominates); request/response is honest. A queue becomes warranted when execution is
   real rendering - which is stubbed by M0 scope.
2. **No persistence.** The audit trail returns in the response; storing it is the
   caller's choice. A trail store is production work, not demo work.
3. **No auth** (section 1).
4. **No streaming.** Trail events could stream; at 5 events per run it is decoration.

## 6. v1.0 definition of done

v1.0 ships when all of the following are true, and nothing more:

1. `pip install` from TestPyPI works and installs a `finops-governor` console command
   (the `python -m` form remains).
2. The five endpoints above exist, typed, with `TestClient` coverage of every row of
   the status-code table.
3. The profile advisor (8.2) works in all three surfaces: library, CLI, API.
4. The README leads with a demo GIF: the redundant production job flagged, trimmed,
   adopted, executed, receipted - under 90 seconds.
5. Zero TODOs or "coming soon" in any doc; the suite, ruff, and mypy strict are green
   across 3.11-3.13.

Perfection is explicitly not the bar; the five items are.

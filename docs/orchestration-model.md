# Orchestration Model - Design Specification

> The design-on-paper artifact for **M7, Task 7.1**. Defines the pipeline state machine,
> the modify-handling strategy, the loop bounds, and the audit-event contract.
> Implementation (Tasks 7.2-7.4) transcribes this spec. The framework decision (plain
> Python over LangGraph) is ADR 0008.
>
> **Status:** Accepted - **Milestone:** M7 - **Consumed by:** the CLI (7.5) and any future service (M8)

---

## 1. What M7 adds

Six milestones built the organs: a planner, an estimator, a three-axis gate that builds
its own proposals. M7 is the nervous system - the loop that runs request -> plan ->
gate -> verdict -> action without a human relaying artifacts between commands - and the
**audit trail**: a structured, serializable record of what happened at every step and
which axis drove each decision. The orchestrator is deliberately small; the audit trail
is the deliverable a FinOps reviewer would actually demand from a spend gate.

## 2. The shape: node functions over typed state

The pipeline is a set of **pure functions over one immutable, typed state object**:

```
plan_node(state)    -> state     # NL request -> GenerationPlan (wraps the Planner)
gate_node(state)    -> state     # plan -> GateDecision (wraps the Governor)
adopt_node(state)   -> state     # MODIFY -> adopt the gate's proposal as the plan
execute_node(state) -> state     # APPROVE -> record what would run (stub)
route(state)        -> next node # the verdict router (the only branch)
```

Each node takes a `PipelineState`, returns a **new** one (frozen models; no mutation),
and appends exactly one `AuditEvent`. This is a state-machine graph expressed in plain
Python - deliberately isomorphic to a LangGraph graph (see ADR 0008): each function is a
node, `route` is the conditional edge, porting is mechanical.

```
        +--------+     +--------+  APPROVE   +----------+
NL ---> |  plan  | --> |  gate  | ---------> | execute  | --> done (audit trail)
        +--------+     +--------+            +----------+
                          |   ^ MODIFY
                          |   +----- adopt proposal
                          | BLOCK
                          v
                        halt (audit trail)
```

## 3. The modify strategy: adopt the proposal (the central decision)

When the gate says MODIFY, two strategies exist:

- **Adopt (chosen):** take the gate's own proposal - already value-trimmed,
  budget-trimmed, schema-validated, and priced - substitute it as the plan, and re-gate.
  Deterministic; zero additional LLM calls.
- **Replan (rejected for v1, documented):** feed the findings back to the LLM planner as
  feedback and ask for a new plan. Stochastic; costs a model call; could in principle
  produce a smarter restructuring than a trim (e.g. redistributing variations across new
  scenes).

Adopt wins on the project's own thesis: when a deterministic component has already
computed a valid, cheaper, coverage-preserving answer, sending the job back to a
stochastic component to rediscover it is spend without benefit. Replan becomes valuable
exactly when the modification requires *restructuring* rather than trimming - which no
current axis produces. The seam stays: the strategy is one branch in one node, and a
future `replan` mode slots in without touching the loop.

**The convergence invariant (verified, not assumed):** the gate's proposal, re-gated,
APPROVES - for all three modify shapes (value-trim only, value+budget, budget-only).
Value trims land exactly at the justified count (no diversity finding re-fires); budget
trims fit by construction (no cost finding re-fires). Adoption therefore converges in
exactly one additional gate pass. Measured: $373.30 MODIFY -> adopt -> $0.20 APPROVE.

## 4. Bounded looping and halting

The invariant makes one adopt->re-gate cycle sufficient, but the loop is still bounded
defensively (`max_gate_passes = 3` by default): if a re-gated proposal ever fails to
approve (a future axis violating the invariant, a bug), the pipeline halts with a clean
`OrchestrationError` naming the invariant violation - never loops silently. Same
bounded-loud-failure philosophy as the planner's repair loop.

Terminal states, exactly three: **EXECUTED** (approve path completed), **BLOCKED**
(gate said block; halt is the correct outcome, not a failure), **FAILED**
(planner exhaustion or invariant violation; carries the error).

## 5. The audit event contract

One event per node execution, frozen and JSON-round-trippable:

| Field | Meaning |
|---|---|
| `sequence` | 0-based position in the trail |
| `node` | which node ran (`plan`, `gate`, `adopt`, `execute`) |
| `timestamp` | UTC, event creation time |
| `summary` | one human-readable sentence |
| `verdict` | the gate's verdict (gate events only) |
| `driving_axes` | which checks produced the decisive findings (gate events only) |
| `estimated_usd` / `budget_usd` | the money at this step (where meaningful) |
| `detail` | node-specific structured payload (e.g. modifications applied) |

`driving_axes` is derived from the findings at the decisive severity: the check names
behind BLOCKING findings for a block, behind MODIFIABLE findings for a modify. This is
the field that answers the reviewer question the whole milestone exists for: *which axis
drove this decision, and what did it cost or save?* The trail also makes savings
first-class: a trail containing an adoption records original estimate vs adopted
estimate - the audit log of a governed job IS the dollars-saved receipt.

## 6. Locked decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Framework | Plain Python, node-over-state | ADR 0008: five nodes and one branch do not warrant a graph runtime; structure keeps the port trivial. |
| 2 | Modify strategy | Adopt the gate's proposal | Deterministic, free, convergence verified (section 3); replan documented as the restructuring-shaped alternative. |
| 3 | Loop bound | max_gate_passes = 3, then FAILED | The invariant needs 2 passes; the bound exists to make violations loud, not to enable long loops. |
| 4 | State | One frozen Pydantic model; nodes return new state | Auditability and testability; no hidden mutation; same contract discipline as GateDecision. |
| 5 | Terminal states | EXECUTED / BLOCKED / FAILED | BLOCKED is a successful governance outcome, distinct from failure. |
| 6 | Execution | Stub that records, never renders | Scope guard from M0: the governance is the product. |

## 7. Scope and assumptions (read this)

1. **Synchronous, in-memory, single-job.** No persistence, no async, no checkpointing,
   no resume - deliberately. These are precisely the features that would warrant
   LangGraph (ADR 0008); building them here in plain Python would be re-implementing a
   framework the project chose not to adopt.
2. **The audit trail lives in the state object and is serialized on completion.** It is
   not a streaming log or an external store; production would emit events to a real
   sink.
3. **Adopt-only modify handling.** The replan alternative is designed (section 3) but
   not built; it becomes worthwhile when an axis can propose restructuring, not
   trimming.
4. **The pipeline trusts its components' contracts** (planner raises PlannerError,
   governor returns a validated GateDecision); it adds bounds and audit, not
   re-validation.

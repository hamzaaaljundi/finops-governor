# Planning Agent - Design Specification

> The design-on-paper artifact for **M6, Task 6.1**. Defines how a natural-language
> request becomes a schema-valid `GenerationPlan` - and, more importantly, the trust
> boundary that keeps the stochastic planner from ever touching spend authority.
> Implementation (Tasks 6.2-6.4) transcribes this spec.
>
> **Status:** Accepted - **Milestone:** M6 - **Consumed by:** the CLI and the M7 orchestration

---

## 1. Role and trust boundary

The planner is the fuzzy front-end of the system: it turns a sentence like *"500
variations of a robotic arm on an assembly floor, RGB and depth, under $50"* into a
structured `GenerationPlan`. It is the only stochastic component in the pipeline, and it
is **advisory by construction**:

- The planner **proposes**; the deterministic Governor **disposes**. No planner output
  reaches execution without passing the same multi-axis gate as a hand-written plan.
- Planner output is **untrusted until validated**. Every response is forced through
  `GenerationPlan.model_validate` with `extra="forbid"` - a hallucinated field, a wrong
  enum, a missing section all fail loudly.
- A malicious or manipulated request (prompt injection lives in the NL input, which is
  untrusted user text) can shape *what the plan asks for* - it cannot raise the budget
  ceiling, skip a validity axis, or approve itself. The gate re-judges everything.

This is the thesis of the whole project exercised end to end: put stochastic power where
it helps (interpreting messy human intent) and deterministic rigor where trust is
required (deciding whether to spend).

## 2. The seam

The planner depends on a `PlannerModel` interface (Protocol), not on any vendor SDK:

```
PlannerModel:  complete(prompt: str) -> str
```

- One live implementation: the Anthropic API client (Task 6.4), a thin wrapper kept
  deliberately minimal because it cannot run in CI.
- One fake implementation for tests: a scripted model that can return valid plans,
  malformed JSON, schema-violating plans, or sequences of these - so the repair loop is
  fully testable without network or keys.

Fourth use of the same pattern (`CostModel`, `ValidityCheck`, `UsdStageLoader` isolation,
now `PlannerModel`): the pluggable seam with one real and one fake implementation.

## 3. The prompt

The prompt is assembled from five parts:

1. **Task instruction** - produce a generation plan as a single JSON object; output JSON
   only (no prose, no code fences).
2. **The live schema** - the verbatim output of `GenerationPlan.model_json_schema()`
   (~1,600 tokens, measured). Single source of truth: the schema the model sees IS the
   validator its output must pass; the two cannot drift.
3. **The user request** - the natural-language text, clearly delimited as data.
4. **The budget** - injected into the plan contract by the caller (the user's number,
   not the model's choice).
5. **Honest-randomization instruction** - the prompt-level mitigation of the declared-
   input circularity (section 6): declare only the randomization the scene genuinely
   varies, with `levels` reflecting meaningfully distinct values; never inflate levels
   to make a plan look diverse.

## 4. The repair loop

Generation is attempted at most **3 times** (1 initial + 2 repairs):

```
prompt -> model -> parse JSON -> GenerationPlan.model_validate
   on JSONDecodeError or ValidationError:
       re-prompt with the previous output and the verbatim error text appended
   on 3rd failure:
       raise PlannerError (the caller decides; nothing partial escapes)
```

- Feedback is the **verbatim** error text. Verified: pydantic errors name the field path,
  the violation, and the allowed values ("Input should be 'RGB', 'DEPTH', ..."), which is
  already corrective instruction - no translation layer.
- The loop is bounded and its exhaustion is a clean domain error, not a fallback plan. A
  planner that cannot produce a valid plan produces nothing.
- The loop logic is deterministic code around a stochastic call - every path (first-try
  success, repair success, exhaustion) is testable against the fake model.

## 5. Locked decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Provider | Anthropic API only, behind the seam | One live client; the Protocol makes others a drop-in. Multi-provider now is scope without payoff. |
| 2 | Framework | None (raw API + schema validation) | The task is one bounded transformation; the M1 schema is the validation layer. A framework would add surface, not capability. |
| 3 | Schema source | `model_json_schema()`, verbatim | Single source of truth with the validator; measured affordable (~1.6k tokens). |
| 4 | Max attempts | 3 (1 + 2 repairs) | Enough to fix mechanical errors; bounded so failure is loud, not looping. |
| 5 | Temperature | 0 | Reduces variance; does not (and need not) make the planner deterministic - determinism lives in the gate. |
| 6 | Circularity mitigation | Prompt-level instruction + documented limitation | Honest v1. Plausibility-checking declared levels is real future work, not a prompt trick. |

## 6. Scope and assumptions (read this)

1. **The planner is stochastic.** The same request may yield different valid plans across
   runs. This is acceptable by design: the *gate* is deterministic - the same plan always
   gets the same verdict - and the gate holds the authority.
2. **Declared-input circularity.** The planner now authors the `randomization` block the
   diversity gate judges (see `docs/diversity-model.md`, assumption 5). The v1 mitigation
   is prompt-level honesty instruction; a planner that inflates `levels` defeats the
   diversity check. A production version would plausibility-check declared levels or
   derive effective levels from the executor's sampler.
3. **Plan quality is not plan validity.** The schema guarantees structure, not sense: a
   valid plan can still be a poor interpretation of the request. Quality evaluation
   (does the plan match intent?) would need an eval harness - out of scope for v1.
4. **The NL request is untrusted input.** Injection can shape plan contents; it cannot
   cross the trust boundary (section 1).

**What a production version would need:** declaration plausibility checks; an eval set of
request->plan pairs scoring interpretation quality; cost-aware planning (the planner
seeing the estimator's feedback to propose within budget on the first try - today that
feedback loop belongs to M7's modify path).

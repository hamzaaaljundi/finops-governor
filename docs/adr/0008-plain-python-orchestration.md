# ADR 0008 - Plain-Python orchestration; LangGraph evaluated and deferred with a named threshold

**Status:** Accepted; amended 2026-07-22 - the named threshold (a spend-approval
checkpoint) is being pursued as a **separate project** (a LangGraph-based agentic
workflow tool), not as a future milestone of this repo. This repo's thesis is a
deterministic gate that an LLM's proposals pass through, never an agent loop; adding
LangGraph here to backfill a HITL checkpoint would contradict the reasoning below, not
fulfill it. See the amendment at the end of this document.

## Context

M7 wires plan -> gate -> verdict -> action into a state machine with a modify loop and
an audit trail. The natural candidate framework is LangGraph: the pipeline is literally
a graph with one conditional edge and one loop, which is LangGraph's home turf. The
question is not whether LangGraph *could* express this - it trivially could - but
whether a dependency earns its place at this scale.

## Decision

Implement the orchestrator in plain Python, structured as **pure node functions over a
single typed, immutable state object** - deliberately isomorphic to a LangGraph graph.

## Why not LangGraph at five nodes

The pipeline has ~5 nodes, one conditional edge, and one bounded loop whose convergence
is verified in two passes (orchestration-model.md section 3). Everything LangGraph would
add at this scale - a graph builder, a runtime, a dependency with its own release
cadence - replaces roughly sixty lines of readable Python that a reviewer can verify at
a glance. The project's recurring standard applies: no component earns its place by
being recognizable, only by being load-bearing. Adding nodes to justify the tool was
considered and rejected as inverted reasoning (parallel branches for microsecond
arithmetic; multi-agent gate voting, which additionally violates ADR 0001's
determinism-in-the-gate principle).

## The named threshold: when LangGraph becomes the right call

Adopt LangGraph at the point where any of these become real requirements:

1. **Human-in-the-loop approval with durable checkpoints** - a spend gate pausing for
   sign-off above a threshold, persisting state, and resuming on approval. This is
   LangGraph's checkpointing feature, and re-implementing durable interrupt/resume by
   hand is framework-building.
2. **Parallel execution of slow nodes** - e.g. multiple LLM calls or IO-bound validity
   axes fanned out concurrently. (Today's axes are microsecond-deterministic; there is
   nothing to parallelize.)
3. **Streaming/observable long-running jobs** - live state inspection mid-pipeline.

## Why the port stays trivial (the structural guarantee)

The plain implementation keeps LangGraph's mental model: each pipeline step is
`node(state) -> state` over one Pydantic state object; routing is a pure function of
state; nodes never mutate. A port is mechanical: each function registers as a graph
node, `route` becomes the conditional edge, the state model becomes the graph state.
No logic rewrites - a one-day exercise, by construction rather than by hope.

## Consequences

- Zero new dependencies at M7; the orchestrator is fully testable with the existing
  fake planner and deterministic gate.
- The audit trail (the milestone's real deliverable) is owned code either way - no
  framework provides the driving-axis attribution this project needs.
- The repo's narrative stays consistent: M6 needed no LangChain, M7 needs no LangGraph,
  and both decisions name the conditions under which the answer flips.
- If HITL checkpointing is pursued post-M8 (a candidate extension), this ADR is the
  design's entry point rather than a reversal.

## Amendment (2026-07-22): the named threshold is being exercised elsewhere

The prediction above held - port is one day, node/route/state map directly - but the
decision on *where* to build it changed. HITL checkpointing is a genuine LangGraph use
case, but it is an agentic loop by definition (propose, pause, wait for a human, resume),
and this project's core thesis is the opposite: an LLM proposes, a deterministic gate
decides, no agent loop governs itself. Building HITL inside finops-governor would mean
adding the exact pattern this ADR spent its Context section arguing against, to close
out a footnote - a worse trade than building it properly in a project whose thesis
*is* the agentic loop, where LangGraph is the natural tool rather than a graft.

This ADR's threshold and structural guarantee remain correct and reusable; a future
maintainer porting *this* orchestrator to LangGraph (for streaming or long-running jobs,
the two conditions named above) still finds this document accurate. HITL checkpointing
itself is simply no longer this repo's deliverable.

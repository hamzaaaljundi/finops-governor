# ADR 0007 - Value-aware modification: the gate removes the waste it prices

**Status:** Accepted (amends ADR 0005's "only cost modifies" and the M4 WARNING decision)

## Context

Since M4 the diversity axis has priced redundancy in dollars, and since M6.5-A it computes
expected coverage precisely - the finding for a redundant scene literally contains the
justified variation count's ingredients. Yet the gate's only modification lever remained
budget-driven (M2's PlanModifier), so a job flagged as "$373.18 of spend adds little
training value" was APPROVED with a warning. The gate held the answer and did not act on
it: an observer, not a governor.

## Decision

1. **The diversity axis emits MODIFIABLE, not WARNING** (amends M4 locked decision 1).
   Redundancy above threshold is recoverable by construction, so it belongs in the
   recoverable severity class. The recoverability guarantee holds mathematically:
   redundant_fraction(1) = 0 for every capacity, so a compliant trim target always
   exists - a diversity MODIFIABLE finding can never promise a fix that does not exist
   (the same single-source-of-truth discipline as CostCheck's use of the modifier).

2. **The trim target is the justified count**: the largest n' whose expected redundant
   fraction is within the threshold. redundant_fraction is monotone non-decreasing in n
   (verified), so n' is found by binary search. Trimming to the LARGEST compliant count
   preserves maximum data while meeting the value bar - the same "largest that fits"
   philosophy as the budget modifier.

3. **The proposal is built in two ordered passes: value first, then budget.**
   - Pass 1 (value): every scene with a diversity MODIFIABLE finding is trimmed to its
     justified count. This removes only expected-redundant frames - it is free in
     training-signal terms.
   - Pass 2 (budget): the value-trimmed plan is re-estimated; if it still exceeds the
     budget, the existing PlanModifier trims further (cutting real signal, because now
     there is no alternative).
   Rationale for the order: waste removal costs nothing; budget trimming costs signal.
   Never cut signal while waste remains. A frequent pleasant consequence: value-trimming
   alone often brings an over-budget job under budget.

4. **Trim composition lives in the Governor; coverage math stays in the diversity
   module.** The Governor is already the composition layer (it imports both gate/ and
   validity/); placing the value pass there preserves the import DAG (gate/ never
   imports validity/). The justified-count function lives beside expected_distinct in
   validity.diversity - one home for all coverage math.

5. **Precedence is unchanged.** BLOCKING still dominates: a geometrically broken or
   unrecoverably over-budget job is BLOCKED regardless of redundancy. Warnings still
   never decide. Only the MODIFY path gained a second, ordered trim pass.

## Consequences

- **Behavior change (the point):** a redundant, affordable plan now yields MODIFY with a
  concrete cheaper proposal instead of APPROVE with a warning. The headline demo becomes:
  flagged $373.18 of expected waste AND handed back the same-coverage plan at ~$0.20
  (50,000 variations -> 26).
- The audit reason records both passes distinctly ("value: scene X 50000 -> 26; budget:
  ..."), so which lever drove each cut is always attributable.
- Exit-code semantics shift for redundant plans (0 -> 1); tests, fixtures, docs, and the
  README demo lines are updated in the same change.
- The modified plan is re-validated through the schema and re-estimated before being
  proposed - a proposal is always itself a valid, priced plan (M2 invariant preserved).
- Opting out returns to flag-only behavior via the check's threshold (set to 1.0 to
  never fire); no parallel severity mode is maintained.

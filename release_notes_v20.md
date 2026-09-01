# v2.0-energy - the gate learns what jobs burn, not just what they cost

Every decision now carries an energy estimate chained on v1's CALIBRATED runtime
term (validated within 1.6% on real hardware) - not a guessed duration. Three
additions:

- **Trim-carbon accounting (the headline).** Every MODIFY reports the kWh and
  gCO2 of the expected-redundant frames it removed. On the flagship redundant
  fixture: ~145.6 kWh / ~67 kg CO2 avoided per submission - carbon reduced by
  not rendering frames that add no training value. Nobody else in synthetic-data
  tooling owns that sentence.
- **Carbon-aware schedule advice.** Plans declare urgency (interactive /
  standard / deferrable); decisions carry a recommended low-intensity start
  window with projected savings. Advice, not a queue - the gate governs
  approval, honestly declining to pretend it owns execution.
- **One governance rule.** Promoting deferrable -> interactive requires an
  explicit, audit-logged human approval (--approve-reclass); unapproved
  promotions BLOCK.

Honesty section (docs/energy-model.md section 4): utilization and PUE are
documented assumptions (with the ~$2 nvidia-smi session that would measure the
former named as roadmap); static average-intensity curves overstate marginal
savings - stated, not solved. 13 new tests; every pre-v2 plan and profile file
loads unchanged.

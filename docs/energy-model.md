# Energy & Carbon Model - Design Specification (v2.0-energy)

> **Status:** Accepted - **Consumed by:** the Governor (every decision now carries
> an EnergyEstimate + ScheduleAdvice; MODIFY carries trim-carbon accounting)

## 1. The claim, precisely

v1 governs what a job costs; v2 reports what it burns - chained on the SAME
calibrated runtime term (`total_gpu_hours`, validated within 1.6% on real
hardware, calibration.md section 8) instead of the guessed durations most energy
estimates multiply TDP by. The headline is not scheduling: **the M6.5 value-trim
now carries a carbon receipt.** Every MODIFY reports the gCO2 of the
expected-redundant frames it removed - carbon reduced by not rendering data that
adds no training value. On the flagship redundant fixture: 145.6 kWh / ~67 kg
CO2 avoided per submission, at evening-peak us-east-1 intensity.

## 2. The chain and the urgency classes

kWh = tdp_kw x utilization x gpu_hours x PUE; gCO2 = kWh x intensity(region, hour).
`tdp_kw` per profile (A10G 150 W, T4 70 W, H100 350 W - PCIe, the variant the
price row prices). Urgency on the plan: `interactive` (never deferred; carbon
logged), `standard` (advised to defer up to 6 h only when intensity > 400
g/kWh and a sub-threshold window exists), `deferrable` (advised to the minimum-
intensity window within 24 h). **Advice, not a queue**: v1 owns approval, not
execution; the gate emits `ScheduleAdvice` and a future scheduler consumes it.

## 3. The governance rule

A planner may PROPOSE promoting deferrable -> interactive (escaping deferral
advice); the gate BLOCKs the promotion unless resubmitted with
`approved_reclass=true` (CLI `--approve-reclass`) - deterministic, and the
approval is audit-visible in the saved plan. No HITL machinery: that thesis
belongs to the companion project.

## 4. What is honestly hard (read this)

1. **Utilization is assumed (0.75), not measured.** Render workloads vary
   between shader-bound and memory-bound phases. It is measurable by this
   project's own protocol - a ~$2 session logging `nvidia-smi
   --query-gpu=power.draw --loop` during a standard render - named here as the
   calibration roadmap item that would convert the weakest term into a measured
   constant.
2. **PUE 1.4 is a fleet-average assumption**; real facilities range ~1.1-1.6.
3. **Static intensity curves, and AVERAGE not MARGINAL intensity.** The shipped
   24-h regional curves are derived from public annual-average shapes; real
   grids vary daily, and deferral savings computed on average intensity
   overstate true marginal impact (the marginal generator your deferred load
   avoids is usually dirtier than average). Stated, not solved; a live source
   (e.g. Electricity Maps) drops into the `IntensitySource` seam.
4. Embodied hardware carbon, network/storage energy: out of scope, named.

## 5. Seams

`IntensitySource` protocol (StaticIntensityCurves ships; live APIs drop in;
tests inject fixtures) - the planner-model seam pattern, reused.

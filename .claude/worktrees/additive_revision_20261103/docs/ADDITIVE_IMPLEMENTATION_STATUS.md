# Additive implementation gate

Continuation note: this document records the initial foundation stage. Its
pending-decision and unconnected-simulator statements below are historical.
The user has approved the beta convention and preservation of submitted B5.
The additive core is now connected to B1-B5. See
`ADDITIVE_VERIFIED_CONTRACT.md` for the current contract, verification scope,
reproduction flag, and remaining gates. Continuation worlds remain unavailable.

This file describes implementation work, not experimental results. The source
snapshot is isolated from existing thinning workers. No additive calibration or
evaluation is authorized to pass this gate until every required item below is
verified. Existing calibration artifacts must not supply missing defaults.

## Confirmed decisions

- Positive-part additive environmental intensity, as in proposal PDF p. 5,
  Eq. (6), and ACC PDF p. 2, Sec. II-C, Eqs. (7)-(9).
- Preserve physical background density and existing load values. Correct the
  ACC PDF p. 4, Sec. IV-A per-cell label, rather than changing physical demand.
- Preserve complete intervention memory, application-time pre-depletion
  effectiveness, corrected estimator mass-to-density scaling, and coupled
  exogenous streams. Retain the old thinning implementation for reproduction.

## Verified source findings

- `DeterrentSystem._suppression_eval` still implements `exp(-S)`. It is not
  additive truth, even when paired with a unit-fixed additive estimator.
- `_spawn_offspring` uses a Poisson count and exponential delay. Its alpha is
  a branching count, not the initial rate amplitude. An unnormalized temporal
  kernel needs initial rate `alpha/omega` to preserve the same continuous-time
  expected offspring count before boundary losses.
- Background uses legacy grid-node weights, node jitter, and coordinate
  clipping. Offspring displacements are also clipped. These create boundary
  atoms. A continuous Gaussian density evaluator alone is not the intensity of
  that sampler; replacing only the acceptance formula is invalid.
- `scenario_rollout._World` has separate additive (`legacy`) and multiplicative
  (`consistent`) branches. The additive branch already divides lambda by its
  candidate field, but has its own grid/stamp and future-offspring conventions.
  It cannot be declared aligned merely by choosing that branch.
- A pre-existing runtime unit-threading test depends on an external frozen
  calibration result. That result is absent from this isolated source snapshot.
  Its failure is an artifact dependency, not an additive verification success.
  Do not copy an old calibration into the new study to hide this dependency.

## Implemented foundation

`additive_intensity.py` supplies validated positive-part intensity and acceptance,
explicit equal-area cell geometry, Gaussian CDF cell integrals without cropped
mass renormalization, background density preserving total physical demand, and
offspring count-to-rate conversion. It has no imports from the simulator and no
truth-state access. It is not yet wired into any production consumer.

The associated tests check independent numerical spatial quadrature, boundary
mass, conservation under grid refinement, additive saturation and overlaps,
input immutability, invalid-input rejection, all three background rates, and
temporal count conservation and convergence. These tests verify primitives;
they do not verify the simulator or forecast pipeline.

## Proposed contract, not a frozen physical reference

The following choices need a complete implementation and verification before
searching. The cue-amplitude reference has been presented to the user for a
decision; do not treat elapsed time as approval.

- A Gaussian with integral one on the full plane. Beta is the initial total
  suppressive rate in events/second before field-boundary loss, multiplied by
  pre-depletion effectiveness. Its time envelope is `exp(-age/omega)` without
  `1/omega`. Reusing old beta numbers is a declared new numerical reference,
  not a dimensional conversion of the old thinning exponent.
- A possible finite-volume implementation uses equal-area cells and uniform
  locations within a cell, with Gaussian cell probabilities from CDF integrals.
  Absorbing boundaries discard outside Gaussian mass. This differs from the old
  clipped-location law and must be disclosed; no result may imply exact spatial
  reproduction. Keep the old spatial weight array so total background demand
  and cell-index probabilities remain unchanged.
- A possible time discretization freezes predictable intensities at step start,
  assigns new offspring to subsequent steps, and uses geometric delay-bin
  masses. With `d=exp(-dt/omega)`, each accepted event contributes initial
  next-step rate `alpha*(1-d)/dt`. Infinite temporal mass is alpha, approaching
  the continuous exponential density as dt decreases. Same-step accepted
  events must not alter the denominator for other proposals in that step.
- All candidate sources use the same dominating field and acceptance
  `max(lambda_plus-u,0)/lambda_plus`, with zero acceptance at zero candidate
  intensity. Accepted events alone excite. These rules require joint sampler
  tests, not just arithmetic tests.

## Remaining implementation and release gate

1. Resolve the physical cue reference and freeze the complete contract before
   comparing policy outcomes. Revisit calibration bounds affected by units.
2. Implement an explicit new truth mode and candidate generator in both warmup
   and normal execution, leaving the historical mode reproducible.
3. Propagate the same geometry, kernel and timing contract through estimator
   construction, feedback, B1 generation, B2 Delta-J valuation, B3/B4 STL, B5
   scoring, committed schedules, and continuation worlds. Keep estimated
   parameters and observed histories separate from truth.
4. Check matching supplied-state intensity agreement, and separately verify
   partial observation, no truth leakage, no live mutation, recovery and
   depletion ordering, deterministic coupling, boundaries and time resolution.
5. Make the model contract part of source/configuration identities. Reject old
   truth recordings and checkpoints, and verify resolved runtime values.
6. Benchmark workers with the memory reserve before new B1 recordings and the
   finite frozen-inheritance calibration. Audit actual seed history and declare
   seed roles. Do not relabel reused seeds as independent fresh validation.
7. Freeze all profiles before paired B1-B5 evaluation. Preserve unchanged
   references where meaningful. Expand to A-E only with declared differences.

The new environment is not ready to recalibrate. No completion time for the new
study has been established. Wednesday draft material must distinguish verified
implementation work from historical thinning results and new additive results.

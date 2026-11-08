# Additive model contract and calibration gate

## User decisions

The user selected the positive-part additive truth equation, preservation of
physical background demand, and the convention below for cue strength. The user
also explicitly selected preservation of submitted B5 after the definition audit.

The main thesis equation is consistent with the chosen convention. Its current
detailed truth-suppression and background-unit paragraphs need revision before
describing the new implementation. Do not silently edit the thesis: the separate
thesis review process approves subsection changes. See `ADDITIVE_THESIS_HANDOFF.md`.

## Reproduction flag

`run_simulation_frames_persistent(truth_process_mode="historical_thinning")`
selects the original truth sampler, kernels and survival law. This is the
default. It does not activate the new grid, acceptance rule or excitation engine.

`truth_process_mode="additive_cells_v1"` explicitly activates the revised model.
It requires coupled streams, complete truth intervention memory, step-start
timing, the additive online estimator and corrected `mass_per_cell` units.
Unsupported combinations fail before simulation. No existing defaults select
the new physical model automatically.

To reproduce a historical run, retain its saved parameters, unit flag, stream
mode, memory mode, seeds and source identity as well as selecting historical
truth. Selecting the old truth law with new calibrated policy settings does not
reproduce a published experiment. Existing ACC tags, source and outputs remain
separate. The active workers' original runtime source has not been edited.

## Implemented mathematical and numerical conventions

The intended continuous formulation is
`lambda_true(x,t) = max(mu(x)*nu(t) + b(x,t) - u(x,t), 0)`.
The simulator implements a declared finite-volume, fixed-step approximation:

- Equal-area cells cover the complete field; their area is `(W/NX)*(H/NY)`.
  Model coordinates are cell centres. The paper grid remains 60 by 48 and the
  time step remains one second. This differs from the old endpoint-node grid.
- The background density in cell j is `mu_now * legacy_spatial_weight[j]`.
  Consequently its total candidate rate is exactly
  `mu_now * mean(legacy_spatial_weights) * W * H`, preserving prior physical
  background demand at each of the three configured loads. The values
  `2e-5`, `1e-4`, `4e-4` retain events/m^2/s per unit spatial weight.
  Accepted events and reactive load may change under suppression.
- Candidate locations are uniform within the sampled cell. Gaussian sources
  are projected to the containing cell centre. Exact Gaussian CDF differences
  give their cell probabilities. Spatial kernels have unit integral on the
  full plane; outside-field probability is lost without renormalization.
  This replaces the old coordinate clipping and its boundary atoms. Aggregate
  background demand is preserved; exact old continuous locations are not.
- For a completed action, beta is its initial total suppressive rate in
  events/second before boundary loss. Its cell density is
  `q_pre * beta * Gaussian_cell_mass / cell_area * exp(-age/omega)`.
  There is no `1/omega` factor in this inhibition envelope. The beta numbers
  from the paper settings are the user-approved new numerical reference, not
  a dimensional conversion from historical thinning strengths. Cue widths,
  decay times, recovery, depletion, fleet and duration are not retuned here.
- Environmental alpha remains the expected offspring count before boundary
  loss. It is not silently reused as an initial rate. With `d=exp(-dt/omega)`,
  the initial next-step rate per accepted event is `alpha*(1-d)/dt`, then
  decays by d per step. Its infinite temporal integral is alpha. It approaches
  the continuous initial rate `alpha/omega` as dt decreases.
- Background and excitation proposals are separate conditional Poisson
  components of the same candidate field. Acceptance in each cell is
  `max(candidate-inhibition,0)/candidate`, zero at zero candidate intensity.
  All proposals in a step use the same predictable fields. Only accepted
  events excite, starting in the next step. The old pre-drawn offspring queue
  is not used by this mode.
- Background draws are dedicated and policy independent. Excitation proposals
  use a separate keyed stream per step. Candidate IDs distinguish background
  and excitation; thinning and observation uniforms remain keyed. Endogenous
  excitation histories may differ across policies. This is not a claim of
  identical parent-tree coupling with the historical engine.

Truth, online estimator stamps, B2/B5 footprint scoring, and Eq. 3 grid stamps
share the same additive kernel and area conventions. Truth states and parameters
are not supplied to online estimation. The matching-state verification fixture
supplies equal fields solely to test numerical agreement; ordinary policies
still operate from detections, received intervention records and estimated state.

## Preserved policy definitions and approximations

The reference builder is `experiments/additive_protocol.py`. It materializes
profiles before execution and retains the existing frozen ownership hierarchy.
B1-B3 retain a fixed laser; B5 branches from B1; B4 branches from B3. No numerical
parameters are added to B4/B5 for tuning. Paper STL requirements are retained.

Submitted B5 maximizes current-effectiveness-weighted predicted benefit minus
cost across candidate cues. Because cues have unequal strengths and footprints,
this is not necessarily literal maximum effectiveness. ACC PDF p. 4 Sec. IV-A
and p. 5 Table III call the comparator "freshest". The user chose to preserve
the submitted implementation and label its actual rule precisely.

All five baseline profiles have `stl_forecast_correction=False` and
`stl_forward_trajectory_correction=False`, preserving the approved uniform-off
correction-isolation baseline. Baseline nominal historical feedback, passive
exposure forecasting and one-cell STL suppression remain declared paper-policy
approximations. These are not advertised as exact conditional truth forecasts.
In particular, without the correction flag the historical feedback amplitude
does not incorporate the planner's application-time effectiveness. A correction
arm must remain separately labeled; the environment revision does not silently
grant that improvement to one baseline. The physical truth always uses recorded
pre-depletion effectiveness.

## Verification and evidence

`results/additive_verification/core.xml` records the scoped tests and the tested
runtime source identity. Checks cover positivity, overlap and saturation,
independent kernel quadrature, boundary mass, area and time normalization,
zero-action sampling, no input mutation, coupled background streams, matching
supplied-state truth/model fields, the counterfactual kernel, warmup, live-field
record/replay equality, all five materialized runtime profiles, inherited-value
protection, margin routing, default/explicit historical flags, and checkpoint
and recording rejection across truth modes.

`results/additive_verification/historical_pair.json` compares B1, B4 and B5
under identical explicitly resolved historical fixture settings against the
preserved source. It checks exact mission/count agreement and verifies that the
original Python sources have not changed. It is a regression check, not a claim
to reconstruct the ACC evaluation results. Two existing artifact-dependent
integration fixtures cannot reconstruct their original calibration state from
this source-only snapshot; that limitation is not hidden by importing an old
calibration into the new study.

`results/additive_verification/release.json` pins the test report, regression
report and runtime source hashes. The additive calibration launcher rejects a
stale source or modified evidence. Replay fingerprints also include the shared
kernel module. Historical truth recordings cannot satisfy its additive-mode
recording preflight.

## Bounded calibration scope and remaining work

`experiments/run_additive_calibration.py` benchmarks one, two and up to four
workers before allocating the pool, retains the four-GB memory reserve, collects
new additive B1 recordings, and executes the existing finite 81-candidate bounded
estimator design and validation guardrails. It stops after this upstream stage.
No settings are globally deployed. Completed work is checkpointed by resolved
parameters, source and machine identity.

Estimator bounds retain their numerical values because the already unit-fixed
model parameters remain initial rate amplitudes, widths, decay times and a
background density. This is a new environment fit within the approved bounded
model class, not conversion of truth branching count into estimator alpha.
The Brier guard remains in probability units, and reference comparisons use the
same new cell geometry and target recordings. Failure to pass is reported and
retains the numerical reference; there is no automatic range expansion or
multiplicative-model fallback.

Training seeds 200-209 and development seeds 210-219 are reused identifiers and
are not described as fresh validation. Before downstream evaluation, audit and
predeclare unused estimator-check and evaluation seeds. Do not call 220-229 or
300-309 fresh. The policy stages still require frozen candidate definitions,
train/development exposure selection and parent configuration provenance.

A-E continuation worlds remain explicitly rejected for additive states until
their own sampler, geometry and rollout tests pass. This limitation is separate
from the verified B1 recording/replay stage and must not be described as an
implemented or evaluated additive planner. Reporting also needs final checks for
task-creation-to-completion response ages and paired uncertainty before release
of B1-B5 thesis tables. No new comparative additive results exist yet.

Within the new study, all systems must share this frozen physical environment.
Differences from historical results include the suppression law and numerical
model conventions; they cannot be attributed to the estimator stamp-unit fix
alone. Numerical approximation and policy conclusions require their own
reported evidence; neither B4 nor any other system is required to win.

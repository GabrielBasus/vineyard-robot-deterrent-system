# Automatic ACC and improvement queues, November 3

At 11:56 UTC (3:56 a.m. Pacific), the policy calibration is running. All sixty
B1 training/development recordings and the bounded estimator search completed.
No estimator finalist passed every guardrail. The numerical ACC reference is
retained, exactly as the approved fallback requires. This is a calibration
failure report, not evidence that the estimator was successfully refitted.

## Frozen source and allocations

The calibration and ACC source remains the verified additive snapshot. Its
runtime source identity remains
1b9abf65b6aade62639f54802b72feb27fbb97534bfc3f5939c70c31f1bed442.
No active runtime source was modified while those jobs ran.

The new distributed policy benchmark selected eight local workers: 46.547 s
versus 47.657 s with eleven, on identical thirty-case benchmarks. Both trials
used twelve desktop workers and produced the same exposure checksum. Twelve
desktop replay workers also beat six in the preceding repeated benchmark.
Memory guards remain in place. Small reference batches can finish on one host
before the other; the full candidate batches supply larger queues.

The older local historical campaign continues with twelve workers. The older
desktop historical campaign remains suspended, with its processes and
checkpoints retained. Do not resume it concurrently with additive jobs.
The thirty-case full-duration, unchanged-constant seed-201 diagnostic finished;
it is exploratory and must not be used to bypass calibration.

## Ordered queue

1. Finite frozen-inheritance policy calibration: B1, B2, fixed-cue B3, inherited
   B5, inherited B4. Exposure-only training selection, best-three development
   selection, no range expansion and no service constraint.
2. Fresh estimator checks under all five frozen policies, seeds 240-249,
   thirty recordings per policy. Failures are reported without retuning.
3. Complete primary B1-B5 comparison, seeds 400-409, all three loads and both
   habituation conditions. Calibrated and unchanged-constant arms give 600
   simulation cases. The ten-seed count follows the approved calibration plan.
4. Separately labelled multi-cue B3 diagnostic for the paper's additional
   comparison: the cue switch alone changes, with no retuning, in calibrated
   and unchanged-constant arms. Another 120 cases compare fixed versus
   multi-cue B3 and multi-cue B3 versus B4's habituation clause.
5. First ten improvement seeds, 400-409, using the frozen hierarchy, all three
   loads and both habituation conditions. Arms: A, B, C, C_gate, C_plan, D_plan,
   E_plan, and B5. A equals B4 exactly and A/B5 reuse the ACC cases. There are
   480 reported cases, of which 360 are new simulations.

Training/development seeds remain 200-209/210-219. Neither is fresh validation.
The replacement check/evaluation identifiers were declared before their results
were observed. Old 220-229/300-309 identifiers were not relabelled fresh.

An optional thirty-seed extension script was drafted but is NOT queued. Do not
silently increase the approved ten-seed budget and delay the improvement runs.
This queue covers the primary ACC comparisons and the explicitly labelled
multi-cue diagnostic; it does not claim to repeat every historical sweep.

## Verified continuation extension

The independent source copy additive_improvement_20261103 changes only
DeterrentSystem.py, habituation_stl/scenario_rollout.py, and the added
habituation_stl/additive_rollout.py relative to the calibration runtime.

The planner world retains the paper's passive-decay legacy forecast. It now
uses equal-area cells, floor indexing, Gaussian cell integrals with boundary
mass lost, and discrete-step candidate rates consistent with its exposure
quadrature. It does not insert truth parameters into the planner.
The oracle world calls the already verified AdditiveGridTruth implementation,
including complete intervention memory, next-step excitation, and coupled
background/thinning/detection draws. These snapshots never mutate live state.

Verification: 133 local tests pass, nine continuation tests pass on the
desktop, serial/parallel results agree, and B1/B4/B5 regression fixtures match
the calibration source on every non-timing metric. The regression fixtures
last sixty seconds at heavy load and do not substitute for full evaluation.
Wall-clock STL scoring timings are expected to differ. Two obsolete
fail-closed checks were replaced by functional continuation tests. One existing
fixture requiring unavailable historical calibration artifacts was deselected;
old artifacts were not copied in to conceal that limitation.

The parent's additive_protocol continuation-availability note and older
contract documents describe the earlier release. The separate continuation
test reports, baseline bridge and improvement manifest govern this extension.

## Controllers and resumption

All paths below are relative to their corresponding source copy.

- Calibration/primary ACC: additive_revision_20261103,
  results/additive_calibration_v1/distributed/overnight.py.
  Supervisor PID 6116, controller PID 55288.
- ACC diagnostic: the same source copy,
  results/additive_calibration_v1/distributed/diagnostic_supervisor.py.
  Supervisor PID 33932, controller PID 16612.
- Improvements: additive_improvement_20261103,
  results/additive_calibration_v1/distributed/overnight.py.
  Supervisor PID 4876, controller PID 24104.
- Report exporter: additive_revision_20261103/results/queued_reports.py,
  PID 33596. It waits for complete cohorts, then exports CSV tables and PNG/PDF
  figures. Existing paired-comparison JSON files contain seed-level intervals.

Every simulation/recording checkpoint has a resolved configuration identity.
Foreign results also carry actual executor/source provenance and transfer
checksums. Remote simulation cases are checkpointed individually, including
within unfinished batches. Supervisors permit three attempts and retain
completed cases. They do not change parameters or start an open-ended search.

The main ACC status is results/additive_policy_v1/status.json. The diagnostic
status is results/additive_ACC_diagnostics_v1/status.json. ACC_COMPLETE.json
is written under results/additive_policy_v1 only after the diagnostic finishes;
the improvement watcher waits for this marker before taking desktop resources.
The improvement status is results/additive_improvement_first10/status.json.
Read supervisor.json and controller stderr logs if progress stops.

The desktop's current calibration service is PID 1766949 with twelve workers,
under /home/gb_linux/thesis-workers/additive_calibration_20261103_1b9abf65.
The preverified improvement mirror is
/home/gb_linux/thesis-workers/additive_improvement_20261103.
The improvement controller drains the completed ACC service before starting
that separate mirror. Forecast arms use outer simulation workers. Continuation
arms use one outer simulation per host and up to twelve inner workers, capped
by the existing rollout memory reserve. A low-memory local host can wait while
the desktop continues.

Both computers must remain awake and connected. Queueing all stages is not a
promise that the expensive continuation cases will finish overnight. No
comparative calibrated performance conclusion is available at this timestamp.

## Local concurrency increase, November 3 at 21:40 UTC

The user requested more concurrent tuning because this computer had spare CPU
and memory. The older local historical campaign had moved from twelve outer
workers to one outer job with a small nested pool, so the earlier eight-worker
allocation no longer represented the competing workload.

A local-only B2 benchmark used 24 identical, 180-second training-seed fixtures
per trial. Median elapsed times: eight workers 58.938 seconds, sixteen workers
55.1875 seconds, twenty-one workers 51.265 seconds. The nominal twenty-four
worker trials were capped at twenty-one by the memory planning allowance.
All five trials produced identical non-timing metric checksums. This is about
15 percent more benchmark throughput; it is not a promise of the same speedup
for full-duration tuning cases.

The selected local ceiling is 21; the resumed scheduler currently has 20 active
local tuning workers after its startup memory cap. CPU measured 76.8 percent,
up from 35.7 percent, with 12.58 GB available. The four-GB hard memory floor is
unchanged. The planning allowance is now 0.50 GB per simulation worker, compared
with an observed full-duration worker peak below 0.30 GB. The desktop's twelve
workers and older local historical job were left running.

All 477 completed B2 checkpoint files were retained and audited. The 627 local
cases reported after resumption are remaining cases, not a reset of the full
960 local-case stage. Completed remote batches are likewise reused. Only a few
unfinished local cases needed restarting during the pool resize.

Current ACC supervisor/controller PIDs: 16920/45452. The new control code reuses
the matching live desktop service instead of stopping it. The first restart
attempts were rejected by a metadata comparison that treated JSON lists and
Python tuples differently; canonical comparison fixed this. The applied
manifest revision changes only controller_sha256, and its audit explicitly
records identical scientific settings. The runtime source gate still passes.

Evidence under results/additive_policy_v1: local_worker_allocation.json,
local_capacity_refresh/, manifest_before_worker_increase.json,
execution_revision_applied.json. The higher concurrency also carries into the
primary ACC checks/evaluations run by this controller. Other queued controllers
and their dependencies remain in place.

## Reporting callback repair, November 4 at 04:43 UTC

Policy calibration is complete and all B1-B5 configurations are frozen. The
post-freeze estimator check stopped because the bounded evaluator supplied a
workers detail to Runner.status, whose dict constructor also supplied workers.
The three-attempt supervisor exhausted its retries at this reporting exception.

A results-local DistributedRunner.status override now merges the detail fields.
The actual duplicate-workers callback was regression-checked, and the frozen
runtime source gate and every frozen configuration hash remained unchanged.
Only the controller checksum changed in the authorized execution revision.
No model, parameter selection, scoring or simulation code was edited.

Current ACC supervisor/controller: 43220/10716. B1 fresh estimator checking has
completed; B2 fresh recordings are being collected. Read live status before
reporting progress. Completed recordings and all search checkpoints were reused.
The ACC diagnostic, improvement and export watchers remain queued.

## Additive support queue, November 4 at 06:00 UTC (November 3 Pacific)

User-approved scope of November 3. New code only in
`results/additive_support_v1/` (support.py controller, supervise.py watcher and
supervisor, analyze.py, test_support.py, PROTOCOL.md, manifest.json). It imports
this runtime read-only, checks the 1b9abf65 source gate, uses the frozen
additive B1-B5 hierarchy without retuning, and selects additive_cells_v1 truth.
No runtime source, other controller, supervisor or desktop service was changed.

Mirrored from the thinning defense campaign (desktop definitions with the
correction-isolation amendment and its preemption-shadow repair), seeds
400-409 unless stated: two-factor F00/F01/F10/F11 (spare, hab on, B1
normalization), the seven-level paired kappa grid (B1, B2, flexible-cue B3, B4,
B5, three loads, hab on/off), depletion mismatch (heavy), and dispatch
sensitivity (preemption, slack and travel caps, reservation fractions,
res-soft/res-adaptive). H4 extension: B1 and B4, heavy, hab off, seeds 410-429
added to 400-409, TOST margin 3,400 units, predeclared before any additive H4
result.

Dry run (dry_run.json): 3,090 logical cells, 1,960 distinct inputs. 1,490 new
local simulations; 300 inputs reused only when the primary ACC or multi-cue B3
diagnostic writes the exactly identical configuration (never re-executed here);
170 held pending user answers (dispatch slack/travel caps, and mismatch B1/B4
at truth kappa 0.5). Held cells run only after approvals.json releases them.

Resources: local only, never the desktop. A run starts only with at least one
free physical core and available memory of at least 4 GB plus the measured
peak (0.29 GB) plus a 1 GB coexistence margin; two workers first, at most
twelve. A 2-worker full-duration benchmark on training seeds 200-205, measured
beside the ACC evaluation, averaged 550 s per run (spare 334 s, heavy about
420 s, overload 545-1,152 s). Unheld work is about 221 CPU-hours: about 55 h
at four workers, 18 h at twelve. Completion is not promised for any deadline.
The A-E improvement queue is unchanged and was not suspended.

Supervisor/watcher PID 39756, controller PID 42868. Status:
results/additive_support_v1/status.json and supervisor.json; reports in
results/additive_support_v1/reports/. Live ACC PIDs at launch: supervisor
14352/controller 14956 (evaluating B1-B5), diagnostic 59248/42444, improvement
4876/24104, report exporter 48776. Read live files before reporting progress.

### Amendment, November 4 at 06:30 UTC: user decisions and A-E priority hold

The user prioritized the support queue over A-E. After verifying that PID 24104
was still improvement.py from additive_improvement_20261103 (parent 4876) and
that ACC_COMPLETE.json did not yet exist, the A-E controller 24104 was
suspended with psutil at 06:23 UTC while idle. It was not killed, and its
supervisor 4876 was not touched. The support supervisor resumes 24104 when
the support queue completes, when its controller attempts are exhausted, or on
any supervisor exit (finally, atexit, signal handlers). If the supervisor is
hard-killed, run results/additive_support_v1/resume_priority_hold.py. Suspend
and resume events are logged in results/additive_support_v1/priority_hold.json
and shown in its status.json. While held, A-E will not start even after
ACC_COMPLETE.json appears.

Decisions: the slack grid and travel caps run as literally mirrored; mismatch
B1/B4 at truth kappa 0.5 reuse the runtime-identical primary heavy rows;
same-host references reuse desktop-executed primary rows and every comparison
reports mixed-host pairs; flexible-cue B3 only in the kappa grid; seeds as
scoped; H4 margin 3,400 unchanged, with the caveat that it was set on the
thinning exposure scale. Nothing is held now.

Revised dry run: 3,090 logical cells, 1,960 distinct inputs, 1,640 new local
simulations (23 already complete and retained), 320 reused rows. Estimated
243 CPU-hours: about 122 h at two workers, 61 h at four, 20 h at twelve.
The support queue was restarted with the amended manifest: supervisor PID
13140, controller PID 47600. Status files are unchanged.

### Amendment, November 4 at 21:20 UTC: old-load cohort, indefinite A-E hold

User decision: evaluation loads move to new background rates targeting
rho_load of about 0.4 / 0.8 / 1.5 (a B1 pilot chooses them), and A-E is redone
at those loads by a new campaign. The old-mu A-E controller 24104 therefore
stays suspended indefinitely; nothing resumes it automatically. Neither 24104
nor its supervisor 4876 was killed. Manual resume
(results/additive_support_v1/resume_priority_hold.py --confirm) is reserved
for an explicit new decision.

The support supervisor 13140 was hard-terminated so its old auto-resume code
could not run. The running controller 47600 was adopted by the new supervisor
59960 without interruption, so no run or checkpoint was lost (1,351 checkpoints
at the switch, stage reservation10). The support queue continues to completion
as the separately labelled OLD-LOAD cohort (mu 2e-5 / 1e-4 / 4e-4), never
pooled with new-load results. priority_hold.json, supervisor.json and
status.json record "held indefinitely pending new-load A-E campaign (user
2026-11-04)".

## New-load campaign, November 4 at 21:30 UTC

User decisions of November 4: new background rates targeting rho_load 0.4 / 0.8 /
1.5, frozen calibrated configurations without recalibration, calibrated arm only,
main B1-B5 on 30 seeds (400-429, covering H4), FINAL thesis results from this
cohort only. The old-load support queue and old-load multi-cue diagnostic were
stopped by the coordinator at the user's request (partial old-load cohorts
retained); the old A-E controller 24104 remains suspended and is not resumed.

New code only in results/additive_newloads_v1 (this copy: newloads.py,
supervise.py, rho_load.py, tests, PROTOCOL.md) and in
additive_improvement_20261103/results/additive_newloads_AE_v1 (ae.py,
supervise.py, test_ae.py, PROTOCOL.md). Both import their copy's runtime
read-only with source-identity gates (1b9abf65 / 946386278f). The only changed
factor is mu_true; a fidelity gate re-resolves every new job at the old mu and
matches the old cohorts' configuration hashes exactly.

rho_load (thesis definition) reproduces 0.458 / 0.821 / 1.659 and the old-mu
additive 0.437 / 1.104 / 2.590. Pilot: frozen B1, hab on, kappa 0.5, training
seeds 200-209, five log-spaced mu per target (factor 1.5 each side of 1.7e-5,
4.8e-5, 1.45e-4), predeclared selection rule (bracket, log-log interpolation,
one confirmation batch, closest observed rho), bootstrap intervals. Results:
results/additive_newloads_v1/pilot_report.json and frozen_loads.json.

Audit gate: after frozen_loads.json the controller writes manifest.json and
stage2_resolved_params.json, then waits for AUDIT_CLEARED.json (cleared_by plus
the manifest SHA-256). No stage-2 run starts before the user's explicit audit
clearance. The A-E controller has the same gate on its own manifest and then
waits for NEWLOADS_COMPLETE.json (priority: main, diagnostic, support, A-E).

Dry run: main 900 runs (400-409 block first), diagnostic 60, support 1,600 new
(4,050 logical cells, 2,560 distinct simulations); A-E 360 new plus 120 reused.
Local only: the desktop service resolves mu from the old load table, so it
cannot run new mu with declared parameters.

PIDs at launch: new-load supervisor 20632 / controller 43096; A-E supervisor
6232 / controller 22820 (waiting). Status: results/additive_newloads_v1/status.json
and supervisor.json; additive_improvement_20261103/results/additive_newloads_AE_v1/
status.json and supervisor.json. Reporting rule: primary results use only the
new-load calibrated cohort; older cohorts only in labelled sensitivity sections.

### Amendment, November 4 at 21:55 UTC: recalibration, audit decisions, relaunch

User decisions after the independent configuration audit (recorded in
results/additive_newloads_v1/decisions.json and both PROTOCOL.md files before any
new-load B2-B5 outcome): B2 then B3 are RECALIBRATED at the new loads with the
unmodified policy.calibrate procedure (B1 kept; B4/B5 inherit), with one deliberate
deviation: the B2 margin probe and reference candidate use the paper reservation
0.25. H4 TOST margin is relative (1.6% of the same-load B1 hab-off mean at rho 0.8).
Kappa-grid Holm family: 24 distinct cells. Support grids keep the literal levels
and add the newly selected B2 slack/reservation if absent. A-E adds B5_FC (B5 with
forecast correction only); correction-including variants are compared with B5_FC,
A with B; A, B5 and B5_FC are rerun in the improvement copy (540 A-E runs).

Every new-load job (pilot, recalibration, stage 2, A-E) carries its explicit
resolved mu_true in its parameters and identity, and the running mu_true is audited.
The old desktop service is not used; a NEW desktop mirror
(/home/gb_linux/thesis-workers/additive_newloads_v1, PID 2894866) runs declared
cases only after a byte-identity check on three training-seed pilot cases. At
launch it had 5.15 GB available, below its 4 GB + peak launch gate, so it is idle.

Predeclared statistics: results/additive_newloads_v1/analysis.py (bootstrap 10,000,
RNG 12345, two-sided Wilcoxon, Holm main and secondary families of 6, H4 TOST, H6,
support analyses). The stage-2 audit gate (AUDIT_CLEARED.json) is unchanged.

Relaunched with the new code (pilot checkpoints retained): new-load supervisor
56520 / controller 60168; A-E supervisor 53492 / controller 54636 (waiting).

### Amendment, November 5 at 02:25 UTC: B1-first campaign adopted, whole-unit desktop execution

The authoritative campaign is now results/additive_newloads_b1recal_v1. It recalibrates
B1, then B2, then B3 at the fixed new mu; B4 and B5 inherit. It was started by Copilot on
November 4 and adopted here. The additive_newloads_v1 controller is retired; its pilot
and frozen_loads.json remain the source of the fixed mu. Production launch guards were
removed. After calibration the controller writes manifest.json and
stage2_resolved_params.json, then waits for AUDIT_CLEARED.json.

Execution uses local (21 workers) plus the new desktop mirror (12 workers, folder
additive_newloads_b1recal_v1, not byte-identical, so under the whole-unit rule). Units
are (load, seed), with all cases of a unit on one machine and the executor per unit
recorded (unit_partition.py). The AWS instance was deleted by the user. A-E is repointed
to this campaign and backfills idle CPU after its own audit clearance, running two
continuation simulations at a time. H6 uses the 97.5th-percentile bound.

PIDs: campaign supervisor 44896 / controller 58604; A-E supervisor 39572 / controller 44196.

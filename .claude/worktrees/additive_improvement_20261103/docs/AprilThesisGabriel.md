Thesis Reframe Context: Reserved-Capacity Dispatch Policy
Current thesis goal

The thesis is now centered on one main robotics contribution: a reserved-capacity task allocation / dispatch policy for decentralized multi-robot teams operating under a mixed reactive and predictive workload with bounded execution bandwidth. The vineyard bird-deterrence system is now the testbed, not the main novelty claim.

The intervention-aware SESTPP and the ΔJ predictive utility scoring are retained, but they are no longer the primary thesis contribution. They are now treated as the predictive workload generator and predictive scoring infrastructure that support the new dispatch-policy contribution. The SESTPP math and the ΔJ formulation are preserved essentially unchanged.

Task model

The reframe assumes two task streams:

Reactive tasks are triggered by confirmed bird detections. They carry a value v
a
	​

, an arrival time, a target location, and a hard deadline t
a
exp
	​

. If they expire, they contribute value-weighted exposure.
Predictive tasks are generated asynchronously by the retained predictive pipeline. They carry a predicted value-weighted exposure reduction ΔJ(a), a cost surrogate c
η
	​

(a,r), and a candidate location, but no hard deadline. Dropping them does not cause direct exposure; it only loses potential future benefit.

The central scenario variable in the thesis is the reactive load factor

ρ
load
	​

=
N
λ
react
	​

E[τ
service,R
	​

]
	​

,

which characterizes whether the fleet has spare bandwidth, is near saturation, or is overloaded by reactive demand alone.

What remains unchanged

The following subsystems are intentionally not the focus of this reframe and should stay unchanged unless there is a compelling compatibility reason:

SESTPP.py
ZonePartitioner.py
TaskGenerator.py as the candidate generator and ΔJ scorer

The reframe explicitly says the new work should be localized to dispatch, per-robot reservation accounting, config/profile plumbing, telemetry, and experiment wiring, not to the predictive model or spatial partitioner.

Main contribution: reserved-capacity dispatch policy

The new core contribution is the reserved-capacity dispatch policy π
res
	​

(ρ), parameterized by a reservation fraction ρ∈[0,1]. Each robot keeps a sliding time window of length T
W
	​

 and tracks:

t
r
react
	​

(t): time spent on reactive tasks
t
r
pred
	​

(t): time spent on predictive tasks
t
r
idle
	​

(t): time spent idle

with

t
r
react
	​

(t)+t
r
pred
	​

(t)+t
r
idle
	​

(t)=T
W
	​


and realized predictive share

ϕ
r
pred
	​

(t)=
T
W
	​

t
r
pred
	​

(t)
	​

.

Dispatch rule Codex should implement

At each dispatch decision point for robot r, the policy applies the following lexicographic rule:

Hard-latency override
If there exists a reactive task whose remaining slack is at most τ
exp
	​

, dispatch that reactive task. This protects hard reactive deadlines.
Reservation claim
If ϕ
r
pred
	​

(t)<ρ and at least one predictive task is available, dispatch the predictive task with highest utility U(a,r).
Reactive service
Otherwise, if reactive tasks are available, dispatch the reactive task with highest value v
a
	​

.
Opportunistic predictive use
Otherwise, if predictive tasks are available, dispatch the predictive task with highest utility.
Idle
Otherwise, remain idle.

Important interpretation:

ρ=0 reduces the policy to a priority-style dispatcher where reactive work beats predictive work unless the reactive queue is empty.
The reservation is soft over the window, not pointwise at every instant. The hard-latency override is what makes the policy compatible with reactive deadlines.
A recommended default is T
W
	​

=10⋅E[τ
service
	​

], and a reasonable default for τ
exp
	​

 is E[τ
service,R
	​

]+ a safety margin.
Baseline policies in the reframed thesis

The thesis now compares three main dispatch policies:

π
react
	​

 (pure reactive): only reactive tasks are eligible for dispatch; predictive tasks may still be generated but are never admitted.
π
unc
	​

 (unconstrained priority): all tasks enter a unified priority queue with no reservation; this is intended to match the current system’s behavior as the strong baseline.
π
res
	​

(ρ) (reserved capacity): the new proposed policy with ρ∈{0.10,0.25,0.40}.

There is also a scoring ablation:

π
res-rand
	​

(ρ): identical to reserved capacity except predictive tasks are chosen uniformly at random from the admitted candidate pool instead of by utility U(a,r). This isolates the value of the reservation mechanism from the value of the predictive scoring.
How this maps to the current repo

Although the April document refers to planner modules abstractly, the actual repo already contains the relevant dispatch behavior inside DeterrentSystem.py. Codex should modify the existing dispatch path rather than inventing a new planner framework unless there is a strong reason to do so. Current production code already distinguishes:

Direct-detection deterring tasks: type == "deterring" and mode in (None, "", "none")
Model-scored preventive deterring tasks: type == "deterring" and mode not in (None, "", "none")
Patrolling tasks: type == "patrolling"

This implies a practical task mapping for the reframe:

Reactive = direct-detection deterring tasks
Predictive = patrol tasks + model-scored preventive deterring tasks

The current unconstrained ordering in DeterrentSystem.py already gives direct-detection tasks an absolute-priority bucket, while the remaining tasks are ordered lexicographically by task-level utility/score, predicted ΔJ, ΔJ/cost, lower ETA, and related tie-breakers. Codex should preserve that behavior as closely as possible for the unc mode.

Predictive model and scoring are supporting infrastructure

The retained predictive subsystem is still important, but it is not the main thesis novelty:

The intervention-aware SESTPP produces the local predictive field λ
r
IA
	​

(x,t).
The value-weighted demand field is q
r
	​

(x,t)=w(x)λ
r
IA
	​

(x,t).

Predictive actions are scored by counterfactual exposure reduction ΔJ(a), cost c
η
	​

(a,r), utility

U(a,r)=ΔJ(a)−c
η
	​

(a,r),

and efficiency

η(a,r)=
c
η
	​

(a,r)
ΔJ(a)
	​

.

These formulas are restated in the April thesis specifically to support the new dispatch-policy framing.

Implementation focus

The April reframe says the main code changes should be localized to:

Robot.py: add per-robot sliding-window counters for reactive, predictive, and idle time
dispatch logic: implement the new policy modes react, unc, res
task selection / override logic: expose τ
exp
	​

config/profile plumbing: add reservation parameters and reserved-capacity profile variants
telemetry: add predictive funnel counters and per-robot time allocation logging
DeterrentSystem.py: wire the new dispatcher and funnel counters into the existing simulator path

The April implementation section estimates the total change at about 400 lines, localized mainly to dispatcher and telemetry logic.

New policy/config concepts Codex should expect

Codex should expect to introduce thesis-facing config support for:

dispatch_policy in {react, unc, res}
reservation fraction ρ
reservation window T
W
	​

hard reactive override threshold τ
exp
	​


The April reframe also proposes reserved-capacity profile variants at:

ρ=0.0
ρ=0.10
ρ=0.25
ρ=0.40
Metrics that matter after the reframe

The key experimental outputs for the reframed thesis are:

Primary: value-weighted exposure E, lower is better.
Secondary: mean reactive response time, fleet-weighted travel distance, reactive completion fraction, predictive completion fraction, and per-robot time allocation fractions.

Critical diagnostic: the predictive funnel

∣generated∣→∣admitted∣→∣dispatched∣→∣completed∣

because the thesis now needs to show why reserved capacity helps, not just whether exposure improved.

What the thesis now claims

The thesis now claims:

A reserved-capacity dispatch policy with a single tunable reservation fraction ρ and a hard-latency reactive override can outperform pure-reactive and unconstrained-priority baselines over a characterizable range of reactive load factors.
The regime boundary where reserved capacity stops paying is determined primarily by reactive load factor ρ
load
	​

.
Within the regime where reserved capacity helps, predictive scoring quality from the SESTPP-driven ΔJ utility adds measurable benefit over random predictive target selection.

What is no longer claimed:

novelty of the point-process model itself
novelty of Laguerre / power-diagram zone partitioning
novelty of the overall simulation framework

Those are now supporting infrastructure.

Practical instruction for future coding chats

When working in this repo under the reframed thesis:

treat the reserved-capacity dispatch policy as the primary feature to implement or analyze
preserve the SESTPP, legacy deltaJ scoring, TaskGenerator, and ZonePartitioner unless a compatibility fix is unavoidable; for the STL addendum, use the opt-in `predictive_utility_mode="stl_robustness"` path rather than changing dispatch commands
prefer editing the existing dispatch logic in DeterrentSystem.py over creating a new planner architecture
use the current task typing in DeterrentSystem.py to map:
direct-detection deterring -> reactive
patrol + model-scored preventive deterring -> predictive
Caveats / limits from the thesis document

The April document explicitly notes these threats to validity:

simulation only, no physical-robot validation
simulator knows the ground-truth bird process
real detection noise is not modeled
the original April dispatch-policy document did not model habituation; the current STL branch now models habituation for the dedicated B0-B4 addendum
the predictive workload generator is in-house and would benefit from external ecological validation

These are acknowledged limitations, but the document argues they do not undermine the central allocation-policy claim.
Current STL addendum note:

The habituation-aware STL work is now implemented separately from the April dispatch reframe. It keeps the dispatcher contract stable, adds per-cell/per-cue truth habituation, and evaluates B3/B4 controls under habituation-on/off truth. Use `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md` for the current evidence.
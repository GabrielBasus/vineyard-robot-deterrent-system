# Thesis_Outline_GBasus.pdf

## Page 1

S.Farzan

1

CPSquare: Cal Poly Cyber-Physical Systems Lab

January 2026

Proposed MS Thesis Topic

1.1

Working Title

Intervention-Aware Spatiotemporal Point Process Modeling for Predictive Multi-Robot Bird Deterrence in Vineyards

1.2

Why This Topic Fits the Existing Framework

The current implementation already provides:
• Health-weighted zone partitioning via a power diagram (UGV zones) with neighbor graph
extraction.
• A decentralized online spatiotemporal intensity estimator per robot (OnlineSESTPP) with
self-excitation and cross-excitation near zone borders.
• A task pipeline where detections generate immediate deterrence tasks and the predicted
intensity field generates patrol tasks via hotspot extraction.
• A capability-aware task assigner that selects primary and secondary robots based on ETA,
endurance, zone membership, and health.
However, deterrence actions currently do not feed back into the event intensity model. This thesis
makes that feedback explicit by modeling deterrence as an intervention that suppresses future event
intensity, enabling predictive planning that is aware of how actions change future risk.

1.3

Core Research Question

How can we design an online spatiotemporal point process model that (i) predicts bird intrusion
hotspots from distributed detections and (ii) explicitly represents the suppressive effect of deterrence
actions, so that multi-robot task selection reduces future bird activity and value-weighted exposure
more effectively than reactive or prediction-only baselines?

1.4

Thesis Objectives

1. Develop an intervention-aware online spatiotemporal intensity model by extending the
current self-exciting formulation with an inhibitory term driven by deterrence actions.
2. Integrate the new model into the existing task pipeline by scoring candidate patrol and
deterrence locations using expected future intensity reduction per unit cost.
3. Evaluate performance in simulation against strong baselines (reactive and prediction-only)
using metrics aligned with agricultural impact, energy, and coordination overhead.

## Page 2

S.Farzan

1.5

CPSquare: Cal Poly Cyber-Physical Systems Lab

January 2026

Problem Setting and Notation

Let Ω ⊂ R2 denote the vineyard area (or a discretized grid over the area). Robots are indexed by
r ∈ R and each robot maintains a local model over its zone Ωr .
Events (bird detections): Er = {(xi , ti )} are detections attributed to robot r (plus cross-shared
neighbor events).
Interventions (deterrence actions): Ur = {(zj , τj , mj )} are completed deterrence actions
executed by robot r at location zj and time τj with deterrence mode or formation label mj .

1.6

Baseline Model: Online Self-Exciting Spatiotemporal Intensity

The current OnlineSESTPP structure corresponds to a Hawkes-type intensity:


X
t − ti
λr (x, t) = µr (x) s(t) +
αin Kσ (x − xi ) exp −
ω
(xi ,ti )∈Er

+

X
(xk ,tk )∈EN (r)



t − tk
αcross wr←k Kσ (x − xk ) exp −
, (1)
ω

where µr (x) is a background rate, s(t) is a diurnal multiplier, and Kσ (·) is a spatial Gaussian kernel.

1.7

Proposed Extension: Intervention-Aware Self-Exciting and Self-Regulating Model

We introduce an inhibitory (self-regulating) component driven by deterrence actions:


h
X
t − τj i
IA
λr (x, t) = λr (x, t) −
β(mj , x, τj ) Kσu (mj ) (x − zj ) exp −
,
ωu (mj ) +
(zj ,τj ,mj )∈Ur
|
{z
}

(2)

intervention suppression

where [·]+ = max(·, 0) enforces nonnegativity of intensity.
Interpretation:
• β(·) controls the immediate strength of deterrence.
• ωu (·) controls how long deterrence effects persist.
• σu (·) controls the spatial footprint of deterrence, which can encode formation footprint (for
example, a wider formation yields larger σu ).

1.7.1

Optional Habituation Model (Diminishing Returns)

To represent habituation, define a local habituation state H(x, t) that increases with repeated
interventions and decays over time:
X
H(x, t + ∆t) = ρH(x, t) +
KσH (x − zj ),
0 < ρ < 1.
(3)
(zj ,τj ,mj )∈U (t,t+∆t)

## Page 3

S.Farzan

CPSquare: Cal Poly Cyber-Physical Systems Lab

January 2026

Then deterrence strength decreases with habituation:
β(m, x, t) = β0 (m) exp(−kH H(x, t)) .

(4)

This connects directly to the agricultural motivation: repeating the same deterrence pattern in the
same region yields weaker future benefit.

1.8

Planning: Scoring Actions by Expected Future Reduction

At each replan cycle, generate candidate targets from the current predicted intensity field (hotspots),
then score each candidate deterrence action by its expected reduction in future intensity over a
horizon TH .
Let a candidate action be a = (z, t, m) executed at current time t. Define the reduction proxy:
Z t+TH Z


IA,a
w(x) λIA
(x,
τ
)
−
λ
(x,
τ
)
dx dτ − cE (a),
(5)
∆J(a) =
r
r
t

Ωr

where w(x) is the value weighting over the vineyard (premium rows, edges, phenology), and cE (a)
is an energy or time cost.
A computationally efficient approximation follows from the exponential temporal kernel:





Z t+TH
τ −t
TH
exp −
dτ = ωu 1 − exp −
.
ωu
ωu
t

(6)

This allows scoring many candidates with low overhead on a grid.

1.9

Decentralized Neighbor Sharing With Interventions

The existing boundary-event mechanism can be extended to share intervention events near zone
boundaries in addition to detection events:
• If a deterrence action completes within a distance db of the zone boundary, broadcast a
compact message (z, τ, m, β, σu , ωu ) to neighbor zones.
• Neighbors add that event into their local inhibitory term (cross-inhibition), improving prediction consistency near borders.
This remains communication-efficient because it is event-triggered and local.

1.10
1.10.1

Implementation Plan Within the Existing Codebase
Model Extension (SESTPP.py)

Add a second grid accumulator for inhibition mass, analogous to trigger mass:
• inhib mass[y,x] updated by add intervention event() with spatial stamping similar to
stamp().

## Page 4

S.Farzan

CPSquare: Cal Poly Cyber-Physical Systems Lab

January 2026

• In advance time(dt), decay trigger mass with exp(−dt/ω) and decay inhib mass with
exp(−dt/ωu ) (possibly mode dependent).
• Update intensity as lam = clip(mu*time mult + trigger mass - inhib mass).

1.10.2

Closed-Loop Integration (DeterrentSystem.py)

When a deterring task completes, call:
• robots[rid].m.add intervention event(x,y,mode=m) at completion time.
• Broadcast intervention boundary events to neighbors when near the boundary (reuse EventBus).

1.10.3

Action Scoring (TaskGenerator.py)

Replace or augment the patrol target selection:
• Generate candidate points from hotspots() (already implemented).
• For each candidate, compute ∆J(a) using the approximation in (6).
• Add the best scoring patrol or deterrence task per robot per cycle (respecting cooldown).

1.11
1.11.1

Experimental Design
Simulation Scenarios

Use a ground-truth generative process for bird events so interventions can have measurable impact:
• Base rate plus self-excitation to generate clustered bird activity.
• Optional edge preference and row value map for w(x).
• Detection noise model (false negatives) consistent with sensor realism.
• Intervention effect applied to the ground-truth intensity to represent actual deterrence impact.

1.11.2

Baselines

At minimum:
1. Reactive: respond only to detections, no predictive patrol.
2. Prediction-only: current self-exciting model generates hotspots but deterrence does not
suppress predicted risk.
3. Proposed: intervention-aware self-exciting and self-regulating model with action scoring by
expected reduction.
Optional ablations:

## Page 5

S.Farzan

CPSquare: Cal Poly Cyber-Physical Systems Lab

January 2026

• No neighbor sharing vs neighbor sharing of detections only vs detections plus interventions.
• No habituation vs habituation-aware suppression (4).

1.11.3

Metrics

Report mean and variance over multiple randomized runs:
• Value-weighted exposure:
Z TZ
Jexp =
0

w(x) λtrue (x, t) dx dt.

Ω

• Mean response time from event onset to first deterrence arrival.
• Total energy or travel distance per robot (UGV and UAV separated).
• Task efficiency: completed tasks per unit distance, or reduction in exposure per task.
• Communication overhead: number of boundary messages and total bytes sent (proxy).

1.12

Expected Contributions

• A practical online intervention-aware spatiotemporal point process model suitable for real-time
robotics.
• A planning objective and scoring method that selects actions based on predicted future
reduction, not only current hotspots.
• A decentralized coordination mechanism that shares both detections and intervention effects
locally to reduce border artifacts.
• An evaluation showing measurable reduction in value-weighted exposure and improved responsiveness under realistic constraints.

1.13

Minimum Deliverables and Stretch Goals

Minimum deliverables:
• Implement (2) and integrate it into the simulation loop.
• Implement action scoring (5) and compare against baselines.
• Provide a full experimental section with metrics and ablations.
Stretch goals (if time permits):
• Habituation model (3) and (4) with mode-dependent parameters.
• Online parameter adaptation for β0 (m) and ωu (m) using likelihood-based updates.
• Formation-dependent footprints by mapping formation choice to σu (m) and comparing footprints empirically.

## Page 6

S.Farzan

1.14

CPSquare: Cal Poly Cyber-Physical Systems Lab

January 2026

Proposed Thesis Chapter Outline

1. Introduction and problem motivation
2. Related work: persistent monitoring, hotspot prediction, spatiotemporal point processes,
intervention modeling
3. System overview and existing architecture
4. Intervention-aware point process model (formulation and online update)
5. Planning and task selection using expected future reduction
6. Experimental setup and baselines
7. Results, ablations, and discussion
8. Conclusions and future work

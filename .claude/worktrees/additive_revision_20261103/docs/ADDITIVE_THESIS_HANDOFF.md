# Thesis wording handoff for additive implementation

This file requests review in the existing thesis editing process. It does not
edit the thesis, replace approved text automatically or assert new results.

Authoritative implementation conventions and evidence are recorded in
`ADDITIVE_VERIFIED_CONTRACT.md` and `experiments/additive_protocol.py`.

## Exact thesis locations needing review

In `Thesis/latex_docs/chapters/03_problem_system.tex`:

1. Section labeled `sec:truth-intensity-model`, equations labeled
   `eq:truth-intensity`, `eq:truth-excitation`, and `eq:truth-suppression-field`:
   the positive-part additive formulation is retained. Define the spatial
   Gaussian as unit integral, beta as initial total rate in events/second, and
   the temporal inhibition envelope without `1/omega`. Explain the simulator's
   discrete excitation normalization separately from its branching count.
2. The paragraph beginning "The configured background rates" in the same
   subsection: preserve the numerical values as spatial densities per unit
   spatial weight. Remove the assertion that these configured densities are
   divided by cell area. The ACC PDF p. 4 Sec. IV-A per-cell label is erroneous.
3. The value-map paragraph beginning "The value surface serves two related
   purposes": old grid-node jitter and clipping describe historical mode.
   New mode samples an equal-area cell according to the old weight array,
   then samples uniformly within that cell. Its aggregate physical background
   demand is preserved, but the exact old within-cell distribution is not.
4. The ground-truth offspring subsection, especially the paragraph following
   `eq:truth-offspring-space`: describe the new conditional Poisson cell process,
   next-step geometric time kernel and absorbing boundary. Retain clipped
   Gaussian offspring queues only as a historical-mode description. Do not
   claim exact continuous-space/time equivalence of the new discretization.
5. Section labeled `sec:truth-suppression`, particularly
   `eq:truth-intervention-contribution` and `eq:truth-event-survival`: replace
   the primary unit-peak exponent and `exp(-u)` survival with the declared
   cell-integrated additive field and `max(lambda_plus-u,0)/lambda_plus`.
   Keep the old law only in the explicit reproduction description. Remove
   text treating qualitatively similar laws as an equivalent implementation.
6. Forecast-model and experimental sections: distinguish physical additive
   truth from retained paper-policy forecasting approximations. Submitted B5
   selects effectiveness-weighted predicted benefit minus cost, not necessarily
   the highest-effectiveness cue. The user explicitly chose to preserve it.

## Reference sources

- Proposal `proposal_stl.pdf`, PDF p. 5, "Effective suppression in the
  ground-truth process", Eq. (6).
- ACC `GB_ACC_2027_v2.pdf`, PDF p. 2 Sec. II-C Eqs. (7)-(9): intended additive
  truth. PDF p. 4 Sec. IV-A: conflicting per-cell label and B5 description.
  PDF p. 5 Table III: B5 labeled "Freshest" despite its submitted code rule.

## Claims the draft can and cannot make

The additive convention is selected and its B1-B5 core implementation has scoped
verification evidence. Existing results remain historical thinning evidence.
There are no new additive comparative results to cite yet. The estimator stage
uses new B1 recordings and existing finite bounds; downstream policies and fresh
evaluation must follow frozen inheritance before thesis result replacement.

An old-to-new comparison bundles model and numerical conventions. It cannot
isolate the effect of the stamp-unit correction alone. Within-cohort comparisons
must use identical physical settings and declared policy differences. Calibration
failure, confidence intervals crossing zero, and service tradeoffs must be
reported rather than adjusted to favor B4.

The reproduction flag defaults to `truth_process_mode="historical_thinning"`.
New runs explicitly use `"additive_cells_v1"`. Exact historical reproduction also
requires its original saved policy settings and all other flags and seeds.

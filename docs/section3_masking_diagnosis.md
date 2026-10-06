# Section 3.2: STL Masking Diagnosis

## Aggregation tree (explicit)

The planner evaluates the following formula at t=0 on a trace of length H/dt steps:

```
rho(Phi, xi, 0) = softmin_theta [
    w_exp * Always_{[0,H]}( softmin_theta_{z in Z} [(E* - e_z(s)) / E*]         )
    w_cov * Always_{[0,H]}( softmin_theta_{z in Z} [(T_cov - g_z(s)) / T_cov]   )
    w_hab * Always_{[0,H]}( softmin_theta_{z in Z} [(eta_z(s) - eta_min) / (1-eta_min)] )
]
```

where `softmin_theta(x_1,...,x_n) = min(x) - (1/theta)*ln(n)` when all x_i = min(x),
and approaches min as theta -> infinity.

The `Always_{[0,H]}` operator takes `softmin` over the time grid s = 0, dt, 2dt, ..., H.

## Numerical convention

All predicates are normalized so their robustness is dimensionless and comparable:

| Clause | Signal | Threshold | Scale | Predicate rho |
|---|---|---|---|---|
| exp | e_z | E_star | E_star | (E* - e_z) / E* |
| cov | g_z | T_cov | T_cov | (T_cov - g_z) / T_cov |
| hab | eta_z | eta_min | 1 - eta_min | (eta_z - eta_min) / (1 - eta_min) |

A positive rho means the constraint is satisfied with margin; negative means violated.

## Masking condition

**The exp clause masks U_stl for ALL lead > 0 under monotone decay.**

When e_nom(s) = e0 * exp(-s/omega_e) decays monotonically, the predicate
`(E* - e_z(s)) / E*` is INCREASING in s (exposure falls, so the margin grows).
The `Always_{[0,H]}` minimum therefore occurs at s=0 for BOTH the nominal and
with-action traces:

```
min_{s in [0,H]} (E* - e_z^{nom}(s)) / E* = (E* - e0) / E*   (at s=0)
min_{s in [0,H]} (E* - e_z^{wa}(s)) / E*  = (E* - e0) / E*   (same, since e_wa(0) = e0)
```

Because the action only modifies the trace at s >= lead > 0, and the minimum
occurs at s=0, both traces give the same Always value. Therefore:

```
rho_exp^nom = rho_exp^wa  =>  U_stl_exp = 0   (for ANY e0, when e_nom is monotone)
```

**The exp clause is a constraint/gate, not a scoring term.** Its role in the
conjunction is to make the overall spec robustness negative when e0 > E* (a severe
event that overrides the benefit of minor cov/hab improvements), not to score how
much a specific action reduces exposure.

**The coverage clause IS a scoring term.** Since g_z grows linearly (g = g0 + s),
the cov predicate `(T_cov - g_z) / T_cov` DECREASES over time. Its Always min is
at s=H. The action resets g to 0 at s=lead, so g_wa(H) = H - lead < g_nom(H),
giving rho_cov^wa > rho_cov^nom and a positive U_stl contribution.

**Additional masking when e0 > E*:** When e0 > E*, the exp clause makes
`rho_exp < 0`. If this is the binding clause (most negative), it sets the overall
`rho` and `U_stl = rho_wa - rho_nom = 0` (both pinned by exp). This is a secondary
masking effect on top of the primary one above.

**Variant C exception:** With `forward_trajectory_correction=True`, e_nom can RISE
when the inhibitory mass decays faster than the trigger mass. In that case, the
minimum of the exp clause may occur at an interior point s > 0 where the suppression
matters, and U_stl_exp > 0. This is one motivation for variant C.

**Smooth aggregation:** With softmin at theta=12, the masking is approximate.
The gradient is exp(-theta * gap) where gap is the margin between the minimum
and second-minimum time step. When the margin is large (e.g., the exp clause is
negative and cov/hab are positive), exp(-12 * gap) is effectively 0 and the
masking is numerically complete.

## Soft-min argument count bias

The softmin with n equal arguments at value x gives:
```
softmin_theta(x, x, ..., x) = x - (1/theta) * ln(n)
```

This means a robot with n_large local cells in its spec gets a score shifted down by
(1/theta)*ln(n_large/n_small) relative to a robot with n_small cells, even when all
signals are at the same value. At theta=12:

| n cells | Bias term (1/theta)*ln(n) | Shift vs n=1 |
|---|---|---|
| 1 | 0.000 | 0.000 |
| 2 | 0.058 | -0.058 |
| 3 | 0.092 | -0.092 |
| 4 | 0.116 | -0.116 |

**Impact:** If candidates for different robots (or different action cells within a robot)
are evaluated over different local cell sets, their U values are not directly comparable.
The current implementation evaluates all of a robot's candidates over the same local cell
set, so within-robot comparisons are fair. Cross-robot comparisons are not made directly
(each robot selects its own best action), so no bias arises in practice. The bias IS
problematic if the local cell set changes between nom and wa evaluations (it does not
in the current implementation).

## Robustness breakdown diagnostic

The `robustness_breakdown()` function in `task_value.py` evaluates each clause
independently and returns:

```python
{
    "nom": {"exp": rho_nom_exp, "cov": rho_nom_cov, "hab": rho_nom_hab},
    "wa":  {"exp": rho_wa_exp,  "cov": rho_wa_cov,  "hab": rho_wa_hab},
    "binding_clause_nom": "exp",   # clause with minimum nom robustness
    "binding_clause_wa":  "exp",   # clause with minimum wa robustness
    "U_stl": rho_wa - rho_nom,    # overall score difference
    "U_ie":  ...,                  # integrated exposure value (always computed)
}
```

When `binding_clause_nom == "exp"` and `U_stl == 0`, the planner is masked. Use
`U_ie` to confirm that the suppression is physically meaningful.

## Timed recovery clause (Eq. 4)

The `timed_recovery` clause implements Eq. (4) from the proposal:

```
phi_timed_recovery = Always_{[0,H]}(
    (e_z > E_high) => Eventually_{[0,T_response]}(e_z <= E_low)
)
```

Composed in STL as:
```python
Implies(
    signal_geq(e_z, E_high),          # trigger: e_z > E_high
    Eventually(                         # consequence: e_z recovers
        signal_leq(e_z, E_low),        # within T_response seconds
        0.0, T_response
    )
)
```

Wrapped in `Always_{[0,H]}` to enforce at every time in the horizon.

The clause is built in `mission_spec.build_clauses()` when:
- `"timed_recovery"` in `params.active_clauses`
- `params.E_high`, `params.E_low`, `params.T_response` are all set (not None)
- Typically: E_low < E_high, and T_response << H

The `Implies` semantics: when e_z <= E_high (no trigger), robustness is
(E_high - e_z)/E_high > 0 -- vacuously satisfied. When e_z > E_high, robustness
is the maximum of the `Eventually` clause over [0, T_response].

## Empirical masking frequency

From the Section 2 30-seed evaluation (seeds 155-184, variant B), the masking
condition (e0 > E_star for the candidate action cell at planning time) can be
estimated from the exposure field trajectories. High-mu runs (mu=4e-4) at which
the habituation reversal was strongest are the most likely cases where masking
occurs and U_stl = 0 for many candidates simultaneously. See
`results/testbench/variant_abc/` for the empirical data.

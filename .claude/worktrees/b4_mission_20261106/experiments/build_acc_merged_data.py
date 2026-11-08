"""
Merge fresh B4 data (post-softmin-collapse-bugfix, correct arena params) with
existing multi-system CSVs. ALL sources use omega_scale=3.0 for cross-experiment
comparability; B2/B3 topup data (omega=4.0) is intentionally excluded.

Sources by experiment:
  ladder_2em05  : confirmatory (B1/B2/B3/B5, omega=3.0, n=10-30) + B4 corrected (omega=3.0, n=30)
  ladder_1em04  : highload sweep (B1/B2/B3-multi/B5, omega=3.0, n=10) + B4 corrected (omega=3.0, n=30)
  ladder_4em04  : highload sweep (B1/B2/B3-multi/B5, omega=3.0, n=10) + B4 corrected (omega=3.0, n=30)
  joint_sweep   : original B1-B3/B5 (omega=3.0) + B4-fixedcue fresh run (omega=3.0)
  h4_rho_res    : fixed rho_res run (omega=3.0)

NOTE: B3-multicue from highload (seeds 125-134) is renamed to B3-fixedcue in the merged
ladder_1em04 / ladder_4em04 files. The 2x2 corrected experiment shows B3-multicue and
B3-fixedcue are NOT execution-equivalent under hab-off (+3.2% vs +0.1% relative to B1).
The rename is a known approximation for the highload seeds; the topup seeds (135-154) run
true B3-fixedcue. The primary confirmatory results at mu=2e-5 are unaffected (all B3
rows use correct fixedcue data).

Produces results/testbench/acc_merged/:
  ladder_2em05.csv
  ladder_1em04.csv
  ladder_4em04.csv
  joint_sweep_summary.csv
  h4_rho_res_sweep_summary.csv

Run this after habituation_stl_b4_corrected_* experiments complete.
"""

import csv
import math
import shutil
import statistics as _stats
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "results" / "testbench"
OUT = RESULTS / "acc_merged"
OUT.mkdir(parents=True, exist_ok=True)

B4_SYSTEM = "B4_res_stl_full_multicue"
B4_FIXED_SYSTEM = "B4_res_stl_full_fixedcue"
B3_MULTI = "B3_res_stl_nohab_multicue"
B3_FIXED = "B3_res_stl_nohab_fixedcue"
B1_SYSTEM = "B1_greedy_fixedcue"


def read_csv(path: Path) -> list[dict]:
    if not path or not path.exists():
        print(f"  [MISSING] {path}")
        return []
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    print(f"  [READ]    {path.name} ({path.parent.name}) -> {len(rows)} rows")
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        print(f"  [SKIP]    {path.name} (no rows)")
        return
    seen: set[str] = set()
    fields: list[str] = []
    for row in rows:
        for k in row:
            if k not in seen:
                fields.append(k)
                seen.add(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, restval="")
        w.writeheader()
        w.writerows(rows)
    baselines = sorted({r.get("baseline", "?") for r in rows})
    print(f"  [WRITE]   {path.name} -> {len(rows)} rows | systems: {baselines}")


def remove_systems(rows: list[dict], systems: set[str]) -> list[dict]:
    return [r for r in rows if r.get("baseline", "") not in systems]


def rename_b3_multi_to_fixed(rows: list[dict]) -> list[dict]:
    """Rename B3-multicue → B3-fixedcue for highload seeds 125-134 (approximation; see module docstring)."""
    result = []
    for r in rows:
        if r.get("baseline", "") == B3_MULTI:
            r = dict(r)
            r["baseline"] = B3_FIXED
        result.append(r)
    return result


# ─── Confirmatory ladder (µ = 2e-5) ──────────────────────────────────────────
print("\n=== ladder_2em05.csv ===")
confirm_rows = read_csv(
    RESULTS / "habituation_stl_revised_confirm_with_b2_1800s_10seed" / "per_run_metrics.csv"
)
b4_2em05 = read_csv(
    RESULTS / "habituation_stl_b4_corrected_2em05" / "per_run_metrics.csv"
)
# Topup: seeds 135-154 for B2 and B3-fixedcue (brings both to n=30)
b2_b3_topup_2em05 = read_csv(
    RESULTS / "habituation_stl_b2_b3_topup" / "mu_2em05" / "per_run_metrics.csv"
)

rows = remove_systems(confirm_rows, {B4_SYSTEM})
rows += b4_2em05
if b2_b3_topup_2em05:
    topup_baselines = {"B2_res_deltaJ_fixedcue", "B3_res_stl_nohab_fixedcue"}
    topup_keys = {(r.get("baseline",""), r.get("habituation_condition",""), str(r.get("seed","")))
                  for r in b2_b3_topup_2em05}
    # Remove any existing B2/B3 rows whose (baseline, hab, seed) appear in topup (dedup guard)
    rows = [r for r in rows if r.get("baseline","") not in topup_baselines
            or (r.get("baseline",""), r.get("habituation_condition",""), str(r.get("seed",""))) not in topup_keys]
    rows += b2_b3_topup_2em05
write_csv(rows, OUT / "ladder_2em05.csv")

# ─── Highload ladder (µ = 1e-4) ───────────────────────────────────────────────
print("\n=== ladder_1em04.csv ===")
high_1em04 = read_csv(
    RESULTS / "habituation_stl_load_sweep_highload" / "mu_1em04" / "per_run_metrics.csv"
)
# Topup: seeds 135-154 for B1/B2/B3-fixed/B5 (brings all systems to n=30, omega=3.0)
high_1em04_topup = read_csv(
    RESULTS / "habituation_stl_highload_topup" / "mu_1em04" / "per_run_metrics.csv"
)
b4_1em04 = read_csv(
    RESULTS / "habituation_stl_b4_corrected_1em04" / "per_run_metrics.csv"
)

rows = remove_systems(high_1em04, {B4_SYSTEM})
rows = rename_b3_multi_to_fixed(rows)
rows += remove_systems(high_1em04_topup, {B4_SYSTEM})  # topup runs B3-fixedcue directly
rows += b4_1em04
write_csv(rows, OUT / "ladder_1em04.csv")

# ─── Highload ladder (µ = 4e-4) ───────────────────────────────────────────────
print("\n=== ladder_4em04.csv ===")
high_4em04 = read_csv(
    RESULTS / "habituation_stl_load_sweep_highload" / "mu_4em04" / "per_run_metrics.csv"
)
# Topup: seeds 135-154 for B1/B2/B3-fixed/B5 (brings all systems to n=30, omega=3.0)
high_4em04_topup = read_csv(
    RESULTS / "habituation_stl_highload_topup" / "mu_4em04" / "per_run_metrics.csv"
)
b4_4em04 = read_csv(
    RESULTS / "habituation_stl_b4_corrected_4em04" / "per_run_metrics.csv"
)

rows = remove_systems(high_4em04, {B4_SYSTEM})
rows = rename_b3_multi_to_fixed(rows)
rows += remove_systems(high_4em04_topup, {B4_SYSTEM})  # topup runs B3-fixedcue directly
rows += b4_4em04
write_csv(rows, OUT / "ladder_4em04.csv")

# ─── Joint sweep summary ──────────────────────────────────────────────────────
print("\n=== joint_sweep_summary.csv ===")
old_joint = read_csv(RESULTS / "habituation_stl_joint_sweep" / "joint_sweep_summary.csv")
b4_joint = read_csv(
    RESULTS / "habituation_stl_joint_sweep_b4_fixed" / "joint_sweep_summary.csv"
)

rows = [r for r in old_joint if "B4" not in r.get("system", r.get("baseline", ""))]
rows += [r for r in b4_joint if "B4" in r.get("system", r.get("baseline", ""))]
write_csv(rows, OUT / "joint_sweep_summary.csv")

# ─── H4 rho_res sweep summary ────────────────────────────────────────────────
print("\n=== h4_rho_res_sweep_summary.csv ===")
h4_candidates = [
    RESULTS / "h4_rho_res_sweep_mu1em04_fixed" / "h4_rho_res_sweep_summary.csv",
    RESULTS / "h4_rho_res_sweep_mu1em04" / "h4_rho_res_sweep_summary.csv",
]
h4_dst = OUT / "h4_rho_res_sweep_summary.csv"
for src in h4_candidates:
    if src.exists():
        shutil.copy2(src, h4_dst)
        print(f"  [COPY]    {src.parent.name}/{src.name} -> {h4_dst.name}")
        break
else:
    print("  [MISSING] No h4_rho_res_sweep source found!")

# ─── 2x2 overhead decomposition (clean, all omega=3.0) ───────────────────────
print("\n=== 2x2_overhead_corrected.csv ===")
# Sources (all omega=3.0):
#   B1, B3-fixed       : from confirmatory
#   B4-multicue        : from b4_corrected_2em05 (post-fix, correct hab_off)
#   B3-multicue        : from habituation_stl_2x2_corrected/new_cells (corrected run)
#   B4-fixedcue        : from habituation_stl_2x2_corrected/new_cells (corrected run)
confirm_for_2x2 = read_csv(
    RESULTS / "habituation_stl_revised_confirm_with_b2_1800s_10seed" / "per_run_metrics.csv"
)
b4_corrected_for_2x2 = read_csv(
    RESULTS / "habituation_stl_b4_corrected_2em05" / "per_run_metrics.csv"
)
new_cells_corrected = read_csv(
    RESULTS / "habituation_stl_2x2_corrected" / "new_cells" / "per_run_metrics.csv"
)

rows_2x2 = []
if confirm_for_2x2 or b4_corrected_for_2x2 or new_cells_corrected:
    # B1 and B3-fixed from confirmatory (omega=3.0)
    rows_2x2 += [r for r in confirm_for_2x2
                 if r.get("baseline", "") in {B1_SYSTEM, B3_FIXED}]
    # B4-multicue from corrected run (post-fix, omega=3.0)
    rows_2x2 += [r for r in b4_corrected_for_2x2
                 if r.get("baseline", "") == B4_SYSTEM]
    # B3-multicue and B4-fixedcue from corrected 2x2 new_cells (omega=3.0)
    rows_2x2 += [r for r in new_cells_corrected
                 if r.get("baseline", "") in {B3_MULTI, B4_FIXED_SYSTEM}]
    write_csv(rows_2x2, OUT / "2x2_overhead_corrected.csv")
    # Print decomposition summary
    if rows_2x2:
        print("\n  --- 2x2 decomposition (hab_on) ---")
        systems_order = [B1_SYSTEM, B3_FIXED, B3_MULTI, B4_FIXED_SYSTEM, B4_SYSTEM]
        for hab in ("hab_on", "hab_off"):
            b1_vals = [float(r["value_weighted_exposure"]) for r in rows_2x2
                       if r.get("baseline") == B1_SYSTEM and r.get("habituation_condition") == hab
                       and r.get("value_weighted_exposure","")]
            b1_mean = _stats.mean(b1_vals) if b1_vals else float("nan")
            print(f"  {hab}  (B1 ref={b1_mean:.1f})")
            for sys in systems_order:
                vals = [float(r["value_weighted_exposure"]) for r in rows_2x2
                        if r.get("baseline") == sys and r.get("habituation_condition") == hab
                        and r.get("value_weighted_exposure","")]
                if not vals:
                    print(f"    {sys:<38} n=0  (missing)")
                    continue
                mean_v = _stats.mean(vals)
                pct = (mean_v - b1_mean) / b1_mean * 100 if math.isfinite(b1_mean) else float("nan")
                print(f"    {sys:<38} n={len(vals):2d}  mean={mean_v:.1f}  pct_B1={pct:+.1f}%")
else:
    print("  [SKIP]    2x2_overhead_corrected.csv (no source data yet)")

print("\n=== Done ===")
print(f"Output: {OUT}")

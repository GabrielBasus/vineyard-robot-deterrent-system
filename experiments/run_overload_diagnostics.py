"""
run_overload_diagnostics.py -- isolate why B4 loses to greedy B1 at overload.

At mu_true=4e-4 the reserved B4 system is about 5.5% worse than greedy B1 in
value-weighted exposure, and the reservation fraction has been ruled out as the
cause. This script runs a set of dispatch-mechanism arms on paired seeds so the
gap can be attributed to a specific mechanism:

  B1                  exact ladder B1_greedy_fixedcue config (dispatch_policy="unc")
  B1_res0             B1 routed through the "res" dispatch path with
                      reservation_fraction=0 and reactive_override_slack_s=90
                      (legacy utility and fixed laser cue are kept)
  B1_res0_nooverride  B1_res0 with reactive_override_slack_s=1e9 (urgent override
                      never fires)
  B4                  exact ladder B4_res_stl_full_multicue config
  B4_nopreempt        B4 with preempt_deterring_goals=False (policy is only
                      re-evaluated when a robot has no goal)
  B4_nearest          B4 with reactive_override_target="nearest_overdue"
  B4_hyst             B4 with goal_switch_margin_s=30
  B4_etafirst         B4 with reactive_priority_key="eta_first"
  B4_all              nearest_overdue + goal_switch_margin_s=30 + eta_first

Arm configs are built from the production ladder's own param builders
(_common_params, _system_params, _habituation_params) so B1 and B4 match the
ladder exactly; each arm only layers its overrides on top.

Note on B1_res0_nooverride: reactive_override_slack_s also feeds the STL
reactive horizon default (stl_T_react_s) and the Plan E service-protection
deadline list, but B1 uses the legacy utility with service protection off, so
for this arm the only behavioral effect is disabling the urgent override.

Defaults follow the high-load sweep (results/testbench/habituation_stl_load_sweep_highload):
60x48 grid, 4 robots, 1800 s, warmup 0, deterrence scales beta=4, sigma=4,
omega=3, kappa=0.5, rho_res=0.25. Seeds 200-209 are development seeds.

Output (under --outdir):
  raw/<arm>_<hab>_seed_<seed>.json, per_run_metrics.csv, summary_by_system.csv,
  paired_vs_B1.csv, OVERLOAD_DIAGNOSTICS.md, manifest.json

Example:
  py -3.10 experiments/run_overload_diagnostics.py --max-workers 16
  py -3.10 experiments/run_overload_diagnostics.py --arms B1,B4,B4_nearest --hab off --num-runs 1
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as stats
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import os

# Batch runs must not append to telemetry_live/ (set before DeterrentSystem is imported).
os.environ.setdefault("DETERRENT_TELEMETRY", "0")
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import experiments.run_habituation_stl_production_ladder as ladder  # noqa: E402

B1_SYSTEM = "B1_greedy_fixedcue"
B4_SYSTEM = "B4_res_stl_full_multicue"

_B1_RES0 = {
    "dispatch_policy": "res",
    "reservation_fraction": 0.0,
    "reservation_window_s": 600.0,
    "reactive_override_slack_s": 90.0,
    "predictive_selection_policy": "utility",
}

# (arm name, ladder system, overrides applied on top of the ladder system params)
ARMS: list[tuple[str, str, dict[str, Any]]] = [
    ("B1", B1_SYSTEM, {}),
    ("B1_res0", B1_SYSTEM, dict(_B1_RES0)),
    ("B1_res0_nooverride", B1_SYSTEM, {**_B1_RES0, "reactive_override_slack_s": 1.0e9}),
    ("B4", B4_SYSTEM, {}),
    ("B4_nopreempt", B4_SYSTEM, {"preempt_deterring_goals": False}),
    ("B4_nearest", B4_SYSTEM, {"reactive_override_target": "nearest_overdue"}),
    ("B4_hyst", B4_SYSTEM, {"goal_switch_margin_s": 30.0}),
    ("B4_etafirst", B4_SYSTEM, {"reactive_priority_key": "eta_first"}),
    (
        "B4_all",
        B4_SYSTEM,
        {
            "reactive_override_target": "nearest_overdue",
            "goal_switch_margin_s": 30.0,
            "reactive_priority_key": "eta_first",
        },
    ),
]
ARM_NAMES = [name for name, _sys, _ov in ARMS]
REFERENCE_ARM = "B1"

PRIMARY_METRIC = "value_weighted_exposure"
MECHANISM_METRICS = [
    "reactive_completed_total",
    "reactive_completed_per_robot_hour",
    "reactive_completed_fraction",
    "reactive_mean_response_time_s",
    "predictive_completed_total",
    "urgent_reactive_override_total",
    "goal_switch_total",
    "goal_switch_abandoned_distance_m",
    "goal_switch_hysteresis_blocked_total",
    "travel_distance_total",
]
N_BOOT = 10000


def _mu_token(mu: float) -> str:
    exp = math.floor(math.log10(mu))
    mantissa = mu / (10.0 ** exp)
    return f"mu_{mantissa:.4g}em{abs(exp):02d}".replace(".", "p")


def _ladder_args(args: argparse.Namespace) -> argparse.Namespace:
    """Namespace accepted by the ladder's param builders (high-load sweep defaults)."""
    return argparse.Namespace(
        mu_true=float(args.mu),
        nx=int(args.nx),
        ny=int(args.ny),
        nrobots=int(args.nrobots),
        duration_s=float(args.duration_s),
        warmup_s=float(args.warmup_s),
        task_replan_period_s=45.0,
        reservation_fraction=float(args.reservation_fraction),
        reactive_override_slack_s=90.0,
        predictive_max_eta_s=None,
        alpha_true=0.3,
        beta_true=0.25,
        sigma_true=12.0,
        omega_true=600.0,
        deterrence_beta_scale=float(args.deterrence_beta_scale),
        deterrence_sigma_scale=float(args.deterrence_sigma_scale),
        deterrence_omega_scale=float(args.deterrence_omega_scale),
        fixed_cue_mode="laser",
        habituation_kappa=float(args.habituation_kappa),
        truth_habituation_t_rec_s=None,
        truth_habituation_kappa=None,
        truth_habituation_gamma=None,
        truth_habituation_update_model=None,
        planner_habituation_t_rec_s=None,
        planner_habituation_kappa=None,
        planner_habituation_gamma=None,
        planner_habituation_update_model=None,
        stl_e_star=5.0,
        stl_t_cov_s=1200.0,
        stl_w_s=600.0,
        stl_eta_min=0.4,
        stl_horizon_s=300.0,
        stl_theta=12.0,
    )


def _selected_arms(arms_arg: str | None) -> list[tuple[str, str, dict[str, Any]]]:
    if not arms_arg:
        return list(ARMS)
    wanted = [a.strip() for a in str(arms_arg).split(",") if a.strip()]
    unknown = [a for a in wanted if a not in ARM_NAMES]
    if unknown:
        raise SystemExit(f"Unknown arm(s) {unknown}; choose from {ARM_NAMES}")
    return [arm for arm in ARMS if arm[0] in wanted]


def _hab_conditions(hab_arg: str) -> list[bool]:
    return {"both": [True, False], "on": [True], "off": [False]}[str(hab_arg)]


def build_jobs(args: argparse.Namespace) -> list[dict[str, Any]]:
    largs = _ladder_args(args)
    common = ladder._common_params(largs)
    systems = ladder._system_params(largs)
    jobs = []
    for seed in range(int(args.seed_start), int(args.seed_start) + int(args.num_runs)):
        for arm, system, overrides in _selected_arms(args.arms):
            for hab_enabled in _hab_conditions(args.hab):
                hab_params = ladder._habituation_params(hab_enabled, largs)
                # Same merge order as ladder._build_jobs: common, system, overrides, hab.
                params = dict(common)
                params.update(systems[system])
                params.update(dict(overrides))
                params.update(hab_params)
                hab = hab_params["habituation_condition"]
                jobs.append(
                    {
                        "system": f"{arm}_{hab}",
                        "baseline": arm,
                        "habituation_condition": hab,
                        "seed": int(seed),
                        "params": params,
                    }
                )
    return jobs


def _safe_float(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return f if math.isfinite(f) else float("nan")


def _values(rows: list[dict], arm: str, hab: str, metric: str) -> dict[int, float]:
    out = {}
    for row in rows:
        if row["baseline"] == arm and row["habituation_condition"] == hab:
            v = _safe_float(row.get(metric))
            if math.isfinite(v):
                out[int(row["seed"])] = v
    return out


def _paired(rows: list[dict], arm: str, ref: str, hab: str, metric: str) -> tuple[list[float], list[float]]:
    """Return (arm - ref deltas, ref values) over seeds present in both."""
    a = _values(rows, arm, hab, metric)
    r = _values(rows, ref, hab, metric)
    seeds = sorted(set(a) & set(r))
    return [a[s] - r[s] for s in seeds], [r[s] for s in seeds]


def paired_rows(rows: list[dict], reference: str = REFERENCE_ARM) -> list[dict]:
    out = []
    habs = sorted({r["habituation_condition"] for r in rows})
    arms = [a for a in ARM_NAMES if any(r["baseline"] == a for r in rows)]
    for hab in habs:
        for arm in arms:
            if arm == reference:
                continue
            for metric in [PRIMARY_METRIC] + MECHANISM_METRICS:
                deltas, refs = _paired(rows, arm, reference, hab, metric)
                if not deltas:
                    continue
                mean_d = float(stats.mean(deltas))
                ref_mean = float(stats.mean(refs))
                lo, hi = ladder._bootstrap_ci95(deltas, n_boot=N_BOOT, rng_seed=0)
                pct = 100.0 * mean_d / ref_mean if abs(ref_mean) > 1e-12 else float("nan")
                pct_lo = 100.0 * lo / ref_mean if abs(ref_mean) > 1e-12 else float("nan")
                pct_hi = 100.0 * hi / ref_mean if abs(ref_mean) > 1e-12 else float("nan")
                out.append(
                    {
                        "habituation_condition": hab,
                        "arm": arm,
                        "reference": reference,
                        "metric": metric,
                        "n_pairs": len(deltas),
                        "reference_mean": ref_mean,
                        "mean_delta": mean_d,
                        "boot_ci95_lo": lo,
                        "boot_ci95_hi": hi,
                        "pct_of_reference_mean": pct,
                        "pct_ci95_lo": pct_lo,
                        "pct_ci95_hi": pct_hi,
                        "n_arm_lower": sum(1 for d in deltas if d < 0.0),
                    }
                )
    return out


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    habs = sorted({r["habituation_condition"] for r in rows})
    arms = [a for a in ARM_NAMES if any(r["baseline"] == a for r in rows)]
    for hab in habs:
        for arm in arms:
            sub = [r for r in rows if r["baseline"] == arm and r["habituation_condition"] == hab]
            if not sub:
                continue
            srow: dict[str, Any] = {"baseline": arm, "habituation_condition": hab, "n": len(sub)}
            for field in ladder.METRIC_FIELDS + ["elapsed_s"]:
                vals = [v for v in (_safe_float(r.get(field)) for r in sub) if math.isfinite(v)]
                srow[f"{field}_mean"] = float(stats.mean(vals)) if vals else float("nan")
                srow[f"{field}_sd"] = float(stats.stdev(vals)) if len(vals) > 1 else float("nan")
            out.append(srow)
    return out


def _fmt(v: Any, digits: int = 1) -> str:
    f = _safe_float(v)
    return "n/a" if not math.isfinite(f) else f"{f:,.{digits}f}"


def _fmt_pct(v: Any) -> str:
    f = _safe_float(v)
    return "n/a" if not math.isfinite(f) else f"{f:+.2f}%"


def write_markdown(rows: list[dict], pairs: list[dict], outdir: Path, args: argparse.Namespace) -> None:
    seeds = sorted({int(r["seed"]) for r in rows})
    lines = [
        "# Overload Dispatch Diagnostics",
        "",
        f"- mu_true: `{args.mu}`",
        f"- Seeds: `{seeds[0]}-{seeds[-1]}` ({len(seeds)} seeds)" if seeds else "- Seeds: none",
        f"- Duration: `{args.duration_s}` s, grid `{args.nx}x{args.ny}`, robots `{args.nrobots}`",
        f"- Deterrence scales: beta `{args.deterrence_beta_scale}`, sigma `{args.deterrence_sigma_scale}`, "
        f"omega `{args.deterrence_omega_scale}`; kappa `{args.habituation_kappa}`; rho_res `{args.reservation_fraction}`",
        f"- Paired deltas are arm minus {REFERENCE_ARM} on matching seeds. Percent is the mean paired delta "
        f"as a percent of the {REFERENCE_ARM} mean. CI: percentile bootstrap of the paired mean difference "
        f"({N_BOOT} resamples over seeds). Negative exposure deltas are better.",
        "",
    ]
    habs = sorted({r["habituation_condition"] for r in rows})
    arms = [a for a in ARM_NAMES if any(r["baseline"] == a for r in rows)]
    for hab in habs:
        lines += [
            f"## {hab}: value-weighted exposure vs {REFERENCE_ARM}",
            "",
            "| Arm | n | Mean VWE | Mean delta | % of B1 | 95% boot CI (%) | Seeds lower |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for arm in arms:
            vals = list(_values(rows, arm, hab, PRIMARY_METRIC).values())
            if not vals:
                continue
            if arm == REFERENCE_ARM:
                lines.append(f"| {arm} | {len(vals)} | {_fmt(stats.mean(vals))} | ref | ref | ref | ref |")
                continue
            prow = next(
                (p for p in pairs if p["habituation_condition"] == hab and p["arm"] == arm
                 and p["metric"] == PRIMARY_METRIC),
                None,
            )
            if prow is None:
                lines.append(f"| {arm} | {len(vals)} | {_fmt(stats.mean(vals))} | n/a | n/a | n/a | n/a |")
                continue
            lines.append(
                f"| {arm} | {len(vals)} | {_fmt(stats.mean(vals))} | {_fmt(prow['mean_delta'])} | "
                f"{_fmt_pct(prow['pct_of_reference_mean'])} | "
                f"[{_fmt_pct(prow['pct_ci95_lo'])}, {_fmt_pct(prow['pct_ci95_hi'])}] | "
                f"{prow['n_arm_lower']}/{prow['n_pairs']} |"
            )
        lines += [
            "",
            f"### {hab}: mechanism metrics (arm means)",
            "",
            "| Arm | Reactive done | Reactive/robot-h | Resp. time s | Urgent overrides | Goal switches | "
            "Abandoned m | Hyst. blocked | Travel m |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for arm in arms:
            def m(metric: str, digits: int = 1) -> str:
                vals = list(_values(rows, arm, hab, metric).values())
                return _fmt(stats.mean(vals), digits) if vals else "n/a"

            if not _values(rows, arm, hab, PRIMARY_METRIC):
                continue
            lines.append(
                f"| {arm} | {m('reactive_completed_total')} | {m('reactive_completed_per_robot_hour', 2)} | "
                f"{m('reactive_mean_response_time_s')} | {m('urgent_reactive_override_total')} | "
                f"{m('goal_switch_total')} | {m('goal_switch_abandoned_distance_m')} | "
                f"{m('goal_switch_hysteresis_blocked_total')} | {m('travel_distance_total')} |"
            )
        lines.append("")

        b4_pairs = [
            (arm, _paired(rows, arm, "B4", hab, PRIMARY_METRIC))
            for arm in arms
            if arm.startswith("B4_")
        ]
        b4_pairs = [(arm, d) for arm, d in b4_pairs if d[0]]
        if b4_pairs:
            lines += [
                f"### {hab}: B4 variants vs B4 (value-weighted exposure)",
                "",
                "| Arm | n | Mean delta vs B4 | % of B4 | 95% boot CI (%) |",
                "|---|---:|---:|---:|---:|",
            ]
            for arm, (deltas, refs) in b4_pairs:
                ref_mean = float(stats.mean(refs))
                mean_d = float(stats.mean(deltas))
                lo, hi = ladder._bootstrap_ci95(deltas, n_boot=N_BOOT, rng_seed=0)
                scale = 100.0 / ref_mean if abs(ref_mean) > 1e-12 else float("nan")
                lines.append(
                    f"| {arm} | {len(deltas)} | {_fmt(mean_d)} | {_fmt_pct(mean_d * scale)} | "
                    f"[{_fmt_pct(lo * scale)}, {_fmt_pct(hi * scale)}] |"
                )
            lines.append("")

    lines += [
        "## Source tables",
        "",
        "- `per_run_metrics.csv`",
        "- `summary_by_system.csv`",
        "- `paired_vs_B1.csv` (all mechanism metrics, paired vs B1 with bootstrap CIs)",
        "",
    ]
    (outdir / "OVERLOAD_DIAGNOSTICS.md").write_text("\n".join(lines), encoding="utf-8")


def _load_raw(raw_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(row, dict) and {"baseline", "habituation_condition", "seed"} <= set(row):
            rows.append(row)
    return rows


def run(args: argparse.Namespace) -> list[dict]:
    outdir = Path(args.outdir or f"results/testbench/overload_diagnostics_{_mu_token(args.mu)}").resolve()
    raw_dir = outdir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    jobs = build_jobs(args)
    if args.resume:
        jobs = [
            j for j in jobs
            if not (raw_dir / f"{j['system']}_seed_{j['seed']}.json").exists()
        ]
    print(f"[overload] jobs={len(jobs)} outdir={outdir}", flush=True)
    started = time.time()

    def _save(row: dict, idx: int) -> None:
        (raw_dir / f"{row['system']}_seed_{row['seed']}.json").write_text(
            json.dumps(row, indent=2, allow_nan=True), encoding="utf-8"
        )
        print(
            f"[overload] done {idx}/{len(jobs)} {row['system']} seed={row['seed']} "
            f"elapsed={row['elapsed_s']:.1f}s VWE={row['value_weighted_exposure']:.1f} "
            f"switches={row.get('goal_switch_total')}",
            flush=True,
        )

    max_workers = max(1, min(int(args.max_workers), len(jobs))) if jobs else 1
    if max_workers == 1:
        for idx, job in enumerate(jobs, start=1):
            _save(ladder._run_one(job), idx)
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(ladder._run_one, job) for job in jobs]
            for idx, future in enumerate(as_completed(futures), start=1):
                _save(future.result(), idx)

    # Rebuild all outputs from every raw row on disk (supports --resume and partial reruns).
    rows = _load_raw(raw_dir)
    rows.sort(key=lambda r: (ARM_NAMES.index(r["baseline"]) if r["baseline"] in ARM_NAMES else 99,
                             r["habituation_condition"], int(r["seed"])))
    ladder._write_csv(rows, outdir / "per_run_metrics.csv")
    ladder._write_csv(summarize(rows), outdir / "summary_by_system.csv")
    pairs = paired_rows(rows)
    ladder._write_csv(pairs, outdir / "paired_vs_B1.csv")
    write_markdown(rows, pairs, outdir, args)
    (outdir / "manifest.json").write_text(
        json.dumps(
            {
                "args": vars(args),
                "arms": {name: {"system": sysname, "overrides": ov} for name, sysname, ov in ARMS},
                "job_count": len(jobs),
                "elapsed_s": time.time() - started,
            },
            indent=2,
            allow_nan=True,
        ),
        encoding="utf-8",
    )
    print(f"[overload] wrote {outdir}", flush=True)
    return rows


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Overload dispatch-mechanism diagnostics (B1 vs B4 arms).")
    p.add_argument("--outdir", default=None,
                   help="Default: results/testbench/overload_diagnostics_<mu token>")
    p.add_argument("--mu", type=float, default=4.0e-4)
    p.add_argument("--seed-start", type=int, default=200)
    p.add_argument("--num-runs", type=int, default=10)
    p.add_argument("--hab", choices=["both", "on", "off"], default="both")
    p.add_argument("--arms", default=None, help=f"Comma-separated subset of {ARM_NAMES}")
    p.add_argument("--max-workers", type=int, default=1)
    p.add_argument("--resume", action="store_true", help="Skip jobs whose raw JSON already exists.")
    p.add_argument("--duration-s", type=float, default=1800.0)
    p.add_argument("--warmup-s", type=float, default=0.0)
    p.add_argument("--nx", type=int, default=60)
    p.add_argument("--ny", type=int, default=48)
    p.add_argument("--nrobots", type=int, default=4)
    p.add_argument("--reservation-fraction", type=float, default=0.25)
    p.add_argument("--habituation-kappa", type=float, default=0.5)
    p.add_argument("--deterrence-beta-scale", type=float, default=4.0)
    p.add_argument("--deterrence-sigma-scale", type=float, default=4.0)
    p.add_argument("--deterrence-omega-scale", type=float, default=3.0)
    return p.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

import experiments.run_current_vs_main_benchmark as bench
import testbench.run_testbench as tb


FAMILY_ORDER: tuple[str, ...] = (
    "reservation_fraction",
    "reservation_window_s",
    "reactive_override_slack_s",
    "tau_service_s",
    "reservation_fraction_x_reservation_window_s",
    "reactive_override_slack_s_x_tau_service_s",
)
REGIME_ORDER: tuple[str, ...] = ("low", "nominal", "high")
REFERENCE_SYSTEM_KEY = "unc"
BASELINE_PLANNER_PROFILE = "thesis_calibrated_selective_proposed"
FIXED_DEFAULTS: dict[str, Any] = {
    "dispatch_policy": "res",
    "reservation_fraction": 0.25,
    "reservation_window_s": 600.0,
    "reactive_override_slack_s": 90.0,
    "tau_service_s": 20.0,
    "predictive_selection_policy": "utility",
}
ACCEPTANCE_THRESHOLDS: dict[str, float] = {
    "max_response_regression_pct": 10.0,
    "max_reactive_completed_fraction_drop": 0.05,
}
SHARED_EXTRA_PARAMS: dict[str, Any] = {
    "simulation_mode": "proposed",
    "enable_patrolling": True,
    "enable_intervention_feedback": True,
    "include_fallback_patrol": True,
    "enable_model_scored_deterring": True,
    "planner_profile": BASELINE_PLANNER_PROFILE,
    "report_metrics_end": False,
    "telemetry_clear_on_start": False,
    "telemetry_prompt_save": False,
}
OUTPUT_METRICS: tuple[str, ...] = (
    "native_value_weighted_exposure",
    "native_mean_response_time_s",
    "native_predictive_completed_fraction",
    "native_robot_predictive_fraction_mean",
    "native_reactive_load_factor_estimate",
    "native_reactive_generated_total",
    "native_predictive_generated_total",
    "native_reactive_admitted_total",
    "native_predictive_admitted_total",
    "native_reactive_completed_total",
    "native_predictive_completed_total",
    "native_urgent_reactive_override_total",
    "native_robot_idle_fraction_mean",
    "native_reactive_completed_fraction",
)
SCOREBOARD_METRICS: tuple[str, ...] = (
    "native_value_weighted_exposure",
    "native_mean_response_time_s",
    "native_predictive_completed_fraction",
    "native_robot_predictive_fraction_mean",
    "native_reactive_load_factor_estimate",
)
TIME_PLOT_METRICS: tuple[str, ...] = (
    "native_value_weighted_exposure",
    "native_mean_response_time_s",
    "native_predictive_completed_fraction",
    "native_robot_predictive_fraction_mean",
    "native_reactive_load_factor_estimate",
    "native_reactive_completed_fraction",
    "active_tasks",
)
LOAD_REGIMES: dict[str, dict[str, Any]] = {
    "low": {
        "title": "Low Load",
        "description": "Higher fleet capacity for the same proposed workload.",
        "scenario_overrides": {"Nrobots": 8},
    },
    "nominal": {
        "title": "Nominal Load",
        "description": "Nominal thesis sweep load regime.",
        "scenario_overrides": {},
    },
    "high": {
        "title": "High Load",
        "description": "Tighter fleet capacity for the same proposed workload.",
        "scenario_overrides": {"Nrobots": 3},
    },
}
FAMILY_VALUE_GRIDS: dict[str, Any] = {
    "reservation_fraction": [0.00, 0.10, 0.25, 0.40],
    "reservation_window_s": [120.0, 300.0, 600.0, 1200.0],
    "reactive_override_slack_s": [15.0, 45.0, 90.0, 180.0],
    "tau_service_s": [10.0, 20.0, 35.0, 50.0],
    "reservation_fraction_x_reservation_window_s": {
        "reservation_fraction": [0.10, 0.25, 0.40],
        "reservation_window_s": [120.0, 600.0, 1200.0],
    },
    "reactive_override_slack_s_x_tau_service_s": {
        "reactive_override_slack_s": [15.0, 90.0, 180.0],
        "tau_service_s": [10.0, 20.0, 35.0],
    },
}


@dataclass(frozen=True)
class SweepSpec:
    family: str
    regime: str
    smoke: bool
    config_name: str
    outdir_name: str
    reference_system: str
    swept_parameters: tuple[str, ...]
    fixed_defaults: dict[str, Any]
    config: dict[str, Any]


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return float(default)
    return out if math.isfinite(out) else float(default)


def _value_token(value: float) -> str:
    return f"{float(value):0.2f}".replace(".", "p").replace("-", "m")


def _format_value_for_title(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{float(value):g}"


def _base_scenario(*, smoke: bool, regime: str) -> dict[str, Any]:
    if regime not in LOAD_REGIMES:
        choices = ", ".join(REGIME_ORDER)
        raise ValueError(f"Unknown load regime {regime!r}. Expected one of: {choices}")
    scenario = {
        "num_runs": 2 if smoke else 3,
        "seed_start": 123,
        "duration_s": 300.0 if smoke else 900.0,
        "dt": 1.0,
        "fps": 1,
        "W": 500.0,
        "H": 500.0,
        "NX": 120,
        "NY": 96,
        "Nrobots": 6,
        "uav_fraction": 0.0,
        "task_replan_period_s": 45.0,
        "arrival_radius_m": 3.0,
        "hold_time_s": 20.0,
        "sample_every_s": 120.0 if smoke else 180.0,
        "warmup_s": 120.0 if smoke else 300.0,
        "extra_params": dict(SHARED_EXTRA_PARAMS),
    }
    scenario.update(dict(LOAD_REGIMES[regime]["scenario_overrides"]))
    return scenario


def _system_payload(*, key: str, title: str, description: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(key),
        "type": "repo_module",
        "repo": "current",
        "module": "DeterrentSystem",
        "title": str(title),
        "description": str(description),
        "params": dict(params),
    }


def _unc_system(*, regime: str) -> dict[str, Any]:
    return _system_payload(
        key=REFERENCE_SYSTEM_KEY,
        title=f"{LOAD_REGIMES[regime]['title']} UNC",
        description="Current proposed workload with unconstrained thesis dispatch as the previous-system baseline.",
        params={"dispatch_policy": "unc"},
    )


def _reservation_fraction_systems(*, regime: str) -> list[dict[str, Any]]:
    systems = [_unc_system(regime=regime)]
    for rho in FAMILY_VALUE_GRIDS["reservation_fraction"]:
        systems.append(
            _system_payload(
                key=f"res_rho_{_value_token(rho)}",
                title=f"{LOAD_REGIMES[regime]['title']} Res rho={_format_value_for_title(rho)}",
                description="Reserved-capacity dispatch with swept reservation fraction.",
                params={
                    "dispatch_policy": "res",
                    "reservation_fraction": float(rho),
                },
            )
        )
    return systems


def _reservation_window_systems(*, regime: str) -> list[dict[str, Any]]:
    systems = [_unc_system(regime=regime)]
    for window_s in FAMILY_VALUE_GRIDS["reservation_window_s"]:
        systems.append(
            _system_payload(
                key=f"res_tw_{int(window_s)}",
                title=f"{LOAD_REGIMES[regime]['title']} Res T_W={int(window_s)}",
                description="Reserved-capacity dispatch with swept reservation window.",
                params={
                    "dispatch_policy": "res",
                    "reservation_fraction": float(FIXED_DEFAULTS["reservation_fraction"]),
                    "reservation_window_s": float(window_s),
                },
            )
        )
    return systems


def _override_slack_systems(*, regime: str) -> list[dict[str, Any]]:
    systems = [_unc_system(regime=regime)]
    for slack_s in FAMILY_VALUE_GRIDS["reactive_override_slack_s"]:
        systems.append(
            _system_payload(
                key=f"res_slack_{int(slack_s):03d}",
                title=f"{LOAD_REGIMES[regime]['title']} Res tau_exp={int(slack_s)}",
                description="Reserved-capacity dispatch with swept reactive override slack.",
                params={
                    "dispatch_policy": "res",
                    "reservation_fraction": float(FIXED_DEFAULTS["reservation_fraction"]),
                    "reactive_override_slack_s": float(slack_s),
                },
            )
        )
    return systems


def _tau_service_systems(*, regime: str) -> list[dict[str, Any]]:
    systems = [_unc_system(regime=regime)]
    for tau_service_s in FAMILY_VALUE_GRIDS["tau_service_s"]:
        systems.append(
            _system_payload(
                key=f"res_tau_service_{int(tau_service_s):03d}",
                title=f"{LOAD_REGIMES[regime]['title']} Res tau_service={int(tau_service_s)}",
                description="Reserved-capacity dispatch with swept deterring service time.",
                params={
                    "dispatch_policy": "res",
                    "reservation_fraction": float(FIXED_DEFAULTS["reservation_fraction"]),
                    "tau_service_s": float(tau_service_s),
                },
            )
        )
    return systems


def _rho_window_interaction_systems(*, regime: str) -> list[dict[str, Any]]:
    systems = [_unc_system(regime=regime)]
    rho_values = FAMILY_VALUE_GRIDS["reservation_fraction_x_reservation_window_s"]["reservation_fraction"]
    window_values = FAMILY_VALUE_GRIDS["reservation_fraction_x_reservation_window_s"]["reservation_window_s"]
    for rho in rho_values:
        for window_s in window_values:
            systems.append(
                _system_payload(
                    key=f"res_rho_{_value_token(rho)}_tw_{int(window_s)}",
                    title=f"{LOAD_REGIMES[regime]['title']} rho={_format_value_for_title(rho)} T_W={int(window_s)}",
                    description="Reserved-capacity interaction sweep over reservation fraction and reservation window.",
                    params={
                        "dispatch_policy": "res",
                        "reservation_fraction": float(rho),
                        "reservation_window_s": float(window_s),
                    },
                )
            )
    return systems


def _slack_tau_interaction_systems(*, regime: str) -> list[dict[str, Any]]:
    systems = [_unc_system(regime=regime)]
    slack_values = FAMILY_VALUE_GRIDS["reactive_override_slack_s_x_tau_service_s"]["reactive_override_slack_s"]
    tau_values = FAMILY_VALUE_GRIDS["reactive_override_slack_s_x_tau_service_s"]["tau_service_s"]
    for slack_s in slack_values:
        for tau_service_s in tau_values:
            systems.append(
                _system_payload(
                    key=f"res_slack_{int(slack_s):03d}_tau_service_{int(tau_service_s):03d}",
                    title=f"{LOAD_REGIMES[regime]['title']} tau_exp={int(slack_s)} tau_service={int(tau_service_s)}",
                    description="Reserved-capacity interaction sweep over override slack and service time.",
                    params={
                        "dispatch_policy": "res",
                        "reservation_fraction": float(FIXED_DEFAULTS["reservation_fraction"]),
                        "reactive_override_slack_s": float(slack_s),
                        "tau_service_s": float(tau_service_s),
                    },
                )
            )
    return systems


def build_testbench_config(
    family: str,
    regime: str,
    *,
    smoke: bool,
    outdir: str | None = None,
) -> dict[str, Any]:
    if family == "reservation_fraction":
        systems = _reservation_fraction_systems(regime=regime)
        swept_parameters = ("reservation_fraction",)
    elif family == "reservation_window_s":
        systems = _reservation_window_systems(regime=regime)
        swept_parameters = ("reservation_window_s",)
    elif family == "reactive_override_slack_s":
        systems = _override_slack_systems(regime=regime)
        swept_parameters = ("reactive_override_slack_s",)
    elif family == "tau_service_s":
        systems = _tau_service_systems(regime=regime)
        swept_parameters = ("tau_service_s",)
    elif family == "reservation_fraction_x_reservation_window_s":
        systems = _rho_window_interaction_systems(regime=regime)
        swept_parameters = ("reservation_fraction", "reservation_window_s")
    elif family == "reactive_override_slack_s_x_tau_service_s":
        systems = _slack_tau_interaction_systems(regime=regime)
        swept_parameters = ("reactive_override_slack_s", "tau_service_s")
    else:
        choices = ", ".join(FAMILY_ORDER)
        raise ValueError(f"Unknown sweep family {family!r}. Expected one of: {choices}")

    config_name = f"thesis_sweep_{family}{'_smoke' if smoke else ''}_{regime}"
    return {
        "scenario": _base_scenario(smoke=smoke, regime=regime),
        "outputs": {
            "outdir": (
                str(outdir)
                if outdir is not None
                else f"results/testbench/{config_name}"
            ),
            "reference_system": REFERENCE_SYSTEM_KEY,
            "metrics": list(OUTPUT_METRICS),
            "scoreboard_metrics": list(SCOREBOARD_METRICS),
            "time_plot_metrics": list(TIME_PLOT_METRICS),
        },
        "systems": systems,
        "metadata": {
            "sweep_family": str(family),
            "load_regime": str(regime),
            "smoke": bool(smoke),
            "reference_system": REFERENCE_SYSTEM_KEY,
            "swept_parameters": list(swept_parameters),
            "fixed_defaults": dict(FIXED_DEFAULTS),
            "load_regime_details": dict(LOAD_REGIMES[regime]),
            "acceptance_thresholds": dict(ACCEPTANCE_THRESHOLDS),
        },
    }


def build_sweep_spec(
    family: str,
    regime: str,
    *,
    smoke: bool,
    outdir_root: Path,
) -> SweepSpec:
    config_name = f"thesis_sweep_{family}{'_smoke' if smoke else ''}_{regime}"
    config = build_testbench_config(
        family,
        regime,
        smoke=smoke,
        outdir=str((outdir_root / config_name).resolve()),
    )
    metadata = dict(config.get("metadata") or {})
    return SweepSpec(
        family=str(family),
        regime=str(regime),
        smoke=bool(smoke),
        config_name=config_name,
        outdir_name=config_name,
        reference_system=str(metadata.get("reference_system", REFERENCE_SYSTEM_KEY)),
        swept_parameters=tuple(str(value) for value in metadata.get("swept_parameters", [])),
        fixed_defaults=dict(metadata.get("fixed_defaults", {})),
        config=config,
    )


def build_sweep_specs(
    *,
    smoke: bool,
    families: Sequence[str] | None = None,
    regimes: Sequence[str] | None = None,
    include_interactions: bool = True,
    outdir_root: Path,
) -> list[SweepSpec]:
    selected_families = list(families or FAMILY_ORDER)
    if not include_interactions:
        selected_families = [family for family in selected_families if "x" not in family]
    selected_regimes = list(regimes or REGIME_ORDER)
    specs: list[SweepSpec] = []
    for family in FAMILY_ORDER:
        if family not in selected_families:
            continue
        for regime in REGIME_ORDER:
            if regime not in selected_regimes:
                continue
            specs.append(
                build_sweep_spec(
                    family,
                    regime,
                    smoke=smoke,
                    outdir_root=outdir_root,
                )
            )
    return specs


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _build_best_setting_by_metric(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return pd.DataFrame(columns=["metric", "label", "goal", "winner"])
    out = summary_df[["metric", "label", "goal", "winner"]].copy()
    return out


def _summary_metric_winner(summary_df: pd.DataFrame, metric: str) -> str:
    if summary_df.empty or "metric" not in summary_df.columns:
        return ""
    row = summary_df.loc[summary_df["metric"] == metric]
    if row.empty:
        return ""
    return str(row.iloc[0].get("winner", "") or "")


def _mean_for_system(per_run_df: pd.DataFrame, system_key: str, column: str) -> float:
    if per_run_df.empty or column not in per_run_df.columns:
        return float("nan")
    subset = pd.to_numeric(
        per_run_df.loc[per_run_df["system"] == system_key, column],
        errors="coerce",
    ).dropna()
    if subset.empty:
        return float("nan")
    return float(subset.mean())


def build_sweep_result_summary(
    *,
    spec: SweepSpec,
    summary_df: pd.DataFrame,
    per_run_df: pd.DataFrame,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    reference = str(spec.reference_system)
    reference_response = _mean_for_system(per_run_df, reference, "native_mean_response_time_s")
    reference_reactive_completed = _mean_for_system(
        per_run_df,
        reference,
        "native_reactive_completed_fraction",
    )
    reference_predictive_util = _mean_for_system(
        per_run_df,
        reference,
        "native_robot_predictive_fraction_mean",
    )
    max_response_regression = float(thresholds["max_response_regression_pct"]) / 100.0
    max_reactive_completed_drop = float(thresholds["max_reactive_completed_fraction_drop"])

    promising: list[str] = []
    if not per_run_df.empty and "system" in per_run_df.columns:
        for system_key in sorted(set(str(value) for value in per_run_df["system"].dropna().tolist())):
            if system_key == reference:
                continue
            response_mean = _mean_for_system(per_run_df, system_key, "native_mean_response_time_s")
            reactive_completed_mean = _mean_for_system(
                per_run_df,
                system_key,
                "native_reactive_completed_fraction",
            )
            predictive_util_mean = _mean_for_system(
                per_run_df,
                system_key,
                "native_robot_predictive_fraction_mean",
            )
            if not math.isfinite(response_mean) or not math.isfinite(reactive_completed_mean):
                continue
            if not math.isfinite(predictive_util_mean) or not math.isfinite(reference_predictive_util):
                continue
            if predictive_util_mean <= reference_predictive_util:
                continue
            if math.isfinite(reference_response) and response_mean > (reference_response * (1.0 + max_response_regression)):
                continue
            if math.isfinite(reference_reactive_completed) and reactive_completed_mean < (
                reference_reactive_completed - max_reactive_completed_drop
            ):
                continue
            promising.append(system_key)

    return {
        "family": spec.family,
        "regime": spec.regime,
        "smoke": bool(spec.smoke),
        "reference_system": reference,
        "best_exposure_system": _summary_metric_winner(summary_df, "native_value_weighted_exposure"),
        "best_response_system": _summary_metric_winner(summary_df, "native_mean_response_time_s"),
        "best_predictive_completion_system": _summary_metric_winner(summary_df, "native_predictive_completed_fraction"),
        "best_predictive_utilization_system": _summary_metric_winner(
            summary_df,
            "native_robot_predictive_fraction_mean",
        ),
        "promising_systems": list(promising),
        "swept_parameters": list(spec.swept_parameters),
    }


def build_suite_manifest(
    *,
    specs: Sequence[SweepSpec],
    thresholds: dict[str, float],
    summary_rows: Sequence[dict[str, Any]],
    outdir: Path,
) -> dict[str, Any]:
    return {
        "outdir": str(outdir.resolve()),
        "acceptance_thresholds": dict(thresholds),
        "fixed_defaults": dict(FIXED_DEFAULTS),
        "sweeps": [
            {
                "family": spec.family,
                "regime": spec.regime,
                "smoke": bool(spec.smoke),
                "config_name": spec.config_name,
                "outdir_name": spec.outdir_name,
                "reference_system": spec.reference_system,
                "swept_parameters": list(spec.swept_parameters),
                "fixed_defaults": dict(spec.fixed_defaults),
            }
            for spec in specs
        ],
        "summary_rows": [dict(row) for row in summary_rows],
    }


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows_"
    return bench._dataframe_to_markdown(df)


def _write_suite_report(
    out_path: Path,
    *,
    overview_df: pd.DataFrame,
    manifest: dict[str, Any],
) -> None:
    thresholds = dict(manifest.get("acceptance_thresholds", {}))
    lines = [
        "# Thesis Variable Sweep Summary",
        "",
        "This report aggregates layered testbench sweeps of the new thesis variables against the `unc` baseline.",
        "",
        "## Acceptance Thresholds",
        "",
    ]
    for key in sorted(thresholds.keys()):
        lines.append(f"- `{key}`: `{thresholds[key]}`")
    lines.extend(
        [
            "",
            "## Sweep Overview",
            "",
            _markdown_table(overview_df),
            "",
            "Promising systems improve predictive utilization over `unc` while staying within the recorded reactive guardrails.",
            "",
            "## Artifacts",
            "",
            "- `sweep_overview.csv`: one row per sweep/regime result bundle",
            "- `suite_manifest.json`: sweep spec metadata, defaults, and thresholds",
            "- `report.md`: this summary",
            "- each sweep subdirectory contains `per_run_metrics.csv`, `summary_by_metric.csv`, `advantage_vs_reference.csv`, `per_run_timeseries.csv`, `report.md`, and `best_setting_by_metric.csv`",
        ]
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_generated_config(path: Path, config: dict[str, Any]) -> None:
    _write_json(path, config)


def _run_testbench_config(
    config_path: Path,
    *,
    current_repo: Path,
    main_repo: Path,
    max_workers: int,
) -> int:
    argv = [
        "--config",
        str(config_path.resolve()),
        "--current-repo",
        str(current_repo.resolve()),
        "--main-repo",
        str(main_repo.resolve()),
        "--max-workers",
        str(max_workers),
    ]
    return int(tb.main(argv))


def run_suite(args: argparse.Namespace) -> dict[str, Any]:
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    config_outdir = outdir / "generated_configs"
    config_outdir.mkdir(parents=True, exist_ok=True)
    current_repo = Path(args.current_repo).resolve()
    main_repo = Path(args.main_repo).resolve()

    specs = build_sweep_specs(
        smoke=bool(args.smoke),
        families=list(args.family or []),
        regimes=list(args.regime or []),
        include_interactions=(not bool(args.skip_interactions)),
        outdir_root=outdir,
    )
    overview_rows: list[dict[str, Any]] = []
    for spec in specs:
        config_path = config_outdir / f"{spec.config_name}.json"
        _write_generated_config(config_path, spec.config)
        rc = _run_testbench_config(
            config_path,
            current_repo=current_repo,
            main_repo=main_repo,
            max_workers=max(1, int(args.max_workers)),
        )
        if rc != 0:
            raise RuntimeError(f"Testbench sweep failed for {spec.config_name} (rc={rc}).")

        sweep_outdir = Path(spec.config["outputs"]["outdir"]).resolve()
        summary_df = _read_csv(sweep_outdir / "summary_by_metric.csv")
        per_run_df = _read_csv(sweep_outdir / "per_run_metrics.csv")
        best_df = _build_best_setting_by_metric(summary_df)
        best_df.to_csv(sweep_outdir / "best_setting_by_metric.csv", index=False)
        overview_rows.append(
            build_sweep_result_summary(
                spec=spec,
                summary_df=summary_df,
                per_run_df=per_run_df,
                thresholds=ACCEPTANCE_THRESHOLDS,
            )
        )

    overview_df = pd.DataFrame(overview_rows)
    overview_csv = outdir / "sweep_overview.csv"
    overview_df.to_csv(overview_csv, index=False)
    manifest = build_suite_manifest(
        specs=specs,
        thresholds=ACCEPTANCE_THRESHOLDS,
        summary_rows=overview_rows,
        outdir=outdir,
    )
    manifest_path = outdir / "suite_manifest.json"
    _write_json(manifest_path, manifest)
    _write_suite_report(outdir / "report.md", overview_df=overview_df, manifest=manifest)
    print(f"[thesis-sweeps] wrote {overview_csv}", flush=True)
    print(f"[thesis-sweeps] wrote {manifest_path}", flush=True)
    return {
        "specs": specs,
        "overview": overview_df,
        "manifest": manifest,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run layered thesis-variable sweeps against the unc baseline.")
    parser.add_argument("--outdir", default="results/thesis_variable_sweeps")
    parser.add_argument("--current-repo", default=str(Path.cwd()))
    parser.add_argument("--main-repo", default=str(Path.cwd().parent / f"{Path.cwd().name}-main"))
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--skip-interactions", action="store_true")
    parser.add_argument("--family", choices=FAMILY_ORDER, nargs="*", default=[])
    parser.add_argument("--regime", choices=REGIME_ORDER, nargs="*", default=[])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    run_suite(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_CALIBRATION_DIR = Path("results") / "sestpp_calibration_sweep"
DEFAULT_CALIBRATION_RANKING_PATH = DEFAULT_CALIBRATION_DIR / "sestpp_calibration_sweep_ranking.csv"
DEFAULT_CALIBRATION_MANIFEST_PATH = DEFAULT_CALIBRATION_DIR / "sestpp_calibration_sweep_manifest.json"

REQUIRED_CALIBRATION_COLUMNS = (
    "config_id",
    "model_alpha_inhib",
    "model_omega_inhib",
    "model_mu_base",
    "model_bg_ema",
)

OPTIONAL_CALIBRATION_METRIC_COLUMNS = (
    "rank",
    "proposed_field_logloss_mean",
    "proposed_field_logloss_ci95",
    "proposed_field_brier_mean",
    "proposed_field_brier_ci95",
    "proposed_nll_mean",
    "proposed_nll_ci95",
    "delta_field_logloss_proposed_minus_prediction_mean",
    "delta_field_brier_proposed_minus_prediction_mean",
    "delta_nll_proposed_minus_prediction_mean",
    "logloss_improvement_pct_mean",
    "brier_improvement_pct_mean",
    "nll_improvement_pct_mean",
)


@dataclass(frozen=True)
class FrozenCalibrationConfig:
    config_id: str
    model_alpha_inhib: float
    model_omega_inhib: float
    model_mu_base: float
    model_bg_ema: float
    summary_metrics: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""
    source_type: str = ""

    def to_runtime_overrides(self) -> dict[str, float]:
        return {
            "alpha_inhib": float(self.model_alpha_inhib),
            "omega_inhib": float(self.model_omega_inhib),
            "mu_base": float(self.model_mu_base),
            "bg_ema": float(self.model_bg_ema),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": str(self.config_id),
            "model_alpha_inhib": float(self.model_alpha_inhib),
            "model_omega_inhib": float(self.model_omega_inhib),
            "model_mu_base": float(self.model_mu_base),
            "model_bg_ema": float(self.model_bg_ema),
            "summary_metrics": dict(self.summary_metrics),
            "source_path": str(self.source_path),
            "source_type": str(self.source_type),
        }


def _resolve_existing_path(path_value: str | Path | None) -> Path | None:
    if path_value in (None, ""):
        return None
    path = Path(path_value)
    return path if path.exists() else None


def _resolve_default_source_paths(
    ranking_path: str | Path | None,
    manifest_path: str | Path | None,
) -> tuple[Path | None, Path | None]:
    ranking = _resolve_existing_path(ranking_path)
    manifest = _resolve_existing_path(manifest_path)
    if ranking is not None or manifest is not None:
        return ranking, manifest

    default_ranking = _resolve_existing_path(DEFAULT_CALIBRATION_RANKING_PATH)
    default_manifest = _resolve_existing_path(DEFAULT_CALIBRATION_MANIFEST_PATH)
    return default_ranking, default_manifest


def _validate_required_columns(frame: pd.DataFrame, source_path: Path) -> None:
    missing = [col for col in REQUIRED_CALIBRATION_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(
            "Calibration ranking is missing required columns "
            f"{missing} in {source_path}"
        )


def _coerce_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key, value in payload.items():
        if key in REQUIRED_CALIBRATION_COLUMNS:
            continue
        if key == "config_id":
            continue
        if hasattr(value, "item"):
            value = value.item()
        metrics[str(key)] = value
    return metrics


def _from_row(row: pd.Series, *, source_path: Path, source_type: str) -> FrozenCalibrationConfig:
    payload = row.to_dict()
    return FrozenCalibrationConfig(
        config_id=str(payload["config_id"]),
        model_alpha_inhib=float(payload["model_alpha_inhib"]),
        model_omega_inhib=float(payload["model_omega_inhib"]),
        model_mu_base=float(payload["model_mu_base"]),
        model_bg_ema=float(payload["model_bg_ema"]),
        summary_metrics=_coerce_metrics(payload),
        source_path=str(source_path),
        source_type=str(source_type),
    )


def _load_ranking_row(ranking_path: Path, config_id: str | None) -> FrozenCalibrationConfig:
    ranking_df = pd.read_csv(ranking_path)
    _validate_required_columns(ranking_df, ranking_path)
    if ranking_df.empty:
        raise ValueError(f"Calibration ranking is empty: {ranking_path}")

    if config_id:
        selected = ranking_df[ranking_df["config_id"].astype(str) == str(config_id)]
        if selected.empty:
            raise ValueError(
                f"Calibration config_id {config_id!r} was not found in ranking {ranking_path}"
            )
        row = selected.iloc[0]
    else:
        if "rank" in ranking_df.columns:
            ordered = ranking_df.sort_values(by=["rank", "config_id"], ascending=[True, True])
            row = ordered.iloc[0]
        else:
            row = ranking_df.iloc[0]
    return _from_row(row, source_path=ranking_path, source_type="ranking_csv")


def _resolve_manifest_ranking_path(manifest_path: Path, manifest: dict[str, Any]) -> Path | None:
    outputs = manifest.get("outputs", {})
    ranking_value = outputs.get("ranking_csv")
    if ranking_value:
        candidate = Path(ranking_value)
        if not candidate.is_absolute():
            candidate = manifest_path.parent / candidate
        if candidate.exists():
            return candidate

    sibling = manifest_path.parent / DEFAULT_CALIBRATION_RANKING_PATH.name
    return sibling if sibling.exists() else None


def _load_manifest_payload(manifest_path: Path) -> dict[str, Any]:
    with open(manifest_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Calibration manifest must contain a JSON object: {manifest_path}")
    return payload


def _load_from_manifest_only(manifest_path: Path, manifest: dict[str, Any], config_id: str | None) -> FrozenCalibrationConfig:
    if config_id in (None, ""):
        best = manifest.get("best_config")
        if isinstance(best, dict):
            payload = dict(best)
            missing = [col for col in REQUIRED_CALIBRATION_COLUMNS if col not in payload]
            if missing:
                raise ValueError(
                    "Calibration manifest best_config is missing required fields "
                    f"{missing} in {manifest_path}"
                )
            return FrozenCalibrationConfig(
                config_id=str(payload["config_id"]),
                model_alpha_inhib=float(payload["model_alpha_inhib"]),
                model_omega_inhib=float(payload["model_omega_inhib"]),
                model_mu_base=float(payload["model_mu_base"]),
                model_bg_ema=float(payload["model_bg_ema"]),
                summary_metrics=_coerce_metrics(payload),
                source_path=str(manifest_path),
                source_type="manifest_best_config",
            )
        raise ValueError(
            "Calibration manifest does not expose a ranking CSV or best_config entry, "
            f"so the top-ranked config cannot be determined from {manifest_path}"
        )

    grid = manifest.get("grid", [])
    if not isinstance(grid, list):
        raise ValueError(f"Calibration manifest grid must be a list: {manifest_path}")
    for entry in grid:
        if str(entry.get("config_id", "")) != str(config_id):
            continue
        missing = [col for col in REQUIRED_CALIBRATION_COLUMNS if col not in entry]
        if missing:
            raise ValueError(
                "Calibration manifest grid entry is missing required fields "
                f"{missing} in {manifest_path}"
            )
        return FrozenCalibrationConfig(
            config_id=str(entry["config_id"]),
            model_alpha_inhib=float(entry["model_alpha_inhib"]),
            model_omega_inhib=float(entry["model_omega_inhib"]),
            model_mu_base=float(entry["model_mu_base"]),
            model_bg_ema=float(entry["model_bg_ema"]),
            summary_metrics={},
            source_path=str(manifest_path),
            source_type="manifest_grid",
        )

    raise ValueError(
        f"Calibration config_id {config_id!r} was not found in manifest {manifest_path}"
    )


def load_frozen_sestpp_calibration(
    *,
    ranking_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    config_id: str | None = None,
) -> FrozenCalibrationConfig:
    """Load a frozen SESTPP calibration result from ranking CSV or sweep manifest."""

    resolved_ranking, resolved_manifest = _resolve_default_source_paths(ranking_path, manifest_path)
    if resolved_ranking is not None:
        return _load_ranking_row(resolved_ranking, config_id=config_id)

    if resolved_manifest is not None:
        manifest = _load_manifest_payload(resolved_manifest)
        manifest_ranking = _resolve_manifest_ranking_path(resolved_manifest, manifest)
        if manifest_ranking is not None:
            return _load_ranking_row(manifest_ranking, config_id=config_id)
        return _load_from_manifest_only(resolved_manifest, manifest, config_id=config_id)

    raise FileNotFoundError(
        "No calibration source was found. Provide --calibration-ranking-path, "
        "--calibration-manifest-path, or run the sweep to create "
        f"{DEFAULT_CALIBRATION_DIR}."
    )

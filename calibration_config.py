from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_CALIBRATION_DIR = Path("results") / "sestpp_calibration_sweep"
DEFAULT_CALIBRATION_RANKING_PATH = DEFAULT_CALIBRATION_DIR / "sestpp_calibration_sweep_ranking.csv"
DEFAULT_CALIBRATION_MANIFEST_PATH = DEFAULT_CALIBRATION_DIR / "sestpp_calibration_sweep_manifest.json"

LEGACY_REQUIRED_CALIBRATION_COLUMNS = (
    "config_id",
    "model_alpha_inhib",
    "model_omega_inhib",
    "model_mu_base",
    "model_bg_ema",
)

MODE_NAMES = ("prediction_only", "proposed")
MODE_REQUIRED_PARAMETER_FIELDS = (
    "model_alpha_inhib",
    "model_omega_inhib",
    "model_mu_base",
    "model_bg_ema",
)
MODE_OPTIONAL_PARAMETER_FIELDS = (
    "model_sigma",
    "model_omega",
    "model_alpha_in",
    "model_alpha_cross",
    "model_feedback_sigma_scale",
    "model_feedback_omega_scale",
)
MODE_PARAMETER_FIELDS = MODE_REQUIRED_PARAMETER_FIELDS + MODE_OPTIONAL_PARAMETER_FIELDS

OPTIONAL_CALIBRATION_METRIC_COLUMNS = (
    "rank",
    "prediction_only_field_logloss_mean",
    "prediction_only_field_logloss_ci95",
    "prediction_only_field_brier_mean",
    "prediction_only_field_brier_ci95",
    "prediction_only_nll_mean",
    "prediction_only_nll_ci95",
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
class FrozenModelCalibration:
    model_alpha_inhib: float
    model_omega_inhib: float
    model_mu_base: float
    model_bg_ema: float
    model_sigma: float | None = None
    model_omega: float | None = None
    model_alpha_in: float | None = None
    model_alpha_cross: float | None = None
    model_feedback_sigma_scale: float = 1.0
    model_feedback_omega_scale: float = 1.0

    def to_runtime_overrides(self) -> dict[str, float]:
        overrides: dict[str, float] = {
            "alpha_inhib": float(self.model_alpha_inhib),
            "omega_inhib": float(self.model_omega_inhib),
            "mu_base": float(self.model_mu_base),
            "bg_ema": float(self.model_bg_ema),
            "model_feedback_sigma_scale": float(self.model_feedback_sigma_scale),
            "model_feedback_omega_scale": float(self.model_feedback_omega_scale),
        }
        if self.model_sigma is not None:
            overrides["sigma"] = float(self.model_sigma)
        if self.model_omega is not None:
            overrides["omega"] = float(self.model_omega)
        if self.model_alpha_in is not None:
            overrides["alpha_in"] = float(self.model_alpha_in)
        if self.model_alpha_cross is not None:
            overrides["alpha_cross"] = float(self.model_alpha_cross)
        return overrides

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_alpha_inhib": float(self.model_alpha_inhib),
            "model_omega_inhib": float(self.model_omega_inhib),
            "model_mu_base": float(self.model_mu_base),
            "model_bg_ema": float(self.model_bg_ema),
            "model_sigma": (None if self.model_sigma is None else float(self.model_sigma)),
            "model_omega": (None if self.model_omega is None else float(self.model_omega)),
            "model_alpha_in": (None if self.model_alpha_in is None else float(self.model_alpha_in)),
            "model_alpha_cross": (None if self.model_alpha_cross is None else float(self.model_alpha_cross)),
            "model_feedback_sigma_scale": float(self.model_feedback_sigma_scale),
            "model_feedback_omega_scale": float(self.model_feedback_omega_scale),
        }


@dataclass(frozen=True)
class FrozenCalibrationConfig:
    config_id: str
    prediction_only: FrozenModelCalibration
    proposed: FrozenModelCalibration
    prediction_only_config_id: str = ""
    proposed_config_id: str = ""
    summary_metrics: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""
    source_type: str = ""

    def params_for_mode(self, simulation_mode: str) -> FrozenModelCalibration:
        mode_key = str(simulation_mode).strip().lower()
        return self.proposed if mode_key == "proposed" else self.prediction_only

    def to_runtime_overrides(self, simulation_mode: str) -> dict[str, float]:
        return self.params_for_mode(simulation_mode).to_runtime_overrides()

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": str(self.config_id),
            "prediction_only_config_id": str(self.prediction_only_config_id or ""),
            "proposed_config_id": str(self.proposed_config_id or ""),
            "best_models": {
                "prediction_only": self.prediction_only.to_dict(),
                "proposed": self.proposed.to_dict(),
            },
            "summary_metrics": dict(self.summary_metrics),
            "source_path": str(self.source_path),
            "source_type": str(self.source_type),
        }

    # Backward-compatible aliases: legacy callers used the shared/proposed values.
    @property
    def model_alpha_inhib(self) -> float:
        return float(self.proposed.model_alpha_inhib)

    @property
    def model_omega_inhib(self) -> float:
        return float(self.proposed.model_omega_inhib)

    @property
    def model_mu_base(self) -> float:
        return float(self.proposed.model_mu_base)

    @property
    def model_bg_ema(self) -> float:
        return float(self.proposed.model_bg_ema)

    @property
    def model_sigma(self) -> float | None:
        return self.proposed.model_sigma

    @property
    def model_omega(self) -> float | None:
        return self.proposed.model_omega

    @property
    def model_alpha_in(self) -> float | None:
        return self.proposed.model_alpha_in

    @property
    def model_alpha_cross(self) -> float | None:
        return self.proposed.model_alpha_cross

    @property
    def model_feedback_sigma_scale(self) -> float:
        return float(self.proposed.model_feedback_sigma_scale)

    @property
    def model_feedback_omega_scale(self) -> float:
        return float(self.proposed.model_feedback_omega_scale)


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


def _coerce_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "config_id":
            continue
        if hasattr(value, "item"):
            value = value.item()
        metrics[str(key)] = value
    return metrics


def _optional_float(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def _float_with_default(payload: dict[str, Any], key: str, default: float) -> float:
    value = _optional_float(payload, key)
    return float(default if value is None else value)


def _mode_payload_from_flat_payload(payload: dict[str, Any], mode: str) -> dict[str, Any]:
    prefix = f"{mode}_"
    out: dict[str, Any] = {}
    for field_name in MODE_PARAMETER_FIELDS:
        prefixed_key = f"{prefix}{field_name}"
        if prefixed_key in payload:
            out[field_name] = payload[prefixed_key]
    return out


def _has_mode_specific_flat_schema(payload: dict[str, Any]) -> bool:
    return any(f"{mode}_model_mu_base" in payload for mode in MODE_NAMES)


def _parse_model_payload(payload: dict[str, Any], *, source_path: Path, mode: str) -> FrozenModelCalibration:
    missing = [field_name for field_name in MODE_REQUIRED_PARAMETER_FIELDS if field_name not in payload]
    if missing:
        raise ValueError(
            f"Calibration payload for {mode} is missing required fields {missing} in {source_path}"
        )
    return FrozenModelCalibration(
        model_alpha_inhib=float(payload["model_alpha_inhib"]),
        model_omega_inhib=float(payload["model_omega_inhib"]),
        model_mu_base=float(payload["model_mu_base"]),
        model_bg_ema=float(payload["model_bg_ema"]),
        model_sigma=_optional_float(payload, "model_sigma"),
        model_omega=_optional_float(payload, "model_omega"),
        model_alpha_in=_optional_float(payload, "model_alpha_in"),
        model_alpha_cross=_optional_float(payload, "model_alpha_cross"),
        model_feedback_sigma_scale=_float_with_default(payload, "model_feedback_sigma_scale", 1.0),
        model_feedback_omega_scale=_float_with_default(payload, "model_feedback_omega_scale", 1.0),
    )


def _from_legacy_payload(
    payload: dict[str, Any],
    *,
    source_path: Path,
    source_type: str,
) -> FrozenCalibrationConfig:
    missing = [col for col in LEGACY_REQUIRED_CALIBRATION_COLUMNS if col not in payload]
    if missing:
        raise ValueError(
            "Calibration payload is missing required legacy fields "
            f"{missing} in {source_path}"
        )
    shared = _parse_model_payload(payload, source_path=source_path, mode="legacy")
    return FrozenCalibrationConfig(
        config_id=str(payload["config_id"]),
        prediction_only=shared,
        proposed=shared,
        prediction_only_config_id=str(payload.get("shared_config_id", payload["config_id"])),
        proposed_config_id=str(payload.get("feedback_config_id", payload["config_id"])),
        summary_metrics=_coerce_metrics(payload),
        source_path=str(source_path),
        source_type=str(source_type),
    )


def _from_mode_specific_payload(
    payload: dict[str, Any],
    *,
    source_path: Path,
    source_type: str,
) -> FrozenCalibrationConfig:
    nested_models = payload.get("best_models")
    if isinstance(nested_models, dict):
        pred_payload = nested_models.get("prediction_only")
        prop_payload = nested_models.get("proposed")
        if not isinstance(pred_payload, dict) or not isinstance(prop_payload, dict):
            raise ValueError(
                "Calibration payload best_models must expose prediction_only and proposed mappings "
                f"in {source_path}"
            )
    else:
        pred_payload = _mode_payload_from_flat_payload(payload, "prediction_only")
        prop_payload = _mode_payload_from_flat_payload(payload, "proposed")

    prediction_only = _parse_model_payload(pred_payload, source_path=source_path, mode="prediction_only")
    proposed = _parse_model_payload(prop_payload, source_path=source_path, mode="proposed")
    return FrozenCalibrationConfig(
        config_id=str(payload["config_id"]),
        prediction_only=prediction_only,
        proposed=proposed,
        prediction_only_config_id=str(payload.get("prediction_only_config_id", payload.get("shared_config_id", ""))),
        proposed_config_id=str(payload.get("proposed_config_id", payload.get("feedback_config_id", ""))),
        summary_metrics=_coerce_metrics(payload),
        source_path=str(source_path),
        source_type=str(source_type),
    )


def _from_payload(payload: dict[str, Any], *, source_path: Path, source_type: str) -> FrozenCalibrationConfig:
    if "config_id" not in payload:
        raise ValueError(f"Calibration payload is missing config_id in {source_path}")
    if _has_mode_specific_flat_schema(payload) or isinstance(payload.get("best_models"), dict):
        return _from_mode_specific_payload(payload, source_path=source_path, source_type=source_type)
    return _from_legacy_payload(payload, source_path=source_path, source_type=source_type)


def _load_ranking_row(ranking_path: Path, config_id: str | None) -> FrozenCalibrationConfig:
    ranking_df = pd.read_csv(ranking_path)
    if "config_id" not in ranking_df.columns:
        raise ValueError(f"Calibration ranking is missing config_id in {ranking_path}")
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
    return _from_payload(row.to_dict(), source_path=ranking_path, source_type="ranking_csv")


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
            if "config_id" not in payload:
                payload["config_id"] = str(manifest.get("best_config_id", ""))
            if isinstance(manifest.get("best_models"), dict) and "best_models" not in payload:
                payload["best_models"] = dict(manifest["best_models"])
            return _from_payload(payload, source_path=manifest_path, source_type="manifest_best_config")
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
        return _from_payload(dict(entry), source_path=manifest_path, source_type="manifest_grid")

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

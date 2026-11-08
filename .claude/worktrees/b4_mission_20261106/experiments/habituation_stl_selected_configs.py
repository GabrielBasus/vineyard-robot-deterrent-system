from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Mirrors the aliases in run_habituation_stl_production_ladder._build_jobs so that
# selected_configs.json entries recorded under legacy names (e.g. B3_res_stl_nohab_fixedcue)
# are returned under the canonical name that _build_jobs uses for override lookup.
SYSTEM_ALIASES: dict[str, str] = {
    "B1_unc_legacy": "B1_greedy_fixedcue",
    "B2_res_deltaJ": "B2_res_deltaJ_fixedcue",
    "B3_res_stl_nohab": "B3_res_stl_nohab_multicue",
    "B3_res_stl_nohab_fixedcue": "B3_res_stl_nohab_multicue",
    "B4_res_stl_full": "B4_res_stl_full_multicue",
}


def load_selected_config_overrides(
    selection_path: str | Path | None,
    *,
    systems: list[str] | tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """Load per-baseline frozen overrides from a fair-tuning selected-config file.

    Keys in the returned dict are canonical system names (after alias resolution),
    matching what run_habituation_stl_production_ladder._build_jobs uses for lookup.
    """
    if selection_path is None:
        return {}
    path = Path(selection_path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list of selected configs in {path}")

    # Resolve aliases in the caller's systems list so the wanted set uses canonical names.
    if systems is not None:
        wanted = {SYSTEM_ALIASES.get(str(s), str(s)) for s in systems}
    else:
        wanted = None

    out: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"Selected config row {idx} in {path} is not an object")
        raw_baseline = str(row.get("baseline", "")).strip()
        if not raw_baseline:
            raise ValueError(f"Selected config row {idx} in {path} has no baseline")
        canonical = SYSTEM_ALIASES.get(raw_baseline, raw_baseline)
        if wanted is not None and canonical not in wanted:
            continue
        if canonical in out:
            raise ValueError(f"Duplicate selected config for baseline {canonical!r} in {path}")
        overrides = row.get("overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError(f"Selected config for baseline {canonical!r} has non-object overrides")
        out[canonical] = dict(overrides)
    return out

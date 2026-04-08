from __future__ import annotations

from typing import Dict, List

from ZonePartitioner import build_neighbors, health_to_weight, point_in_polygon, point_to_poly_distance


class RowZonePartitioner:
    """
    Assign contiguous whole-row blocks to robots.

    Rows are owned in 1D along the vineyard y-axis so no zone splits an
    individual row. Each owned block is expanded into a full-width rectangle
    for compatibility with the existing Robot / TaskGenerator code.
    """

    def __init__(
        self,
        W,
        H,
        robots_def,
        profiles,
        mode="direct",
        scale=15000.0,
        gamma=1.5,
        partition_types=("UGV",),
        row_spacing_m=4.8,
        row_width_m=3.2,
        headland_space_m=10.0,
        row_health_gain_m=None,
    ):
        self.W = float(W)
        self.H = float(H)
        self.mode = str(mode)
        self.scale = float(scale)
        self.gamma = float(gamma)
        self.partition_types = tuple(partition_types)
        self.row_spacing_m = float(row_spacing_m)
        self.row_width_m = float(row_width_m)
        self.headland_space_m = float(headland_space_m)
        self.row_health_gain_m = (
            float(row_health_gain_m)
            if row_health_gain_m is not None
            else max(float(row_spacing_m) * 2.0, float(row_width_m) * 1.5, 1.0)
        )

        self.ids = [r["id"] for r in robots_def if profiles[r["id"]].type in self.partition_types]
        self.anchors = {
            rid: tuple(next(rd["anchor"] for rd in robots_def if rd["id"] == rid))
            for rid in self.ids
        }
        self.healths = {
            rid: float(next(rd["health"] for rd in robots_def if rd["id"] == rid))
            for rid in self.ids
        }
        self.profiles = profiles

        self.row_bands: List[tuple[float, float]] = self._build_row_bands()
        self.row_centers = [0.5 * (a + b) for (a, b) in self.row_bands]
        self.row_owner_by_index: Dict[int, str] = {}
        self.row_indices_by_id: Dict[str, List[int]] = {rid: [] for rid in self.ids}
        self.cells: List[list[tuple[float, float]]] = []
        self.nbrs: Dict[int, List[int]] = {}

        self.recompute(force=True)

    def _build_row_bands(self) -> List[tuple[float, float]]:
        if self.row_spacing_m <= 0.0 or self.row_width_m <= 0.0:
            return [(0.0, self.H)]
        bands: List[tuple[float, float]] = []
        k = 0
        while True:
            y = self.headland_space_m + k * self.row_spacing_m
            if (y - 0.5 * self.row_width_m) > (self.H - self.headland_space_m):
                break
            bands.append((max(0.0, y - 0.5 * self.row_width_m), min(self.H, y + 0.5 * self.row_width_m)))
            k += 1
        if not bands:
            bands.append((0.0, self.H))
        return bands

    def _row_power_score(self, rid: str, row_center_y: float) -> float:
        anchor_y = float(self.anchors[rid][1])
        raw_weight = float(health_to_weight(self.healths[rid], mode=self.mode, scale=self.scale, gamma=self.gamma))
        normalized_weight = raw_weight / max(abs(self.scale), 1.0)
        weight_shift = self.row_health_gain_m * normalized_weight
        return (row_center_y - anchor_y) ** 2 - (weight_shift ** 2)

    def _assign_rows(self) -> None:
        self.row_owner_by_index = {}
        self.row_indices_by_id = {rid: [] for rid in self.ids}
        if not self.ids:
            return
        for idx, row_center_y in enumerate(self.row_centers):
            best_rid = min(
                self.ids,
                key=lambda rid: (self._row_power_score(rid, row_center_y), abs(row_center_y - float(self.anchors[rid][1])), str(rid)),
            )
            self.row_owner_by_index[idx] = best_rid
            self.row_indices_by_id.setdefault(best_rid, []).append(idx)

    def _interval_polygon_for_rows(self, row_indices: List[int]) -> list[tuple[float, float]]:
        if not row_indices:
            return []
        first_idx = min(row_indices)
        last_idx = max(row_indices)
        lower = 0.0 if first_idx <= 0 else 0.5 * (self.row_centers[first_idx - 1] + self.row_centers[first_idx])
        upper = self.H if last_idx >= (len(self.row_centers) - 1) else 0.5 * (self.row_centers[last_idx] + self.row_centers[last_idx + 1])
        lower = max(0.0, min(float(lower), self.H))
        upper = max(lower, min(float(upper), self.H))
        return [(0.0, lower), (self.W, lower), (self.W, upper), (0.0, upper)]

    def recompute(self, force=False):
        self._assign_rows()
        self.cells = [self._interval_polygon_for_rows(self.row_indices_by_id.get(rid, [])) for rid in self.ids]
        self.nbrs = build_neighbors(self.cells)
        return True

    def update_anchor(self, rid, xy):
        if rid in self.anchors:
            self.anchors[rid] = (float(xy[0]), float(xy[1]))

    def set_health(self, rid, h):
        if rid in self.healths:
            self.healths[rid] = float(h)

    def maybe_trigger(self, health_threshold=0.25, drop_fraction=0.5, previous_healths=None) -> bool:
        if any(self.healths[rid] <= float(health_threshold) for rid in self.ids):
            return True
        if previous_healths is not None:
            for rid in self.ids:
                h0 = float(previous_healths.get(rid, self.healths[rid]))
                if h0 > 1e-6 and (self.healths[rid] / h0) <= float(drop_fraction):
                    return True
        return False

    def cells_for_ids(self):
        return self.cells

    def neighbors_for_id(self, rid):
        if rid not in self.ids:
            return []
        i = self.ids.index(rid)
        return [self.ids[j] for j in self.nbrs.get(i, [])]

    def rows_for_id(self, rid):
        return list(self.row_indices_by_id.get(rid, []))


__all__ = [
    "RowZonePartitioner",
    "health_to_weight",
    "point_in_polygon",
    "point_to_poly_distance",
]


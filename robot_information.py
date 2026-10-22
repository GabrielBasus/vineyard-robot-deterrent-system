"""Per-robot information sets for the planner's cue effectiveness (decision 17).

With ``planner_hab_mode="per_robot"`` every robot keeps its own
``HabituationField`` reconstructed only from the interventions it has received:
its own completions immediately, the other robots' completions through the
EventBus relay (subject to ``neighbor_delay_s`` / ``neighbor_drop_prob``). The
field uses the planner's recovery/depletion routine (the same ``recover`` and
update function that drive the shared planner field).

Reconstruction is chronological: an intervention received after its own time is
inserted at its own time and the state is replayed from a checkpoint, so a
robot's field always equals the field it would hold had it received exactly the
same set of interventions without delay. With instant delivery (no delay) the
replay is never used and the field is updated by the identical calls, in the
identical order, as the shared planner field, so with instant complete relay
every robot's field equals the shared field bit for bit.

See docs/communication_assumptions.md.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np


class RobotHabituationState:
    """One robot's planner effectiveness field and the interventions behind it."""

    def __init__(self, template, *, update_fn: Callable, max_lag_s: float, t_clock: float | None = None):
        self.field = template.copy()
        # Time the field represents. None: set by the first recover(dt, now_t) to now_t - dt,
        # since the simulator's first recover call moves the initial state to now_t.
        self.t = None if t_clock is None else float(t_clock)
        self._update_fn = update_fn                # (hab, cell, mode) -> None
        self.max_lag_s = max(float(max_lag_s), 0.0)
        self._ck_t = self.t                        # checkpoint time
        self._ck_eta = np.array(self.field.eta, dtype=float, copy=True)
        self._log: list[tuple[float, int, int, int]] = []   # (t, seq, cell, mode) after checkpoint
        self._seq = 0
        self.applied_total = 0
        self.late_applied_total = 0

    # -- dynamics -----------------------------------------------------------
    def recover(self, dt: float, now_t: float) -> None:
        """Same recovery call as the shared planner field, once per step."""
        if self._ck_t is None:
            self._ck_t = float(now_t) - float(dt)
        self.field.recover(dt)
        self.t = float(now_t)

    def _recover_eta(self, eta: np.ndarray, dt: float) -> np.ndarray:
        if dt <= 0.0:
            return eta
        return 1.0 - (1.0 - eta) * math.exp(-float(dt) / float(self.field.T_rec))

    def apply(self, t_event: float, cell: int, mode: int) -> None:
        """Apply one received intervention (own completion or relayed message)."""
        t_event = float(t_event)
        self.applied_total += 1
        if self.max_lag_s > 0.0:
            self._log.append((t_event, self._seq, int(cell), int(mode)))
            self._seq += 1
        if self.t is None or t_event >= self.t or self.max_lag_s <= 0.0:
            self._update_fn(self.field, int(cell), int(mode))
            return
        # Late arrival: rebuild the field chronologically from the checkpoint.
        self.late_applied_total += 1
        if t_event < self._ck_t:
            raise RuntimeError(
                f"intervention at t={t_event} arrived after the reconstruction checkpoint "
                f"t={self._ck_t} (max_lag_s={self.max_lag_s})"
            )
        self._log.sort(key=lambda e: (e[0], e[1]))
        new_ck_t = max(self._ck_t, self.t - self.max_lag_s)
        eta = np.array(self._ck_eta, dtype=float, copy=True)
        tau = self._ck_t
        scratch = self.field.copy()
        new_ck_eta = None
        keep = []
        for entry in self._log:
            te, _sq, c, m = entry
            if new_ck_eta is None and te > new_ck_t:
                new_ck_eta = self._recover_eta(np.array(eta, copy=True), new_ck_t - tau)
            if new_ck_eta is not None:
                keep.append(entry)
            eta = self._recover_eta(eta, te - tau)
            tau = te
            scratch.eta = eta
            self._update_fn(scratch, c, m)
            eta = np.array(scratch.eta, dtype=float, copy=True)
        if new_ck_eta is None:
            new_ck_eta = self._recover_eta(np.array(eta, copy=True), new_ck_t - tau)
        self.field.eta = self._recover_eta(eta, self.t - tau)
        self._ck_t, self._ck_eta, self._log = new_ck_t, new_ck_eta, keep

    def effectiveness(self, cell, mode) -> float:
        return self.field.effectiveness(cell, mode)


class PerRobotHabituation:
    """The fleet's per-robot planner fields (decision 17, planner_hab_mode="per_robot")."""

    def __init__(self, robot_ids, template, *, update_fn: Callable, max_lag_s: float, t_clock: float | None = None):
        self.states = {
            str(rid): RobotHabituationState(template, t_clock=t_clock, update_fn=update_fn, max_lag_s=max_lag_s)
            for rid in robot_ids
        }

    def recover(self, dt: float, now_t: float) -> None:
        for st in self.states.values():
            st.recover(dt, now_t)

    def field(self, rid):
        return self.states[str(rid)].field

    def apply(self, rid, t_event: float, cell: int, mode: int) -> None:
        self.states[str(rid)].apply(t_event, cell, mode)

    def snapshot(self) -> dict:
        return {rid: np.array(st.field.eta, copy=True) for rid, st in self.states.items()}

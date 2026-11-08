"""Coupled exogenous random streams for common-random-number policy comparisons.

Plan Sections 4 and 6 require exogenous randomness to be coupled across compared
policies. In ``random_stream_mode="coupled"`` the simulator draws every truth
quantity from a generator that no policy action can perturb:

* background arrivals (count, location, within-step offset) come from one
  dedicated generator that is consumed every step regardless of policy;
* each candidate event carries a stable id, background ``(step, k)`` and
  offspring ``(*parent_id, child_index)``, and its thinning uniform comes from a
  generator keyed by that id;
* offspring count, delays and positions of an accepted parent come from a
  generator keyed by the parent id;
* detection noise comes from a generator keyed by ``(event id, robot id)``;
* relayed neighbor messages are dropped (EventBus ``neighbor_drop_prob``) by a
  uniform keyed by ``(message kind, message id, recipient robot)``;
* policy randomness (patrol jitter, idle roam, random predictive selection)
  uses a separate ``policy_rng``.

Keyed generators hash ``[entropy, purpose, len(key), *key]`` through
``numpy.random.SeedSequence`` (via ``default_rng``), so the same event faces the
same draws under every policy.
"""

from __future__ import annotations

import zlib
from typing import Iterable

import numpy as np

RANDOM_STREAM_MODES = ("legacy", "coupled")

PURPOSE_BACKGROUND = 1
PURPOSE_POLICY = 2
PURPOSE_NO_GROUND_TRUTH = 3
PURPOSE_THINNING = 11
PURPOSE_OFFSPRING = 12
PURPOSE_DETECTION = 13
PURPOSE_RELAY = 14
# Decision 29 disturbance study (user decision 2026-10-22): start time of the unforecast
# arrival burst, drawn per seed only (identical for every policy of a seed).
PURPOSE_ARRIVAL_BURST = 15

# Relay message kinds (EventBus neighbor_drop_prob draws, see relay_uniform).
RELAY_KIND_DETECTION = 1          # key: truth event id
RELAY_KIND_INTERVENTION = 2       # key: action (task) id
RELAY_KIND_DETECTION_SEQ = 3      # key: bus detection sequence number (no event id available)
RELAY_KIND_INTERVENTION_SEQ = 4   # key: bus intervention sequence number (no action id available)


def robot_key(robot_id) -> int:
    """Map a robot id string to a stable non-negative integer."""
    return int(zlib.crc32(str(robot_id).encode("utf-8")))


def _as_key(values: Iterable[int]) -> tuple[int, ...]:
    out = tuple(int(v) for v in values)
    if any(v < 0 for v in out):
        raise ValueError(f"stream keys must be non-negative integers, got {out!r}")
    return out


class CoupledRandomStreams:
    """Seed-derived generators that keep exogenous draws policy invariant."""

    def __init__(self, seed):
        if seed is None:
            entropy = int(np.random.SeedSequence().entropy)
        else:
            entropy = int(seed)
            if entropy < 0:
                raise ValueError(f"coupled random streams need a non-negative seed, got {seed!r}")
        self.entropy = entropy
        self.background_rng = np.random.default_rng([entropy, PURPOSE_BACKGROUND])
        self.policy_rng = np.random.default_rng([entropy, PURPOSE_POLICY])
        self.no_ground_truth_rng = np.random.default_rng([entropy, PURPOSE_NO_GROUND_TRUTH])
        self._step_index = 0

    def next_step_index(self) -> int:
        """Return the index of the truth step being generated and advance the counter."""
        idx = int(self._step_index)
        self._step_index += 1
        return idx

    def keyed_rng(self, purpose: int, key: Iterable[int]) -> np.random.Generator:
        """Generator determined only by (seed, purpose, key)."""
        k = _as_key(key)
        return np.random.default_rng([self.entropy, int(purpose), len(k), *k])

    def thinning_uniform(self, event_id: Iterable[int]) -> float:
        return float(self.keyed_rng(PURPOSE_THINNING, event_id).random())

    def detection_uniform(self, event_id: Iterable[int], robot_id) -> float:
        return float(
            self.keyed_rng(PURPOSE_DETECTION, (*_as_key(event_id), robot_key(robot_id))).random()
        )

    def offspring_rng(self, parent_id: Iterable[int]) -> np.random.Generator:
        return self.keyed_rng(PURPOSE_OFFSPRING, parent_id)

    def relay_uniform(self, kind: int, message_id: Iterable[int], recipient_id) -> float:
        """Uniform for the drop decision of one relayed message to one recipient.

        The same (kind, message id, recipient) always gets the same draw, so the
        detection and habituation parts of one intervention message share a fate.
        """
        return float(
            self.keyed_rng(
                PURPOSE_RELAY, (int(kind), *_as_key(message_id), robot_key(recipient_id))
            ).random()
        )

    def arrival_burst_start_s(self, lo_s: float = 300.0, hi_s: float = 1200.0) -> float:
        """Start time (scored-run seconds) of the decision-29 arrival burst.

        Uniform on [lo_s, hi_s] from the stream (seed, PURPOSE_ARRIVAL_BURST); it depends
        only on the seed, so every variant run with the same seed sees the same burst.
        """
        lo, hi = float(lo_s), float(hi_s)
        if not (hi >= lo):
            raise ValueError(f"arrival burst window needs hi >= lo, got [{lo}, {hi}]")
        u = float(self.keyed_rng(PURPOSE_ARRIVAL_BURST, ()).random())
        return lo + (hi - lo) * u

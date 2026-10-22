"""
scenario_rollout.py -- Monte Carlo continuation rollouts of the B5 decision rule.

Implements the expectation in Plan Eq. (3),

    J_H(pi | I_t) = E[ int_t^{t+H} sum_z w_z lambda^pi_z(s) ds | I_t ],

by Monte Carlo over ``n_scenarios`` sampled futures, and the continuation value
of Plan Eq. (5), U(a) = J_H(pi_0) - J_H(pi_a), where

  * pi_0 is the habituation-aware greedy policy B5 (ladder system
    ``B5_greedy_habcue``: proposed generation, dispatch policy ``unc``,
    predictive utility ``legacy_habituation``, multicue, freshest-cue choice);
  * pi_a executes candidate a = (robot, x, y, mode) first with its proposing
    robot, after which that robot rejoins the same B5 rule, recomputed from the
    resulting state (robot availability, task queues, bird intensity and cue
    effectiveness all differ from pi_0).

Everything the engine starts from is a :class:`RolloutSnapshot`, i.e. what a
robot-side planner knows at decision time.  It never reads the truth state; a
snapshot built with ``full_observability=True`` from a running simulator (used
by the agreement test) simply copies truth quantities into the planner fields.

Common random numbers
---------------------
For each decision the exogenous randomness of every scenario is sampled once,
as a *candidate-event tree* (see :func:`_sample_scenario_tree`):

  * background candidate events at the dominating background rate, one batch
    per simulator step (Poisson count, node chosen by rate, uniform jitter in
    the cell exactly as ``DeterrentSystem._sample_from_value_map``); a time
    profile, when present, is applied by Lewis thinning with a stored uniform;
  * for every candidate event, its potential offspring (Poisson(alpha) count,
    Exp(omega) delays, N(x, sigma^2) positions clipped to the field), keyed by
    the parent's event id, recursively up to t + H;
  * remaining offspring of known past events (planner excitation terms) and,
    with full observability, the already scheduled truth queue;
  * one thinning uniform and one detection uniform per event id (only the zone
    owner can detect an event, so the detection uniform keyed by (event, owner)
    is the single per-event uniform), and per-(robot, replan step) patrol jitter.

pi_0 and every pi_a consume the same tree.  A candidate event exists in a
policy's future only if its parent was accepted under that policy and is
accepted iff its stored uniform is below the policy's acceptance probability
(exp(-S) in the consistent form).  Intensities, detections and decisions
therefore evolve differently while the exogenous draws are shared.

J quadrature
------------
J is computed from the scenario's intensity, not from counted events:

  * background part: per simulator step k the expected exposure of that step's
    background candidates, sum_n mask_n wbar_n r_n m(t_k) dt exp(-S_n(t_k)).
    This is the simulator's own discretisation (``run_truth_generation_stage``
    draws Poisson(lambda dt) events at the step time and thins them with S at
    the step time), so it is exact up to evaluating S at the node instead of
    the jittered event location.
  * excitation part: integrated exactly in time between steps.  Accepted
    events are accumulated into a decayed source grid A (one exponential, the
    planner omega), and int_{t_k}^{t_{k+1}} E dt = omega (1 - e^{-dt/omega}) E;
    the partial interval from a continuous-time event to the next step is
    integrated exactly as well.  exp(-S) is frozen over each 1 s step (S decays
    on 1200-2400 s scales, relative error below 1e-3 per step).
  * already scheduled candidates (full observability) contribute their
    Rao-Blackwellised expected exposure w(x) exp(-S(x, t)) at their exact time.

Residual differences with the real B5 system are listed in
``B5_RESIDUAL_DIFFERENCES`` and in docs (see report).  Performance: candidates
are simulated in parallel worker processes (``n_workers``); this never changes
results because every (policy, scenario) run is deterministic given the tree.
"""
from __future__ import annotations

import copy
import math
import os
import pickle
import sys
import time
import uuid
from collections import deque
from concurrent.futures import ProcessPoolExecutor, wait
from dataclasses import dataclass, field, fields
from typing import Any, Callable, Optional, Sequence

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scipy.special import ndtr  # noqa: E402

from ZonePartitioner import point_in_polygon, point_to_poly_distance, polygon_area  # noqa: E402
from action_schema import (  # noqa: E402
    task_action,
    task_action_kind,
    task_action_name,
    task_action_service_time_s,
)
from planner_dispatch import (  # noqa: E402
    evaluate_model_deterring_dispatch_gating,
    has_direct_detection_conflict,
    passes_busy_fallback_quality,
    select_assignment,
)
from planner_task_estimation import (  # noqa: E402
    _normalized_gaussian_kernel,
    _time_integral_factor,
    cluster_points,
)
from planner_task_extraction import (  # noqa: E402
    annotate_predictive_utility_fields,
    build_task_dispatch_candidate_buffer,
)
from planner_task_generation import current_busy_deterring_robots  # noqa: E402
from habituation_stl.habituation import HabituationField  # noqa: E402


# ---------------------------------------------------------------------------
# Lazy access to DeterrentSystem's module-level pure helpers.  Importing the
# real helpers keeps the engine faithful to edits made there; the import is
# lazy so DeterrentSystem can itself import this module later.
# ---------------------------------------------------------------------------
_DS_MODULE = None


def _ds():
    global _DS_MODULE
    if _DS_MODULE is None:
        if "DeterrentSystem" not in sys.modules:
            os.environ.setdefault("DETERRENT_TELEMETRY", "0")
        import DeterrentSystem as _mod  # noqa: WPS433
        _DS_MODULE = _mod
    return _DS_MODULE


# ---------------------------------------------------------------------------
# Residual differences between this engine's B5 and the real B5 (report list)
# ---------------------------------------------------------------------------
B5_RESIDUAL_DIFFERENCES = (
    "R1 Zones, robot health and retirement are frozen over the horizon "
    "(DeterrentSystem.py:4643 _run_zone_partitioning_algorithm never fires in B5 runs "
    "because health is static; mirrored as a no-op).",
    "R2 Only lane_projection motion is mirrored (DeterrentSystem.py:6044-6210); the "
    "optional graph motion planner (motion_planning_mode='graph') is not.",
    "R3 Within one 1 s step, due offspring events are processed in time order; the "
    "simulator processes its truth_queue in insertion order "
    "(system_stage_helpers.py:291-313).  Only same-step event ordering differs.",
    "R4 Exposure weights: the simulator weights an event by value_weight at its exact "
    "location (DeterrentSystem.py:3529); the engine uses the expected weight of the "
    "event's grid cell (exact expectation for background jitter, cell average for "
    "offspring) and evaluates S at the node for the J integral.",
    "R5 Offspring kernels in the J integral are computed for sources snapped to the "
    "nearest node (clipped-normal cell masses are exact for node-centred sources); "
    "simulated offspring themselves use exact continuous positions.",
    "R6 The planner's world forecast replaces the truth: in 'consistent' form "
    "lambda=[bg+excitation]exp(-S) with planner alpha/sigma/omega and planner cue "
    "effectiveness; the truth uses truth_hab (DeterrentSystem.py:6649-6661).",
    "R7 Exposure counting (record_metrics), forecast-quality metrics, STL monitors, "
    "pending_event_onsets/response-time matching and telemetry are not mirrored; "
    "they do not influence B5 decisions.",
    "R8 predictive_action_variants are not attached to generated rows "
    "(TaskGenerator.py:1088-1106); they are only read when "
    "defer_predictive_action_selection=True, which B5 does not use.",
    "R9 Diagnostic counters of TaskGenerator (diag_counts) are not updated.",
    "R10 Patrol jitter uses a scenario-keyed RNG stream instead of the simulator's "
    "shared rng (TaskGenerator.py:1746-1748), so it is common across policies.",
    "R11 Preventive-capacity state (planner_task_generation.compute_preventive_capacity_state) "
    "is not recomputed: it only feeds the sprt_capacity gate, which TaskGenerator forces "
    "to 'heuristic' (TaskGenerator.py:609).",
    "R12 The proposing robot executes the candidate first: the candidate task is exempt "
    "from age pruning, predictive expiry and goal preemption until it completes "
    "(engine rule, not a B5 rule).  If the robot is holding at t, the hold finishes first.",
    "R13 Planner-model mu EMA (SESTPP.add_local_event bg_ema) is applied only through the "
    "robots' own estimator objects; the 'legacy' world form ignores it.  With "
    "estimator_mode='consistent' the robots' estimators are advanced exactly as in the "
    "simulator (footprint relay of detections and interventions, q_hat*beta planner "
    "amplitudes, per-step background exposure accumulation then advance_to).",
    "R14 Decision snapshots (start_stage='replan', decision_snapshot_from_sim_locals) are the "
    "planner's belief: the world's background, excitation parents, suppression terms and cue "
    "parameters come from the robots' estimators, so the forecast differs from the truth by "
    "the planner's model error (detection-thinned parents, the estimated mu_hat in the "
    "estimator's dA density convention, nominal planner parameters).  This difference is "
    "measured by the oracle evaluations, not assumed small.",
)


# ---------------------------------------------------------------------------
# Configuration of the B5 decision rule (resolved values of a B5 run)
# ---------------------------------------------------------------------------
@dataclass
class B5Config:
    """Resolved B5 parameters; field names match run_simulation_frames_persistent."""

    dt: float = 1.0
    W: float = 500.0
    H: float = 500.0
    task_replan_period_s: float = 45.0
    arrival_radius_m: float = 3.0
    tau_service_s: float = 20.0
    detect_range_m: float = 30.0
    bird_detection_prob: float = 0.10
    bird_stay_mean_s: float = 20.0
    # direct detection tasks
    enable_direct_detection_tasks: bool = True
    enable_direct_detection_task_clustering: bool = True
    direct_detection_cluster_radius_m: float = 20.0
    direct_detection_cluster_window_s: float = 60.0
    direct_detection_active_refresh_radius_m: float = 20.0
    direct_detection_active_refresh_window_s: float = 60.0
    direct_detection_task_active_refresh_require_assigned: bool = True
    direct_detection_active_refresh_max_eta_s: float = 45.0
    direct_detection_queued_cluster_radius_m: float = 20.0
    direct_detection_queued_cluster_window_s: float = 60.0
    # pruning
    deterring_suppress_radius_m: float = 20.0
    deterring_suppress_window_s: float = 60.0
    task_refresh_min_score: float = 1e-4
    task_max_age_s: float = 120.0
    # caps and preemption
    max_active_tasks_per_robot: int = 4
    max_active_patrolling_per_robot: int = 2
    max_active_model_deterring_per_robot: int = 1
    preempt_deterring_goals: bool = True
    preempt_direct_detection_goals: bool = True
    preempt_model_scored_goals: bool = False
    protect_active_model_deterring_persistence: bool = True
    model_deterring_min_persistence_lifetime_s: float = 180.0
    model_deterring_persistence_eta_multiplier: float = 2.0
    model_deterring_persistence_buffer_s: float = 60.0
    model_deterring_max_persistence_lifetime_s: float = 420.0
    model_deterring_lock_near_goal_radius_m: float = 10.0
    protect_active_model_deterring_goal_preemption: bool = True
    protect_locked_model_deterring_from_patrol_assignment: bool = True
    # model deterring dispatch gates
    model_deterring_global_admission_cap_per_cycle: int = 1
    model_deterring_require_idle_robot_for_admission: bool = False
    model_deterring_prefer_idle_robots_for_assignment: bool = True
    model_deterring_busy_fallback_p_event_min: float = 0.95
    model_deterring_busy_fallback_deltaJ_per_cost_min: float = 1.0e6
    model_deterring_busy_fallback_eta_s_max: float = 1.25
    protect_direct_detection_from_model_deterring: bool = True
    model_deterring_direct_conflict_radius_m: float = 35.0
    model_deterring_direct_conflict_window_s: float = 120.0
    model_deterring_budget_mode: str = "count_per_hour"
    model_deterring_budget_per_robot_per_hr: int = 4
    model_deterring_budget_utility_per_robot_per_hr: float = 5.0
    # generation (TaskGenerator.periodic_patrolling arguments)
    enable_patrolling: bool = True
    enable_predictive_patrol_tasks: bool = True
    include_fallback_patrol: bool = True
    enable_model_scored_deterring: bool = True
    model_deterring_window_s: float = 120.0
    model_deterring_risk_threshold: float = 0.35
    model_deterring_risk_scale: float = 1e-4
    model_deterring_min_recent_points: int = 1
    model_deterring_field_threshold: Optional[float] = None
    model_deterring_min_persistence_replans: int = 2
    model_deterring_persistence_max_gap_s: float = 120.0
    model_deterring_score_margin: float = 0.10
    model_deterring_repeat_block_window_s: float = 120.0
    model_deterring_repeat_block_radius_m: float = 25.0
    model_deterring_max_eta_s: float = 120.0
    model_deterring_busy_min_support_override: int = 1
    model_deterring_busy_risk_override: float = 0.20
    model_deterring_sprt_alpha: float = 0.25
    model_deterring_sprt_beta: float = 0.40
    model_deterring_sprt_patch_radius_m: Optional[float] = 30.0
    hotspot_top_k: int = 5
    min_hotspot_score: float = 1e-4
    patrol_hotspot_filter_mode: str = "percentile"
    patrol_hotspot_score_percentile: float = 97.0
    patrol_hotspot_keep_top_k: Optional[int] = None
    patrol_feedback_inhibition_retention: float = 1.0
    patrol_scoring_mode: str = "shared_response_reduction"
    patrol_shared_followup_success_prob: float = 0.75
    patrol_shared_response_eta_decay_s: Optional[float] = None
    hotspot_spacing_m: float = 25.0
    jitter_m: float = 4.0
    forecast_horizon_s: float = 300.0
    cost_w_eta: float = 1.0
    use_live_robot_pose_for_task_planning: bool = True
    # predictive lead time and utility
    enable_predictive_lead_time: bool = True
    predictive_lead_time_min_s: float = 30.0
    predictive_lead_time_max_eta_s: float = 120.0
    predictive_lead_time_buffer_s: float = 15.0
    predictive_lead_time_risk_power: float = 1.0
    predictive_timing_mode: str = "synthetic"
    predictive_expiry_grace_s: float = 0.0
    predictive_utility_mode: str = "legacy_habituation"
    predictive_confidence_source: str = "p_event_times_selection_weight"
    predictive_confidence_power: float = 1.0
    predictive_fixed_deterring_mode: Optional[str] = None
    # assignment
    w_prio: float = 3.0
    prio_deterring: float = 2.0
    prio_patrolling: float = 0.2
    assigner_w_load: float = 0.8
    enable_assignment_task_value_term: bool = True
    assigner_w_task_value: float = 0.2
    # intervention feedback into the robots' estimators
    enable_intervention_feedback: bool = True
    model_feedback_sigma_scale: float = 0.875
    model_feedback_omega_scale: float = 2.0
    stl_forecast_correction: bool = False
    intervention_boundary_min_interval_s: float = 60.0
    intervention_boundary_spatial_quant_m: float = 20.0
    intervention_boundary_min_weight: float = 0.35
    # lanes
    row_spacing_m: float = 4.8
    row_width_m: float = 3.2
    headland_m: float = 20.0
    lane_eps_m: float = 0.5
    headland_space_m: float = 10.0
    # habituation
    enable_habituation: bool = True
    planner_habituation_update_model: str = "multiplicative"
    direct_detection_habituation_mode: str = "laser"
    dispatch_policy: str = "unc"
    # planner intensity estimator of the robots (DeterrentSystem estimator_mode).
    # "consistent" mirrors the footprint relay of detections and interventions
    # (EventBus.publish_detection / broadcast_intervention, DeterrentSystem.py:197-243),
    # the planner-parameter feedback amplitude q_hat * beta (DeterrentSystem.py:7122-7147)
    # and the per-step background-exposure accumulation (DeterrentSystem.py:7947-7954).
    estimator_mode: str = "legacy"
    consistent_footprint_sigmas: float = 3.0
    planner_beta: float = 0.25
    planner_sigma: float = 12.0
    planner_omega: float = 600.0
    planner_deterring_modes: Optional[dict] = None
    use_mode_dependent_truth_suppression: bool = True

    @classmethod
    def from_sim_locals(cls, L: dict) -> "B5Config":
        kw = {}
        aliases = {
            "direct_detection_cluster_radius_m": "direct_detection_cluster_radius_m",
            "direct_detection_cluster_window_s": "direct_detection_cluster_window_s",
            "direct_detection_active_refresh_radius_m": "direct_detection_active_refresh_radius_m",
            "direct_detection_active_refresh_window_s": "direct_detection_active_refresh_window_s",
            "direct_detection_active_refresh_max_eta_s": "direct_detection_active_refresh_max_eta_s",
            "direct_detection_queued_cluster_radius_m": "direct_detection_queued_cluster_radius_m",
            "direct_detection_queued_cluster_window_s": "direct_detection_queued_cluster_window_s",
        }
        for f in fields(cls):
            src = aliases.get(f.name, f.name)
            if src in L:
                kw[f.name] = L[src]
        cfg = cls(**kw)
        cfg.estimator_mode = str(cfg.estimator_mode or "legacy").strip().lower()
        if cfg.dispatch_policy != "unc":
            raise ValueError("B5 continuation requires dispatch_policy='unc'")
        return cfg


# ---------------------------------------------------------------------------
# Snapshot data classes
# ---------------------------------------------------------------------------
@dataclass
class CueParams:
    """World (truth-like) suppression parameters of one cue label."""

    beta: float
    sigma: float
    omega: float


@dataclass
class IntensityForecast:
    """Planner forecast of the bird process used as the scenario world.

    form="consistent":
        lambda_n(t) = [bg_n m(t) + E_n(t)] exp(-S_n(t)) with E from accepted
        events, alpha/sigma/omega the planner's excitation parameters, and S the
        sum of suppression terms amp K_sigma(x - x_u) exp(-(t - t_u)/omega_u).
        bg_node_rate is in events/s attributed to each node (the integral of
        the background density over the node's cell).
    form="legacy":
        lambda_n(t) = clip(mu_n m(t) + T_n(t) - I_n(t), 0) per m^2 with
        node-mass stamps as in SESTPP.OnlineSESTPP (alpha_in self excitation,
        alpha_inhib * weight inhibition channels).  bg_node_rate is mu (per m^2).
    """

    form: str
    bg_node_rate: np.ndarray
    alpha: float = 0.0
    sigma: float = 12.0
    omega: float = 600.0
    bg_time_profile: Any = None          # None | "sestpp_diurnal" | picklable callable
    bg_time_profile_max: float = 1.0
    excitation_terms: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    scheduled_candidates: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))
    # legacy-only state
    legacy_trigger_mass: Optional[np.ndarray] = None
    legacy_inhib_channels: dict = field(default_factory=dict)   # mode -> (grid, omega)
    legacy_alpha_in: float = 0.0
    legacy_alpha_inhib: float = 0.0
    # Paper Eq. 20 (system assumption kept as in the original system): the legacy
    # forecast advances existing excitation by passive decay and does NOT generate
    # future offspring.  Generating them with the legacy amplitude read as an
    # expected offspring count is supercritical (alpha_in * omega >> 1) and exploded
    # the event trees (13 GB arrays, 2026-10-16).  True re-enables it for diagnostics.
    legacy_future_offspring: bool = False


@dataclass
class RobotState:
    rid: str
    pose: tuple
    goal: Optional[tuple]
    loiter_until: float
    profile: Any                 # Robot.RobotProfile
    planner: Any                 # Robot.Robot with its planner estimator in .m
    zone_polygon: list


@dataclass
class PendingReactive:
    key: tuple                   # buffer key of the detection row
    x: float
    y: float
    created_t: float
    deadline_t: float
    assigned_robot: Optional[str]
    active_task_id: Optional[int]


@dataclass
class RolloutSnapshot:
    """Everything a robot-side planner knows at decision time t0 (no truth state)."""

    t0: float
    horizon_s: float
    nx: int
    ny: int
    W: float
    H: float
    w_node: np.ndarray                  # exposure weight of events attributed to a node
    w_bg_node: np.ndarray               # expected weight of a background event at a node
    region_mask: np.ndarray             # bool grid; J integrates over this region
    forecast: IntensityForecast
    world_cues: dict                    # cue label -> CueParams (world suppression)
    deterring_modes: dict               # planner cue catalog (beta, sigma, omega, w_eta, ...)
    habituation: HabituationField       # planner habituation copy
    hab_cell_polys: list                # habituation cell polygons (zones), in index order
    mode_to_id: dict                    # cue label -> habituation mode index
    robots: list                        # RobotState in robots_def order
    active_tasks: list
    completed_tasks: list
    consumed_task_keys: set
    taskgen: Any                        # TaskGenerator copy (planner-side state)
    recent_deterrences: list            # applied interventions (also the S terms)
    model_deterring_by_robot: dict      # rid -> list[(t, utility)]
    next_tid: int
    last_replan: float
    bus_last_intervention_key_t: dict
    cfg: B5Config
    pending_reactive: list = field(default_factory=list)
    planner_weight_grid: Optional[np.ndarray] = None   # value_weight at planner-model nodes
    # "truth": state at the end of step t0, the rollout starts with the truth stage of t0+dt.
    # "replan": state inside step t0 after its truth and expiry stages, exactly where the
    # simulator's Stage 3 replans (DeterrentSystem.py main loop); the rollout starts with
    # the replan stage of t0, then motion and model advance of t0, then step t0+dt.
    start_stage: str = "truth"
    # Optional extensions (defaults reproduce the original engine exactly):
    # robot id -> polygons the robot models (consistent-estimator footprint relay)
    robot_region_polys: Optional[dict] = None
    # complete world suppression store (dicts with x, y, t, eta, beta, sigma, omega);
    # None means the world reads recent_deterrences (the original behaviour)
    world_suppression: Optional[list] = None
    # world cue effectiveness, when it differs from the policy's (oracle snapshots);
    # None means the world uses ``habituation`` (the planner copy)
    world_habituation: Optional[HabituationField] = None
    world_habituation_update_model: Optional[str] = None
    # timed-recovery obligations tracked along every rollout:
    # dicts {"id", "cell", "deadline_t", "e_low"}
    obligations: list = field(default_factory=list)

    def __getstate__(self):
        state = dict(self.__dict__)
        state.pop("_sim_template", None)    # per-process copy template (see _sim_state_copy)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    @property
    def xs(self):
        return np.linspace(0.0, self.W, self.nx)

    @property
    def ys(self):
        return np.linspace(0.0, self.H, self.ny)


@dataclass(frozen=True)
class Candidate:
    """Candidate a = (robot, x, y, mode); robot_id None means 'do nothing'."""

    robot_id: Optional[str]
    x: float = 0.0
    y: float = 0.0
    mode: Optional[str] = None
    label: str = ""

    @property
    def is_noop(self) -> bool:
        return self.robot_id is None or self.mode is None


NOOP = Candidate(robot_id=None, label="noop")


def _is_forced(tr) -> bool:
    """A forced-first task: the evaluated candidate or an admitted (committed) deviation.

    Its robot drives to it first (engine rule R12): exempt from age pruning,
    predictive expiry and goal preemption until it completes.
    """
    return bool(tr.get("_rollout_candidate") or tr.get("_forced_first"))


def forced_task_row(cand: Candidate, *, t0: float, task_id: int, deterring_modes: dict, tau_service_s: float,
                    origin: str = "plan_deviation") -> dict:
    """The task row of an admitted predictive deviation (identical in the simulator and the engine)."""
    row = {
        "id": int(task_id),
        "robot_id": str(cand.robot_id),
        "type": "deterring",
        "x": float(cand.x),
        "y": float(cand.y),
        "time": float(t0),
        "origin": str(origin),
        "mode": str(cand.mode),
        "score": 0.0,
        "utility": 0.0,
        "support": 0,
        "assigned_primary": str(cand.robot_id),
        "assigned_secondary": None,
        "state": "active",
        "started_hold": None,
        "t_assigned": float(t0),
        "_forced_first": True,
        "_plan_deviation": True,
    }
    row["action"] = task_action(row, deterring_modes=deterring_modes, default_service_time_s=float(tau_service_s))
    return row


# ---------------------------------------------------------------------------
# Grid helpers
# ---------------------------------------------------------------------------
def _world_to_idx_vec(x, y, W, H, nx, ny):
    ix = np.rint(np.asarray(x, float) / W * (nx - 1)).astype(np.int64)
    iy = np.rint(np.asarray(y, float) / H * (ny - 1)).astype(np.int64)
    return np.clip(iy, 0, ny - 1), np.clip(ix, 0, nx - 1)


def _clipped_normal_cell_matrix(coords: np.ndarray, sigma: float) -> np.ndarray:
    """M[s, i] = P(clip(c_s + N(0, sigma^2)) lies in node cell i).

    Node cells are the Voronoi intervals of the node coordinates; clipped mass
    beyond the field edges lands on the edge nodes, exactly as np.clip in
    DeterrentSystem._spawn_offspring.
    """
    c = np.asarray(coords, float)
    edges = np.concatenate(([-np.inf], 0.5 * (c[1:] + c[:-1]), [np.inf]))
    z = (edges[None, :] - c[:, None]) / max(float(sigma), 1e-9)
    cdf = ndtr(z)
    return np.diff(cdf, axis=1)


def _sestpp_mass_kernel(sigma, dx, dy):
    """Identical to SESTPP.OnlineSESTPP._build_kernel."""
    sigma = max(float(sigma), 1e-9)
    rad = int(math.ceil(3 * sigma / max(dx, dy)))
    k = np.arange(-rad, rad + 1)
    KX, KY = np.meshgrid(k, k, indexing="xy")
    G = np.exp(-0.5 * ((KX * dx) ** 2 + (KY * dy) ** 2) / (sigma ** 2))
    s = G.sum()
    return rad, G / (s if s > 0 else 1.0)


def _stamp(grid, iy, ix, amp, rad, kernel):
    ny, nx = grid.shape
    y0 = max(0, iy - rad); y1 = min(ny, iy + rad + 1)
    x0 = max(0, ix - rad); x1 = min(nx, ix + rad + 1)
    ky0 = y0 - (iy - rad); kx0 = x0 - (ix - rad)
    grid[y0:y1, x0:x1] += amp * kernel[ky0:ky0 + (y1 - y0), kx0:kx0 + (x1 - x0)]


def points_in_polygon(x: np.ndarray, y: np.ndarray, poly) -> np.ndarray:
    """Vectorised ZonePartitioner.point_in_polygon (same formula, incl. +1e-12)."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    inside = np.zeros(x.shape, bool)
    if not poly:
        return inside
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
        inside ^= cond
    return inside


def cell_average_weight(value_fn: Callable[[float, float], float], W: float, H: float,
                        nx: int, ny: int, n_sub: int = 16) -> np.ndarray:
    """E[value_fn(clip(x_n + U), clip(y_n + V))], U,V ~ U(-d/2, d/2).

    This is the exact expected exposure weight of a background event attributed
    to node n by DeterrentSystem._sample_from_value_map (midpoint quadrature
    with n_sub x n_sub sub-samples).
    """
    dx = W / max(nx - 1, 1)
    dy = H / max(ny - 1, 1)
    xs = np.linspace(0.0, W, nx)
    ys = np.linspace(0.0, H, ny)
    off_x = (np.arange(n_sub) + 0.5) / n_sub - 0.5
    off_y = (np.arange(n_sub) + 0.5) / n_sub - 0.5
    out = np.zeros((ny, nx))
    for iy, yy in enumerate(ys):
        sy = np.clip(yy + off_y * dy, 0.0, H)
        for ix, xx in enumerate(xs):
            sx = np.clip(xx + off_x * dx, 0.0, W)
            acc = 0.0
            for py in sy:
                for px in sx:
                    acc += float(value_fn(float(px), float(py)))
            out[iy, ix] = acc / (n_sub * n_sub)
    return out


def sestpp_time_multiplier(t: float) -> float:
    """SESTPP.OnlineSESTPP.time_multiplier."""
    day = 24 * 3600.0
    phi = 2 * math.pi * (t % day) / day
    return max(0.2, 1.0 + 0.4 * math.sin(phi) + 0.15 * math.sin(2 * phi))


def _profile_value(profile, t):
    if profile is None:
        return 1.0
    if isinstance(profile, str):
        if profile == "sestpp_diurnal":
            return sestpp_time_multiplier(t)
        raise ValueError(f"unknown time profile {profile!r}")
    return float(profile(t))


# ---------------------------------------------------------------------------
# Scenario tree (exogenous randomness, shared by all policies)
# ---------------------------------------------------------------------------
@dataclass
class _ScenarioTree:
    t: np.ndarray
    x: np.ndarray
    y: np.ndarray
    node: np.ndarray            # flat node index used for weights / sources
    parent: np.ndarray          # -1 for roots
    kind: np.ndarray            # 0 bg, 1 offspring, 2 scheduled, 3 past-excitation child
    u_thin: np.ndarray
    u_det: np.ndarray
    owner: np.ndarray           # robot index (robots_def order) or -1
    w_sched: np.ndarray         # exposure weight for scheduled events (nan otherwise)
    order: np.ndarray           # event ids sorted by (proc_step, bg first, t, id)
    step_start: np.ndarray      # order[step_start[k]:step_start[k+1]] processed at step k
    jitter_seed: int


def _sample_scenario_tree(snap: RolloutSnapshot, seed: int, scenario: int) -> _ScenarioTree:
    fc = snap.forecast
    cfg = snap.cfg
    dt = float(cfg.dt)
    n_steps = int(round(snap.horizon_s / dt))
    t0 = float(snap.t0)
    t_end = t0 + n_steps * dt
    nx, ny, W, H = snap.nx, snap.ny, snap.W, snap.H
    xs = snap.xs
    ys = snap.ys
    dxc = W / (nx - 1)
    dyc = H / (ny - 1)
    ss = np.random.SeedSequence([int(seed) & 0xFFFFFFFF, 0x5CE1A410, int(scenario)])
    rng = np.random.Generator(np.random.PCG64(ss))
    legacy = fc.form == "legacy"
    node_area = dxc * dyc

    T, X, Y, NODE, PAR, KIND, STEP, WS = [], [], [], [], [], [], [], []

    # -- background candidates (one batch per step, like run_truth_generation_stage)
    rate = np.asarray(fc.bg_node_rate, float).ravel()
    if legacy:
        rate = rate * node_area
    m_max = float(fc.bg_time_profile_max) if fc.bg_time_profile is not None else 1.0
    legacy_tm = None
    if legacy:
        # the legacy world's background is mu * sestpp_time_multiplier(t) * m(t)
        # (_World.begin_step), so the dominating rate and the time thinning use it too
        legacy_tm = np.array([sestpp_time_multiplier(t0 + k * dt) * _profile_value(fc.bg_time_profile, t0 + k * dt)
                              for k in range(1, n_steps + 1)]) if n_steps > 0 else np.zeros(0)
        m_max = float(legacy_tm.max()) if legacy_tm.size else 1.0
    lam_dom = float(rate.sum()) * m_max
    if lam_dom > 0.0 and n_steps > 0:
        counts = rng.poisson(lam_dom * dt, n_steps)
        n_tot = int(counts.sum())
        cdf = np.cumsum(rate) / rate.sum()
        r = rng.random(n_tot)
        idx = np.minimum(np.searchsorted(cdf, r, side="right"), rate.size - 1)
        iy, ix = np.divmod(idx, nx)
        jx = rng.uniform(-0.5 * dxc, 0.5 * dxc, n_tot)
        jy = rng.uniform(-0.5 * dyc, 0.5 * dyc, n_tot)
        steps = np.repeat(np.arange(1, n_steps + 1), counts)
        tt = t0 + steps * dt
        keep = np.ones(n_tot, bool)
        if legacy:
            u_tp = rng.random(n_tot)
            keep = u_tp <= legacy_tm[steps - 1] / m_max
        elif fc.bg_time_profile is not None:
            u_tp = rng.random(n_tot)
            m_vals = np.array([_profile_value(fc.bg_time_profile, ti) for ti in tt]) if n_tot else np.zeros(0)
            keep = u_tp <= m_vals / m_max
        T.append(tt[keep]); X.append(np.clip(xs[ix] + jx, 0.0, W)[keep]); Y.append(np.clip(ys[iy] + jy, 0.0, H)[keep])
        NODE.append(idx[keep]); PAR.append(np.full(int(keep.sum()), -1)); KIND.append(np.zeros(int(keep.sum()), int))
        STEP.append(steps[keep]); WS.append(np.full(int(keep.sum()), np.nan))

    def _offspring_positions(px, py, pnode, n_each):
        if legacy:
            rad, G = _sestpp_mass_kernel(fc.sigma, dxc, dyc)
            pys, pxs = np.divmod(np.repeat(pnode, n_each), nx)
            flatG = G.ravel()
            pick = rng.choice(flatG.size, size=int(n_each.sum()), p=flatG / flatG.sum())
            ky, kx = np.divmod(pick, G.shape[1])
            cy = pys + ky - rad
            cx = pxs + kx - rad
            ok = (cy >= 0) & (cy < ny) & (cx >= 0) & (cx < nx)
            cy = np.clip(cy, 0, ny - 1); cx = np.clip(cx, 0, nx - 1)
            ox = np.clip(xs[cx] + rng.uniform(-0.5 * dxc, 0.5 * dxc, cx.size), 0, W)
            oy = np.clip(ys[cy] + rng.uniform(-0.5 * dyc, 0.5 * dyc, cy.size), 0, H)
            return ox, oy, ok
        ox = np.clip(np.repeat(px, n_each) + rng.normal(0.0, fc.sigma, int(n_each.sum())), 0.0, W)
        oy = np.clip(np.repeat(py, n_each) + rng.normal(0.0, fc.sigma, int(n_each.sum())), 0.0, H)
        return ox, oy, np.ones(ox.size, bool)

    # -- remaining offspring of known past events (consistent form)
    ex = np.asarray(fc.excitation_terms, float).reshape(-1, 3)
    if (not legacy) and ex.shape[0] and fc.alpha > 0.0:
        mean_rem = fc.alpha * np.exp(-np.maximum(t0 - ex[:, 2], 0.0) / fc.omega)
        n_each = rng.poisson(mean_rem)
        if n_each.sum():
            delays = rng.exponential(fc.omega, int(n_each.sum()))
            ox, oy, _ = _offspring_positions(ex[:, 0], ex[:, 1], None, n_each)
            tt = t0 + delays
            keep = tt <= t_end
            T.append(tt[keep]); X.append(ox[keep]); Y.append(oy[keep])
            iyy, ixx = _world_to_idx_vec(ox[keep], oy[keep], W, H, nx, ny)
            NODE.append(iyy * nx + ixx); PAR.append(np.full(int(keep.sum()), -1)); KIND.append(np.full(int(keep.sum()), 3))
            STEP.append(np.maximum(1, np.ceil((tt[keep] - t0) / dt - 1e-9).astype(int))); WS.append(np.full(int(keep.sum()), np.nan))
    # -- legacy: candidates born from the existing trigger mass
    if legacy and fc.legacy_trigger_mass is not None and fc.omega > 0:
        Tm = np.asarray(fc.legacy_trigger_mass, float).ravel()
        frac = 1.0 - math.exp(-snap.horizon_s / fc.omega)
        n_node = rng.poisson(np.clip(Tm, 0, None) * node_area * fc.omega * frac)
        if n_node.sum():
            nodes = np.repeat(np.arange(Tm.size), n_node)
            u = rng.random(nodes.size)
            tau = -fc.omega * np.log1p(-u * frac)
            iyy, ixx = np.divmod(nodes, nx)
            ox = np.clip(xs[ixx] + rng.uniform(-0.5 * dxc, 0.5 * dxc, nodes.size), 0, W)
            oy = np.clip(ys[iyy] + rng.uniform(-0.5 * dyc, 0.5 * dyc, nodes.size), 0, H)
            tt = t0 + tau
            T.append(tt); X.append(ox); Y.append(oy); NODE.append(nodes); PAR.append(np.full(nodes.size, -1))
            KIND.append(np.full(nodes.size, 3)); STEP.append(np.maximum(1, np.ceil((tt - t0) / dt - 1e-9).astype(int)))
            WS.append(np.full(nodes.size, np.nan))
    # -- scheduled candidates (full observability: the truth queue)
    sc = np.asarray(fc.scheduled_candidates, float).reshape(-1, 4)
    if sc.shape[0]:
        keep = sc[:, 2] <= t_end
        sc = sc[keep]
        iyy, ixx = _world_to_idx_vec(sc[:, 0], sc[:, 1], W, H, nx, ny)
        T.append(sc[:, 2]); X.append(sc[:, 0]); Y.append(sc[:, 1]); NODE.append(iyy * nx + ixx)
        PAR.append(np.full(sc.shape[0], -1)); KIND.append(np.full(sc.shape[0], 2))
        STEP.append(np.maximum(1, np.ceil((sc[:, 2] - t0) / dt - 1e-9).astype(int))); WS.append(sc[:, 3])

    def _cat(lst, dtype=float):
        return np.concatenate(lst).astype(dtype) if lst else np.zeros(0, dtype)

    t_all = _cat(T); x_all = _cat(X); y_all = _cat(Y); node_all = _cat(NODE, np.int64)
    par_all = _cat(PAR, np.int64); kind_all = _cat(KIND, np.int64); step_all = _cat(STEP, np.int64)
    ws_all = _cat(WS)

    # -- offspring generations, keyed by parent id
    if legacy:
        rad, G = _sestpp_mass_kernel(fc.sigma, dxc, dyc)
        inb = np.zeros((ny, nx))
        # in-bounds kernel mass per source node (SESTPP stamps truncate at edges)
        for iy0 in range(ny):
            for ix0 in range(nx):
                y0 = max(0, iy0 - rad); y1 = min(ny, iy0 + rad + 1)
                x0 = max(0, ix0 - rad); x1 = min(nx, ix0 + rad + 1)
                ky0 = y0 - (iy0 - rad); kx0 = x0 - (ix0 - rad)
                inb[iy0, ix0] = G[ky0:ky0 + (y1 - y0), kx0:kx0 + (x1 - x0)].sum()
        child_mean_node = fc.legacy_alpha_in * node_area * fc.omega * inb.ravel()
    gen_lo, gen_hi = 0, t_all.size
    if legacy and not getattr(fc, "legacy_future_offspring", False):
        gen_hi = gen_lo  # Eq. 20: no future offspring in the legacy world
    while gen_hi > gen_lo:
        p_ids = np.arange(gen_lo, gen_hi)
        p_ids = p_ids[t_all[p_ids] <= t_end]
        if p_ids.size == 0:
            break
        if legacy:
            n_each = rng.poisson(child_mean_node[node_all[p_ids]])
        else:
            n_each = rng.poisson(fc.alpha, p_ids.size) if fc.alpha > 0 else np.zeros(p_ids.size, int)
        n_new = int(n_each.sum())
        if n_new == 0:
            break
        if t_all.size + n_new > MAX_SCENARIO_EVENTS:
            raise MemoryError(f"scenario tree exceeds {MAX_SCENARIO_EVENTS} events "
                              f"({t_all.size + n_new}); the forecast excitation is supercritical")
        parents = np.repeat(p_ids, n_each)
        delays = rng.exponential(fc.omega, n_new)
        ox, oy, ok = _offspring_positions(x_all[p_ids], y_all[p_ids], node_all[p_ids], n_each)
        tt = t_all[parents] + delays
        keep = (tt <= t_end) & ok
        parents = parents[keep]; tt = tt[keep]; ox = ox[keep]; oy = oy[keep]
        iyy, ixx = _world_to_idx_vec(ox, oy, W, H, nx, ny)
        st = np.maximum(np.ceil((tt - t0) / dt - 1e-9).astype(np.int64), step_all[parents] + 1)
        t_all = np.concatenate([t_all, tt]); x_all = np.concatenate([x_all, ox]); y_all = np.concatenate([y_all, oy])
        node_all = np.concatenate([node_all, iyy * nx + ixx]); par_all = np.concatenate([par_all, parents])
        kind_all = np.concatenate([kind_all, np.ones(tt.size, np.int64)]); step_all = np.concatenate([step_all, st])
        ws_all = np.concatenate([ws_all, np.full(tt.size, np.nan)])
        gen_lo, gen_hi = gen_hi, t_all.size

    n = t_all.size
    u_thin = rng.random(n)
    u_det = rng.random(n)
    owner = np.full(n, -1, np.int64)
    unassigned = np.ones(n, bool)
    for r_idx, rs in enumerate(snap.robots):
        if not rs.zone_polygon:
            continue
        inside = points_in_polygon(x_all, y_all, rs.zone_polygon) & unassigned
        owner[inside] = r_idx
        unassigned &= ~inside
    valid = step_all <= n_steps
    ids = np.nonzero(valid)[0]
    key_bg = (kind_all[ids] != 0).astype(np.int64)
    order = ids[np.lexsort((ids, t_all[ids], key_bg, step_all[ids]))]
    step_start = np.searchsorted(step_all[order], np.arange(1, n_steps + 2), side="left")
    return _ScenarioTree(
        t=t_all, x=x_all, y=y_all, node=node_all, parent=par_all, kind=kind_all,
        u_thin=u_thin, u_det=u_det, owner=owner, w_sched=ws_all, order=order,
        step_start=step_start, jitter_seed=int(rng.integers(0, 2 ** 31 - 1)),
    )


# ---------------------------------------------------------------------------
# World model: intensity, thinning and J accumulation for one (policy, scenario)
# ---------------------------------------------------------------------------
class _World:
    def __init__(self, snap: RolloutSnapshot, recent_deterrences: deque):
        self.snap = snap
        fc = snap.forecast
        self.form = fc.form
        self.nx, self.ny = snap.nx, snap.ny
        self.xs = snap.xs
        self.ys = snap.ys
        self.W, self.H = snap.W, snap.H
        self.dx = snap.W / (snap.nx - 1)
        self.dy = snap.H / (snap.ny - 1)
        self.dt = float(snap.cfg.dt)
        self.mask = np.asarray(snap.region_mask, bool)
        self.w_node = np.asarray(snap.w_node, float)
        self.w_bg = np.asarray(snap.w_bg_node, float)
        self.recent = recent_deterrences
        self._terms_version = -1
        self._build_terms()
        self.J_bg = 0.0
        self.J_exc = 0.0
        self.J_sched = 0.0
        self.counted = 0.0
        if self.form == "consistent":
            self.rate_bg = np.asarray(fc.bg_node_rate, float)
            self.alpha, self.omega = float(fc.alpha), float(fc.omega)
            self.Kx = _clipped_normal_cell_matrix(self.xs, fc.sigma)
            self.Ky = _clipped_normal_cell_matrix(self.ys, fc.sigma)
            A = np.zeros((self.ny, self.nx))
            ex = np.asarray(fc.excitation_terms, float).reshape(-1, 3)
            if ex.shape[0] and self.alpha > 0:
                iy, ix = _world_to_idx_vec(ex[:, 0], ex[:, 1], self.W, self.H, self.nx, self.ny)
                np.add.at(A, (iy, ix), np.exp(-np.maximum(snap.t0 - ex[:, 2], 0.0) / self.omega))
            self.A = A
            self.decay1 = math.exp(-self.dt / max(self.omega, 1e-9))
        else:
            self.mu = np.asarray(fc.bg_node_rate, float).copy()
            self.alpha_in = float(fc.legacy_alpha_in)
            self.alpha_inhib = float(fc.legacy_alpha_inhib)
            self.omega = float(fc.omega)
            self.T = (np.zeros((self.ny, self.nx)) if fc.legacy_trigger_mass is None
                      else np.asarray(fc.legacy_trigger_mass, float).copy())
            self.I = {k: (np.asarray(g, float).copy(), float(om)) for k, (g, om) in fc.legacy_inhib_channels.items()}
            self.krad, self.kern = _sestpp_mass_kernel(fc.sigma, self.dx, self.dy)
            self.node_area = self.dx * self.dy
        self.profile = fc.bg_time_profile

    # -- suppression terms (consistent form) are the recent_deterrences deque
    def _build_terms(self):
        rec = list(self.recent)
        if not rec:
            self.tx = self.ty = self.tt = self.amp = self.sig = self.om = np.zeros(0)
            self.Kstack = np.zeros((0, self.ny * self.nx))
            return
        self.tx = np.array([float(e.get("x", 0.0)) for e in rec])
        self.ty = np.array([float(e.get("y", 0.0)) for e in rec])
        self.tt = np.array([float(e.get("t", 0.0)) for e in rec])
        self.amp = np.array([float(e.get("eta", 1.0)) * float(e.get("beta", 0.0)) for e in rec])
        self.sig = np.array([max(float(e.get("sigma", 1.0)) ** 2, 1e-9) for e in rec])
        self.om = np.array([max(float(e.get("omega", 1.0)), 1e-9) for e in rec])
        if self.form == "consistent":
            gx = self.xs[None, :] - self.tx[:, None]
            gy = self.ys[None, :] - self.ty[:, None]
            kx = np.exp(-0.5 * gx * gx / self.sig[:, None])
            ky = np.exp(-0.5 * gy * gy / self.sig[:, None])
            self.Kstack = (ky[:, :, None] * kx[:, None, :]).reshape(len(rec), -1)

    def on_deterrence_added(self):
        self._build_terms()

    def S_grid(self, t):
        if self.amp.size == 0:
            return np.zeros((self.ny, self.nx))
        d = self.amp * np.exp(-np.maximum(t - self.tt, 0.0) / self.om)
        d[self.tt > t] = 0.0
        return (d @ self.Kstack).reshape(self.ny, self.nx)

    def S_points(self, x, y, t):
        """Exact DeterrentSystem._suppression_eval sum at event positions/times."""
        if self.amp.size == 0 or x.size == 0:
            return np.zeros(x.size)
        dtm = t[:, None] - self.tt[None, :]
        k = np.exp(-0.5 * ((x[:, None] - self.tx[None, :]) ** 2 + (y[:, None] - self.ty[None, :]) ** 2)
                   / self.sig[None, :])
        c = self.amp[None, :] * k * np.exp(-np.maximum(dtm, 0.0) / self.om[None, :])
        c[dtm < 0] = 0.0
        return c.sum(axis=1)

    # -- per-step processing
    def begin_step(self, t_k):
        """Accumulate the background J for step t_k and prepare the excitation weights."""
        m = _profile_value(self.profile, t_k)
        if self.form == "consistent":
            eS = np.exp(-self.S_grid(t_k))
            G = np.where(self.mask, self.w_node * eS, 0.0)
            self.J_bg += float(np.sum(np.where(self.mask, self.w_bg * self.rate_bg, 0.0) * eS)) * m * self.dt
            self.M = self.Ky @ G @ self.Kx.T      # M[a, b] = sum_n K(src ab -> n) G_n
            if self.alpha > 0:
                # excitation of events accepted up to t_{k-1}, integrated over (t_{k-1}, t_k]
                self.J_exc += self.alpha * (1.0 - self.decay1) * float(np.sum(self.A * self.M))
                self.A *= self.decay1
        else:
            Itot = sum((g for g, _ in self.I.values()), np.zeros((self.ny, self.nx)))
            c = self.mu * sestpp_time_multiplier(t_k) * m + self.T
            lam = np.clip(c - Itot, 0.0, None)
            self.c_grid = c
            self.lam_grid = lam
            self.J_bg += float(np.sum(np.where(self.mask, self.w_bg * lam, 0.0))) * self.node_area * self.dt

    def accept_probs(self, tree: _ScenarioTree, ids: np.ndarray, t_k: float):
        if ids.size == 0:
            return np.zeros(0)
        if self.form == "consistent":
            return np.exp(-self.S_points(tree.x[ids], tree.y[ids], tree.t[ids]))
        n = tree.node[ids]
        c = self.c_grid.ravel()[n]
        lam = self.lam_grid.ravel()[n]
        with np.errstate(invalid="ignore", divide="ignore"):
            p = np.where(c > 0, lam / c, 0.0)
        return p

    def add_scheduled_expectation(self, tree, ids, p_keep):
        if ids.size == 0:
            return
        w = tree.w_sched[ids]
        n = tree.node[ids]
        w = np.where(np.isfinite(w), w, self.w_node.ravel()[n])
        self.J_sched += float(np.sum(w * p_keep * self.mask.ravel()[n]))

    def add_accepted(self, tree, ids, t_k):
        if ids.size == 0:
            return
        n = tree.node[ids]
        w = np.where(tree.kind[ids] == 0, self.w_bg.ravel()[n], self.w_node.ravel()[n])
        ws = tree.w_sched[ids]
        w = np.where(np.isfinite(ws), ws, w)
        self.counted += float(np.sum(w * self.mask.ravel()[n]))
        if self.form == "consistent":
            if self.alpha <= 0:
                return
            age = np.maximum(t_k - tree.t[ids], 0.0)
            dec = np.exp(-age / self.omega)
            # exact partial integral from the event time to the step time
            self.J_exc += float(self.alpha * np.sum((1.0 - dec) * self.M.ravel()[n]))
            np.add.at(self.A.ravel(), n, dec)
        else:
            iy, ix = np.divmod(n, self.nx)
            for a, b in zip(iy, ix):
                _stamp(self.T, int(a), int(b), self.alpha_in, self.krad, self.kern)

    def end_step(self):
        """Decay the legacy state to the next step (consistent form integrates in begin_step)."""
        if self.form == "consistent":
            return
        else:
            self.T *= math.exp(-self.dt / max(self.omega, 1e-9))
            for k, (g, om) in self.I.items():
                g *= math.exp(-self.dt / max(om, 1e-9))

    def add_legacy_inhibition(self, x, y, mode, weight, sigma, omega):
        if self.form != "legacy":
            return
        key = str(mode)
        if key not in self.I:
            self.I[key] = (np.zeros((self.ny, self.nx)), float(omega))
        g, _ = self.I[key]
        self.I[key] = (g, float(omega))
        rad, kern = _sestpp_mass_kernel(sigma, self.dx, self.dy)
        iy, ix = _world_to_idx_vec(x, y, self.W, self.H, self.nx, self.ny)
        _stamp(g, int(iy), int(ix), self.alpha_inhib * float(weight), rad, kern)

    def residual_rate(self, t):
        if self.form == "consistent":
            eS = np.exp(-self.S_grid(t))
            G = np.where(self.mask, self.w_node * eS, 0.0)
            M = self.Ky @ G @ self.Kx.T
            bg = float(np.sum(np.where(self.mask, self.w_bg * self.rate_bg, 0.0) * eS)) * _profile_value(self.profile, t)
            exc = (self.alpha / max(self.omega, 1e-9)) * float(np.sum(self.A * M))
            return bg + exc
        Itot = sum((g for g, _ in self.I.values()), np.zeros((self.ny, self.nx)))
        lam = np.clip(self.mu * sestpp_time_multiplier(t) * _profile_value(self.profile, t) + self.T - Itot, 0.0, None)
        return float(np.sum(np.where(self.mask, self.w_bg * lam, 0.0))) * self.node_area

    def node_exposure_rate(self, t):
        """Expected value-weighted event rate attributed to every node at time t.

        Consistent form: [w_bg * r_n * m(t) + w_n * E_n(t)] * exp(-S_n(t)) with the
        excitation rate E = alpha/omega * Ky^T A Kx (the clipped-normal cell masses
        of the accepted sources in A, decayed to the current state).  Legacy form:
        w_bg * lam_n * node_area.  Summing over a cell's nodes gives the cell's
        forecast exposure e_z (Plan Eq. 4); summing over the region gives
        residual_rate.
        """
        if self.form == "consistent":
            eS = np.exp(-self.S_grid(t))
            m = _profile_value(self.profile, t)
            out = self.w_bg * self.rate_bg * m
            if self.alpha > 0:
                E = (self.alpha / max(self.omega, 1e-9)) * (self.Ky.T @ self.A @ self.Kx)
                out = out + self.w_node * E
            return out * eS
        Itot = sum((g for g, _ in self.I.values()), np.zeros((self.ny, self.nx)))
        lam = np.clip(self.mu * sestpp_time_multiplier(t) * _profile_value(self.profile, t) + self.T - Itot, 0.0, None)
        return self.w_bg * lam * self.node_area

    @property
    def J(self):
        return self.J_bg + self.J_exc + self.J_sched


# ---------------------------------------------------------------------------
# One (policy, scenario) simulation of the B5 system
# ---------------------------------------------------------------------------
def _prune_taskgen(tg, t0):
    tg = copy.deepcopy(tg)
    tg._rows = list(tg._rows[-200:])
    tg._keys = {k for k in tg._keys if float(k[4]) >= float(t0) - 1.0}
    return tg


def _sim_template_signature(snap):
    return (id(snap.robots), id(snap.active_tasks), len(snap.active_tasks), id(snap.completed_tasks),
            len(snap.completed_tasks), id(snap.taskgen), len(snap.taskgen._rows), len(snap.taskgen._keys),
            id(snap.recent_deterrences), len(snap.recent_deterrences), id(snap.world_suppression),
            -1 if snap.world_suppression is None else len(snap.world_suppression))


def _sim_state_copy(snap):
    """Fresh copies of the snapshot's mutable state for one (policy, scenario) simulation.

    Equivalent to deep-copying each part (robots' planners, profiles, active and
    completed tasks, the pruned TaskGenerator, recent deterrences, the world
    suppression store); the parts are pickled once per snapshot object and each
    simulation unpickles its own copy.  The template is rebuilt if a part is
    replaced or resized, and it is never pickled with the snapshot.
    """
    sig = _sim_template_signature(snap)
    ent = snap.__dict__.get("_sim_template")
    if ent is None or ent[0] != sig:
        parts = ({rs.rid: rs.planner for rs in snap.robots}, {rs.rid: rs.profile for rs in snap.robots},
                 snap.active_tasks, snap.completed_tasks, _prune_taskgen(snap.taskgen, snap.t0),
                 list(snap.recent_deterrences),
                 None if snap.world_suppression is None else list(snap.world_suppression))
        ent = (sig, pickle.dumps(parts, protocol=pickle.HIGHEST_PROTOCOL))
        snap.__dict__["_sim_template"] = ent
    return pickle.loads(ent[1])


def _world_process_events(world: "_World", tree: _ScenarioTree, accepted: np.ndarray, step_k: int, t_k: float):
    """Truth stage of one step on a scenario tree: existence, thinning, J accumulation.

    Returns the ids of the accepted events (the caller handles detections).
    """
    lo, hi = tree.step_start[step_k - 1], tree.step_start[step_k]
    ids = tree.order[lo:hi]
    if ids.size == 0:
        return ids
    par = tree.parent[ids]
    exists = (par < 0) | accepted[np.maximum(par, 0)]
    ids = ids[exists]
    if ids.size == 0:
        return ids
    p_keep = world.accept_probs(tree, ids, t_k)
    sched = tree.kind[ids] == 2
    if sched.any():
        world.add_scheduled_expectation(tree, ids[sched], p_keep[sched])
    acc = tree.u_thin[ids] <= p_keep
    acc_ids = ids[acc]
    accepted[acc_ids] = True
    world.add_accepted(tree, acc_ids, t_k)
    return acc_ids


def _hab_indices(snap: RolloutSnapshot, x: float, y: float, mode_label: str):
    """(cell id, habituation mode index, habituation label) of an application (simulator rule)."""
    c = snap.cfg
    hab_label = (str(c.direct_detection_habituation_mode or "direct_detection")
                 if mode_label == "direct_detection" else mode_label)
    mode_idx = snap.mode_to_id.get(hab_label)
    cell_id = None
    for cid, poly in enumerate(snap.hab_cell_polys):
        if poly and point_in_polygon(float(x), float(y), poly):
            cell_id = cid
            break
    return cell_id, mode_idx, hab_label


def _application_world_effects(snap: RolloutSnapshot, tr: dict, t: float, *, eta_apply: float, eta_world: float,
                               model, source: str, hab_label: str, deterring_modes: dict, tau: float):
    """World-side effects of one completed deterrence (DeterrentSystem._complete_deterring_task).

    Returns (world store entry, legacy inhibition args (x, y, mode, weight, sigma, omega),
    action params, mode label, feedback (eff_beta, fb_sigma, fb_omega)).  With
    stl_forecast_correction the legacy planner-world inhibition and the model feedback
    use q_hat * beta (Plan Sec. 2, user decision 1: q x beta everywhere); the
    consistent-form world entry carries eta (planner q_hat, or the truth eta in
    oracle snapshots) times the world cue beta.
    """
    c = snap.cfg
    spec = task_action(tr, deterring_modes=deterring_modes, default_service_time_s=tau)
    mode_label = str(spec.name or "direct_detection")
    params = dict(spec.params)
    wc = snap.world_cues.get(mode_label)
    if wc is None:
        wc = snap.world_cues.get("direct_detection")
    entry = {
        "x": float(tr["x"]), "y": float(tr["y"]), "t": float(t), "mode": mode_label,
        "source": source, "action_id": int(tr.get("id", -1)),
        "beta": float(wc.beta), "sigma": float(wc.sigma), "omega": float(wc.omega),
        "eta": float(eta_world), "habituation_mode": hab_label,
    }
    fb_beta = float(params.get("beta", 1.0))
    fb_omega = float(params.get("omega", model.omega_inhib)) * float(c.model_feedback_omega_scale)
    fb_sigma = float(params.get("sigma", model.sigma)) * float(c.model_feedback_sigma_scale)
    eff_beta = float(eta_apply) * fb_beta if bool(c.stl_forecast_correction) else fb_beta
    inhib = (float(tr["x"]), float(tr["y"]), mode_label, eff_beta, fb_sigma, fb_omega)
    return entry, inhib, params, mode_label, (eff_beta, fb_sigma, fb_omega)


def one_intervention_J(snap: RolloutSnapshot, tree: _ScenarioTree, app_row: Optional[dict],
                       t_apply: float = math.inf, robot_id: Optional[str] = None) -> float:
    """J_H of the one-intervention counterfactual (Plan Sec. 1 "one-intervention
    counterfactual"; variant C_plan, user decision 8) on one scenario tree.

    The world starts from the snapshot's world state (forecast background,
    excitation state and every PAST suppression term) and evolves over the same
    horizon, region and scenario tree as the continuation rollouts, with NO future
    intervention of any robot: no B5 continuation, no pending task service, no
    committed deviation.  Only ``app_row`` (the candidate) is applied, at
    ``t_apply`` (the candidate's application time in the same scenario of its
    continuation rollout, i.e. the motion-stage completion step), with the
    effectiveness the planner copy reaches at t_apply by recovery alone (no other
    application depletes it in this world) and q_hat * beta as in every other
    application (decision 1).  ``app_row=None`` (or t_apply = inf) is the
    no-intervention arm; U_one = J(no intervention) - J(candidate only) therefore
    isolates the candidate's own suppression from any continuation effect.
    """
    cfg = snap.cfg
    dt = float(cfg.dt)
    t0 = float(snap.t0)
    n_steps = int(round(snap.horizon_s / dt))
    store = list(snap.world_suppression) if snap.world_suppression is not None else list(snap.recent_deterrences)
    world = _World(snap, store)
    hab = snap.habituation.copy()
    world_hab = None if snap.world_habituation is None else snap.world_habituation.copy()
    accepted = np.zeros(tree.t.size, bool)
    apply_now = app_row is not None and math.isfinite(float(t_apply))
    model = None
    if apply_now:
        rs = next((r for r in snap.robots if r.rid == str(robot_id)), None)
        if rs is None:
            raise KeyError(f"robot {robot_id!r} not in snapshot")
        model = rs.planner.m
    tau = float(cfg.tau_service_s)

    def _apply(t):
        spec = task_action(app_row, deterring_modes=snap.deterring_modes, default_service_time_s=tau)
        mode_label = str(spec.name or "direct_detection")
        cell_id, mode_idx, hab_label = _hab_indices(snap, app_row["x"], app_row["y"], mode_label)
        eta_apply = eta_world = 1.0
        if bool(cfg.enable_habituation) and cell_id is not None and mode_idx is not None:
            eta_apply = hab.effectiveness(cell_id, mode_idx)
            eta_world = eta_apply if world_hab is None else world_hab.effectiveness(cell_id, mode_idx)
        entry, inhib, _p, _m, _fb = _application_world_effects(
            snap, app_row, t, eta_apply=eta_apply, eta_world=eta_world, model=model, source="model_scored",
            hab_label=hab_label, deterring_modes=snap.deterring_modes, tau=tau)
        store.append(entry)
        world.on_deterrence_added()
        world.add_legacy_inhibition(*inhib)

    if snap.start_stage == "replan":
        if apply_now and abs(float(t_apply) - t0) < 1e-9:
            _apply(t0)
        world.end_step()
    for k in range(1, n_steps + 1):
        t = t0 + k * dt
        if bool(cfg.enable_habituation):
            hab.recover(dt)
            if world_hab is not None:
                world_hab.recover(dt)
        world.begin_step(t)
        _world_process_events(world, tree, accepted, k, t)
        if apply_now and abs(float(t_apply) - t) < 1e-9:
            _apply(t)
        world.end_step()
    return float(world.J)


class _Sim:
    def __init__(self, snap: RolloutSnapshot, tree: _ScenarioTree, candidate: Candidate,
                 *, scenario: int, reactive_deadline_s: float, planner_model_advance: str = "per_step",
                 one_intervention: bool = False):
        self.snap = snap
        self.one_intervention = bool(one_intervention)
        self.candidate_arrival_t = math.inf    # start of the candidate's application hold
        self.candidate_eta_planner = math.nan  # planner q_hat of the candidate at application
        self.candidate_eta_world = math.nan
        self._candidate_row = None
        self.cfg = cfg = snap.cfg
        self.tree = tree
        self.scenario = scenario
        self.reactive_deadline_s = float(reactive_deadline_s)
        self.model_advance = planner_model_advance
        self.dt = float(cfg.dt)
        self.t0 = float(snap.t0)
        self.n_steps = int(round(snap.horizon_s / self.dt))
        self.deterring_modes = snap.deterring_modes
        self.tau = float(cfg.tau_service_s)
        self.rids = [rs.rid for rs in snap.robots]
        # Independent copies of every mutable part of the snapshot.  They are taken
        # from one pickled template per snapshot (pickle.loads is several times
        # faster than copy.deepcopy and yields the same independent objects).
        (robots_c, profiles_c, active_c, completed_c, taskgen_c, recent_c, store_c) = _sim_state_copy(snap)
        self.robots = robots_c
        self.profiles = profiles_c
        self.pose = {rs.rid: (float(rs.pose[0]), float(rs.pose[1])) for rs in snap.robots}
        self.goal = {rs.rid: (None if rs.goal is None else (float(rs.goal[0]), float(rs.goal[1]))) for rs in snap.robots}
        self.loiter_until = {rs.rid: float(rs.loiter_until) for rs in snap.robots}
        self.zone = {rs.rid: rs.zone_polygon for rs in snap.robots}
        self.active_tasks = active_c
        self.completed_tasks = completed_c
        self.consumed_task_keys = set(snap.consumed_task_keys)
        self.taskgen = taskgen_c
        self.recent_deterrences = deque(recent_c, maxlen=200)
        # World suppression store: the B5-facing deque (original behaviour) or a
        # separate complete store (planner / oracle snapshots).
        if snap.world_suppression is None:
            self.world_store = self.recent_deterrences
        else:
            self.world_store = store_c
        self.model_det_budget = {rid: deque(snap.model_deterring_by_robot.get(rid, [])) for rid in self.rids}
        self.next_tid = int(snap.next_tid)
        self.last_replan = float(snap.last_replan)
        self.bus_last = dict(snap.bus_last_intervention_key_t)
        self.hab = snap.habituation.copy()
        self.world_hab = None if snap.world_habituation is None else snap.world_habituation.copy()
        self.consistent = str(getattr(cfg, "estimator_mode", "legacy")) == "consistent"
        self.world = _World(snap, self.world_store)
        from TaskGenerator import TaskAssigner
        self.assigner = TaskAssigner(
            robots_state=self.robots,
            profiles=self.profiles,
            params={
                "uav_spinup_s": 8.0,
                "w_prio": cfg.w_prio,
                "prio_deterring": cfg.prio_deterring,
                "prio_patrolling": cfg.prio_patrolling,
                "w_load": float(cfg.assigner_w_load),
                "w_task_value": float(cfg.assigner_w_task_value) if bool(cfg.enable_assignment_task_value_term) else 0.0,
            },
        )
        self.accepted = np.zeros(tree.t.size, bool)
        self.row_bands = self._row_bands()
        # derived node grids for the vectorised TaskGenerator port
        self._zone_mask = {}
        self.candidate = candidate
        self.candidate_task_id = None
        # outputs
        self.interventions = []
        self.detections = 0
        self.new_reactive = {}        # key -> dict(created_t, x, y)
        self.done_keys = {}           # buffer key -> completion time
        self.dropped_keys = {}        # buffer key -> drop time
        self.reactive_completed = 0
        self.predictive_completed = 0
        self.patrol_completed = 0
        self.candidate_completed_t = math.inf
        self.forced_completed = {}    # id of a forced-first task -> completion time
        self.gen_log = None           # optional list: (t, rid, preventive candidates) per replan
        self.seed_log = None          # optional list: (t, rid, registered preventive seeds) per replan
        self.mode_score_log = None    # optional list: (rid, x, y, mode, B5 generation score) per seed and cue
        self.choice_log = None        # optional dict: rid -> B5's generated predictive row (before jitter)
        # timed-recovery obligations: cell node masks and first satisfaction times
        self.obligations = list(getattr(snap, "obligations", None) or [])
        self.obl_sat = {}
        self.obl_min_e = {}
        self.obl_e_deadline = {}
        if self.obligations:
            XX, YY = np.meshgrid(snap.xs, snap.ys, indexing="xy")
            owner = np.full(XX.shape, -1, np.int64)
            for cid, poly in enumerate(snap.hab_cell_polys):
                if not poly:
                    continue
                ins = points_in_polygon(XX, YY, poly) & (owner < 0)
                owner[ins] = cid
            self._cell_owner = owner
            for ob in self.obligations:
                self.obl_sat[ob["id"]] = math.inf
                self.obl_min_e[ob["id"]] = math.inf
                self.obl_e_deadline[ob["id"]] = math.nan
        if not candidate.is_noop:
            self._inject_candidate(candidate)

    # ------------------------------------------------------------------ utils
    def _kind(self, tr):
        return task_action_kind(tr, self.deterring_modes, self.tau)

    def _name(self, tr):
        return task_action_name(tr, self.deterring_modes, self.tau)

    def _service_s(self, tr):
        return float(task_action_service_time_s(tr, deterring_modes=self.deterring_modes, default_service_time_s=self.tau))

    def _deterring_source(self, tr):
        """DeterrentSystem.py:3578."""
        kind = self._kind(tr)
        name = self._name(tr)
        origin = str(tr.get("origin", "")).strip().lower()
        if kind == "deterring" and name != "direct_detection":
            return "model_scored"
        if origin == "detection" or name == "direct_detection":
            return "direct_detection"
        return "direct_detection"

    def _is_direct(self, tr):
        return self._kind(tr) == "deterring" and self._deterring_source(tr) == "direct_detection"

    def _buffer_key(self, task):
        """DeterrentSystem.py:3597 _task_buffer_key."""
        return (
            self._kind(task),
            self._name(task),
            round(float(task.get("x", float("nan"))), 2),
            round(float(task.get("y", float("nan"))), 2),
            round(float(task.get("time", float("nan"))), 0),
        )

    # ---------------------------------------------------------- lane motion
    def _row_bands(self):
        """DeterrentSystem.py:6005."""
        c = self.cfg
        if c.row_spacing_m <= 0:
            return []
        bands = []
        k = 0
        while True:
            y = c.headland_space_m + k * c.row_spacing_m
            if y - 0.5 * c.row_width_m > (c.H - c.headland_space_m):
                break
            bands.append((y - 0.5 * c.row_width_m, y + 0.5 * c.row_width_m))
            k += 1
        return bands

    def _lane_center_for(self, y):
        """DeterrentSystem.py:6021 _nearest_free_lane_y (memoised; same result)."""
        cache = self.__dict__.setdefault("_lane_cache", {})
        v = cache.get(y)
        if v is None:
            v = self._lane_center_for_raw(y)
            if len(cache) > 200000:
                cache.clear()
            cache[y] = v
        return v

    def _lane_center_for_raw(self, y):
        bands = self.row_bands
        H = self.cfg.H
        if not bands:
            return float(y)
        prev = 0.0
        for (a, b) in bands:
            if prev <= y <= a:
                return 0.5 * (prev + a)
            prev = b
        if y >= prev:
            return 0.5 * (prev + H)
        for i, (a, b) in enumerate(bands):
            if a <= y <= b:
                lower = 0.0 if i == 0 else bands[i - 1][1]
                upper = bands[i + 1][0] if i + 1 < len(bands) else H
                lower_c = 0.5 * (lower + a)
                upper_c = 0.5 * (b + upper)
                return lower_c if abs(y - lower_c) <= abs(y - upper_c) else upper_c
        return float(y)

    def _is_at_headland(self, x):
        return x <= self.cfg.headland_m or x >= (self.cfg.W - self.cfg.headland_m)

    def _nearest_headland_x(self, x):
        left = max(0.0, self.cfg.headland_space_m)
        right = min(float(self.cfg.W), self.cfg.W - self.cfg.headland_space_m)
        return left if x <= self.cfg.W * 0.5 else float(right)

    def _effective_goal(self, rid, tgt):
        """DeterrentSystem.py:6058 _project_to_lane."""
        x, y = self.pose[rid]
        tx, ty = tgt
        cur_lane = self._lane_center_for(y)
        tgt_lane = self._lane_center_for(ty)
        if abs(cur_lane - tgt_lane) <= self.cfg.lane_eps_m:
            return (tx, cur_lane)
        if not self._is_at_headland(x):
            return (self._nearest_headland_x(x), cur_lane)
        if abs(y - tgt_lane) > self.cfg.lane_eps_m:
            return (self._nearest_headland_x(x), tgt_lane)
        return (tx, tgt_lane)

    def _step_to(self, rid, tgt):
        """DeterrentSystem.py:6078 _move_directly_to_point toward the lane waypoint."""
        x, y = self.pose[rid]
        tx, ty = self._effective_goal(rid, tgt)
        dx, dy = tx - x, ty - y
        dist = math.hypot(dx, dy)
        if dist < 1.0e-6:
            return
        speed = max(float(self.profiles[rid].speed_mps), 1.0e-6)
        step = speed * self.dt
        nx_, ny_ = (tx, ty) if step >= dist else (x + dx * (step / dist), y + dy * (step / dist))
        self.pose[rid] = (min(max(nx_, 0.0), float(self.cfg.W)), min(max(ny_, 0.0), float(self.cfg.H)))

    def _eta(self, rid, tgt_xy):
        """DeterrentSystem.py:6280 _assigned_robot_eta_seconds (lane projection)."""
        if rid not in self.pose:
            return float("nan")
        tx, ty = self._effective_goal(rid, tgt_xy)
        px, py = self.pose[rid]
        dist = math.hypot(float(tx) - float(px), float(ty) - float(py))
        prof = self.profiles.get(rid)
        speed = max(float(prof.speed_mps), 1e-6) if prof is not None else 1.0
        spin = {"UAV": 8.0, "UGV": 0.0}.get(prof.type, 0.0) if prof is not None else 0.0
        return float(dist / speed + spin)

    # ------------------------------------------------- task lifecycle helpers
    def _task_age_anchor_t(self, tr, t):
        ta = tr.get("t_assigned", None)
        if ta is not None:
            try:
                return float(ta)
            except Exception:
                pass
        return float(tr.get("time", t))

    def _is_active_model_det(self, tr):
        return (str(tr.get("state", "")).strip().lower() == "active"
                and self._kind(tr) == "deterring" and self._deterring_source(tr) == "model_scored")

    def _arrival_imminent(self, tr):
        """DeterrentSystem.py:6300."""
        if not self._is_active_model_det(tr):
            return False
        rid = str(tr.get("assigned_primary", ""))
        if rid not in self.pose or rid not in self.profiles:
            return False
        tx, ty = self._effective_goal(rid, (float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
        px, py = self.pose[rid]
        dist = math.hypot(px - tx, py - ty)
        step_reach = max(0.0, float(self.profiles[rid].speed_mps) * self.dt)
        eta_s = self._eta(rid, (float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
        return dist <= self.cfg.arrival_radius_m + step_reach or (math.isfinite(eta_s) and eta_s <= self.dt)

    def _persist_locked(self, tr, t):
        """DeterrentSystem.py:6243 _is_model_deterring_persist_locked (+ candidate exemption)."""
        if _is_forced(tr) and str(tr.get("state", "")).strip().lower() == "active":
            return True
        c = self.cfg
        if not bool(c.protect_active_model_deterring_persistence):
            return False
        if not self._is_active_model_det(tr):
            return False
        if tr.get("started_hold") is not None:
            return True
        lock = tr.get("persist_lock_until_t", None)
        if lock is not None:
            try:
                if float(t) < float(lock):
                    return True
            except Exception:
                pass
        if float(t) - self._task_age_anchor_t(tr, t) < float(c.model_deterring_min_persistence_lifetime_s):
            return True
        if self._arrival_imminent(tr):
            return True
        rid = str(tr.get("assigned_primary", ""))
        if rid in self.pose:
            tx, ty = self._effective_goal(rid, (float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
            if math.hypot(self.pose[rid][0] - tx, self.pose[rid][1] - ty) <= float(c.model_deterring_lock_near_goal_radius_m):
                return True
        return False

    def _has_locked_model_det_on_robot(self, rid, t):
        for tr in self.active_tasks:
            if str(tr.get("assigned_primary", "")) != str(rid):
                continue
            if self._persist_locked(tr, t):
                return True
        return False

    def _lock_until(self, tr, t):
        """DeterrentSystem.py:6322."""
        c = self.cfg
        rid = str(tr.get("assigned_primary", ""))
        eta_s = self._eta(rid, (float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
        if not math.isfinite(eta_s):
            eta_s = max(0.0, float(tr.get("eta_s", 0.0)))
        dur = max(float(c.model_deterring_min_persistence_lifetime_s),
                  float(c.model_deterring_persistence_buffer_s) + self._service_s(tr)
                  + float(c.model_deterring_persistence_eta_multiplier) * eta_s)
        dur = min(dur, float(c.model_deterring_max_persistence_lifetime_s))
        return float(t) + dur

    def _task_intensity_score(self, tr):
        """DeterrentSystem.py:6934."""
        x = tr.get("x", float("nan")); y = tr.get("y", float("nan"))
        if not np.isfinite(x) or not np.isfinite(y):
            return float("-inf")
        rid = tr.get("robot_id")
        if rid not in self.robots:
            return 0.0
        m = self.robots[rid].m
        iy, ix = m.world_to_idx(float(x), float(y))
        return float(m.lam[iy, ix] - m.mu[iy, ix])

    def _annotate(self, row):
        return annotate_predictive_utility_fields(
            row,
            predictive_utility_mode=str(self.cfg.predictive_utility_mode),
            predictive_confidence_source=str(self.cfg.predictive_confidence_source),
            predictive_confidence_power=float(self.cfg.predictive_confidence_power),
            is_direct_detection_task_fn=self._is_direct,
        )

    # ------------------------------------------------------------- candidate
    def _inject_candidate(self, cand: Candidate):
        rid = str(cand.robot_id)
        if rid not in self.robots:
            raise KeyError(f"candidate robot {rid!r} not in snapshot")
        if cand.mode not in self.deterring_modes:
            raise KeyError(f"candidate mode {cand.mode!r} not in deterring_modes")
        for tr in self.active_tasks:
            if (_is_forced(tr) and str(tr.get("assigned_primary")) == rid
                    and str(tr.get("state", "")).strip().lower() == "active"):
                raise ValueError(f"robot {rid!r} already executes a forced-first task (id {tr.get('id')})")
        row = {
            "id": -1,
            "robot_id": rid,
            "type": "deterring",
            "x": float(cand.x),
            "y": float(cand.y),
            "time": float(self.t0),
            "origin": "rollout_candidate",
            "mode": str(cand.mode),
            "score": 0.0,
            "utility": 0.0,
            "support": 0,
            "assigned_primary": rid,
            "assigned_secondary": None,
            "state": "active",
            "started_hold": None,
            "t_assigned": float(self.t0),
            "_rollout_candidate": True,
        }
        row["action"] = task_action(row, deterring_modes=self.deterring_modes, default_service_time_s=self.tau)
        self.active_tasks.append(row)
        self.candidate_task_id = -1
        self._candidate_row = copy.deepcopy(row)

    # ------------------------------------------------------- truth stage
    def _process_events(self, step_k, t_k):
        tree = self.tree
        acc_ids = _world_process_events(self.world, tree, self.accepted, step_k, t_k)
        if acc_ids.size == 0:
            return
        # detections (zone owner within range, then detection uniform)
        own = tree.owner[acc_ids]
        cand = acc_ids[own >= 0]
        if cand.size == 0:
            return
        own = tree.owner[cand]
        px = np.array([self.pose[self.rids[o]][0] for o in own])
        py = np.array([self.pose[self.rids[o]][1] for o in own])
        d = np.hypot(tree.x[cand] - px, tree.y[cand] - py)
        det = (d <= self.cfg.detect_range_m) & (tree.u_det[cand] <= min(max(self.cfg.bird_detection_prob, 0.0), 1.0))
        for e in cand[det]:
            self._on_detection(self.rids[int(tree.owner[e])], float(tree.x[e]), float(tree.y[e]), float(t_k))

    def _on_detection(self, owner, x, y, t):
        """DeterrentSystem.py:3520-3576 (_process_truth_event, detected branch)."""
        self.detections += 1
        b = self.robots[owner].ingest_detection(x, y, t)
        if self.consistent:
            # EventBus.publish_detection, consistent mode (DeterrentSystem.py:197-211)
            for rid in self.rids:
                if rid == owner:
                    continue
                rob = self.robots[rid]
                if not self._region_affected(rid, x, y, float(getattr(rob.m, "sigma", 0.0))):
                    continue
                rob.ingest_boundary_event(x=float(x), y=float(y), t=float(t), weight=1.0)
        else:
            for ev in b:
                rid = ev["target_robot"]
                if rid in self.robots and rid != owner:
                    self.robots[rid].ingest_boundary_event(
                        x=ev["x"], y=ev["y"], t=ev["t"], weight=ev.get("weight", 0.35),
                        sigma=ev.get("sigma"), omega=ev.get("omega"))
        if bool(self.cfg.enable_direct_detection_tasks):
            refresh = self._find_refreshable(x, y, t)
            if refresh is None:
                before = len(self.taskgen._rows)
                self.taskgen.on_detection(owner, x, y, t)
                if len(self.taskgen._rows) > before:
                    row = self.taskgen._rows[-1]
                    self.new_reactive[self._buffer_key(row)] = {"created_t": float(t), "x": x, "y": y}
            else:
                refresh["last_detection_t"] = float(t)
                refresh["merged_detection_count"] = int(refresh.get("merged_detection_count", 1)) + 1
                refresh["cluster_refresh_count"] = int(refresh.get("cluster_refresh_count", 0)) + 1

    def _refresh_status(self, tr):
        rid = str(tr.get("assigned_primary", "") or "").strip()
        if bool(self.cfg.direct_detection_task_active_refresh_require_assigned) and not rid:
            return False
        if tr.get("started_hold") is not None:
            return True
        lim = float(self.cfg.direct_detection_active_refresh_max_eta_s)
        if math.isfinite(lim) and lim >= 0.0:
            eta_s = float("inf")
            if rid:
                eta_s = self._eta(rid, (float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
            if not math.isfinite(eta_s):
                eta_s = float(tr.get("eta_s", float("inf")))
            if eta_s > lim:
                return False
        return True

    def _find_refreshable(self, x, y, t):
        """DeterrentSystem.py:3627."""
        if not bool(self.cfg.enable_direct_detection_task_clustering):
            return None
        r2 = float(self.cfg.direct_detection_active_refresh_radius_m) ** 2
        win = float(self.cfg.direct_detection_active_refresh_window_s)
        nearby = []
        for tr in self.active_tasks:
            if str(tr.get("state", "")).strip().lower() != "active" or not self._is_direct(tr):
                continue
            t_ref = float(tr.get("last_detection_t", tr.get("time", -1e18)))
            if (t - t_ref) > win:
                continue
            d2 = (x - float(tr.get("x", 0.0))) ** 2 + (y - float(tr.get("y", 0.0))) ** 2
            if d2 > r2:
                continue
            nearby.append((d2, tr))
        if not nearby:
            return None
        nearby.sort(key=lambda it: it[0])
        for _, tr in nearby:
            if self._refresh_status(tr):
                return tr
        return None

    # ------------------------------------------------------- expiry
    def _expire_predictive(self, t):
        """DeterrentSystem.py:6363."""
        ds = _ds()
        expired = set()
        for tr in list(self.active_tasks):
            if str(tr.get("state", "")).strip().lower() != "active":
                continue
            if _is_forced(tr):
                continue
            if ds._task_stream(tr) != "predictive" or tr.get("started_hold") is not None:
                continue
            rid = str(tr.get("assigned_primary", "") or "").strip()
            eta_s = None
            if rid:
                e = self._eta(rid, (float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
                if math.isfinite(float(e)):
                    eta_s = float(e)
            if ds._predictive_task_has_expired(tr, now_t=float(t), eta_s=eta_s,
                                               predictive_expiry_grace_s=float(self.cfg.predictive_expiry_grace_s)):
                expired.add(tr.get("id"))
                tr["state"] = "expired"
                if rid and self.goal.get(rid) is not None:
                    gx, gy = self.goal[rid]
                    if math.hypot(float(tr.get("x", 0.0)) - gx, float(tr.get("y", 0.0)) - gy) <= self.cfg.arrival_radius_m:
                        self.goal[rid] = None
        if expired:
            self.active_tasks[:] = [tr for tr in self.active_tasks if tr.get("id") not in expired]

    # ------------------------------------------------------- replan stage
    def _replan(self, t):
        c = self.cfg
        if self.model_advance != "per_step":
            for rob in self.robots.values():
                rob.advance_time(t - rob.m.t_now)
        self._process_near_goal_model_det(t)
        if self.recent_deterrences:
            rec = list(self.recent_deterrences)
            r2 = c.deterring_suppress_radius_m ** 2
            self.active_tasks[:] = [
                tr for tr in self.active_tasks
                if (self._kind(tr) == "deterring" or not any(
                    (float(ev.get("t", -1e9)) >= t - c.deterring_suppress_window_s)
                    and ((tr["x"] - float(ev.get("x", 0.0))) ** 2 + (tr["y"] - float(ev.get("y", 0.0))) ** 2 <= r2)
                    for ev in rec))
            ]
        kept = []
        for tr in self.active_tasks:
            ok = ((self._persist_locked(tr, t) or (t - self._task_age_anchor_t(tr, t) <= c.task_max_age_s))
                  and (self._kind(tr) != "patrolling" or self._task_intensity_score(tr) >= c.task_refresh_min_score))
            if ok:
                kept.append(tr)
            elif self._is_direct(tr):
                for k in (tr.get("_member_task_keys") or [self._buffer_key(tr)]):
                    self.dropped_keys.setdefault(tuple(k), float(t))
        self.active_tasks[:] = kept
        self._generate(t)
        self._dispatch(t)
        self.last_replan = t

    def _process_near_goal_model_det(self, t):
        """DeterrentSystem.py:6814."""
        for rid in self.rids:
            for tr in list(self.active_tasks):
                if not self._is_active_model_det(tr):
                    continue
                if str(tr.get("assigned_primary", "")) != str(rid):
                    continue
                tx, ty = self._effective_goal(rid, (float(tr.get("x", 0.0)), float(tr.get("y", 0.0))))
                if math.hypot(self.pose[rid][0] - tx, self.pose[rid][1] - ty) > self.cfg.arrival_radius_m:
                    continue
                if tr.get("started_hold") is None:
                    self._start_hold(rid, tr, t)
                    if self.goal[rid] is None:
                        self.goal[rid] = (float(tr.get("x", tx)), float(tr.get("y", ty)))
                elif float(t) >= float(tr["started_hold"]) + self._service_s(tr):
                    self._complete_deterring(rid, tr, t)
                break

    # ---------------------------------------------- generation (TaskGenerator port)
    def _zmask(self, rid, m):
        key = (rid, m.nx, m.ny)
        if key not in self._zone_mask:
            zone = self.robots[rid].zone_polygon
            XX, YY = np.meshgrid(np.asarray(m.xs, float), np.asarray(m.ys, float), indexing="xy")
            mask = points_in_polygon(XX, YY, zone) if zone else np.ones(XX.shape, bool)
            self._zone_mask[key] = mask
        return self._zone_mask[key]

    def _generate(self, now_t):
        _b5_periodic_patrolling(self, now_t)

    def _jitter(self, rid, now_t):
        r_idx = self.rids.index(rid)
        g = np.random.Generator(np.random.PCG64(np.random.SeedSequence(
            [self.tree.jitter_seed, r_idx, int(round(now_t * 1000))])))
        return g

    # ---------------------------------------------- dispatch (DeterrentSystem port)
    def _cluster_direct(self, tasks):
        """DeterrentSystem.py:3673 _cluster_direct_detection_candidate_tasks."""
        if not bool(self.cfg.enable_direct_detection_task_clustering):
            return list(tasks)
        direct_idx = [i for i, tr in enumerate(tasks) if self._is_direct(tr)]
        if len(direct_idx) <= 1:
            return list(tasks)
        rows = [dict(tasks[i]) for i in direct_idx]
        r2 = float(self.cfg.direct_detection_queued_cluster_radius_m) ** 2
        win = float(self.cfg.direct_detection_queued_cluster_window_s)
        visited = [False] * len(rows)
        clustered = []

        def _nb(a, b):
            if abs(float(a.get("time", 0.0)) - float(b.get("time", 0.0))) > win:
                return False
            return ((float(a.get("x", 0.0)) - float(b.get("x", 0.0))) ** 2
                    + (float(a.get("y", 0.0)) - float(b.get("y", 0.0))) ** 2) <= r2

        for i in range(len(rows)):
            if visited[i]:
                continue
            queue = [i]
            visited[i] = True
            comp = []
            while queue:
                cur = queue.pop()
                comp.append(cur)
                for j in range(len(rows)):
                    if visited[j]:
                        continue
                    if _nb(rows[cur], rows[j]):
                        visited[j] = True
                        queue.append(j)
            members = [rows[j] for j in comp]
            members.sort(key=lambda tr: float(tr.get("time", 0.0)))
            rep = dict(members[0])
            rep["_member_task_keys"] = [self._buffer_key(mm) for mm in members]
            rep["merged_detection_count"] = int(sum(int(mm.get("merged_detection_count", 1)) for mm in members))
            rep["cluster_refresh_count"] = int(sum(int(mm.get("cluster_refresh_count", 0)) for mm in members))
            rep["last_detection_t"] = float(max(float(mm.get("last_detection_t", mm.get("time", 0.0))) for mm in members))
            clustered.append(rep)
        out = []
        inserted = False
        dset = set(direct_idx)
        for i, tr in enumerate(tasks):
            if i in dset:
                if not inserted:
                    out.extend(clustered)
                    inserted = True
                continue
            out.append(tr)
        if not inserted:
            out.extend(clustered)
        return out

    def _dispatch(self, now_t):
        """DeterrentSystem.py:5210 _run_dispatch_stage, restricted to the B5 path."""
        ds = _ds()
        c = self.cfg
        buf = build_task_dispatch_candidate_buffer(
            now_t=now_t,
            active_tasks=self.active_tasks,
            completed_tasks=self.completed_tasks,
            consumed_task_keys=self.consumed_task_keys,
            taskgen=self.taskgen,
            robot_ids=self.robots.keys(),
            task_buffer_key_fn=self._buffer_key,
            is_direct_detection_task_fn=self._is_direct,
            cluster_direct_detection_candidate_tasks_fn=self._cluster_direct,
            predictive_utility_mode=str(c.predictive_utility_mode),
            predictive_confidence_source=str(c.predictive_confidence_source),
            predictive_confidence_power=float(c.predictive_confidence_power),
            predictive_owner_override_id=None,
        )
        active_load = dict(buf["active_load"])
        active_patrol_load = dict(buf["active_patrol_load"])
        active_model_det_load = dict(buf["active_model_det_load"])
        self.assigner.set_robot_poses(self.pose if bool(c.use_live_robot_pose_for_task_planning) else None)
        self.assigner.set_disabled_robot_ids(set())
        accepted_this_cycle = 0
        ordered = ds._ordered_dispatch_candidates(buf["candidate_tasks"])
        for t in ordered:
            sel = select_assignment(
                task_row=t,
                active_load=active_load,
                assigner=self.assigner,
                prefer_idle_for_model_deterring=bool(c.model_deterring_prefer_idle_robots_for_assignment),
                is_model_deterring_candidate_fn=ds._is_model_deterring_candidate,
            )
            cand = t
            if ds._task_stream(cand) == "predictive":
                cand = self._annotate(cand)
            ttype = str(sel.task_type)
            is_model_det = bool(sel.is_model_det)
            primary = sel.assigned_primary
            secondary = sel.assigned_secondary
            if primary is None:
                continue
            busy = active_load.get(primary, 0) > 0
            if (ttype == "patrolling" and bool(c.protect_locked_model_deterring_from_patrol_assignment)
                    and self._has_locked_model_det_on_robot(primary, now_t)):
                continue
            gating = evaluate_model_deterring_dispatch_gating(
                task_row=cand,
                assigned_primary=primary,
                assigned_primary_busy=bool(busy),
                accepted_this_cycle=int(accepted_this_cycle),
                active_model_det_load_map=active_model_det_load,
                now_t=now_t,
                model_deterring_global_admission_cap_per_cycle=int(c.model_deterring_global_admission_cap_per_cycle),
                model_deterring_require_idle_robot_for_admission=bool(c.model_deterring_require_idle_robot_for_admission),
                model_deterring_budget_mode=str(c.model_deterring_budget_mode),
                model_deterring_budget_per_robot_per_hr=int(c.model_deterring_budget_per_robot_per_hr),
                model_deterring_budget_utility_per_robot_per_hr=float(c.model_deterring_budget_utility_per_robot_per_hr),
                max_active_model_deterring_per_robot=int(c.max_active_model_deterring_per_robot),
                model_deterring_by_robot=self.model_det_budget,
                dispatch_task_value_fn=ds._dispatch_task_value,
                is_model_deterring_candidate_fn=ds._is_model_deterring_candidate,
                direct_conflict_fn=lambda row, rid: has_direct_detection_conflict(
                    task_row=row, assigned_primary=rid, active_tasks=self.active_tasks,
                    completed_tasks=self.completed_tasks, now_t=now_t,
                    protect_direct_detection_from_model_deterring=bool(c.protect_direct_detection_from_model_deterring),
                    direct_conflict_radius_m=float(c.model_deterring_direct_conflict_radius_m),
                    direct_conflict_window_s=float(c.model_deterring_direct_conflict_window_s),
                    deterring_source_fn=self._deterring_source),
                busy_fallback_quality_fn=lambda row: passes_busy_fallback_quality(
                    task_row=row, p_event_min=float(c.model_deterring_busy_fallback_p_event_min),
                    deltaJ_per_cost_min=float(c.model_deterring_busy_fallback_deltaJ_per_cost_min),
                    eta_s_max=float(c.model_deterring_busy_fallback_eta_s_max)),
            )
            if gating.reason is not None:
                continue
            if active_load.get(primary, 0) >= int(c.max_active_tasks_per_robot):
                if ttype == "patrolling" or is_model_det:
                    worst = ds._select_patrol_replacement_task(self.active_tasks, primary, cand)
                    if worst is None:
                        continue
                    self._evict_patrol(worst, active_load, active_patrol_load)
            if ttype == "patrolling" and active_patrol_load.get(primary, 0) >= int(c.max_active_patrolling_per_robot):
                worst = ds._select_patrol_replacement_task(self.active_tasks, primary, cand)
                if worst is None:
                    continue
                self._evict_patrol(worst, active_load, active_patrol_load)
            if is_model_det:
                q = gating.budget_queue
                q.append((float(now_t), float(gating.task_utility)))
                self.model_det_budget[primary] = q
                accepted_this_cycle += 1
            accepted = {
                "id": self.next_tid,
                **cand,
                "assigned_primary": primary,
                "assigned_secondary": secondary,
                "state": "active",
                "started_hold": None,
                "t_assigned": float(now_t),
            }
            if ds._task_stream(accepted) == "predictive":
                accepted = self._annotate(accepted)
                accepted["assigned_eta_s"] = float(ds._finite_task_metric(
                    accepted, "assigned_eta_s",
                    self._eta(primary, (float(cand.get("x", 0.0)), float(cand.get("y", 0.0))))))
                slack = ds._predictive_deadline_slack_s(accepted)
                if math.isfinite(slack):
                    accepted["predictive_deadline_slack_s"] = float(slack)
            if is_model_det:
                accepted["persist_lock_until_t"] = self._lock_until(accepted, now_t)
            self.active_tasks.append(accepted)
            mk = t.get("_member_task_keys")
            if isinstance(mk, list) and mk:
                for k in mk:
                    try:
                        self.consumed_task_keys.add(tuple(k))
                    except Exception:
                        pass
            self.consumed_task_keys.add(self._buffer_key(t))
            active_load[primary] = active_load.get(primary, 0) + 1
            if ttype == "patrolling":
                active_patrol_load[primary] = active_patrol_load.get(primary, 0) + 1
            if is_model_det:
                active_model_det_load[primary] = active_model_det_load.get(primary, 0) + 1
            if primary and self.goal[primary] is None:
                self.goal[primary] = (cand["x"], cand["y"])
            self.next_tid += 1

    def _evict_patrol(self, ev, active_load, active_patrol_load):
        rid_e = ev.get("assigned_primary")
        self.active_tasks[:] = [tr for tr in self.active_tasks if tr.get("id") != ev.get("id")]
        if rid_e in active_load:
            active_load[rid_e] = max(0, active_load.get(rid_e, 0) - 1)
            active_patrol_load[rid_e] = max(0, active_patrol_load.get(rid_e, 0) - 1)
        if rid_e in self.goal and self.goal.get(rid_e) is not None:
            gx, gy = self.goal[rid_e]
            if math.hypot(float(ev.get("x", 0.0)) - gx, float(ev.get("y", 0.0)) - gy) <= self.cfg.arrival_radius_m:
                self.goal[rid_e] = None

    # ------------------------------------------------------- motion stage
    def _start_hold(self, rid, tr, t):
        tr["started_hold"] = float(t)
        if tr.get("_rollout_candidate"):
            self.candidate_arrival_t = float(t)
        self.loiter_until[rid] = float(t) + self._service_s(tr)

    def _motion(self, t):
        """DeterrentSystem.py:7128-7428 for dispatch_policy='unc' and lane projection."""
        c = self.cfg
        for rid in self.rids:
            if self.loiter_until[rid] > t:
                pass
            else:
                cand_tr = None
                for tr in self.active_tasks:
                    if (_is_forced(tr) and tr.get("assigned_primary") == rid
                            and tr.get("state") == "active"):
                        cand_tr = tr
                        break
                if cand_tr is not None and self.loiter_until[rid] < t:
                    self.goal[rid] = (float(cand_tr["x"]), float(cand_tr["y"]))
                if bool(c.preempt_deterring_goals) and cand_tr is None:
                    det = [
                        tr for tr in self.active_tasks
                        if tr.get("assigned_primary") == rid
                        and str(tr.get("state", "")).strip().lower() == "active"
                        and self._kind(tr) == "deterring"
                        and ((self._deterring_source(tr) == "direct_detection" and bool(c.preempt_direct_detection_goals))
                             or (self._deterring_source(tr) == "model_scored"
                                 and (bool(c.preempt_model_scored_goals)
                                      or (bool(c.protect_active_model_deterring_goal_preemption)
                                          and self._persist_locked(tr, t)))))
                    ]
                    if det:
                        px, py = self.pose[rid]
                        best = min(det, key=lambda tr: self._eta(rid, (float(tr.get("x", px)), float(tr.get("y", py)))))
                        det_goal = (float(best.get("x", px)), float(best.get("y", py)))
                        cur_is_det = False
                        if self.goal[rid] is not None:
                            gx, gy = self.goal[rid]
                            for tr in det:
                                if math.hypot(float(tr.get("x", 0.0)) - gx, float(tr.get("y", 0.0)) - gy) <= c.arrival_radius_m:
                                    cur_is_det = True
                                    break
                        if self.goal[rid] is None or not cur_is_det:
                            self.goal[rid] = det_goal
                if self.goal[rid] is None:
                    assigned = [tr for tr in self.active_tasks if tr["assigned_primary"] == rid and tr["state"] == "active"]
                    if assigned:
                        _tid, gx, gy = min(((tr["id"], tr["x"], tr["y"]) for tr in assigned),
                                           key=lambda z: self._eta(rid, (float(z[1]), float(z[2]))))
                        self.goal[rid] = (gx, gy)
                if self.goal[rid] is not None:
                    self._step_to(rid, self.goal[rid])
            # arrival / completion
            if self.goal[rid] is not None:
                gx, gy = self._effective_goal(rid, self.goal[rid])
                if math.hypot(self.pose[rid][0] - gx, self.pose[rid][1] - gy) <= c.arrival_radius_m:
                    matched = False
                    for tr in self.active_tasks:
                        if tr["assigned_primary"] != rid or tr["state"] != "active":
                            continue
                        tx, ty = self._effective_goal(rid, (tr["x"], tr["y"]))
                        if math.hypot(self.pose[rid][0] - tx, self.pose[rid][1] - ty) > c.arrival_radius_m:
                            continue
                        matched = True
                        if self._kind(tr) == "deterring":
                            if tr["started_hold"] is None:
                                self._start_hold(rid, tr, t)
                            elif t >= tr["started_hold"] + self._service_s(tr):
                                self._complete_deterring(rid, tr, t)
                            break
                        self._complete_patrol(rid, tr, t)
                        break
                    if not matched:
                        self.goal[rid] = None

    def _complete_patrol(self, rid, tr, t):
        tr["state"] = "done"
        tr["t_done"] = float(t)
        self.patrol_completed += 1
        self.completed_tasks.append(tr)
        self.active_tasks[:] = [x for x in self.active_tasks if x["id"] != tr["id"]]
        self.goal[rid] = None

    def _complete_deterring(self, rid, tr, t):
        """DeterrentSystem.py:6603 _complete_deterring_task."""
        c = self.cfg
        ds = _ds()
        tr["state"] = "done"
        tr["t_done"] = float(t)
        self.completed_tasks.append(tr)
        stream = ds._task_stream(tr)
        if tr.get("_rollout_candidate"):
            self.candidate_completed_t = float(t)
        if _is_forced(tr):
            self.forced_completed[tr.get("id")] = float(t)
        if stream == "reactive":
            self.reactive_completed += 1
            for k in (tr.get("_member_task_keys") or [self._buffer_key(tr)]):
                self.done_keys.setdefault(tuple(k), float(t))
        else:
            self.predictive_completed += 1
        spec = task_action(tr, deterring_modes=self.deterring_modes, default_service_time_s=self.tau)
        mode_label = str(spec.name or "direct_detection")
        cell_id, mode_idx, hab_label = _hab_indices(self.snap, tr["x"], tr["y"], mode_label)
        eta_apply = 1.0
        eta_world = 1.0
        if bool(c.enable_habituation) and cell_id is not None and mode_idx is not None:
            eta_apply = self.hab.effectiveness(cell_id, mode_idx)
            eta_world = eta_apply
            if self.world_hab is not None:
                eta_world = self.world_hab.effectiveness(cell_id, mode_idx)
                _ds()._apply_habituation_update(
                    self.world_hab, cell_id, mode_idx,
                    self.snap.world_habituation_update_model or c.planner_habituation_update_model)
            _ds()._apply_habituation_update(self.hab, cell_id, mode_idx, c.planner_habituation_update_model)
        action_id = int(tr.get("id", -1))
        if tr.get("_rollout_candidate"):
            self.candidate_eta_planner = float(eta_apply)
            self.candidate_eta_world = float(eta_world)
        m = self.robots[rid].m
        entry, inhib, params, _ml, (eff_beta, fb_sigma, fb_omega) = _application_world_effects(
            self.snap, tr, t, eta_apply=eta_apply, eta_world=eta_world, model=m,
            source=self._deterring_source(tr), hab_label=hab_label, deterring_modes=self.deterring_modes,
            tau=self.tau)
        self.recent_deterrences.append(entry)
        if self.world_store is not self.recent_deterrences:
            self.world_store.append(dict(entry))
        self.world.on_deterrence_added()
        self.interventions.append({
            "t": float(t), "robot": rid, "x": float(tr["x"]), "y": float(tr["y"]), "mode": mode_label,
            "source": self._deterring_source(tr), "eta": float(eta_world), "eta_planner": float(eta_apply),
            "candidate": bool(tr.get("_rollout_candidate", False)), "forced": bool(_is_forced(tr)),
        })
        self.world.add_legacy_inhibition(*inhib)
        if bool(c.enable_intervention_feedback) and self.consistent:
            # DeterrentSystem.py:7122-7147: planner parameters, amplitude q_hat * beta,
            # footprint broadcast to the executing robot and every affected robot.
            _, p_beta, p_sigma, p_omega = _ds()._resolve_planner_deterrence_event_params(
                mode_label, params,
                planner_deterring_modes=c.planner_deterring_modes,
                use_mode_dependent_truth_suppression=bool(c.use_mode_dependent_truth_suppression),
                planner_beta=float(c.planner_beta), planner_sigma=float(c.planner_sigma),
                planner_omega=float(c.planner_omega))
            self._broadcast_intervention(
                x=float(tr["x"]), y=float(tr["y"]), t=float(t), amplitude=float(eta_apply) * float(p_beta),
                sigma=float(p_sigma), omega=float(p_omega), mode=mode_label, action_id=action_id, source_id=rid)
        elif bool(c.enable_intervention_feedback):
            self.robots[rid].ingest_intervention_event(
                tr["x"], tr["y"], t, weight=eff_beta, sigma=fb_sigma, omega_inhib=fb_omega,
                mode=mode_label, beta=eff_beta, action_id=action_id)
            evs = self.robots[rid].intervention_boundary_events(
                tr["x"], tr["y"], t, weight=eff_beta, mode=mode_label, sigma=fb_sigma,
                omega_inhib=fb_omega, beta=eff_beta, action_id=action_id)
            self._send_intervention_events(evs, rid)
        self.active_tasks[:] = [x for x in self.active_tasks if x["id"] != tr["id"]]
        self.goal[rid] = None
        self.loiter_until[rid] = -1.0

    # ------------------------------------------- consistent-estimator relay
    def _region_affected(self, rid, x, y, sigma):
        """EventBus.robot_region_affected (DeterrentSystem.py:183-195)."""
        regions = self.snap.robot_region_polys
        if regions is None:
            return True
        radius = float(self.cfg.consistent_footprint_sigmas) * max(float(sigma), 0.0)
        for poly in regions.get(rid, []) or []:
            if not poly:
                continue
            if point_in_polygon(float(x), float(y), poly):
                return True
            if point_to_poly_distance((float(x), float(y)), poly) <= radius:
                return True
        return False

    def _broadcast_intervention(self, *, x, y, t, amplitude, sigma, omega, mode, action_id, source_id):
        """EventBus.broadcast_intervention (DeterrentSystem.py:213-243)."""
        for rid in self.rids:
            if rid != source_id and not self._region_affected(rid, x, y, sigma):
                continue
            self.robots[rid].ingest_intervention_event(
                x, y, t, weight=float(amplitude), sigma=float(sigma), omega_inhib=float(omega),
                mode=mode, beta=float(amplitude), action_id=action_id)

    def _coverage_mask(self, rid, m):
        """DeterrentSystem._detection_coverage_mask: own zone nodes within sensor range."""
        zone = self.robots[rid].zone_polygon
        if not zone:
            return None
        key = ("cov", rid, m.nx, m.ny)
        if key not in self._zone_mask:
            XX, YY = np.meshgrid(np.asarray(m.xs, float), np.asarray(m.ys, float), indexing="xy")
            self._zone_mask[key] = (points_in_polygon(XX, YY, zone), XX, YY)
        zmask, XX, YY = self._zone_mask[key]
        px, py = self.pose[rid]
        in_range = ((XX - float(px)) ** 2 + (YY - float(py)) ** 2) <= float(self.cfg.detect_range_m) ** 2
        return zmask & in_range

    def _advance_models(self, t):
        """Stage 5 model advance after the motion stage of step t."""
        dt = self.dt
        if self.consistent:
            # _consistent_accumulate_exposure(dt) then advance_to(t + dt) (DeterrentSystem.py:7947-7952)
            for rid in self.rids:
                rob = self.robots[rid]
                mask = self._coverage_mask(rid, rob.m)
                if mask is not None:
                    rob.m.accumulate_detection_exposure(mask, dt)
            for rid in self.rids:
                self.robots[rid].m.advance_to(float(t) + float(dt))
        else:
            for rob in self.robots.values():
                rob.advance_time(dt)

    def _track_obligations(self, t):
        if not self.obligations:
            return
        rate = self.world.node_exposure_rate(t)
        for ob in self.obligations:
            if t > float(ob["deadline_t"]) + 1e-9:
                continue
            e = float(np.sum(rate[self._cell_owner == int(ob["cell"])]))
            oid = ob["id"]
            if e < self.obl_min_e[oid]:
                self.obl_min_e[oid] = e
            self.obl_e_deadline[oid] = e     # last tracked step t <= deadline: e_z at the deadline
            if e <= float(ob["e_low"]) and not math.isfinite(self.obl_sat[oid]):
                self.obl_sat[oid] = float(t)

    def _send_intervention_events(self, events, source_id):
        """DeterrentSystem.py:171 EventBus.send_intervention_events."""
        c = self.cfg
        min_int = max(0.0, float(c.intervention_boundary_min_interval_s))
        quant = float(c.intervention_boundary_spatial_quant_m)
        min_w = float(c.intervention_boundary_min_weight)
        for ev in events:
            rid = ev["target_robot"]
            if rid not in self.robots or rid == source_id:
                continue
            w = float(ev.get("weight", 1.0))
            if w < min_w:
                continue
            if min_int > 0.0:
                x = float(ev.get("x", 0.0)); y = float(ev.get("y", 0.0)); t = float(ev.get("t", 0.0))
                if quant > 1e-9:
                    qx = int(round(x / quant)); qy = int(round(y / quant))
                else:
                    qx = int(round(x)); qy = int(round(y))
                k = (str(source_id), str(rid), qx, qy,
                     None if ev.get("mode") is None else str(ev.get("mode")), ev.get("action_id"))
                if (t - float(self.bus_last.get(k, -1e18))) < min_int:
                    continue
                self.bus_last[k] = t
            self.robots[rid].ingest_intervention_event(
                x=ev["x"], y=ev["y"], t=ev["t"], weight=w, sigma=ev.get("sigma"),
                omega_inhib=ev.get("omega_inhib"), mode=ev.get("mode"), beta=ev.get("beta"),
                action_id=ev.get("action_id"))

    # ------------------------------------------------------------ main loop
    def run(self):
        c = self.cfg
        dt = self.dt
        if self.snap.start_stage == "replan":
            # The truth and expiry stages of step t0 already ran in the simulator
            # (the snapshot is taken at its Stage 3); finish step t0 here.
            t = self.t0
            if (t - self.last_replan) >= c.task_replan_period_s:
                self._replan(t)
            self._motion(t)
            if self.model_advance == "per_step":
                self._advance_models(t)
            self.world.end_step()
        for k in range(1, self.n_steps + 1):
            t = self.t0 + k * dt
            # Stage 2: habituation recovery then truth events (DeterrentSystem.py:4742)
            if bool(c.enable_habituation):
                self.hab.recover(dt)
                if self.world_hab is not None:
                    self.world_hab.recover(dt)
            self.world.begin_step(t)
            self._process_events(k, t)
            self._track_obligations(t)
            self._expire_predictive(t)
            # Stage 3: replanning
            if (t - self.last_replan) >= c.task_replan_period_s:
                self._replan(t)
            # Stage 4: motion and completion
            self._motion(t)
            # Stage 5: advance robot estimators
            if self.model_advance == "per_step":
                self._advance_models(t)
            self.world.end_step()
        self.J_one = None
        if self.one_intervention:
            # one-intervention counterfactual (variant C_plan) on the same tree: the
            # candidate's suppression alone, at its application time in this scenario
            self.J_one = one_intervention_J(
                self.snap, self.tree, self._candidate_row,
                t_apply=(self.candidate_completed_t if self._candidate_row is not None else math.inf),
                robot_id=(None if self.candidate.is_noop else str(self.candidate.robot_id)))
        return self._result()

    def _terminal_summary(self, t_end, pend, new):
        """Per-scenario terminal state at t + H (user decision 30; logged, no terminal cost).

        unfinished_by_stream counts the active task rows at t + H by the stream
        definition of decision 13: reactive (direct detection), predictive (B5
        predictive deterrence and patrols) and deviation (forced-first tasks:
        the evaluated candidate and committed deviations).  reactive_uncompleted
        counts the reactive work items (pending at t plus created within H) with
        no completion by t + H (queued, active, or dropped); their completion
        time is +inf in every comparison.  robots_busy counts robots with at
        least one active assigned task at t + H (a robot holding at a target
        still has that task active).
        """
        ds = _ds()
        by = {"reactive": 0, "predictive": 0, "deviation": 0}
        busy = set()
        for tr in self.active_tasks:
            if str(tr.get("state", "")) != "active":
                continue
            s = "deviation" if _is_forced(tr) else ds._task_stream(tr)
            by[s] = by.get(s, 0) + 1
            rid = tr.get("assigned_primary")
            if rid:
                busy.add(str(rid))
        unc = sum(1 for v in pend.values() if not math.isfinite(float(v["completed_t"]))) +             sum(1 for v in new if not math.isfinite(float(v["completed_t"])))
        return {"unfinished_by_stream": by, "reactive_uncompleted": int(unc),
                "residual_exposure_rate": float(self.world.residual_rate(t_end)),
                "robots_busy": int(len(busy)), "robots_busy_ids": sorted(busy)}

    def _result(self):
        t_end = self.t0 + self.n_steps * self.dt
        pend = {}
        for p in self.snap.pending_reactive:
            ct = self.done_keys.get(tuple(p.key), math.inf)
            pend[p.key] = {"created_t": p.created_t, "deadline_t": p.deadline_t, "completed_t": ct,
                           "on_time": bool(ct <= p.deadline_t), "dropped_t": self.dropped_keys.get(tuple(p.key))}
        new = []
        for key, info in self.new_reactive.items():
            ct = self.done_keys.get(tuple(key), math.inf)
            new.append({"key": key, "created_t": info["created_t"], "x": info["x"], "y": info["y"],
                        "deadline_t": info["created_t"] + self.reactive_deadline_s, "completed_t": ct,
                        "dropped_t": self.dropped_keys.get(tuple(key))})
        unfinished = [
            {"id": tr.get("id"), "stream": _ds()._task_stream(tr), "type": tr.get("type"), "x": tr.get("x"),
             "y": tr.get("y"), "assigned": tr.get("assigned_primary"), "started_hold": tr.get("started_hold"),
             "candidate": bool(tr.get("_rollout_candidate", False))}
            for tr in self.active_tasks if str(tr.get("state", "")) == "active"
        ]
        terminal = {
            "robots": {rid: {"pose": self.pose[rid], "goal": self.goal[rid], "loiter_until": self.loiter_until[rid]}
                       for rid in self.rids},
            "unfinished_tasks": unfinished,
            "residual_exposure_rate": float(self.world.residual_rate(t_end)),
            "habituation_eta": self.hab.eta.copy(),
        }
        return {
            "J": float(self.world.J),
            "J_bg": float(self.world.J_bg),
            "J_exc": float(self.world.J_exc),
            "J_sched": float(self.world.J_sched),
            "counted_exposure": float(self.world.counted),
            "pending_completion": pend,
            "new_reactive": new,
            "interventions": list(self.interventions),
            "detections": int(self.detections),
            "reactive_completed": int(self.reactive_completed),
            "predictive_completed": int(self.predictive_completed),
            "patrol_completed": int(self.patrol_completed),
            "candidate_completed_t": float(self.candidate_completed_t),
            "forced_completed": dict(self.forced_completed),
            "obligations": {oid: {"satisfied_t": float(self.obl_sat[oid]), "min_e": float(self.obl_min_e[oid]),
                                  "e_deadline": float(self.obl_e_deadline[oid])}
                            for oid in self.obl_sat},
            "terminal": terminal,
            "terminal_summary": self._terminal_summary(t_end, pend, new),
            "candidate_arrival_t": float(self.candidate_arrival_t),
            "candidate_eta_planner": float(self.candidate_eta_planner),
            "candidate_eta_world": float(self.candidate_eta_world),
            "J_one": (None if self.J_one is None else float(self.J_one)),
        }


# ---------------------------------------------------------------------------
# Vectorised port of TaskGenerator.periodic_patrolling for the B5 configuration
# ---------------------------------------------------------------------------
def _patch_window(m, x, y, rad):
    iy, ix = m.world_to_idx(x, y)
    y0 = max(0, iy - rad); y1 = min(m.ny, iy + rad + 1)
    x0 = max(0, ix - rad); x1 = min(m.nx, ix + rad + 1)
    return iy, ix, y0, y1, x0, x1


def fast_counterfactual_reduction(m, x, y, *, beta_u, sigma_u, omega_u, horizon_s, mask_grid,
                                  weight_grid, available_integral_grid, kernel_cache=None):
    """Vectorised planner_task_estimation.estimate_counterfactual_reduction (same terms)."""
    key = (round(float(sigma_u), 12), float(m.dx), float(m.dy))
    if kernel_cache is not None and key in kernel_cache:
        rad, kern = kernel_cache[key]
    else:
        rad, kern = _normalized_gaussian_kernel(m.dx, m.dy, sigma_u)
        if kernel_cache is not None:
            kernel_cache[key] = (rad, kern)
    iy, ix, y0, y1, x0, x1 = _patch_window(m, x, y, rad)
    ky0 = y0 - (iy - rad); kx0 = x0 - (ix - rad)
    pk = kern[ky0:ky0 + (y1 - y0), kx0:kx0 + (x1 - x0)]
    sf = _time_integral_factor(omega_u, horizon_s)
    amp = float(m.alpha_inhib) * float(beta_u)
    w = weight_grid[y0:y1, x0:x1]
    av = available_integral_grid[y0:y1, x0:x1]
    msk = mask_grid[y0:y1, x0:x1] if mask_grid is not None else np.ones(av.shape, bool)
    ok = msk & (w > 0.0) & (av > 0.0) & (pk > 0.0)
    supp = amp * pk * sf
    red = np.minimum(av, supp)
    da = float(m.dx * m.dy)
    return float(np.sum((w * red)[ok]) * da)


def fast_patrol_response_reduction(m, x, y, *, horizon_s, detect_range_m, detect_prob_per_step,
                                   detection_dwell_s, followup_success_prob, response_eta_decay_s,
                                   followup_speed_mps, mask_grid, weight_grid, available_integral_grid):
    """Vectorised planner_task_estimation.estimate_patrol_response_reduction."""
    detect_range = max(float(detect_range_m), 1e-9)
    detect_sigma = max(0.5 * detect_range, max(float(m.dx), float(m.dy), 1e-9))
    detect_prob = min(max(float(detect_prob_per_step), 0.0), 1.0)
    dwell_s = max(float(detection_dwell_s), 1e-9)
    follow = min(max(float(followup_success_prob), 0.0), 1.0)
    decay = max(float(response_eta_decay_s), 1e-9)
    speed = max(float(followup_speed_mps), 1e-9)
    response_scale = (1.0 - math.exp(-detect_prob * dwell_s)) * follow
    grid_step = max(float(m.dx), float(m.dy), 1e-9)
    rad = int(math.ceil(detect_range / grid_step))
    iy, ix, y0, y1, x0, x1 = _patch_window(m, x, y, rad)
    wx = np.asarray(m.xs[x0:x1], float)[None, :]
    wy = np.asarray(m.ys[y0:y1], float)[:, None]
    dxw = wx - float(x)
    dyw = wy - float(y)
    d2 = dxw * dxw + dyw * dyw
    av = available_integral_grid[y0:y1, x0:x1]
    w = weight_grid[y0:y1, x0:x1]
    msk = mask_grid[y0:y1, x0:x1] if mask_grid is not None else np.ones(av.shape, bool)
    kr = np.exp(-0.5 * d2 / max(detect_sigma ** 2, 1e-9))
    ef = np.exp(-(np.sqrt(d2) / speed) / decay)
    ok = msk & (d2 <= detect_range ** 2) & (av > 0.0) & (kr > 0.0) & (w > 0.0) & (ef > 0.0)
    da = float(m.dx * m.dy)
    cap = float(np.sum((w * av * kr * ef)[ok]) * da)
    mass = float(np.sum(kr[ok]))
    if mass > 0.0 and response_scale > 0.0:
        return max(0.0, response_scale * cap / max(math.sqrt(mass), 1e-6))
    return 0.0


def _b5_periodic_patrolling(sim: _Sim, now_t: float):
    """Port of TaskGenerator.periodic_patrolling (TaskGenerator.py:495-1816) for B5.

    B5 path: heuristic preventive gate (forced at TaskGenerator.py:609),
    legacy_habituation scoring, shared_response_reduction patrol scoring,
    percentile hotspot filter, synthetic predictive lead time.  The hot loops
    (counterfactual reduction, patrol reduction, patch sums) are vectorised;
    the state transitions (persistence, cooldown, rows, dedupe, fallback
    waypoints) use the TaskGenerator instance's own methods.
    """
    c = sim.cfg
    tg = sim.taskgen
    if not bool(c.enable_patrolling):
        return
    busy = current_busy_deterring_robots(sim.active_tasks)
    recent_det_events = list(sim.recent_deterrences)
    deterring_modes = sim.deterring_modes
    hab = sim.hab
    replan_s = float(c.task_replan_period_s)
    horizon_s = float(c.forecast_horizon_s)
    merge_r = float(tg.merge_radius_m)
    spacing = float(c.hotspot_spacing_m)
    top_k = int(c.hotspot_top_k)
    repeat_r2 = max(1e-6, float(c.model_deterring_repeat_block_radius_m)) ** 2
    persist_gap = max(float(c.model_deterring_persistence_max_gap_s), 1e-6)
    persist_min = max(1, int(c.model_deterring_min_persistence_replans))
    score_margin = float(c.model_deterring_score_margin)
    max_eta = max(1e-6, float(c.model_deterring_max_eta_s))
    busy_support = max(1, int(c.model_deterring_busy_min_support_override))
    busy_risk = float(c.model_deterring_busy_risk_override)
    repeat_window = max(0.0, float(c.model_deterring_repeat_block_window_s))
    cluster_quant = max(1.0, 0.5 * merge_r)
    preventive_quant = max(cluster_quant, 0.5 * max(merge_r, spacing))
    overlap_r = max(merge_r, 0.5 * spacing)
    overlap_r2 = overlap_r ** 2
    sprt_alpha = min(max(float(c.model_deterring_sprt_alpha), 1e-6), 1 - 1e-6)
    sprt_beta = min(max(float(c.model_deterring_sprt_beta), 1e-6), 1 - 1e-6)
    patch_radius = (float(c.model_deterring_sprt_patch_radius_m) if c.model_deterring_sprt_patch_radius_m is not None
                    else merge_r)
    patch_radius = max(patch_radius, 1e-6)
    patch_r2 = patch_radius ** 2
    count_window = max(replan_s, 1e-6)
    window_s = float(c.model_deterring_window_s)
    pct = float(c.patrol_hotspot_score_percentile)
    if pct <= 1.0:
        pct *= 100.0
    pct = min(max(pct, 0.0), 100.0)
    filter_mode = str(c.patrol_hotspot_filter_mode).strip().lower()
    keep_top_k = top_k if c.patrol_hotspot_keep_top_k is None else max(1, int(c.patrol_hotspot_keep_top_k))
    fixed = str(c.predictive_fixed_deterring_mode or "").strip()
    if fixed.lower() in {"", "none", "auto", "best", "multi", "multicue"}:
        fixed = ""
    modes = [fixed] if fixed else list(deterring_modes.keys())
    hab_aware = str(c.predictive_utility_mode).strip().lower().replace("-", "_") in {
        "legacy_habituation", "habituation_legacy", "habituation_aware", "habituation_aware_legacy",
        "eta_scaled_legacy", "eta_scaled_deltaj", "eta_scaled_delta_j"}
    shared_range = float(c.detect_range_m)
    shared_prob = float(c.bird_detection_prob)
    shared_dwell = float(c.bird_stay_mean_s)
    shared_decay = (max(float(c.bird_stay_mean_s), replan_s, 1.0) if c.patrol_shared_response_eta_decay_s is None
                    else float(c.patrol_shared_response_eta_decay_s))
    spin_by_type = {"UAV": 8.0, "UGV": 0.0}
    kcache = {}

    def _cell_id(x, y):
        for cid, poly in enumerate(sim.snap.hab_cell_polys):
            if poly and point_in_polygon(float(x), float(y), poly):
                return int(cid)
        return None

    for rid, rob in sim.robots.items():
        m = rob.m
        m.advance_time(now_t - m.t_now)
        recent_pts = [(x, y) for (x, y, t) in rob.recent_events if (now_t - t) <= window_s]
        count_pts = [(x, y) for (x, y, t) in rob.recent_events if (now_t - t) <= count_window]
        det_points = cluster_points(recent_pts, merge_r) if (c.enable_model_scored_deterring and window_s > 0) else []
        zone = rob.zone_polygon
        mask = zone if zone else None
        mask_grid = sim._zmask(rid, m) if mask is not None else None
        weight_grid = sim.snap_weight_grid(m)
        excess = m.lam - m.mu
        prof = sim.profiles.get(rid)
        rx, ry = sim.pose[rid] if bool(c.use_live_robot_pose_for_task_planning) else _zone_centroid(zone)
        speed = max(float(prof.speed_mps), 1e-6) if prof is not None else 1.0
        spin = float(spin_by_type.get(prof.type, 0.0)) if prof is not None else 0.0

        def _eta_s(x, y):
            return float(math.hypot(x - rx, y - ry) / max(speed, 1e-6) + spin)

        def _field_score(x, y):
            iy, ix = m.world_to_idx(x, y)
            return float(m.lam[iy, ix] - m.mu[iy, ix])

        raw = m.hotspots(top_k=max(top_k * 3, top_k), merge_radius=max(merge_r, spacing * 0.5),
                         use_excess=True, mask_poly=mask)
        raw_scores = sorted(float(h.get("score", 0.0)) for h in raw)
        if filter_mode == "absolute":
            filtered = [h for h in raw if float(h.get("score", 0.0)) >= float(c.min_hotspot_score)]
        elif filter_mode == "percentile":
            thr = _quantile(raw_scores, pct)
            filtered = [h for h in raw if float(h.get("score", 0.0)) >= thr] if math.isfinite(thr) else []
        else:
            filtered = sorted(raw, key=lambda h: float(h.get("score", 0.0)), reverse=True)[:keep_top_k]
        picks = []
        for h in filtered:
            hx, hy, hs = h["x"], h["y"], h["score"]
            if any((hx - px) ** 2 + (hy - py) ** 2 <= spacing ** 2 for (px, py, _) in picks):
                continue
            picks.append((hx, hy, hs))

        baseline_grid = m.mu * m.time_multiplier(m.t_now)
        avail_det = np.clip(m.lam - baseline_grid, 0.0, None) * _time_integral_factor(m.omega, horizon_s)
        avail_pat = np.clip(excess, 0.0, None) * _time_integral_factor(m.omega, horizon_s)
        da = float(m.dx * m.dy)

        def _risk_conf(x, y):
            fs = max(0.0, _field_score(x, y))
            return 1.0 - math.exp(-fs / max(float(c.model_deterring_risk_scale), 1e-12))

        def _patch_lam(x, y, sigma_u):
            rad = int(math.ceil(3.0 * sigma_u / max(m.dx, m.dy)))
            iy, ix, y0, y1, x0, x1 = _patch_window(m, x, y, rad)
            dxw = np.asarray(m.xs[x0:x1], float)[None, :] - x
            dyw = np.asarray(m.ys[y0:y1], float)[:, None] - y
            d2 = dxw * dxw + dyw * dyw
            k = np.exp(-0.5 * d2 / max(sigma_u ** 2, 1e-9))
            tf = float(m.omega) * (1.0 - math.exp(-horizon_s / max(float(m.omega), 1e-9)))
            acc = float(np.sum((m.lam[y0:y1, x0:x1] * k)[d2 <= patch_r2]))
            return max(da * tf * acc, 1e-9)

        def _patch_area(x, y):
            rad = int(math.ceil(patch_radius / max(m.dx, m.dy)))
            iy, ix, y0, y1, x0, x1 = _patch_window(m, x, y, rad)
            dxw = np.asarray(m.xs[x0:x1], float)[None, :] - x
            dyw = np.asarray(m.ys[y0:y1], float)[:, None] - y
            ok = (dxw * dxw + dyw * dyw) <= patch_r2
            if mask_grid is not None:
                ok = ok & mask_grid[y0:y1, x0:x1]
            return max(float(np.count_nonzero(ok)) * da, da)

        def _det_metrics(x, y, mode):
            params = deterring_modes.get(mode, {})
            beta = float(params.get("beta", m.alpha_inhib))
            omega_u = float(params.get("omega", m.omega_inhib))
            sigma_u = float(params.get("sigma", m.sigma))
            w_eta = float(params.get("w_eta", c.cost_w_eta))
            fixed_cost = float(params.get("fixed_cost", 0.0))
            cost = w_eta * _eta_s(x, y) + fixed_cost
            raw_red = fast_counterfactual_reduction(
                m, x, y, beta_u=beta, sigma_u=sigma_u, omega_u=omega_u, horizon_s=horizon_s,
                mask_grid=mask_grid, weight_grid=weight_grid, available_integral_grid=avail_det, kernel_cache=kcache)
            eta_plan = 1.0
            if hab_aware and hab is not None:
                cid = _cell_id(x, y)
                mid = sim.snap.mode_to_id.get(str(mode))
                if cid is not None and mid is not None:
                    eta_plan = float(hab.effectiveness(cid, mid))
            pdj = raw_red * eta_plan
            util = pdj - cost
            return {"predicted_reduction_raw": raw_red, "predicted_deltaJ": pdj, "cost_eta": cost,
                    "utility": util, "score": util, "deltaJ_per_cost": pdj / max(cost, 1e-6),
                    "habituation_eta_at_plan": eta_plan, "sigma_u": sigma_u}

        def _cluster_key(x, y):
            return (rid, int(round(float(x) / cluster_quant)), int(round(float(y) / cluster_quant)))

        def _candidate_key(origin, x, y):
            return (rid, str(origin).strip().lower(), int(round(float(x) / preventive_quant)),
                    int(round(float(y) / preventive_quant)))

        def _near_any(x, y, pts, r2):
            return any(((x - px) ** 2 + (y - py) ** 2) <= r2 for (px, py) in pts)

        seeds, seed_pts = [], []

        def _register(x, y, origin, fs=0.0):
            if _near_any(x, y, seed_pts, overlap_r2):
                return
            seed_pts.append((float(x), float(y)))
            seeds.append({"x": float(x), "y": float(y), "origin": str(origin), "forecast_score": float(fs)})

        if c.enable_model_scored_deterring:
            for (dx_, dy_) in det_points:
                _register(dx_, dy_, "model_detection_cluster", _field_score(dx_, dy_))
            for (hx, hy, hs) in picks:
                if float(hs) <= 0.0:
                    continue
                _register(hx, hy, "model_hotspot", hs)
            if mask is not None:
                bk = max(1, int(math.ceil(keep_top_k / 2.0)))
                field_b = np.clip(m.lam - m.mu, 0.0, None)
                shortlist = min(field_b.size, max(8 * bk, bk))
                flat = np.argpartition(field_b.ravel(), -shortlist)[-shortlist:]
                flat = flat[np.argsort(field_b.ravel()[flat])[::-1]]
                band = max(merge_r, spacing)
                bmin = max(float(c.min_hotspot_score), 0.0)
                bcoords, bpicks = [], []
                for idx in flat:
                    iy, ix = divmod(int(idx), m.nx)
                    x = float(m.xs[ix]); y = float(m.ys[iy]); sc = float(field_b[iy, ix])
                    if sc < bmin:
                        if bpicks:
                            break
                        continue
                    if not point_in_polygon(x, y, mask):
                        continue
                    if point_to_poly_distance((x, y), mask) > band:
                        continue
                    if _near_any(x, y, bcoords, overlap_r2):
                        continue
                    bcoords.append((x, y))
                    bpicks.append((x, y, sc))
                    if len(bpicks) >= bk:
                        break
                for (bx, by, bs) in bpicks:
                    _register(bx, by, "model_border_hotspot", bs)

        if sim.seed_log is not None:
            sim.seed_log.append((float(now_t), rid, [dict(sd) for sd in seeds], list(modes)))

        patrol_cands = []
        if c.enable_predictive_patrol_tasks:
            for (hx, hy, hs) in picks:
                patrol_cands.append({"type": "patrolling", "x": float(hx), "y": float(hy), "origin": "hotspot",
                                     "mode": None, "support": 0, "persistence": 0, "risk_conf": 0.0,
                                     "eta_s": _eta_s(hx, hy), "cluster_key": None, "candidate_key": None,
                                     "forecast_score": float(hs)})

        prev_cands = []
        if c.enable_model_scored_deterring:
            zone_area = float(polygon_area(mask)) if mask else float(
                (max(m.xs) - min(m.xs) + float(m.dx)) * (max(m.ys) - min(m.ys) + float(m.dy)))
            zone_area = max(zone_area, da)
            zone_det_count = float(len(count_pts))
            for sd in seeds:
                dx_, dy_ = sd["x"], sd["y"]
                origin = sd["origin"]
                support = sum(1 for (qx, qy) in recent_pts if (qx - dx_) ** 2 + (qy - dy_) ** 2 <= merge_r ** 2)
                rcount = sum(1 for (qx, qy) in count_pts if (qx - dx_) ** 2 + (qy - dy_) ** 2 <= patch_r2)
                parea = _patch_area(dx_, dy_)
                mu0 = max(zone_det_count * (parea / zone_area), 1e-6)
                mu1 = float("nan"); llr = float("nan"); persistence = 1
                ckey = None; cluster_key = None
                obs_sum = obs_win = obs_mean = float("nan")
                if origin == "model_detection_cluster":
                    cluster_key = _cluster_key(dx_, dy_)
                    ckey = cluster_key
                    prev = tg._deterring_cluster_state.get(cluster_key)
                    if prev and (now_t - float(prev.get("last_t", -1e9)) <= persist_gap):
                        persistence = int(prev.get("count", 0)) + 1
                        p_sum = float(prev.get("obs_count_sum", 0.0)); p_win = float(prev.get("obs_count_windows", 0.0))
                    else:
                        p_sum = 0.0; p_win = 0.0
                    obs_sum = p_sum + float(rcount); obs_win = p_win + 1.0
                    obs_mean = obs_sum / max(obs_win, 1.0)
                    mu1 = max(mu0 * 1.25, obs_mean)
                    llr_prev = float(prev.get("llr", 0.0)) if prev else 0.0
                    llr = llr_prev + (float(rcount) * math.log(max(mu1, 1e-9) / max(mu0, 1e-9)) - (mu1 - mu0))
                else:
                    ckey = _candidate_key(origin, dx_, dy_)
                    prev = tg._deterring_forecast_state.get(ckey)
                    if prev and (now_t - float(prev.get("last_t", -1e9)) <= persist_gap):
                        persistence = int(prev.get("count", 0)) + 1
                best = None
                for mode in modes:
                    mm = _det_metrics(dx_, dy_, mode)
                    if sim.mode_score_log is not None:
                        sim.mode_score_log.append((rid, float(dx_), float(dy_), str(mode), float(mm["score"])))
                    p_ev = float(1.0 - math.exp(-max(_patch_lam(dx_, dy_, mm["sigma_u"]), 0.0)))
                    if best is None or mm["utility"] > best[1]["utility"]:
                        best = (mode, mm, p_ev)
                if origin == "model_detection_cluster":
                    tg._deterring_cluster_state[cluster_key] = {
                        "count": int(persistence), "last_t": float(now_t), "x": float(dx_), "y": float(dy_),
                        "support": int(support), "llr": float(llr), "last_count_window_start_t": float(now_t - count_window),
                        "recent_detection_count": int(rcount), "patch_area": float(parea), "obs_count_sum": float(obs_sum),
                        "obs_count_windows": float(obs_win), "obs_count_mean": float(obs_mean), "patch_mu0": float(mu0),
                        "patch_mu1": float(mu1), "p_event": float(best[2] if best else 0.0),
                        "deltaJ_per_cost": float(best[1]["deltaJ_per_cost"] if best else 0.0)}
                elif origin in ("model_hotspot", "model_border_hotspot"):
                    tg._deterring_forecast_state[ckey] = {
                        "count": int(persistence), "last_t": float(now_t), "x": float(dx_), "y": float(dy_),
                        "support": int(support), "forecast_score": float(sd.get("forecast_score", _field_score(dx_, dy_))),
                        "recent_detection_count": int(rcount), "p_event": float(best[2] if best else 0.0),
                        "deltaJ_per_cost": float(best[1]["deltaJ_per_cost"] if best else 0.0)}
                if best is not None:
                    mode, mm, p_ev = best
                    prev_cands.append({
                        "type": "deterring", "x": float(dx_), "y": float(dy_), "origin": origin, "mode": mode,
                        "support": int(support), "persistence": int(persistence), "risk_conf": float(_risk_conf(dx_, dy_)),
                        "eta_s": _eta_s(dx_, dy_), "cluster_key": cluster_key, "candidate_key": ckey,
                        "score": float(mm["score"]), "utility": float(mm["utility"]),
                        "predicted_deltaJ": float(mm["predicted_deltaJ"]), "predictive_stl_U": None,
                        "habituation_eta_at_plan": mm["habituation_eta_at_plan"], "llr": float(llr),
                        "recent_detection_count": int(rcount), "patch_area": float(parea), "patch_mu0": float(mu0),
                        "patch_mu1": float(mu1), "p_event": float(p_ev), "deltaJ_per_cost": float(mm["deltaJ_per_cost"]),
                        "cost_eta": float(mm["cost_eta"]), "forecast_score": float(sd.get("forecast_score", 0.0)),
                        "predictive_generation_best_mode": mode,
                    })
            for store in (tg._deterring_cluster_state, tg._deterring_forecast_state):
                stale = [k for k, st in store.items()
                         if k[0] == rid and (now_t - float(st.get("last_t", -1e9))) > 3.0 * persist_gap]
                for k in stale:
                    store.pop(k, None)
                    tg._last_model_deterring_fire.pop(k, None)

        if sim.gen_log is not None:
            sim.gen_log.append((float(now_t), rid, [dict(cd) for cd in prev_cands]))
        next_ok = tg._next_allowed.get(rid, -1e9)
        if now_t >= next_ok and (prev_cands or patrol_cands):
            eligible = []
            best_det = None
            for cd in prev_cands:
                is_cluster = cd["origin"] == "model_detection_cluster"
                x, y = cd["x"], cd["y"]
                pred_dj = float(cd.get("predicted_deltaJ", 0.0))
                if rid in busy:
                    if int(cd.get("support", 0)) < busy_support and float(cd.get("risk_conf", 0.0)) < busy_risk:
                        continue
                if float(cd.get("eta_s", float("inf"))) > max_eta:
                    continue
                if c.model_deterring_field_threshold is not None and _field_score(x, y) < float(c.model_deterring_field_threshold):
                    continue
                if float(cd.get("risk_conf", _risk_conf(x, y))) < float(c.model_deterring_risk_threshold):
                    continue
                if int(cd.get("persistence", 0)) < persist_min:
                    continue
                if is_cluster and int(cd.get("support", 0)) < int(c.model_deterring_min_recent_points):
                    continue
                ckey = cd.get("candidate_key", cd.get("cluster_key"))
                if repeat_window > 0.0 and is_cluster:
                    has_recent = False
                    for ev in recent_det_events:
                        dt_ev = now_t - float(ev.get("t", -1e9))
                        if dt_ev < 0.0 or dt_ev > repeat_window:
                            continue
                        if (x - float(ev.get("x", 0.0))) ** 2 + (y - float(ev.get("y", 0.0))) ** 2 <= repeat_r2:
                            has_recent = True
                            break
                    last_fire = tg._last_model_deterring_fire.get(ckey) if ckey is not None else None
                    if (not has_recent) and last_fire is not None:
                        has_recent = (now_t - float(last_fire.get("t", -1e9))) <= repeat_window
                    if has_recent:
                        prev_support = int(last_fire.get("support", 0)) if last_fire is not None else 0
                        if int(cd.get("support", 0)) <= prev_support:
                            continue
                scored = dict(cd)
                scored["predicted_deltaJ"] = pred_dj
                scored["selection_weight"] = 1.0
                scored["posterior_h1"] = float("nan")
                scored["count_excess_ratio"] = float("nan")
                eligible.append(scored)
                if best_det is None or float(scored["score"]) > float(best_det["score"]):
                    best_det = scored
            best_pat = None
            for cd in patrol_cands:
                x, y = cd["x"], cd["y"]
                if _field_score(x, y) < float(c.min_hotspot_score):
                    continue
                if any((x - float(d.get("x", 0.0))) ** 2 + (y - float(d.get("y", 0.0))) ** 2 <= overlap_r2 for d in eligible):
                    continue
                cost = float(c.cost_w_eta) * _eta_s(x, y)
                if str(c.patrol_scoring_mode) == "shared_response_reduction":
                    pdj = fast_patrol_response_reduction(
                        m, x, y, horizon_s=horizon_s, detect_range_m=shared_range,
                        detect_prob_per_step=shared_prob, detection_dwell_s=shared_dwell,
                        followup_success_prob=float(c.patrol_shared_followup_success_prob),
                        response_eta_decay_s=shared_decay, followup_speed_mps=speed,
                        mask_grid=mask_grid, weight_grid=weight_grid, available_integral_grid=avail_pat)
                    util = pdj - cost
                    met = {"utility": util, "cost_eta": cost, "score": util, "predicted_deltaJ": pdj,
                           "deltaJ_per_cost": pdj / max(cost, 1e-6)}
                else:
                    iy, ix = m.world_to_idx(x, y)
                    benefit = max(0.0, _field_score(x, y)) * max(float(weight_grid[iy, ix]), 0.0) * \
                        _time_integral_factor(m.omega, horizon_s) * da
                    util = benefit - cost
                    met = {"utility": util, "cost_eta": cost, "score": util, "predicted_deltaJ": 0.0,
                           "deltaJ_per_cost": 0.0}
                scored = dict(cd)
                scored.update(met)
                scored["selection_weight"] = 1.0
                scored["posterior_h1"] = float("nan")
                scored["count_excess_ratio"] = float("nan")
                if best_pat is None or float(scored["score"]) > float(best_pat["score"]):
                    best_pat = scored
            best = best_det
            if best is not None and best_pat is not None:
                if float(best["score"]) <= float(best_pat["score"]) + score_margin:
                    best = best_pat
            elif best is None:
                best = best_pat
            if best is not None:
                ttype = str(best["type"]).strip().lower()
                if ttype == "patrolling":
                    g = sim._jitter(rid, now_t)
                    jx = float(g.uniform(-1.0, 1.0)) * float(c.jitter_m)
                    jy = float(g.uniform(-1.0, 1.0)) * float(c.jitter_m)
                else:
                    jx = jy = 0.0
                row = {
                    "robot_id": rid, "type": ttype, "x": float(best["x"] + jx), "y": float(best["y"] + jy),
                    "time": float(now_t), "origin": str(best.get("origin", "unknown")), "mode": best.get("mode"),
                    "score": float(best["score"]), "utility": float(best.get("utility", best["score"])),
                    "support": int(best.get("support", 0)), "risk_conf": float(best.get("risk_conf", 0.0)),
                    "eta_s": float(best.get("eta_s", 0.0)), "cost_eta": float(best.get("cost_eta", 0.0)),
                    "persistence": int(best.get("persistence", 0)),
                    "predicted_deltaJ": float(best.get("predicted_deltaJ", 0.0)),
                    "predictive_stl_U": best.get("predictive_stl_U"),
                    "habituation_eta_at_plan": best.get("habituation_eta_at_plan"),
                    "stl_summary": None, "p_event": float(best.get("p_event", 0.0)),
                    "deltaJ_per_cost": float(best.get("deltaJ_per_cost", 0.0)), "llr": float(best.get("llr", 0.0)),
                    "selection_weight": float(best.get("selection_weight", 1.0)),
                    "posterior_h1": float(best.get("posterior_h1", float("nan"))),
                    "count_excess_ratio": float(best.get("count_excess_ratio", float("nan"))),
                    "predictive_action_variants": [],
                    "predictive_mode_variant_count": int(len(modes)) if ttype == "deterring" else 0,
                    "predictive_generation_best_mode": best.get("predictive_generation_best_mode"),
                }
                added = tg._add(tg._apply_predictive_lead_time_fields(row, replan_interval_s=replan_s,
                                                                       forecast_horizon_s=horizon_s))
                if sim.choice_log is not None:
                    sim.choice_log[rid] = {"type": ttype, "x": float(best["x"]), "y": float(best["y"]),
                                           "mode": best.get("mode"), "origin": str(best.get("origin", "")),
                                           "score": float(best["score"]), "added": bool(added)}
                if ttype == "deterring" and added:
                    ck = best.get("candidate_key", best.get("cluster_key"))
                    if ck is not None:
                        tg._last_model_deterring_fire[ck] = {"t": float(now_t), "support": int(best.get("support", 0))}
                tg._next_allowed[rid] = now_t + tg._cooldown
        if c.enable_predictive_patrol_tasks and c.include_fallback_patrol and not tg._has_robot_at_time(rid, now_t):
            cx, cy = tg._select_fallback_patrol_point(rid, rob)
            tg._add(tg._apply_predictive_lead_time_fields({
                "robot_id": rid, "type": "patrolling", "x": float(cx), "y": float(cy), "time": float(now_t),
                "origin": "fallback", "score": 0.0}, replan_interval_s=replan_s, forecast_horizon_s=horizon_s))


def _quantile(sorted_vals, pct):
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * (float(pct) / 100.0)
    lo = int(math.floor(pos)); hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def _zone_centroid(zone):
    from ZonePartitioner import polygon_centroid
    cx, cy = polygon_centroid(zone)
    return float(cx), float(cy)


def _snap_weight_grid(self, m):
    """Planner value weight value_weight(x_n, y_n) at the planner model's nodes."""
    key = ("w", m.nx, m.ny)
    if key not in self._zone_mask:
        wg = self.snap.planner_weight_grid
        if wg is None or wg.shape != (m.ny, m.nx):
            raise ValueError("snapshot.planner_weight_grid must match the planner model grid")
        self._zone_mask[key] = np.asarray(wg, float)
    return self._zone_mask[key]


_Sim.snap_weight_grid = _snap_weight_grid


# ---------------------------------------------------------------------------
# Public API: evaluate()
# ---------------------------------------------------------------------------
_POOL_CACHE = {}


def _pool_worker_init():
    _ds()


def _pool_ping(_x=None):
    return os.getpid()


def _run_task(args):
    """Worker task: one policy over a chunk of scenarios (trees cached per worker)."""
    key, blob, seed, scenarios, candidate, kw = args
    kw = dict(kw)
    slim = bool(kw.pop("slim", False))
    ent = _POOL_CACHE.get(key)
    if ent is None:
        _POOL_CACHE.clear()
        if isinstance(blob, str):          # path of a pickled snapshot (sent once per worker)
            with open(blob, "rb") as fh:
                blob = fh.read()
        ent = (pickle.loads(blob), {})
        _POOL_CACHE[key] = ent
    snap, trees = ent
    out = []
    for s in scenarios:
        if s not in trees:
            trees[s] = _sample_scenario_tree(snap, seed, s)
        r = _Sim(snap, trees[s], candidate, scenario=s, **kw).run()
        out.append(_slim_result(r) if slim else r)
    return out


def _slim_result(r: dict) -> dict:
    """Keep only what the decision procedure reads (J, pending completions, obligations).

    Full results carry per-task records for every (policy, scenario); at overload one
    decision returned about 106 MB of pickles that expanded to about 2 GB in the main
    process (2026-10-18).  The decision is unchanged: service_feasibility reads only
    completed_t and deadline_t, obligation_satisfaction reads satisfied_t, U reads J.
    """
    return {
        "J": r["J"], "J_bg": r["J_bg"], "J_exc": r["J_exc"], "J_sched": r["J_sched"],
        "counted_exposure": r["counted_exposure"],
        "pending_completion": {k: {"completed_t": v["completed_t"], "deadline_t": v["deadline_t"]}
                               for k, v in r["pending_completion"].items()},
        "detections": r["detections"], "reactive_completed": r["reactive_completed"],
        "predictive_completed": r["predictive_completed"], "patrol_completed": r["patrol_completed"],
        "candidate_completed_t": r["candidate_completed_t"],
        "obligations": r["obligations"],
        # decisions 26, 13, 30, 8: candidate q_hat and arrival at application, terminal summary,
        # one-intervention J (None unless requested)
        "candidate_arrival_t": r["candidate_arrival_t"],
        "candidate_eta_planner": r["candidate_eta_planner"],
        "candidate_eta_world": r["candidate_eta_world"],
        "terminal_summary": r["terminal_summary"],
        "J_one": r["J_one"],
    }


# Hard cap on events per scenario tree (overload trees are about 7e4 events).
MAX_SCENARIO_EVENTS = int(os.environ.get("ROLLOUT_MAX_SCENARIO_EVENTS", "2000000"))


class RolloutPool:
    """Persistent worker processes, reused across decisions to avoid start-up cost.

    Worker start-up (process spawn plus importing DeterrentSystem) costs about
    1-2 s per worker on Windows; a pool created once per simulation run makes
    each evaluate() call pay only for the rollouts themselves.
    """

    _BLAS_ENV = ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS")

    # Memory guard (added 2026-10-16 after a 31-worker pool exhausted 32 GB of RAM):
    # the pool is sized from AVAILABLE memory, keeping a reserve free for the user,
    # and evaluate() shrinks it before a call if available memory falls below the
    # reserve.  Results do not depend on the worker count (parallel equals serial).
    WORKER_MEM_GB = float(os.environ.get("ROLLOUT_WORKER_MEM_GB", "1.5"))
    RESERVE_FRACTION = float(os.environ.get("ROLLOUT_RESERVE_FRACTION", "0.30"))
    MAX_WORKERS = int(os.environ.get("ROLLOUT_MAX_WORKERS", "12"))

    @classmethod
    def reserve_bytes(cls) -> float:
        import psutil
        return cls.RESERVE_FRACTION * psutil.virtual_memory().total

    @classmethod
    def memory_capped_workers(cls, requested: Optional[int]) -> int:
        import psutil
        want = int(requested or max(1, (os.cpu_count() or 2) - 1))
        want = min(want, cls.MAX_WORKERS)
        spare = psutil.virtual_memory().available - cls.reserve_bytes()
        cap = int(spare // (cls.WORKER_MEM_GB * 1024 ** 3))
        if cap < 1:
            raise MemoryError(
                f"rollout pool: only {psutil.virtual_memory().available / 1024**3:.1f} GB available, "
                f"below the {cls.reserve_bytes() / 1024**3:.1f} GB reserve; refusing to start workers")
        return max(1, min(want, cap))

    def __init__(self, n_workers: Optional[int] = None):
        self.requested = n_workers
        self.n_workers = self.memory_capped_workers(n_workers)
        self._spawn()

    def ensure_memory(self):
        """Shrink the pool (or stop) if available memory has fallen below the reserve."""
        import psutil
        if psutil.virtual_memory().available >= self.reserve_bytes():
            return
        self.close()
        while self.n_workers > 1 and psutil.virtual_memory().available < self.reserve_bytes():
            self.n_workers = max(1, self.n_workers // 2)
        if psutil.virtual_memory().available < self.reserve_bytes():
            raise MemoryError("rollout pool: available memory below reserve even with the pool closed")
        self._spawn()

    def _spawn(self):
        # One BLAS thread per worker: the workers already use every core, and a
        # multi-threaded BLAS on the small per-step products only oversubscribes
        # (measured: S_grid 1.8 ms -> 0.05 ms per call).  Spawned workers inherit
        # the environment at start-up, so it is set around the spawn only.
        saved = {k: os.environ.get(k) for k in self._BLAS_ENV}
        for k in self._BLAS_ENV:
            os.environ[k] = "1"
        try:
            self.ex = ProcessPoolExecutor(max_workers=self.n_workers, initializer=_pool_worker_init)
            list(self.ex.map(_pool_ping, range(self.n_workers * 2)))   # spawn and import now
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def close(self):
        self.ex.shutdown(wait=True)

    def kill(self):
        """Terminate worker processes immediately (memory emergency)."""
        procs = list(getattr(self.ex, "_processes", {}).values())
        for proc in procs:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            self.ex.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def run_policy(snap: RolloutSnapshot, candidate: Candidate, *, n_scenarios: int = 16, seed: int = 0,
               reactive_deadline_s: float = 90.0, planner_model_advance: str = "per_step",
               trees: Optional[list] = None, one_intervention: bool = False) -> list:
    """Simulate one policy (NOOP = pi_0) over all scenarios in this process."""
    if trees is None:
        trees = [_sample_scenario_tree(snap, seed, s) for s in range(n_scenarios)]
    return [
        _Sim(snap, trees[s], candidate, scenario=s, reactive_deadline_s=reactive_deadline_s,
             planner_model_advance=planner_model_advance, one_intervention=one_intervention).run()
        for s in range(n_scenarios)
    ]


@dataclass
class EvaluationResult:
    policies: list            # [NOOP, *candidates]
    per_scenario: list        # per policy: list of per-scenario result dicts
    J: np.ndarray             # (n_policies, n_scenarios)
    J_mean: np.ndarray
    J_se: np.ndarray
    U: np.ndarray             # (n_candidates, n_scenarios), J(pi_0) - J(pi_a)
    U_mean: np.ndarray
    U_se: np.ndarray
    wall_time_s: float
    n_scenarios: int
    # one-intervention counterfactual (evaluate(..., one_intervention=True)); else None
    J_one: Optional[np.ndarray] = None
    U_one: Optional[np.ndarray] = None
    U_one_mean: Optional[np.ndarray] = None
    U_one_se: Optional[np.ndarray] = None


class EvaluationTimeout(RuntimeError):
    """Raised by evaluate() when the wall-clock deadline passes before every rollout finished."""

    def __init__(self, elapsed_s: float):
        super().__init__(f"rollout evaluation exceeded its deadline after {elapsed_s:.3f} s")
        self.elapsed_s = float(elapsed_s)


def evaluate(snapshot: RolloutSnapshot, candidates: Sequence[Candidate], n_scenarios: int = 16, seed: int = 0,
             *, n_workers: Optional[int] = None, reactive_deadline_s: float = 90.0,
             planner_model_advance: str = "per_step", pool: Optional["RolloutPool"] = None,
             scenario_chunk: int = 8, deadline: Optional[float] = None, slim: bool = False,
             one_intervention: bool = False) -> EvaluationResult:
    """Evaluate pi_0 (B5) and every candidate continuation with common random numbers.

    Returns per-scenario J_H, pending-task completion times (inf if not
    completed within H), new reactive tasks and their completions,
    interventions executed and terminal state, plus means and standard errors.
    U standard errors are paired across scenarios.  ``deadline`` is an absolute
    ``time.perf_counter()`` value; if it passes first, unfinished rollouts are
    cancelled and :class:`EvaluationTimeout` is raised.
    """
    t_start = time.perf_counter()
    snap = snapshot
    if snap.start_stage not in ("truth", "replan"):
        raise ValueError(f"unknown start_stage {snap.start_stage!r}")
    for p in snap.pending_reactive:
        if not math.isfinite(p.deadline_t):
            p.deadline_t = p.created_t + float(reactive_deadline_s)
    policies = [NOOP] + list(candidates)
    kw = {"reactive_deadline_s": float(reactive_deadline_s), "planner_model_advance": str(planner_model_advance)}
    if one_intervention:
        kw["one_intervention"] = True
    if slim:
        kw["slim"] = True
    if pool is None and n_workers is None:
        n_workers = min(len(policies) * 2, max(1, (os.cpu_count() or 2) - 1))
    if pool is None and n_workers <= 1:
        trees = [_sample_scenario_tree(snap, seed, s) for s in range(n_scenarios)]
        results = []
        for pol in policies:
            if deadline is not None and time.perf_counter() > float(deadline):
                raise EvaluationTimeout(time.perf_counter() - t_start)
            results.append(run_policy(snap, pol, n_scenarios=n_scenarios, seed=seed, trees=trees, **kw))
    else:
        own = pool is None
        if own:
            pool = RolloutPool(n_workers)
        blob_path = None
        try:
            blob = pickle.dumps(snap, protocol=pickle.HIGHEST_PROTOCOL)
            pool.ensure_memory()
            key = (uuid.uuid4().hex, int(seed))
            if scenario_chunk is None or int(scenario_chunk) <= 0:
                # adaptive: about four tasks per worker; the snapshot travels by file,
                # once per worker, so small chunks cost no extra transfer
                chunk = max(1, min(n_scenarios, math.ceil(len(policies) * n_scenarios / (4 * pool.n_workers))))
                import tempfile
                fd, blob_path = tempfile.mkstemp(prefix="rollout_snap_", suffix=".pkl")
                with os.fdopen(fd, "wb") as fh:
                    fh.write(blob)
                blob = blob_path
            else:
                chunk = max(1, int(scenario_chunk))
            chunks = [list(range(a, min(a + chunk, n_scenarios))) for a in range(0, n_scenarios, chunk)]
            tasks = [(key, blob, int(seed), ch, pol, kw) for pol in policies for ch in chunks]
            # Poll memory while the workers run; if available memory falls below half
            # the reserve, stop the workers and raise instead of exhausting the machine.
            import psutil
            critical = 0.5 * pool.reserve_bytes()
            futs = [pool.ex.submit(_run_task, tk) for tk in tasks]
            not_done = set(futs)
            while not_done:
                if deadline is not None and time.perf_counter() >= float(deadline):
                    for f in not_done:
                        f.cancel()
                    raise EvaluationTimeout(time.perf_counter() - t_start)
                if psutil.virtual_memory().available < critical:
                    for f in not_done:
                        f.cancel()
                    pool.kill()
                    raise MemoryError("rollout evaluation stopped: available memory fell below "
                                      f"{critical / 1024**3:.1f} GB")
                _, not_done = wait(not_done, timeout=0.5)
            flat = [f.result() for f in futs]
        finally:
            if own:
                pool.close()
            if blob_path is not None:
                try:
                    os.remove(blob_path)
                except OSError:
                    pass
        results = []
        i = 0
        for _pol in policies:
            res = []
            for _ch in chunks:
                res.extend(flat[i])
                i += 1
            results.append(res)
    J = np.array([[r["J"] for r in res] for res in results])
    sq = math.sqrt(max(n_scenarios, 1))
    J_mean = J.mean(axis=1)
    J_se = J.std(axis=1, ddof=1) / sq if n_scenarios > 1 else np.zeros(len(policies))
    U = J[0][None, :] - J[1:]
    U_mean = U.mean(axis=1) if U.size else np.zeros(0)
    U_se = (U.std(axis=1, ddof=1) / sq) if (U.size and n_scenarios > 1) else np.zeros(U.shape[0])
    one = {}
    if one_intervention:
        J1 = np.array([[r["J_one"] for r in res] for res in results], float)
        U1 = J1[0][None, :] - J1[1:]
        one = {"J_one": J1, "U_one": U1,
               "U_one_mean": U1.mean(axis=1) if U1.size else np.zeros(0),
               "U_one_se": (U1.std(axis=1, ddof=1) / sq) if (U1.size and n_scenarios > 1) else np.zeros(U1.shape[0])}
    return EvaluationResult(policies=policies, per_scenario=results, J=J, J_mean=J_mean, J_se=J_se,
                            U=U, U_mean=U_mean, U_se=U_se, wall_time_s=time.perf_counter() - t_start,
                            n_scenarios=n_scenarios, **one)


# ---------------------------------------------------------------------------
# Snapshot construction from a running simulator (generator frame locals)
# ---------------------------------------------------------------------------
def _pending_reactive_from(active_tasks, taskgen_rows_buffer, key_fn, is_direct, deadline_s):
    out = []
    seen = set()
    for tr in active_tasks:
        if str(tr.get("state", "")) != "active" or not is_direct(tr):
            continue
        for k in (tr.get("_member_task_keys") or [key_fn(tr)]):
            k = tuple(k)
            if k in seen:
                continue
            seen.add(k)
            out.append(PendingReactive(key=k, x=float(k[2]), y=float(k[3]), created_t=float(k[4]),
                                       deadline_t=float(k[4]) + deadline_s,
                                       assigned_robot=tr.get("assigned_primary"), active_task_id=tr.get("id")))
    for row in taskgen_rows_buffer:
        if not is_direct(row):
            continue
        k = tuple(key_fn(row))
        if k in seen:
            continue
        seen.add(k)
        out.append(PendingReactive(key=k, x=float(row["x"]), y=float(row["y"]), created_t=float(row["time"]),
                                   deadline_t=float(row["time"]) + deadline_s, assigned_robot=None,
                                   active_task_id=None))
    return out


_WEIGHT_CACHE = {}


def snapshot_from_sim_locals(L: dict, *, horizon_s: float = 300.0, full_observability: bool = True,
                             reactive_deadline_s: float = 90.0, n_sub_weight: int = 8,
                             region_mask: Optional[np.ndarray] = None) -> RolloutSnapshot:
    """Build a snapshot from run_simulation_frames_persistent's suspended frame.

    ``L`` is ``generator.gi_frame.f_locals`` after a ``next()``; the state is
    the end of step ``L['t']`` and the rollout starts at the truth stage of the
    next step.  With ``full_observability`` the planner forecast is set equal
    to the truth (truth parameters, truth habituation, the scheduled truth
    queue); otherwise it is built from the planner's own knowledge (detected
    events, planner habituation and the frozen calibration's SESTPP alpha).
    """
    cfg = B5Config.from_sim_locals(L)
    W, H, NX, NY = float(L["W"]), float(L["H"]), int(L["NX"]), int(L["NY"])
    t0 = float(L["t"])
    vw = L["value_weight"]
    xs = np.linspace(0.0, W, NX)
    ys = np.linspace(0.0, H, NY)
    ck2 = ("exact", id(vw), W, H, NX, NY)
    if ck2 not in _WEIGHT_CACHE:
        _WEIGHT_CACHE[ck2] = (np.array([[float(vw(float(x), float(y))) for x in xs] for y in ys]), vw)
    w_node_exact = _WEIGHT_CACHE[ck2][0]
    ck = (id(vw), W, H, NX, NY, int(n_sub_weight))
    if ck not in _WEIGHT_CACHE:
        _WEIGHT_CACHE[ck] = (cell_average_weight(vw, W, H, NX, NY, n_sub=n_sub_weight), vw)
    w_bar = _WEIGHT_CACHE[ck][0]
    W_grid = L["w_shape"][4]
    area = W * H
    mu_true = float(L["_mu_true_at"](t0 + 1.0))
    total = mu_true * float(np.mean(W_grid)) * area
    bg_rate = total * W_grid / float(W_grid.sum())
    deterring_modes = copy.deepcopy(L["deterring_modes"])
    world_cues = {"direct_detection": CueParams(float(L["beta_true"]), float(L["sigma_true"]), float(L["omega_true"]))}
    for mode, p in deterring_modes.items():
        if bool(L.get("use_mode_dependent_truth_suppression", True)):
            world_cues[str(mode)] = CueParams(float(p.get("beta", L["beta_true"])), float(p.get("sigma", L["sigma_true"])),
                                              float(p.get("omega", L["omega_true"])))
        else:
            world_cues[str(mode)] = world_cues["direct_detection"]
    if full_observability:
        tq = list(L["truth_queue"])
        sched = np.array([[x, y, te, float(vw(x, y))] for (x, y, te) in tq]) if tq else np.zeros((0, 4))
        forecast = IntensityForecast(form="consistent", bg_node_rate=bg_rate, alpha=float(L["alpha_true"]),
                                     sigma=float(L["sigma_true"]), omega=float(L["omega_true"]),
                                     scheduled_candidates=sched)
        hab = L["truth_hab"].copy()
    else:
        dets = []
        for rid, rob in L["robots"].items():
            dets.extend([(x, y, te) for (x, y, te) in rob.recent_events])
        ex = np.array(sorted(set(dets)), float).reshape(-1, 3)
        forecast = IntensityForecast(form="consistent", bg_node_rate=bg_rate, alpha=float(L["alpha_true"]),
                                     sigma=float(L["sigma_true"]), omega=float(L["omega_true"]),
                                     excitation_terms=ex)
        hab = L["planner_hab"].copy()
    robots_def = L["robots_def"]
    id_to_cell = L["id_to_cell"]
    robots = []
    for r in robots_def:
        rid = r["id"]
        robots.append(RobotState(rid=rid, pose=tuple(L["pose"][rid]), goal=(None if L["goal"][rid] is None else tuple(L["goal"][rid])),
                                 loiter_until=float(L["loiter_until"][rid]), profile=copy.deepcopy(L["profiles"][rid]),
                                 planner=copy.deepcopy(L["robots"][rid]), zone_polygon=list(id_to_cell.get(rid, []))))
    taskgen = _prune_taskgen(L["taskgen"], t0)
    tau = float(L["tau_service_s"])

    def key_fn(task):
        return (task_action_kind(task, deterring_modes, tau), task_action_name(task, deterring_modes, tau),
                round(float(task.get("x", float("nan"))), 2), round(float(task.get("y", float("nan"))), 2),
                round(float(task.get("time", float("nan"))), 0))

    def is_direct(task):
        return task_action_kind(task, deterring_modes, tau) == "deterring" and \
            task_action_name(task, deterring_modes, tau) == "direct_detection"

    active = copy.deepcopy(L["active_tasks"])
    completed = [copy.deepcopy(tr) for tr in L["completed_tasks"] if float(tr.get("t_done", -1e18)) >= t0 - 600.0]
    seen = {key_fn(tr) for tr in active} | {key_fn(tr) for tr in completed} | set(L["consumed_task_keys"])
    buffer_rows = [r for r in taskgen.rows()[-200:] if key_fn(r) not in seen]
    pending = _pending_reactive_from(active, buffer_rows, key_fn, is_direct, reactive_deadline_s)
    mask = np.ones((NY, NX), bool) if region_mask is None else np.asarray(region_mask, bool)
    snap = RolloutSnapshot(
        t0=t0, horizon_s=float(horizon_s), nx=NX, ny=NY, W=W, H=H, w_node=w_bar, w_bg_node=w_bar,
        region_mask=mask, forecast=forecast, world_cues=world_cues, deterring_modes=deterring_modes,
        habituation=hab, hab_cell_polys=[list(p) for p in L["cells"]], mode_to_id=dict(L["mode_to_id"]),
        robots=robots, active_tasks=active, completed_tasks=completed,
        consumed_task_keys=set(L["consumed_task_keys"]), taskgen=taskgen,
        recent_deterrences=copy.deepcopy(list(L["recent_deterrences"])),
        model_deterring_by_robot={rid: list(q) for rid, q in L["model_deterring_by_robot"].items()},
        next_tid=int(L["next_tid"]), last_replan=float(L["last_replan"]),
        bus_last_intervention_key_t=dict(L["bus"]._last_intervention_key_t), cfg=cfg,
        pending_reactive=pending, planner_weight_grid=w_node_exact,
    )
    return snap


# ---------------------------------------------------------------------------
# Decision-time snapshots for the plan procedure (start_stage="replan")
# ---------------------------------------------------------------------------
class StepProfile:
    """Picklable background time profile m(t) = factor for t >= t_switch, else 1 (truth mu step)."""

    def __init__(self, t_switch: float, factor: float):
        self.t_switch = float(t_switch)
        self.factor = float(factor)

    def __call__(self, t: float) -> float:
        return self.factor if float(t) >= self.t_switch else 1.0


def _profile_max_over_steps(profile, t0: float, n_steps: int, dt: float) -> float:
    """Exact maximum of m(t) over the step times the scenario tree samples (t0+dt .. t0+n dt)."""
    if profile is None or n_steps <= 0:
        return 1.0
    return max(float(_profile_value(profile, t0 + k * dt)) for k in range(1, n_steps + 1))


def _node_grid(W, H, NX, NY):
    xs = np.linspace(0.0, W, NX)
    ys = np.linspace(0.0, H, NY)
    XX, YY = np.meshgrid(xs, ys, indexing="xy")
    return xs, ys, XX, YY


def _zone_owner_grid(L, XX, YY):
    """Index (robots_def order) of the robot whose zone contains each node, first match, or -1.

    Same first-match rule as the simulator's owner of a truth event
    (DeterrentSystem._process_truth_event loops robots_def and takes the first zone).
    """
    owner = np.full(XX.shape, -1, np.int64)
    for i, r in enumerate(L["robots_def"]):
        zone = L["id_to_cell"].get(r["id"], [])
        if not zone:
            continue
        ins = points_in_polygon(XX, YY, zone) & (owner < 0)
        owner[ins] = i
    return owner


def _weight_grids(L, W, H, NX, NY, n_sub_weight):
    vw = L["value_weight"]
    xs = np.linspace(0.0, W, NX)
    ys = np.linspace(0.0, H, NY)
    ck2 = ("exact", id(vw), W, H, NX, NY)
    if ck2 not in _WEIGHT_CACHE:
        _WEIGHT_CACHE[ck2] = (np.array([[float(vw(float(x), float(y))) for x in xs] for y in ys]), vw)
    ck = (id(vw), W, H, NX, NY, int(n_sub_weight))
    if ck not in _WEIGHT_CACHE:
        _WEIGHT_CACHE[ck] = (cell_average_weight(vw, W, H, NX, NY, n_sub=n_sub_weight), vw)
    return _WEIGHT_CACHE[ck2][0], _WEIGHT_CACHE[ck][0]


def planner_world_cues(L) -> dict:
    """Planner cue suppression parameters: the planner mirror of the truth mapping.

    Same mapping as DeterrentSystem._resolve_planner_deterrence_event_params
    (DeterrentSystem.py:458-487), used for the consistent estimator's own
    suppression stamps (DeterrentSystem.py:7126-7134).
    """
    ds = _ds()
    kw = dict(planner_deterring_modes=L.get("planner_deterring_modes"),
              use_mode_dependent_truth_suppression=bool(L.get("use_mode_dependent_truth_suppression", True)),
              planner_beta=float(L["planner_beta"]), planner_sigma=float(L["planner_sigma"]),
              planner_omega=float(L["planner_omega"]))
    out = {}
    _, b, s, o = ds._resolve_planner_deterrence_event_params("direct_detection", {}, **kw)
    out["direct_detection"] = CueParams(float(b), float(s), float(o))
    for mode, p in L["deterring_modes"].items():
        _, b, s, o = ds._resolve_planner_deterrence_event_params(str(mode), dict(p), **kw)
        out[str(mode)] = CueParams(float(b), float(s), float(o))
    return out


def truth_world_cues(L) -> dict:
    """Truth cue suppression parameters (DeterrentSystem._resolve_truth_deterrence_event_params)."""
    out = {"direct_detection": CueParams(float(L["beta_true"]), float(L["sigma_true"]), float(L["omega_true"]))}
    for mode, p in L["deterring_modes"].items():
        if bool(L.get("use_mode_dependent_truth_suppression", True)) and p:
            out[str(mode)] = CueParams(float(p.get("beta", L["beta_true"])), float(p.get("sigma", L["sigma_true"])),
                                       float(p.get("omega", L["omega_true"])))
        else:
            out[str(mode)] = out["direct_detection"]
    return out


def planner_forecast_from_sim_locals(L, *, t0: float, horizon_s: float):
    """The fleet's planner belief of the bird process (no truth state).

    Built only from the robots' estimators:
      consistent: background mu_hat of each node's zone owner times the
        planner value map times the node area (the estimator's own density
        convention, SESTPP.ConsistentOnlineSESTPP: densities integrate with
        dA), the planner time multiplier, the planner (alpha, sigma, omega),
        the union of every robot's detected excitation parents (each detection
        is recorded by its zone owner, so the union is every detection the
        fleet made) and the union of every robot's suppression terms
        (amplitude q_hat * beta, planner sigma/omega), deduplicated by action id.
      legacy: per node the zone owner's additive grids (mu, trigger mass and
        per-mode inhibition channels) with its alpha_in/alpha_inhib/sigma/omega.
    Returns (IntensityForecast, world_suppression list or None).
    """
    W, H, NX, NY = float(L["W"]), float(L["H"]), int(L["NX"]), int(L["NY"])
    xs, ys, XX, YY = _node_grid(W, H, NX, NY)
    owner = _zone_owner_grid(L, XX, YY)
    rdef = L["robots_def"]
    models = [L["robots"][r["id"]].m for r in rdef]
    mode = str(L.get("estimator_mode", "legacy")).strip().lower()
    dt = float(L["dt"])
    n_steps = int(round(float(horizon_s) / dt))
    if mode == "consistent":
        m0 = models[0]
        for m in models[1:]:
            if (m.alpha, m.sigma, m.omega) != (m0.alpha, m0.sigma, m0.omega):
                raise ValueError("planner models disagree on (alpha, sigma, omega)")
        mu_rates = np.array([float(m.mu_rate) for m in models])
        mu_node = np.where(owner >= 0, mu_rates[np.maximum(owner, 0)], float(np.mean(mu_rates)))
        bg = mu_node * np.asarray(m0.value_map, float) * float(m0.dA)
        prof = m0.time_multiplier_fn
        parents = {}
        for m in models:
            for (ex, ey, et, ew) in m.excitation_events:
                if abs(float(ew) - 1.0) > 1e-12:
                    raise ValueError("consistent planner excitation events must have weight 1")
                parents[(float(ex), float(ey), float(et))] = True
        ex = np.array(sorted(parents), float).reshape(-1, 3)
        terms = {}
        for m in models:
            for term in m.suppression_terms:
                k = ("id", int(term.action_id)) if term.action_id is not None else \
                    ("xyt", term.x, term.y, term.tau, term.mode)
                terms[k] = term
        store = [{"x": float(tm.x), "y": float(tm.y), "t": float(tm.tau), "eta": 1.0, "beta": float(tm.amplitude),
                  "sigma": float(tm.sigma), "omega": float(tm.omega), "mode": str(tm.mode),
                  "action_id": tm.action_id} for tm in sorted(terms.values(), key=lambda q: (q.tau, str(q.action_id)))]
        fc = IntensityForecast(form="consistent", bg_node_rate=bg, alpha=float(m0.alpha), sigma=float(m0.sigma),
                               omega=float(m0.omega), bg_time_profile=prof,
                               bg_time_profile_max=_profile_max_over_steps(prof, t0, n_steps, dt),
                               excitation_terms=ex)
        return fc, store
    # legacy additive estimator
    m0 = models[0]

    def _by_owner(grids):
        st = np.stack([np.asarray(g, float) for g in grids])
        picked = np.take_along_axis(st, np.maximum(owner, 0)[None], axis=0)[0]
        return np.where(owner >= 0, picked, st.mean(axis=0))   # unowned nodes: fleet mean

    mu = _by_owner([m.mu for m in models])
    trig = _by_owner([m.trigger_mass for m in models])
    chans = {}
    keys = sorted({k for m in models for k in m.inhib_channels})
    for key in keys:
        grids = [np.asarray(m.inhib_channels.get(key, np.zeros((NY, NX))), float) for m in models]
        om = [float(m.inhib_channel_omegas.get(key, m.omega_inhib)) for m in models if key in m.inhib_channels]
        chans[key] = (_by_owner(grids), float(om[0]))
    fc = IntensityForecast(form="legacy", bg_node_rate=mu, sigma=float(m0.sigma), omega=float(m0.omega),
                           legacy_trigger_mass=trig, legacy_inhib_channels=chans,
                           legacy_alpha_in=float(m0.alpha_in), legacy_alpha_inhib=float(m0.alpha_inhib))
    return fc, None


def truth_forecast_from_sim_locals(L, *, t0: float, horizon_s: float):
    """The simulator truth as a scenario world (oracle / full observability).

    Truth background (DeterrentSystem._coupled_truth_step / run_truth_generation_stage:
    Poisson(mu w_mean area dt) per step, node by value map), the truth mu step as a
    time profile, the truth excitation kernel (truth_excitation_sigma/omega_eff), the
    already scheduled truth offspring queue, and the truth suppression store with the
    truth effectiveness at application.
    """
    W, H = float(L["W"]), float(L["H"])
    vw = L["value_weight"]
    W_grid = L["w_shape"][4]
    area = W * H
    mu_true = float(L["mu_true"])
    bg_rate = mu_true * float(np.mean(W_grid)) * area * W_grid / float(W_grid.sum())
    prof = None
    if L.get("mu_step_time_s") is not None:
        prof = StepProfile(float(L["warmup_s"]) + float(L["mu_step_time_s"]), float(L["mu_step_factor"]))
    dt = float(L["dt"])
    n_steps = int(round(float(horizon_s) / dt))
    tq = list(L["truth_queue"])
    sched = (np.array([[float(ev[0]), float(ev[1]), float(ev[2]), float(vw(float(ev[0]), float(ev[1])))]
                       for ev in tq]) if tq else np.zeros((0, 4)))
    fc = IntensityForecast(form="consistent", bg_node_rate=bg_rate, alpha=float(L["alpha_true"]),
                           sigma=float(L["truth_excitation_sigma_eff"]), omega=float(L["truth_excitation_omega_eff"]),
                           bg_time_profile=prof, bg_time_profile_max=_profile_max_over_steps(prof, t0, n_steps, dt),
                           scheduled_candidates=sched)
    store = [dict(e) for e in L["truth_deterrence_store"]]
    return fc, store


def decision_snapshot_from_sim_locals(L: dict, *, horizon_s: float = 300.0, reactive_deadline_s: float = 90.0,
                                      oracle: bool = False, n_sub_weight: int = 8) -> RolloutSnapshot:
    """Snapshot at the simulator's replan point (Stage 3 of step t), start_stage="replan".

    ``L`` is the simulator's ``locals()`` inside Stage 3 (truth and expiry stages of
    step t done, nothing of the replan done).  The policy side (robots and their
    estimators, tasks, TaskGenerator state, planner habituation, commitments) is
    always planner information.  With ``oracle=False`` the world is the planner's
    belief (planner_forecast_from_sim_locals); with ``oracle=True`` it is the truth
    (truth_forecast_from_sim_locals, truth habituation as world habituation).
    """
    cfg = B5Config.from_sim_locals(L)
    W, H, NX, NY = float(L["W"]), float(L["H"]), int(L["NX"]), int(L["NY"])
    t0 = float(L["t"])
    w_node_exact, w_bar = _weight_grids(L, W, H, NX, NY, n_sub_weight)
    deterring_modes = copy.deepcopy(L["deterring_modes"])
    if oracle:
        forecast, store = truth_forecast_from_sim_locals(L, t0=t0, horizon_s=horizon_s)
        world_cues = truth_world_cues(L)
        world_hab = L["truth_hab"].copy()
        world_hab_model = str(L["truth_habituation_update_model"])
    else:
        forecast, store = planner_forecast_from_sim_locals(L, t0=t0, horizon_s=horizon_s)
        world_cues = planner_world_cues(L)
        world_hab = None
        world_hab_model = None
    robots_def = L["robots_def"]
    id_to_cell = L["id_to_cell"]
    robots = []
    for r in robots_def:
        rid = r["id"]
        robots.append(RobotState(rid=rid, pose=tuple(L["pose"][rid]),
                                 goal=(None if L["goal"][rid] is None else tuple(L["goal"][rid])),
                                 loiter_until=float(L["loiter_until"][rid]), profile=copy.deepcopy(L["profiles"][rid]),
                                 planner=copy.deepcopy(L["robots"][rid]), zone_polygon=list(id_to_cell.get(rid, []))))
    taskgen = _prune_taskgen(L["taskgen"], t0)
    tau = float(L["tau_service_s"])

    def key_fn(task):
        return (task_action_kind(task, deterring_modes, tau), task_action_name(task, deterring_modes, tau),
                round(float(task.get("x", float("nan"))), 2), round(float(task.get("y", float("nan"))), 2),
                round(float(task.get("time", float("nan"))), 0))

    def is_direct(task):
        return task_action_kind(task, deterring_modes, tau) == "deterring" and \
            task_action_name(task, deterring_modes, tau) == "direct_detection"

    active = copy.deepcopy(L["active_tasks"])
    # Completed tasks feed only the dispatch buffer dedupe (every dispatched key is also in
    # consumed_task_keys) and the direct-conflict window (120 s), so t_done >= t0 - 600 is exact.
    completed = [copy.deepcopy(tr) for tr in L["completed_tasks"] if float(tr.get("t_done", -1e18)) >= t0 - 600.0]
    seen = {key_fn(tr) for tr in active} | {key_fn(tr) for tr in completed} | set(L["consumed_task_keys"])
    buffer_rows = [r for r in taskgen.rows()[-200:] if key_fn(r) not in seen]
    pending = _pending_reactive_from(active, buffer_rows, key_fn, is_direct, reactive_deadline_s)
    # B5-facing record of the fleet's own completed actions (pruning / repeat-block read x, y, t):
    # keep the planner-known fields only (the simulator's entries also carry the truth eta).
    keep = ("x", "y", "t", "mode", "source", "action_id", "habituation_mode")
    recent = [{k: e[k] for k in keep if k in e} for e in L["recent_deterrences"]]
    regions = None
    if cfg.estimator_mode == "consistent":
        regions = {r["id"]: [list(p) for p in (L["_consistent_region_polys"](r["id"]) or [])] for r in robots_def}
    snap = RolloutSnapshot(
        t0=t0, horizon_s=float(horizon_s), nx=NX, ny=NY, W=W, H=H, w_node=w_bar, w_bg_node=w_bar,
        region_mask=np.ones((NY, NX), bool), forecast=forecast, world_cues=world_cues,
        deterring_modes=deterring_modes, habituation=L["planner_hab"].copy(),
        hab_cell_polys=[list(p) for p in L["cells"]], mode_to_id=dict(L["mode_to_id"]),
        robots=robots, active_tasks=active, completed_tasks=completed,
        consumed_task_keys=set(L["consumed_task_keys"]), taskgen=taskgen, recent_deterrences=recent,
        model_deterring_by_robot={rid: list(q) for rid, q in L["model_deterring_by_robot"].items()},
        next_tid=int(L["next_tid"]), last_replan=float(L["last_replan"]),
        bus_last_intervention_key_t=dict(L["bus"]._last_intervention_key_t), cfg=cfg,
        pending_reactive=pending, planner_weight_grid=w_node_exact, start_stage="replan",
        robot_region_polys=regions, world_suppression=store, world_habituation=world_hab,
        world_habituation_update_model=world_hab_model,
    )
    return snap


def restrict_snapshot_to_information(snap: RolloutSnapshot, *, effectiveness: Optional[HabituationField] = None,
                                     received_interventions: Optional[list] = None,
                                     known_task_ids: Optional[set] = None,
                                     known_pending_keys: Optional[set] = None) -> RolloutSnapshot:
    """Decision snapshot restricted to the information that reached the decision's robots
    (user decision 17: per-robot information sets; instant full sharing is the default).

    INTEGRATION POINT (agent C, planner_hab_mode="per_robot"): the caller passes, for
    the robots involved in a decision,
      effectiveness           the planner effectiveness field reconstructed by those
                              robots from the interventions they received
                              (HabituationField; replaces snap.habituation, which the
                              policy and the planner world both read);
      received_interventions  the intervention records those robots received (dicts
                              with at least x, y, t, mode, action_id); they replace the
                              B5-facing recent_deterrences, and in the consistent form
                              the world suppression store keeps only the received
                              action ids;
      known_task_ids          ids of the active task rows those robots know;
      known_pending_keys      buffer keys of the pending reactive tasks they know.
    Any argument left None keeps the shared (full-information) value, so calling this
    with every argument None returns an equivalent copy: shared mode is unchanged.
    The legacy forecast world (per-owner robot estimator grids) is left as built by
    planner_forecast_from_sim_locals.
    """
    out = copy.copy(snap)
    out.__dict__.pop("_sim_template", None)
    if effectiveness is not None:
        out.habituation = effectiveness.copy()
    if received_interventions is not None:
        keep = ("x", "y", "t", "mode", "source", "action_id", "habituation_mode")
        out.recent_deterrences = [{k: e[k] for k in keep if k in e} for e in received_interventions]
        if snap.world_suppression is not None:
            ids = {e.get("action_id") for e in received_interventions if e.get("action_id") is not None}
            out.world_suppression = [dict(e) for e in snap.world_suppression
                                     if e.get("action_id") is None or e.get("action_id") in ids]
    if known_task_ids is not None:
        out.active_tasks = [copy.deepcopy(tr) for tr in snap.active_tasks if tr.get("id") in known_task_ids]
    if known_pending_keys is not None:
        out.pending_reactive = [p for p in snap.pending_reactive if tuple(p.key) in known_pending_keys]
    return out


def generation_details(snap: RolloutSnapshot) -> dict:
    """B5's generation at t0 per robot: seeds, cue modes, the B5 generation score of
    every (seed, cue) pair (TaskGenerator._det_metrics score, the quantity B5 ranks
    by) and B5's own generated predictive row (type, x, y, mode, before patrol
    jitter; None when B5 generates nothing for the robot at t0, e.g. cooldown).
    Nothing of the snapshot is mutated."""
    tree = _ScenarioTree(t=np.zeros(0), x=np.zeros(0), y=np.zeros(0), node=np.zeros(0, np.int64),
                         parent=np.zeros(0, np.int64), kind=np.zeros(0, np.int64), u_thin=np.zeros(0),
                         u_det=np.zeros(0), owner=np.zeros(0, np.int64), w_sched=np.zeros(0),
                         order=np.zeros(0, np.int64), step_start=np.zeros(1, np.int64), jitter_seed=0)
    sim = _Sim(snap, tree, NOOP, scenario=0, reactive_deadline_s=90.0)
    sim.seed_log = []
    sim.mode_score_log = []
    sim.choice_log = {}
    _b5_periodic_patrolling(sim, float(snap.t0))
    out = {}
    for (_t, rid, seeds, modes) in sim.seed_log:
        out[rid] = {"seeds": seeds, "modes": modes, "scores": {}, "choice": sim.choice_log.get(rid)}
    for (rid, x, y, mode, sc) in sim.mode_score_log:
        out.setdefault(rid, {"seeds": [], "modes": [], "scores": {}, "choice": sim.choice_log.get(rid)})
        out[rid]["scores"][(x, y, mode)] = sc
    return out


def generation_seeds(snap: RolloutSnapshot) -> dict:
    """Preventive seeds B5's generation registers at t0 for every robot.

    Runs the verified TaskGenerator port (_b5_periodic_patrolling) on a
    throwaway copy of the snapshot's planner state and records, per robot, the
    deduplicated seed list (detection clusters, forecast hotspots after the
    percentile/spacing filter, border hotspots) together with the cue modes
    B5 scores for each seed (TaskGenerator.py:1240-1253 and 1376).  Nothing
    of the snapshot is mutated.
    """
    tree = _ScenarioTree(t=np.zeros(0), x=np.zeros(0), y=np.zeros(0), node=np.zeros(0, np.int64),
                         parent=np.zeros(0, np.int64), kind=np.zeros(0, np.int64), u_thin=np.zeros(0),
                         u_det=np.zeros(0), owner=np.zeros(0, np.int64), w_sched=np.zeros(0),
                         order=np.zeros(0, np.int64), step_start=np.zeros(1, np.int64), jitter_seed=0)
    sim = _Sim(snap, tree, NOOP, scenario=0, reactive_deadline_s=90.0)
    sim.seed_log = []
    _b5_periodic_patrolling(sim, float(snap.t0))
    out = {}
    for (_t, rid, seeds, modes) in sim.seed_log:
        out[rid] = (seeds, modes)
    return out

"""Explicit additive B1-B5 reference profiles; this module launches no searches.

Keep the submitted policy approximations and isolate forecast corrections in
separate arms. Historical thinning outputs are never an additive reference.
"""
from copy import deepcopy

from additive_intensity import ADDITIVE_CONTRACT
from experiments import run_hierarchical_calibration as hierarchy


CONTRACT = {
    "id": ADDITIVE_CONTRACT,
    "intensity": "positive_part(background + accepted_event_excitation - intervention_inhibition)",
    "background_mu_units": "events/m^2/s per unit spatial weight",
    "background_reference": [2e-5, 1e-4, 4e-4],
    "background_total": "mu * mean(legacy_node_weights) * field_area",
    "spatial_grid": "equal-area cells, centres (i+1/2)*width/nx, (j+1/2)*height/ny",
    "source_projection": "containing cell centre",
    "candidate_location": "uniform within sampled cell",
    "spatial_kernel": "unit-integral full-plane Gaussian; exact cell CDF integrals",
    "boundary": "outside Gaussian mass lost; no boundary renormalization",
    "cue_beta_units": "initial total suppressive rate, events/s, before boundary loss",
    "cue_time_kernel": "exp(-age/omega), without 1/omega",
    "cue_beta_reference": "existing numerical cue beta values are an explicit new reference, not a conversion",
    "effectiveness": "fixed pre-depletion effectiveness recorded at application",
    "truth_alpha_units": "mean offspring count before boundary loss",
    "excitation_time": "next-step rate alpha*(1-exp(-dt/omega))/dt, then geometric decay",
    "acceptance": "positive_part(candidate-inhibition)/candidate; zero if candidate is zero",
    "timing": "predictable step-start fields; current accepted events excite from next step",
    "observations": "existing observation and communication rules; no truth-state input to policy",
    "policy_forecasts": "retain paper approximations; do not silently add forecast-correction improvements",
    "B5_rule": "submitted implementation: maximize current-effectiveness-weighted predicted benefit minus cost; not literal max-effectiveness for unequal cues",
    "B5_decision": "user explicitly selected preservation of submitted B5 after definition audit",
    "historical_comparison": "environment/model revision comparison, not an isolated stamp-unit effect",
    "continuation_worlds": "unavailable until their separate additive verification gate passes",
}


def reference():
    params = hierarchy.paper_reference()
    params.update(truth_process_mode=ADDITIVE_CONTRACT,
                  random_stream_mode="coupled", truth_deterrence_memory="complete",
                  truth_background_timing="step_start", estimator_mode="legacy",
                  legacy_stamp_units="mass_per_cell",
                  # Uniform paper baseline. The old mixed correction cohort is
                  # deliberately not carried into the new environment.
                  stl_forecast_correction=False,
                  stl_forward_trajectory_correction=False)
    return params


def resolved_hierarchy():
    ref = reference()
    configs = {}
    for system in hierarchy.SYSTEMS:
        parent = ref if system == "B1" else configs[hierarchy.PARENTS[system]]
        configs[system] = hierarchy.derive(system, parent)
        if configs[system]["truth_process_mode"] != ADDITIVE_CONTRACT:
            raise AssertionError("descendant changed the physical environment")
        if configs[system]["stl_forecast_correction"]:
            raise AssertionError("baseline descendant enabled a correction improvement")
    return deepcopy(configs)

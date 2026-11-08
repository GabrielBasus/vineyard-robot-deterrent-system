"""Explicit B4_mission profile; never modifies the frozen calibration hierarchy."""
from copy import deepcopy

SYSTEM_ID = 'B4_mission'
INTENDED_PARAMETER_CHANGES = frozenset((
    'stl_active_clauses', 'stl_T_react_s', 'stl_proposal_predictive_dispatch',
))


def build_b4_mission(parent_b4):
    if parent_b4.get('dispatch_policy') != 'res' or parent_b4.get('predictive_utility_mode') != 'stl_robustness':
        raise ValueError('B4_mission must derive from the retained B4 configuration')
    if set(parent_b4.get('stl_active_clauses', ())) != {'exp', 'cov', 'hab'}:
        raise ValueError('Expected original three-clause B4 profile')
    deadline = float(parent_b4.get('reactive_service_deadline_s', 90.0))
    if deadline <= 0:
        raise ValueError('Reactive service deadline must be positive')
    profile = deepcopy(parent_b4)
    profile.update(
        stl_active_clauses=['exp', 'cov', 'hab', 'react'],
        stl_T_react_s=deadline,
        stl_proposal_predictive_dispatch=True,
    )
    return profile

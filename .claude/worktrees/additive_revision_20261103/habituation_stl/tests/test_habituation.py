"""Tests for habituation.py, including the core mechanism the thesis relies on:
rotating cue modes keeps effectiveness (and thus total suppression) higher than
repeating one mode, holding the number of actions fixed."""
import numpy as np

from habituation import HabituationField


def test_recovery_toward_one():
    h = HabituationField(n_cells=1, n_modes=1, T_rec=100.0, kappa=0.5)
    h.eta[0, 0] = 0.2
    h.recover(100.0)  # one time constant
    # 1 - (1-0.2)*e^-1 = 1 - 0.8*0.3679 = 0.7057
    assert abs(h.effectiveness(0, 0) - (1 - 0.8 * np.exp(-1))) < 1e-9
    # recovery is bounded above by 1
    for _ in range(50):
        h.recover(100.0)
    assert h.effectiveness(0, 0) <= 1.0 + 1e-12


def test_habituation_jump():
    h = HabituationField(n_cells=1, n_modes=2, T_rec=1e9, kappa=[0.4, 0.1])
    h.apply(0, 0)
    assert abs(h.effectiveness(0, 0) - 0.6) < 1e-12   # 1*(1-0.4)
    assert abs(h.effectiveness(0, 1) - 1.0) < 1e-12   # other mode untouched (gamma=0)
    h.apply(0, 0)
    assert abs(h.effectiveness(0, 0) - 0.36) < 1e-12  # 0.6*0.6


def test_cross_mode_generalization():
    h = HabituationField(n_cells=1, n_modes=2, T_rec=1e9, kappa=0.5, gamma=0.4)
    h.apply(0, 0)
    assert abs(h.effectiveness(0, 0) - 0.5) < 1e-12          # applied mode
    assert abs(h.effectiveness(0, 1) - (1 - 0.4 * 0.5)) < 1e-12  # generalized


def test_rotation_beats_repetition():
    """With T_rec finite and several actions between recoveries, rotating modes
    yields higher cumulative effectiveness than repeating one mode. This is the
    mechanism that makes predictive variety operationally valuable."""
    n_actions = 12
    dt_between = 60.0
    T_rec = 1800.0
    kappa = 0.45

    # Policy A: always mode 0
    hA = HabituationField(1, 3, T_rec=T_rec, kappa=kappa)
    supp_A = 0.0
    for _ in range(n_actions):
        supp_A += hA.effectiveness(0, 0)  # suppression proportional to eta at application
        hA.apply(0, 0)
        hA.recover(dt_between)

    # Policy B: rotate modes 0,1,2
    hB = HabituationField(1, 3, T_rec=T_rec, kappa=kappa)
    supp_B = 0.0
    for k in range(n_actions):
        m = k % 3
        supp_B += hB.effectiveness(0, m)
        hB.apply(0, m)
        hB.recover(dt_between)

    assert supp_B > supp_A, (supp_B, supp_A)
    print(f"    cumulative suppression: repeat={supp_A:.3f}  rotate={supp_B:.3f}  "
          f"(+{100*(supp_B-supp_A)/supp_A:.1f}%)")


def run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"habituation.py: {len(fns)}/{len(fns)} tests passed")


if __name__ == "__main__":
    run_all()

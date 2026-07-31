"""Unit tests for stl.py -- checked against hand-computed reference values."""
import numpy as np

import stl
from stl import (Trace, Aggregator, signal_leq, signal_geq, Neg, And, Or,
                 Implies, Eventually, Always, Once, Historically, Until,
                 robustness, robustness_at)


def approx(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


def test_predicate():
    tr = Trace([0, 1, 2], {"x": [1.0, 3.0, -2.0]})
    # (x <= 2) robustness = 2 - x
    r = robustness(signal_leq("x", 2.0), tr)
    assert np.allclose(r, [1.0, -1.0, 4.0])
    # (x >= 0) robustness = x
    r2 = robustness(signal_geq("x", 0.0), tr)
    assert np.allclose(r2, [1.0, 3.0, -2.0])


def test_neg_and_or():
    tr = Trace([0, 1], {"x": [2.0, -1.0], "y": [0.5, 0.5]})
    px = signal_geq("x", 0.0)   # rob = x
    py = signal_geq("y", 0.0)   # rob = 0.5
    assert np.allclose(robustness(Neg(px), tr), [-2.0, 1.0])
    assert np.allclose(robustness(And([px, py]), tr), [0.5, -1.0])  # min(x,0.5)
    assert np.allclose(robustness(Or([px, py]), tr), [2.0, 0.5])    # max(x,0.5)


def test_always_eventually_window():
    # uniform dt = 1
    x = [0.0, 2.0, -1.0, 3.0, 1.0]
    tr = Trace(list(range(5)), {"x": x})
    p = signal_geq("x", 0.0)  # rob = x
    # Always_[0,1] x>=0 at i: min(x[i], x[i+1]) (clamped at end)
    ralways = robustness(Always(p, 0, 1), tr)
    assert np.allclose(ralways, [0.0, -1.0, -1.0, 1.0, 1.0])
    # Eventually_[0,2] x>=0 at i: max over x[i..i+2]
    rev = robustness(Eventually(p, 0, 2), tr)
    assert np.allclose(rev, [2.0, 3.0, 3.0, 3.0, 1.0])


def test_once_historically():
    x = [0.0, 2.0, -1.0, 3.0, 1.0]
    tr = Trace(list(range(5)), {"x": x})
    p = signal_geq("x", 0.0)
    # Once_[0,1] : max over x[i-1..i]
    ronce = robustness(Once(p, 0, 1), tr)
    assert np.allclose(ronce, [0.0, 2.0, 2.0, 3.0, 3.0])
    # Historically_[0,1] : min over x[i-1..i]
    rh = robustness(Historically(p, 0, 1), tr)
    assert np.allclose(rh, [0.0, 0.0, -1.0, -1.0, 1.0])


def test_implies_deadline_pattern():
    # always( arr -> eventually_[0,2] srv )  -- the phi_react pattern
    arr = [1.0, -1.0, -1.0, -1.0]   # arrival "true" (>=0) only at t=0
    srv = [-1.0, -1.0, 1.0, -1.0]   # serviced at t=2
    tr = Trace(list(range(4)), {"arr": arr, "srv": srv})
    p_arr = signal_geq("arr", 0.0)
    p_srv = signal_geq("srv", 0.0)
    phi = Always(Implies(p_arr, Eventually(p_srv, 0, 2)), 0, 0)
    r = robustness_at(phi, tr, 0)
    # at t0: arrival present, serviced within 2 steps -> satisfied (r>0)
    assert r > 0


def test_until():
    # x stays >=0 until y >=0 within [0,3]
    x = [1.0, 1.0, 1.0, -1.0]
    y = [-1.0, -1.0, 2.0, 5.0]
    tr = Trace(list(range(4)), {"x": x, "y": y})
    px = signal_geq("x", 0.0)
    py = signal_geq("y", 0.0)
    r = robustness_at(Until(px, py, 0, 3), tr, 0)
    # best j=2: min(y[2]=2, min(x[0..2]=1)) = 1
    assert approx(r, 1.0)


def test_softmin_limits_to_min():
    tr = Trace([0, 1], {"x": [2.0, -1.0], "y": [0.5, 0.5]})
    px = signal_geq("x", 0.0)
    py = signal_geq("y", 0.0)
    classical = robustness(And([px, py], agg=Aggregator("classical")), tr)
    smooth_hi = robustness(And([px, py], agg=Aggregator("smooth", theta=200.0)), tr)
    # smooth with high theta approaches classical min
    assert np.allclose(classical, smooth_hi, atol=1e-2)
    # smooth is a conservative under-approximation of min (softmin <= min)
    smooth_lo = robustness(And([px, py], agg=Aggregator("smooth", theta=3.0)), tr)
    assert np.all(smooth_lo <= classical + 1e-9)


def test_softmin_gradient_nonflat():
    # min has flat gradient; softmin distinguishes near-equal components
    tr = Trace([0], {"a": [1.000], "b": [1.001], "c": [1.002]})
    pa = signal_geq("a", 0.0)
    pb = signal_geq("b", 0.0)
    pc = signal_geq("c", 0.0)
    cl = robustness(And([pa, pb, pc], agg=Aggregator("classical")), tr)[0]
    sm = robustness(And([pa, pb, pc], agg=Aggregator("smooth", theta=10.0)), tr)[0]
    # smooth value is strictly below the hard min (all three contribute)
    assert sm < cl


def run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  PASS {fn.__name__}")
    print(f"stl.py: {passed}/{len(fns)} tests passed")


if __name__ == "__main__":
    run_all()

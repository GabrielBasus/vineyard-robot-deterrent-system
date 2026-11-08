import numpy as np
import pytest
from scipy.integrate import dblquad

from additive_intensity import CellGrid, offspring_initial_rate, positive_part_intensity


def test_acceptance_realizes_additive_rate_and_saturates_without_mutation():
    bg = np.array([0., 2., 2., 2.])
    inh = np.array([0., 1., 3., 8.])
    before = bg.copy(), inh.copy()
    candidate, lam, p = positive_part_intensity(bg, [0, 0, 1, 1], inh)
    np.testing.assert_allclose(lam, [0, 1, 0, 0])
    np.testing.assert_allclose(candidate * p, lam)
    assert p[0] == 0
    np.testing.assert_array_equal(bg, before[0])
    np.testing.assert_array_equal(inh, before[1])


def test_overlapping_inhibition_is_added_before_clipping():
    _, lam, _ = positive_part_intensity(4., 2., np.array([1., 3.])[:, None].sum(0))
    np.testing.assert_allclose(lam, [2.])


@pytest.mark.parametrize("bad", [-1., np.nan, np.inf])
def test_invalid_rate_fails_closed(bad):
    with pytest.raises(ValueError):
        positive_part_intensity(1., 0., bad)


def test_gaussian_cell_mass_matches_independent_quadrature():
    grid = CellGrid(8., 6., 4, 3)
    x, y, sigma = .7, 1.8, 1.2
    masses = grid.gaussian_mass(x, y, sigma)
    for iy, ix in [(0, 0), (1, 0), (2, 3)]:
        integral, _ = dblquad(
            lambda yy, xx: np.exp(-((xx-x)**2+(yy-y)**2)/(2*sigma**2))/(2*np.pi*sigma**2),
            ix * 2., (ix+1) * 2., lambda _: iy * 2., lambda _: (iy+1) * 2.)
        assert masses[iy, ix] == pytest.approx(integral, abs=1e-12)


def test_boundary_mass_lost_and_grid_refinement_preserves_integral():
    totals = []
    for n in (10, 20, 40):
        grid = CellGrid(100., 100., n, n)
        field = grid.rate_density(0., 0., 2., 7.)
        totals.append(field.sum() * grid.area)
    np.testing.assert_allclose(totals, 7. / 4., atol=1e-12)
    central = CellGrid(100., 100., 20, 20)
    assert central.gaussian_mass(50., 50., 2.).sum() == pytest.approx(1.)


@pytest.mark.parametrize("mu", [2e-5, 1e-4, 4e-4])
def test_preserves_existing_physical_background_demand(mu):
    grid = CellGrid(1200., 600., 19, 13)
    weights = np.linspace(.3, 2.1, grid.nx * grid.ny).reshape(grid.ny, grid.nx)
    assert grid.background_density(mu, weights).sum() * grid.area == pytest.approx(
        mu * weights.mean() * grid.width * grid.height)


def test_temporal_conversion_preserves_branching_count_and_converges():
    alpha, omega = .3, 600.
    continuous = offspring_initial_rate(alpha, omega)
    errors = []
    for dt in (10., 1., .1):
        rate = offspring_initial_rate(alpha, omega, dt)
        assert rate * dt / (-np.expm1(-dt/omega)) == pytest.approx(alpha)
        errors.append(abs(rate - continuous))
    assert errors[2] < errors[1] < errors[0]


@pytest.mark.parametrize("kwargs", [{"nx": 0}, {"nx": 1.5}, {"width": float("nan")}])
def test_invalid_geometry_rejected(kwargs):
    values = dict(width=10., height=10., nx=3, ny=3)
    values.update(kwargs)
    with pytest.raises(ValueError):
        CellGrid(**values)

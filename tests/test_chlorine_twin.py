"""P6 tests: chlorine twin physics + regression on fixed input (Part A §7)."""
import numpy as np

from models.twin.chlorine import (
    k_bulk_per_day, residual_along_path, monte_carlo_residuals, load_network)

# a simple 2-segment path: 3 h pipe (k_wall 0.3) + 12 h tank residence
PATH = [
    {"type": "pipe", "from": "wtp", "to": "tank", "time_h": 3.0, "time_sd": 0.0, "k_wall": 0.3},
    {"type": "residence", "from": "tank", "to": "tank", "time_h": 12.0, "time_sd": 0.0, "k_wall": 0.0},
]


def test_k_bulk_increases_with_temperature():
    assert k_bulk_per_day(30, 0.9, 1.096) > k_bulk_per_day(20, 0.9, 1.096)
    # at 20C, k_b(T) == k_b20 exactly
    assert abs(k_bulk_per_day(20, 0.9, 1.096) - 0.9) < 1e-9


def test_residual_never_exceeds_dose_and_non_negative():
    r = residual_along_path(2.0, 0.8, 25.0, PATH, 0.9, 1.096)
    assert 0.0 <= r <= 2.0


def test_higher_temperature_lowers_residual():
    cold = residual_along_path(2.0, 0.8, 15.0, PATH, 0.9, 1.096)
    hot = residual_along_path(2.0, 0.8, 30.0, PATH, 0.9, 1.096)
    assert hot < cold


def test_higher_demand_lowers_residual():
    lo = residual_along_path(2.0, 0.3, 25.0, PATH, 0.9, 1.096)
    hi = residual_along_path(2.0, 1.2, 25.0, PATH, 0.9, 1.096)
    assert hi < lo


def test_demand_above_dose_gives_zero_start():
    r = residual_along_path(1.0, 1.5, 25.0, PATH, 0.9, 1.096)
    assert r == 0.0


def test_longer_residence_lowers_residual():
    short = [PATH[0], {**PATH[1], "time_h": 6.0}]
    long = [PATH[0], {**PATH[1], "time_h": 24.0}]
    assert residual_along_path(2.0, 0.8, 25.0, long, 0.9, 1.096) < \
        residual_along_path(2.0, 0.8, 25.0, short, 0.9, 1.096)


def test_mc_percentiles_ordered_and_within_dose():
    model = load_network()
    res = monte_carlo_residuals(model, dose_mg_l=2.0, temp_c=25.0,
                                demand_mg_l=0.8, n_mc=200, seed=42)
    for node, q in res["nodes"].items():
        assert q["p10"] <= q["p50"] <= q["p90"]
        assert 0.0 <= q["p10"] and q["p90"] <= 2.0


def test_mc_regression_fixed_seed():
    model = load_network()
    a = monte_carlo_residuals(model, 2.0, 25.0, 0.8, n_mc=200, seed=123)
    b = monte_carlo_residuals(model, 2.0, 25.0, 0.8, n_mc=200, seed=123)
    assert a["nodes"] == b["nodes"]  # byte-identical for the same seed


def test_higher_dose_raises_worst_tap_residual():
    model = load_network()
    lo = monte_carlo_residuals(model, 1.0, 25.0, 0.8, n_mc=200, seed=1)
    hi = monte_carlo_residuals(model, 3.0, 25.0, 0.8, n_mc=200, seed=1)
    worst_lo = min(v["p10"] for k, v in lo["nodes"].items() if k.startswith("H") and "_" not in k)
    worst_hi = min(v["p10"] for k, v in hi["nodes"].items() if k.startswith("H") and "_" not in k)
    assert worst_hi > worst_lo

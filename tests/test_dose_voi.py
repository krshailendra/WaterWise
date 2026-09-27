"""P8 tests: dose solver monotonicity/bounds, test-next VOI, anomaly recall."""
from pathlib import Path

import pytest

from models.dose.solver import solve_dose
from models.voi.test_next import rank_tests


def test_higher_temperature_needs_more_dose():
    lo = solve_dose(18.0, 0.6, n_mc=150, seed=1)
    hi = solve_dose(24.0, 0.6, n_mc=150, seed=1)
    # both feasible in this band; hotter water -> more dose (or at least not less)
    assert hi["recommended_dose_mg_l"] >= lo["recommended_dose_mg_l"]


def test_higher_demand_needs_more_dose():
    lo = solve_dose(20.0, 0.5, n_mc=150, seed=1)
    hi = solve_dose(20.0, 0.9, n_mc=150, seed=1)
    assert hi["recommended_dose_mg_l"] >= lo["recommended_dose_mg_l"]


def test_dose_within_bounds():
    r = solve_dose(25.0, 0.8, n_mc=150, seed=1)
    assert 0.5 <= r["recommended_dose_mg_l"] <= 4.0
    assert "worst_tap_site_id" in r and "inputs" in r


def test_dose_returns_uncertainty_and_inputs():
    r = solve_dose(20.0, 0.6, n_mc=150, seed=1)
    assert "worst_tap_p10_residual_mg_l" in r
    assert r["inputs"]["water_temp_c"] == 20.0


def test_test_next_returns_site_and_numeric_reason():
    r = rank_tests(25.0, 0.8, 2.0, n_mc=150)
    assert r["test_next_site_id"] is not None
    assert "VOI" in r["test_next_reason"]
    assert len(r["ranking"]) == 12  # all hostels ranked


@pytest.mark.skipif(not Path("data/silver/anomaly_labels.parquet").exists(),
                    reason="run P6 first")
def test_tank_anomaly_recall_on_synthetic():
    from models.anomaly.tank_anomaly import detect
    r = detect(z_threshold=3.5)
    assert r["recall"] >= 0.8       # catches injected dirty-tank anomalies
    assert r["precision"] > 0.4     # honest: precision is modest, reported as-is


@pytest.mark.skipif(not Path("data/gold/daily_briefing.parquet").exists(),
                    reason="run daily_briefing first")
def test_daily_briefing_written():
    import pandas as pd
    df = pd.read_parquet("data/gold/daily_briefing.parquet")
    assert len(df) >= 1
    assert {"recommended_dose_mg_l", "worst_tap_site_id", "raw_risk_level",
            "test_next_reason"}.issubset(df.columns)
    assert (df["provenance"] == "modelled").all()

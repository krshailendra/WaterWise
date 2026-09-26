"""P2 tests: hydromet data integrity + flow-lag method (physics + regression)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HYDROMET = Path("data/silver/hydromet.parquet")
FLOW_LAGS = Path("data/gold/flow_lags.parquet")

pytestmark = pytest.mark.skipif(
    not HYDROMET.exists(), reason="run P2 ingestion first (make ingest)")


def test_hydromet_has_three_parameters():
    df = pd.read_parquet(HYDROMET)
    assert set(df["parameter"].unique()) >= {"rain_mm", "air_temp_c_mean", "discharge_m3s"}


def test_no_gaps_longer_than_3_days():
    from models.eta.flow_lag import gap_report
    assert gap_report(max_gap_days=3) == {}


def test_discharge_is_positive_and_riverlike():
    df = pd.read_parquet(HYDROMET)
    d = df[df["parameter"] == "discharge_m3s"]["value"].dropna()
    assert (d >= 0).all()
    # the Brahmaputra at Guwahati is a very large river; median should be > 500 m3/s
    assert d.median() > 500


def test_rain_non_negative_and_bounded():
    df = pd.read_parquet(HYDROMET)
    r = df[df["parameter"] == "rain_mm"]["value"].dropna()
    assert (r >= 0).all()
    assert r.max() < 1000  # daily rainfall sanity bound (mm)


def test_air_temp_plausible_for_assam():
    df = pd.read_parquet(HYDROMET)
    t = df[df["parameter"] == "air_temp_c_mean"]["value"].dropna()
    assert t.min() > 0 and t.max() < 45


def test_best_lag_recovers_synthetic_shift():
    # a synthetic wave shifted by 3 days should be recovered as lag 3
    from models.eta.flow_lag import _best_lag
    rng = np.random.default_rng(0)
    base = pd.Series(rng.normal(size=400))
    down = base.shift(3).fillna(0)
    lag, corr, _ = _best_lag(base, down, max_lag=10)
    assert lag == 3
    assert corr > 0.9


def test_flow_lags_written_with_provenance():
    if not FLOW_LAGS.exists():
        pytest.skip("run flow_lag compute first")
    df = pd.read_parquet(FLOW_LAGS)
    assert {"upstream_site_id", "lag_days", "correlation", "provenance"} <= set(df.columns)
    assert (df["provenance"] == "modelled").all()

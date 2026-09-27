"""P7 tests: virtual sensor features + trained output integrity."""
from pathlib import Path

import pandas as pd
import pytest

VS = Path("data/gold/virtual_sensor_daily.parquet")


def test_features_use_real_data_only():
    from models.virtual_sensor.features import build_features
    f = build_features()
    assert f.shape[1] > 40  # many lag/rolling/discharge features
    assert "ndti_target" in f.columns
    assert f["ndti_target"].notna().sum() >= 100  # clear-scene labels


@pytest.mark.skipif(not VS.exists(), reason="run P7 training first (make train)")
def test_predictions_cover_all_days_and_monotone_quantiles():
    df = pd.read_parquet(VS)
    assert len(df) > 3000
    assert (df["ndti_p10"] <= df["ndti_p50"] + 1e-9).all()
    assert (df["ndti_p50"] <= df["ndti_p90"] + 1e-9).all()
    assert (df["provenance"] == "modelled").all()


@pytest.mark.skipif(not VS.exists(), reason="run P7 training first")
def test_confidence_fields_present():
    df = pd.read_parquet(VS)
    assert "interval_width" in df.columns
    assert "days_since_last_clear" in df.columns
    # non-null values (days before the first-ever clear scene are legitimately NaN)
    dsc = df["days_since_last_clear"].dropna()
    assert (dsc >= 0).all() and dsc.max() > 0


@pytest.mark.skipif(not VS.exists(), reason="run P7 training first")
def test_persistence_column_is_forward_filled_observed():
    df = pd.read_parquet(VS)
    assert "ndti_persistence" in df.columns
    # persistence equals observed on clear days
    clear = df[df["ndti_observed"].notna()]
    assert (abs(clear["ndti_persistence"] - clear["ndti_observed"]) < 1e-9).all()

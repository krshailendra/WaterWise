"""P3 tests: NDTI parquet integrity + relative-index sanity."""
from pathlib import Path

import pandas as pd
import pytest

S2 = Path("data/silver/s2_ndti.parquet")

pytestmark = pytest.mark.skipif(
    not S2.exists(), reason="run P3 extraction first (python -m pipeline.ingest.sentinel2)")


def _median_df():
    df = pd.read_parquet(S2)
    return df[df["parameter"] == "ndti_median"].copy()


def test_ndti_within_index_bounds():
    v = _median_df()["value"]
    assert v.between(-1.0, 1.0).all()


def test_has_expected_parameters():
    df = pd.read_parquet(S2)
    assert {"ndti_median", "ndti_iqr", "water_pixels", "cloud_fraction"} <= set(df["parameter"].unique())


def test_water_pixels_above_floor():
    from pipeline.ingest.sentinel2 import MIN_WATER_PIXELS
    df = pd.read_parquet(S2)
    wp = df[df["parameter"] == "water_pixels"]["value"]
    assert (wp >= MIN_WATER_PIXELS).all()


def test_all_public_observed_satellite():
    df = pd.read_parquet(S2)
    assert (df["provenance"] == "public_observed").all()
    assert (df["method"] == "satellite").all()
    assert df["source_ref"].str.contains("NOT NTU").all()  # relative-index label kept


def test_reasonable_scene_count():
    med = _median_df()
    # acceptance: at least a few dozen clear scenes across years per polygon
    assert med.groupby("site_id").size().min() >= 30

"""P6 tests: synthetic network + realism/audit checks (Part B §6)."""
from pathlib import Path

import pandas as pd
import pytest

SILVER = Path("data/silver")
HAS = (SILVER / "tap_readings.parquet").exists()

pytestmark = pytest.mark.skipif(not HAS, reason="run P6 generators first (make synth)")


def test_network_builds_deterministically():
    from pipeline.synthetic.network import build_network
    a = build_network(seed=20250926)
    b = build_network(seed=20250926)
    assert a["edges"] == b["edges"] and a["nodes"] == b["nodes"]
    assert len(a["nodes"]) == 38 and len(a["edges"]) == 37


def test_tap_readings_physical_and_texture():
    from pipeline.validate.synthetic_checks import check_tap_readings
    r = check_tap_readings()
    assert r["pass"]
    assert r["negatives"] == 0 and r["over_dose"] == 0
    assert 0.03 <= r["missing_frac"] <= 0.13
    assert r["resolution_ok"]


def test_water_temp_within_envelope():
    from pipeline.validate.synthetic_checks import check_water_temp
    assert check_water_temp()["pass"]


def test_anomaly_labels_exist():
    adf = pd.read_parquet(SILVER / "anomaly_labels.parquet")
    assert len(adf) >= 3
    assert set(["site_id", "start_date", "end_date", "k_multiplier"]).issubset(adf.columns)
    assert (adf["k_multiplier"] >= 2.0).all() and (adf["k_multiplier"] <= 4.0).all()


def test_complaints_language_and_provenance():
    c = pd.read_parquet(SILVER / "complaints.parquet")
    assert 60 <= len(c) <= 150
    assert set(c["language"].unique()) <= {"en", "hi", "as"}
    assert (c["provenance"] == "synthetic").all()
    assert "category_true" in c.columns


def test_all_synthetic_provenance_labelled():
    for f in ["network_edges.parquet", "tap_readings.parquet"]:
        df = pd.read_parquet(SILVER / f)
        assert (df["provenance"] == "synthetic").all()
        assert df["source_ref"].str.contains("SIMULATED").all()

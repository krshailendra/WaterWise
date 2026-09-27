"""P5 tests: consumer area-risk BIS checks + geospatial nearest-station."""
from pathlib import Path

import pytest

from models.consumer.area_risk import _bis_check, _haversine_km, area_risk

HAS_GW = Path("data/silver/cpcb_groundwater.parquet").exists()


def test_bis_ph_band():
    assert _bis_check("ph", 7.0) is None
    assert _bis_check("ph", 9.5)["kind"] == "outside_band"
    assert _bis_check("ph", 5.0)["kind"] == "outside_band"


def test_bis_arsenic_levels():
    assert _bis_check("arsenic_mg_l", 0.005) is None
    assert _bis_check("arsenic_mg_l", 0.03)["kind"] == "above_acceptable"
    assert _bis_check("arsenic_mg_l", 0.2)["kind"] == "above_permissible"


def test_bis_coliform_any_presence_fails():
    ex = _bis_check("total_coliform_mpn_100ml", 10.0)
    assert ex is not None and ex["kind"] == "above_acceptable"


def test_haversine_known_distance():
    # Pandu to Kacharighat ~ a few km
    d = _haversine_km(26.176, 91.684, 26.190, 91.746)
    assert 5 < d < 8


@pytest.mark.skipif(not HAS_GW, reason="run P1 groundwater ingestion first")
def test_area_risk_returns_dated_distant_evidence():
    r = area_risk(26.176, 91.684)  # Pandu, Guwahati
    assert r["groundwater"], "should find nearby GW stations"
    g = r["groundwater"][0]
    assert "distance_km" in g and "data_year" in g and "data_age_years" in g
    assert "what_this_cannot_tell_you" in r
    assert "summary" in r and len(r["summary"]) > 20


@pytest.mark.skipif(not HAS_GW, reason="run P1 groundwater ingestion first")
def test_area_risk_all_four_demo_points():
    pts = [(26.176, 91.684), (26.183, 91.746), (26.126, 91.800), (26.192, 91.699)]
    for la, lo in pts:
        r = area_risk(la, lo)
        assert r["groundwater"], f"no GW near {la},{lo}"
        # every reported station must show its age + distance (honesty requirement)
        for g in r["groundwater"]:
            assert g["distance_km"] >= 0 and g["data_year"] >= 2015

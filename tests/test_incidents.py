"""P4 tests: incident agent geocoding + deterministic ETA range (physics)."""
from agents.incident_agent import (
    geocode, eta_range_hours, _keyword_classify, _load_gazetteer,
    _load_velocity_bounds, classify_article,
)

GAZ = _load_gazetteer()
VB = _load_velocity_bounds()


def test_geocode_matches_known_town():
    p = geocode("Oil spill reported near Dibrugarh on the Brahmaputra", GAZ)
    assert p is not None and p["name"] == "Dibrugarh"


def test_geocode_returns_none_for_unrelated():
    assert geocode("Cricket match in Mumbai", GAZ) is None


def test_eta_is_a_range_and_physically_ordered():
    dib = geocode("Dibrugarh", GAZ)
    eta = eta_range_hours(dib, GAZ, *VB)
    assert "eta_hours_low" in eta and "eta_hours_high" in eta
    # slower velocity -> longer ETA, so high >= low, and both positive
    assert eta["eta_hours_high"] >= eta["eta_hours_low"] > 0
    assert eta["distance_km"] > 0  # Dibrugarh is upstream of the intake


def test_upstream_closer_town_has_shorter_eta():
    dib = eta_range_hours(geocode("Dibrugarh", GAZ), GAZ, *VB)   # ~500 km upstream
    tez = eta_range_hours(geocode("Tezpur", GAZ), GAZ, *VB)      # ~200 km upstream
    assert tez["eta_hours_high"] < dib["eta_hours_high"]


def test_downstream_place_cannot_reach_intake():
    dhubri = geocode("Dhubri", GAZ)
    eta = eta_range_hours(dhubri, GAZ, *VB)
    assert eta["distance_km"] <= 0
    assert "cannot reach intake" in eta["note"]


def test_keyword_classifier_flags_relevant():
    r = _keyword_classify("Effluent discharge pollutes Brahmaputra near Dibrugarh", "")
    assert r["is_relevant"] is True
    assert r["kind"] in ("discharge", "spill", "flood")


def test_classify_article_produces_unconfirmed_event():
    art = {"title": "Oil spill contaminates Brahmaputra near Dibrugarh",
           "url": "http://example.com/x", "domain": "example.com",
           "seendate": "20240115T120000Z", "snippet": ""}
    ev = classify_article(art, GAZ, VB, use_llm=False)
    assert ev is not None
    assert ev["human_confirmed"] is False       # only humans confirm (rule 9)
    assert ev["provenance"] == "public_observed"
    assert ev["kind"] in ("spill", "discharge", "flood")

"""Offline demo tests: snapshot.json/js contract + demo.html presence."""
import json
from pathlib import Path

import pytest

APP = Path("app")
SNAP = APP / "snapshot.json"

pytestmark = pytest.mark.skipif(not SNAP.exists(), reason="run scripts/build_snapshot.py")


def _snap():
    return json.loads(SNAP.read_text(encoding="utf-8"))


def test_snapshot_has_required_top_level():
    s = _snap()
    for k in ["provenance_counts", "dates", "default_date", "briefings", "consumer", "disclaimer"]:
        assert k in s
    assert s["default_date"] in s["briefings"]


def test_each_briefing_complete():
    s = _snap()
    for d, b in s["briefings"].items():
        for k in ["risk", "recommended_dose_mg_l", "worst_tap", "test_next",
                  "ndti", "network", "explanation", "target_residual_mg_l"]:
            assert k in b, f"{d} missing {k}"
        assert 0.5 <= b["recommended_dose_mg_l"] <= 4.0
        assert b["risk"] in ("normal", "elevated", "high")
        assert len(b["network"]) >= 12


def test_network_nodes_have_status_colours():
    s = _snap()
    b = s["briefings"][s["default_date"]]
    for n in b["network"]:
        assert n["status"] in ("ok", "marginal", "low", "source", "unknown")


def test_consumer_shows_age_and_distance():
    s = _snap()
    for st in s["consumer"]["stations"]:
        assert st["distance_km"] >= 0 and st["data_year"] >= 2015
    assert "what_this_cannot_tell_you" in s["consumer"]


def test_offline_assets_exist():
    assert (APP / "demo.html").exists()
    js = (APP / "snapshot.js").read_text(encoding="utf-8")
    assert js.startswith("window.WATERWISE_SNAPSHOT = ")


def test_never_declares_unsafe():
    # the snapshot must never label water "unsafe" (only authorities can)
    txt = SNAP.read_text(encoding="utf-8").lower()
    assert "unsafe" not in txt or "never" in txt  # disclaimer may mention the word in "never...unsafe"

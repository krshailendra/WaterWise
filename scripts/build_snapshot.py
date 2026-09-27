"""Build app/snapshot.json (+ app/snapshot.js) for the offline demo (P-DEMO).

Assembles, from the REAL gold/silver data, everything the static demo.html needs:
briefing per replay date (risk, dose with p10-p90, worst tap, test-next), the
campus network nodes with p10 residuals + status colours, provenance counts, and
one consumer "my area" example. Every synthetic/modelled value keeps a badge.

snapshot.js sets window.WATERWISE_SNAPSHOT so demo.html works when opened directly
from disk (file:// blocks fetch of a sibling .json in some browsers).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from models.consumer.area_risk import area_risk
from models.twin.chlorine import load_network, monte_carlo_residuals
from pipeline.daily_briefing import build
from pipeline.validate.synthetic_checks import provenance_counts

APP = Path("app")
DATES = ["2024-07-15", "2024-01-15", datetime.now(timezone.utc).date().isoformat()]
TARGET = 0.2


def _status(p10: float) -> str:
    if p10 is None:
        return "unknown"
    if p10 >= TARGET:
        return "ok"            # green
    if p10 >= TARGET * 0.5:
        return "marginal"      # amber
    return "low"               # red — "under verification", never "unsafe"


def _network_for(model, temp, demand, dose, n_mc=200):
    res = monte_carlo_residuals(model, dose, temp, demand, n_mc=n_mc)
    pop = {}
    import yaml
    for h in yaml.safe_load(open("config/campus.yaml", encoding="utf-8"))["hostels"]:
        pop[h["id"]] = h["population"]
    nodes = []
    order = ["wtp", "reservoir"] + [f"H{i:02d}" for i in range(1, 13)]
    for nid in order:
        q = res["nodes"].get(nid)
        if nid == "wtp":
            nodes.append({"id": nid, "kind": "wtp", "p10": None, "p50": None,
                          "status": "source", "population": None})
            continue
        if not q:
            continue
        nodes.append({"id": nid, "kind": ("reservoir" if nid == "reservoir" else "hostel"),
                      "p10": q["p10"], "p50": q["p50"], "status": _status(q["p10"]),
                      "population": pop.get(nid)})
    return nodes


def main() -> dict:
    APP.mkdir(exist_ok=True)
    model = load_network()
    briefings = {}
    for ds in DATES:
        b = build(ds, n_mc=200)
        row = b["row"]
        temp = row["water_temp_c_est"]
        demand = float(b["dose"]["inputs"]["chlorine_demand_mg_l"])
        dose = row["recommended_dose_mg_l"]
        network = _network_for(model, temp, demand, dose)
        briefings[ds] = {
            "date": ds,
            "risk": row["raw_risk_level"],
            "recommended_dose_mg_l": dose,
            "dose_feasible": b["dose"]["feasible"],
            "dose_p90_needed_mg_l": row["dose_p90_needed"],
            "worst_tap": {"id": row["worst_tap_site_id"],
                          "p10": row["worst_tap_p10_residual_mg_l"],
                          "p50": b["dose"].get("worst_tap_p50_residual_mg_l")},
            "test_next": {"id": row["test_next_site_id"], "reason": row["test_next_reason"]},
            "ndti": {"p10": row["ndti_p10"], "p50": row["ndti_p50"], "p90": row["ndti_p90"]},
            "water_temp_c": temp,
            "chlorine_demand_mg_l": round(demand, 2),
            "active_alerts": row["active_alerts"],
            "target_residual_mg_l": TARGET,
            "network": network,
            "badges": {"dose": "modelled (simulated network)", "network": "synthetic",
                       "ndti": "modelled from real satellite", "temp": "modelled from real air-temp"},
            "explanation": _explain(row, b["dose"]),
        }

    consumer = area_risk(26.183, 91.746)  # Guwahati Panbazar example
    # trim consumer to what the UI needs
    consumer_ui = {
        "location": "Guwahati (Panbazar) — example",
        "summary": consumer["summary"],
        "what_this_cannot_tell_you": consumer["what_this_cannot_tell_you"],
        "stations": [{"name": g["name"], "distance_km": g["distance_km"],
                      "data_year": g["data_year"], "data_age_years": g["data_age_years"],
                      "exceedances": g["bis_exceedances"],
                      "parameters_tested": g["parameters_tested"]}
                     for g in consumer["groundwater"]],
        "sources": consumer["sources"],
        "badge": "public_observed (CPCB groundwater)",
    }

    snap = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": "WaterWise — offline demo snapshot",
        "provenance_counts": provenance_counts(),
        "dates": DATES,
        "default_date": "2024-07-15",
        "briefings": briefings,
        "consumer": consumer_ui,
        "disclaimer": ("Campus network + tap residuals are SIMULATED from documented "
                       "physics (labelled synthetic). Safety numbers are deterministic. "
                       "The app never calls water 'unsafe' — only an authority can."),
    }
    (APP / "snapshot.json").write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
    (APP / "snapshot.js").write_text(
        "window.WATERWISE_SNAPSHOT = " + json.dumps(snap, default=str) + ";",
        encoding="utf-8")
    return {"dates": DATES, "provenance": snap["provenance_counts"],
            "network_nodes": len(briefings[DATES[0]]["network"])}


def _explain(row, dose) -> str:
    d = row["recommended_dose_mg_l"]
    wt = row["worst_tap_site_id"]
    p10 = row["worst_tap_p10_residual_mg_l"]
    if not dose["feasible"]:
        return (f"Even the maximum {d} mg/L leaves the farthest tank {wt} at a p10 "
                f"residual of {p10} mg/L, below the 0.2 mg/L BIS minimum. Recommend "
                f"booster chlorination or reducing tank residence, and test {row['test_next_site_id']} first.")
    return (f"Dose {d} mg/L keeps the worst tap ({wt}) at p10 residual {p10} mg/L, "
            f"at or above the 0.2 mg/L BIS minimum. Test {row['test_next_site_id']} next.")


if __name__ == "__main__":
    print("snapshot:", main())

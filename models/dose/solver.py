"""Inverse chlorine dose solver (P8) — DETERMINISTIC, unit-tested.

For a given day, find the minimum plant dose (0.5-4.0 mg/L, 0.05 steps) such that
the p10 residual at the WORST hostel tap >= 0.2 mg/L (BIS IS 10500 minimum),
given the day's modelled water temperature and chlorine-demand distribution.

Returns the dose, the binding (worst) tap and its p10/p50 residual, and the p90
dose needed under a pessimistic scenario. Pure Python + the Monte-Carlo twin; no
LLM (Part A rule 4). Every safety number comes back with its inputs (Part A §7).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import yaml

from models.twin.chlorine import load_network, monte_carlo_residuals


def _params():
    return yaml.safe_load(open("config/params.yaml", encoding="utf-8"))


def _hostel_nodes(res_nodes: dict) -> dict:
    return {k: v for k, v in res_nodes.items() if k.startswith("H") and "_" not in k}


def solve_dose(water_temp_c: float, chlorine_demand_mg_l: float,
               model: Optional[dict] = None, n_mc: int = 300,
               seed: Optional[int] = None, params: Optional[dict] = None) -> dict:
    """Minimum dose so worst-tap p10 residual >= target. Deterministic given seed."""
    params = params or _params()
    model = model or load_network()
    dose_cfg = params["dose"]
    lo, hi, step = dose_cfg["min_mg_l"], dose_cfg["max_mg_l"], dose_cfg["step_mg_l"]
    target = dose_cfg["target_residual_mg_l"]
    seed = seed if seed is not None else params["seed"]

    doses = np.round(np.arange(lo, hi + 1e-9, step), 2)
    chosen = None
    worst_info = None
    for dose in doses:
        res = monte_carlo_residuals(model, float(dose), water_temp_c,
                                    chlorine_demand_mg_l, n_mc=n_mc, seed=seed,
                                    params=params)
        hostels = _hostel_nodes(res["nodes"])
        worst_id = min(hostels, key=lambda k: hostels[k]["p10"])
        worst = hostels[worst_id]
        if worst["p10"] >= target:
            chosen = float(dose)
            worst_info = {"worst_tap_site_id": worst_id,
                          "worst_tap_p10_residual_mg_l": worst["p10"],
                          "worst_tap_p50_residual_mg_l": worst["p50"]}
            break
        worst_info = {"worst_tap_site_id": worst_id,
                      "worst_tap_p10_residual_mg_l": worst["p10"],
                      "worst_tap_p50_residual_mg_l": worst["p50"]}

    feasible = chosen is not None
    recommended = chosen if feasible else float(hi)

    # p90 dose needed under a pessimistic scenario: hotter + higher demand
    pess_temp = water_temp_c + 3.0
    pess_demand = chlorine_demand_mg_l * 1.3
    dose_p90 = None
    for dose in doses:
        res = monte_carlo_residuals(model, float(dose), pess_temp, pess_demand,
                                    n_mc=n_mc, seed=seed, params=params)
        hostels = _hostel_nodes(res["nodes"])
        worst_p10 = min(hostels[k]["p10"] for k in hostels)
        if worst_p10 >= target:
            dose_p90 = float(dose)
            break

    return {
        "recommended_dose_mg_l": round(recommended, 2),
        "feasible": feasible,
        "target_residual_mg_l": target,
        **(worst_info or {}),
        "dose_p90_needed_mg_l": round(dose_p90, 2) if dose_p90 is not None else None,
        "inputs": {"water_temp_c": water_temp_c,
                   "chlorine_demand_mg_l": chlorine_demand_mg_l,
                   "dose_bounds": [lo, hi], "step": step, "n_mc": n_mc, "seed": seed,
                   "pessimistic": {"water_temp_c": pess_temp, "demand_mg_l": round(pess_demand, 3)}},
        "note": ("SIMULATED network — dose is computed on assumed campus parameters "
                 "until the WTP calibrates them."),
    }


if __name__ == "__main__":
    import json
    r = solve_dose(water_temp_c=25.0, chlorine_demand_mg_l=0.8)
    print(json.dumps(r, indent=2, default=str))

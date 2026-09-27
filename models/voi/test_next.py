"""Test-next: value-of-information ranking (P8) — DETERMINISTIC.

Which single test today reduces the most risk? We rank hostel taps by:

    VOI(site) = P(residual < 0.2 mg/L) * population_served * uncertainty_width

where P(residual < target) and the p10-p90 uncertainty width come from the twin's
Monte Carlo at the day's recommended dose. The idea: a test is most valuable where
failure is likely (P high), many people are exposed (population), and we are most
uncertain (wide band) — testing there collapses the most risk. Pure Python; the
returned reason is made of numbers only (no LLM).
"""
from __future__ import annotations

from typing import Optional

import yaml

from models.twin.chlorine import load_network, monte_carlo_residuals


def _population_map() -> dict[str, int]:
    c = yaml.safe_load(open("config/campus.yaml", encoding="utf-8"))
    return {h["id"]: int(h["population"]) for h in c["hostels"]}


def rank_tests(water_temp_c: float, chlorine_demand_mg_l: float, dose_mg_l: float,
               model: Optional[dict] = None, n_mc: int = 300,
               seed: Optional[int] = None, target: float = 0.2) -> dict:
    model = model or load_network()
    pop = _population_map()
    res = monte_carlo_residuals(model, dose_mg_l, water_temp_c, chlorine_demand_mg_l,
                                n_mc=n_mc, seed=seed, target_mg_l=target)
    ranked = []
    for node_id, q in res["nodes"].items():
        if not (node_id.startswith("H") and "_" not in node_id):
            continue
        width = max(0.0, q["p90"] - q["p10"])
        population = pop.get(node_id, 0)
        voi = q["p_below"] * population * width
        ranked.append({
            "site_id": node_id, "voi_score": round(voi, 4),
            "p_residual_below_target": q["p_below"],
            "population_served": population,
            "uncertainty_width_mg_l": round(width, 4),
            "p10_residual_mg_l": q["p10"],
        })
    ranked.sort(key=lambda r: r["voi_score"], reverse=True)
    top = ranked[0] if ranked else None
    reason = None
    if top:
        reason = (f"Test {top['site_id']}: P(residual<{target})="
                  f"{top['p_residual_below_target']:.2f} x pop {top['population_served']} "
                  f"x uncertainty {top['uncertainty_width_mg_l']:.2f} mg/L "
                  f"= VOI {top['voi_score']:.2f} (p10 residual {top['p10_residual_mg_l']:.3f})")
    return {"test_next_site_id": top["site_id"] if top else None,
            "test_next_reason": reason, "ranking": ranked,
            "inputs": {"water_temp_c": water_temp_c, "demand_mg_l": chlorine_demand_mg_l,
                       "dose_mg_l": dose_mg_l, "target": target, "n_mc": n_mc}}


if __name__ == "__main__":
    r = rank_tests(25.0, 0.8, 2.0)
    print(r["test_next_reason"])
    for x in r["ranking"][:5]:
        print(" ", x)

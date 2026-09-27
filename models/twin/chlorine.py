"""Source-to-tap chlorine twin (P6, Part B §5) — DETERMINISTIC, unit-tested.

First-order decay:   C(t) = C0 * exp(-k * t)
Bulk decay at temp:  k_b(T) = k_b20 * theta^(T-20)
In tank/reservoir:   k = k_b(T)
In pipes:            k = k_b(T) + k_w_eff

Chlorine demand D (immediate, turbidity-driven) is consumed first: the effective
starting residual leaving the WTP is max(0, dose - D). Then the residual decays
along the path (pipe travel + tank residence), each segment with its own k and
time. Monte Carlo over parameter/time uncertainty gives p10/p50/p90 at every node.

This is a SAFETY number generator (Part A rule 4): pure Python, no LLM. Every
result is returned WITH its uncertainty and the inputs used (Part A §7).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

SILVER = Path("data/silver")


def k_bulk_per_day(temp_c: float, k_b20: float, theta: float) -> float:
    """Bulk chlorine decay rate (day^-1) at water temperature `temp_c`."""
    return k_b20 * (theta ** (temp_c - 20.0))


def residual_along_path(dose_mg_l: float, demand_mg_l: float, temp_c: float,
                        path: list[dict], k_b20: float, theta: float,
                        k_wall_scale: float = 1.0,
                        time_scale: Optional[list[float]] = None) -> float:
    """Deterministic residual (mg/L) at the end of `path` for one parameter set.

    `time_scale` optionally multiplies each segment's nominal time (for MC).
    """
    kb = k_bulk_per_day(temp_c, k_b20, theta)
    c = max(0.0, dose_mg_l - demand_mg_l)  # immediate demand consumed
    for i, seg in enumerate(path):
        t_h = seg["time_h"] * (time_scale[i] if time_scale else 1.0)
        t_days = max(0.0, t_h) / 24.0
        k = kb + (seg["k_wall"] * k_wall_scale if seg["type"] == "pipe" else 0.0)
        c *= np.exp(-k * t_days)
    return float(c)


def _params():
    return yaml.safe_load(open("config/params.yaml", encoding="utf-8"))


def monte_carlo_residuals(model: dict, dose_mg_l: float, temp_c: float,
                          demand_mg_l: float, n_mc: int = 500,
                          seed: Optional[int] = None,
                          params: Optional[dict] = None) -> dict:
    """Return {node_id: {p10,p50,p90,mean}} plus 'inputs'. MC over k_b20, demand
    noise, segment times and wall-decay noise."""
    params = params or _params()
    ch = params["chlorine"]
    seed = seed if seed is not None else params["seed"]
    rng = np.random.default_rng(seed)

    kb_lo, kb_hi = ch["k_b20"]["min"], ch["k_b20"]["max"]
    theta = ch["theta"]["value"]
    eps_sd = params["chlorine_demand"]["epsilon_sd"]

    paths = model["paths"]
    # pre-sample global params per MC iteration
    kb_samples = rng.uniform(kb_lo, kb_hi, n_mc)
    demand_samples = np.clip(rng.normal(demand_mg_l, eps_sd, n_mc), 0.0, None)
    kwall_scale = np.clip(rng.normal(1.0, 0.2, n_mc), 0.3, None)

    results: dict[str, dict] = {}
    for node_id, path in paths.items():
        # per-iteration time jitter for this node's segments
        vals = np.empty(n_mc)
        for m in range(n_mc):
            tscale = []
            for seg in path:
                sd_frac = (seg["time_sd"] / seg["time_h"]) if seg["time_h"] else 0.0
                tscale.append(max(0.0, rng.normal(1.0, sd_frac)))
            vals[m] = residual_along_path(
                dose_mg_l, demand_samples[m], temp_c, path,
                kb_samples[m], theta, kwall_scale[m], tscale)
        p10, p50, p90 = np.percentile(vals, [10, 50, 90])
        results[node_id] = {"p10": round(float(p10), 4), "p50": round(float(p50), 4),
                            "p90": round(float(p90), 4), "mean": round(float(vals.mean()), 4)}
    return {"nodes": results,
            "inputs": {"dose_mg_l": dose_mg_l, "water_temp_c": temp_c,
                       "chlorine_demand_mg_l": demand_mg_l, "n_mc": n_mc,
                       "seed": seed, "theta": theta,
                       "k_b20_range": [kb_lo, kb_hi]}}


def load_network() -> dict:
    p = SILVER / "campus_network.json"
    if not p.exists():
        from pipeline.synthetic.network import persist
        persist()
    return json.loads((SILVER / "campus_network.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    model = load_network()
    res = monte_carlo_residuals(model, dose_mg_l=2.0, temp_c=25.0, demand_mg_l=0.8)
    print("inputs:", res["inputs"])
    # worst hostel tap by p10
    hostels = {k: v for k, v in res["nodes"].items() if k.startswith("H") and "_" not in k}
    worst = min(hostels.items(), key=lambda kv: kv[1]["p10"])
    print(f"worst hostel tap: {worst[0]} p10={worst[1]['p10']} p50={worst[1]['p50']} p90={worst[1]['p90']}")
    for hid in sorted(hostels)[:5]:
        print(f"  {hid}: p10={hostels[hid]['p10']} p50={hostels[hid]['p50']}")

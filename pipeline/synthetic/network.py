"""Synthetic IITG distribution network (P6, Part B §5).

Builds the campus graph WTP -> reservoir -> hostel tanks -> coolers/RO units from
config/campus.yaml, sampling pipe travel times and wall-decay coefficients from
config/params.yaml with the FIXED seed so output is byte-reproducible (Part A
rule 3). All rows are provenance=synthetic with generator name+version+seed in
source_ref. Nothing here is a real measurement — the app badges it "simulated".

Persists:
  data/silver/network_edges.parquet   (core NetworkEdge schema)
  data/silver/network_sites.parquet   (synthetic Site rows)
  data/silver/campus_network.json     (nodes+edges+paths for the chlorine twin)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from pipeline.schemas import NetworkEdge, Provenance, Site, SiteKind, write_table

SILVER = Path("data/silver")


def _cfg():
    campus = yaml.safe_load(open("config/campus.yaml", encoding="utf-8"))
    params = yaml.safe_load(open("config/params.yaml", encoding="utf-8"))
    return campus, params


def _gen_ref(params: dict) -> str:
    return (f"generator=pipeline.synthetic.network@{params['generator_version']} "
            f"seed={params['seed']} | SIMULATED (team-estimate params, Part B §5)")


def _dist_to_travel_h(dist_m: float, max_dist_m: float, lo: float, hi: float) -> float:
    """Map a pipe length to a travel time within the team-estimate [lo,hi] h band."""
    frac = 0.0 if max_dist_m <= 0 else min(1.0, dist_m / max_dist_m)
    return lo + frac * (hi - lo)


def build_network(seed: Optional[int] = None) -> dict:
    """Return the network model: nodes (with residence_h), edges (time + k_wall),
    and precomputed WTP->node paths of segments. Deterministic given the seed."""
    campus, params = _cfg()
    seed = seed if seed is not None else params["seed"]
    rng = np.random.default_rng(seed)

    net = params["network"]
    t_lo, t_hi = net["pipe_travel_time_h"]["min"], net["pipe_travel_time_h"]["max"]
    tr_lo, tr_hi = net["tank_residence_time_h"]["min"], net["tank_residence_time_h"]["max"]
    kw_lo, kw_hi = params["chlorine"]["k_w_eff"]["min"], params["chlorine"]["k_w_eff"]["max"]

    hostels = campus["hostels"]
    max_dist = max(h["dist_from_reservoir_m"] for h in hostels)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    # --- fixed infrastructure nodes ---
    reservoir_cfg = next(n for n in campus["nodes"] if n["id"] == "reservoir")
    nodes["wtp"] = {"kind": "wtp", "residence_h": 0.0}
    nodes["reservoir"] = {"kind": "reservoir",
                          "residence_h": float(reservoir_cfg["storage_hours_demand"]) * 0.25}
    # WTP -> reservoir: short main
    wtp_res_t = _dist_to_travel_h(150, max_dist, t_lo, t_hi)
    edges.append({"from_site_id": "wtp", "to_site_id": "reservoir",
                  "travel_time_h_mean": round(wtp_res_t, 3),
                  "travel_time_h_sd": round(wtp_res_t * 0.2, 3),
                  "pipe_k_wall_per_day": round(float(rng.uniform(kw_lo, kw_hi)), 3)})

    # --- hostels + point-of-use ---
    for h in hostels:
        hid = h["id"]
        dist = h["dist_from_reservoir_m"]
        travel = _dist_to_travel_h(dist, max_dist, t_lo, t_hi)
        residence = float(rng.uniform(tr_lo, tr_hi))
        nodes[hid] = {"kind": "hostel_tank", "residence_h": round(residence, 2),
                      "population": h["population"]}
        edges.append({"from_site_id": "reservoir", "to_site_id": hid,
                      "travel_time_h_mean": round(travel, 3),
                      "travel_time_h_sd": round(travel * 0.25, 3),
                      "pipe_k_wall_per_day": round(float(rng.uniform(kw_lo, kw_hi)), 3)})
        # point-of-use devices (short pipe, negligible residence)
        for kind, suffix in (("cooler", "cooler"), ("ro_unit", "ro")):
            nid = f"{hid}_{suffix}"
            pou_t = _dist_to_travel_h(30, max_dist, t_lo, t_hi)
            nodes[nid] = {"kind": kind, "residence_h": 0.5}
            edges.append({"from_site_id": hid, "to_site_id": nid,
                          "travel_time_h_mean": round(pou_t, 3),
                          "travel_time_h_sd": round(pou_t * 0.25, 3),
                          "pipe_k_wall_per_day": round(float(rng.uniform(kw_lo, kw_hi)), 3)})

    # --- precompute WTP -> node paths as ordered segments ---
    edge_by_to = {e["to_site_id"]: e for e in edges}

    def path_to(node_id: str) -> list[dict]:
        segs: list[dict] = []
        chain = []
        cur = node_id
        while cur in edge_by_to:
            e = edge_by_to[cur]
            chain.append(e)
            cur = e["from_site_id"]
        chain.reverse()
        for e in chain:
            # pipe travel segment
            segs.append({"type": "pipe", "from": e["from_site_id"], "to": e["to_site_id"],
                         "time_h": e["travel_time_h_mean"], "time_sd": e["travel_time_h_sd"],
                         "k_wall": e["pipe_k_wall_per_day"]})
            # residence at the destination node (tank/reservoir)
            res = nodes[e["to_site_id"]].get("residence_h", 0.0)
            if res > 0:
                segs.append({"type": "residence", "from": e["to_site_id"], "to": e["to_site_id"],
                             "time_h": res, "time_sd": res * 0.15, "k_wall": 0.0})
        return segs

    paths = {nid: path_to(nid) for nid in nodes if nid != "wtp"}

    return {"seed": seed, "nodes": nodes, "edges": edges, "paths": paths,
            "generator_version": params["generator_version"]}


def persist(model: Optional[dict] = None) -> dict:
    campus, params = _cfg()
    model = model or build_network()
    ref = _gen_ref(params)
    SILVER.mkdir(parents=True, exist_ok=True)

    # network_edges (core schema)
    edge_rows = [{**e, "provenance": Provenance.synthetic,
                  "source_id": "synthetic_network", "source_ref": ref}
                 for e in model["edges"]]
    write_table(edge_rows, SILVER / "network_edges.parquet", NetworkEdge)

    # synthetic sites
    kind_map = {"wtp": SiteKind.wtp, "reservoir": SiteKind.reservoir,
                "hostel_tank": SiteKind.hostel_tank, "cooler": SiteKind.cooler,
                "ro_unit": SiteKind.ro_unit}
    site_rows = []
    for nid, n in model["nodes"].items():
        site_rows.append({
            "site_id": nid, "name": nid, "kind": kind_map[n["kind"]],
            "lat": None, "lon": None,
            "population_served": n.get("population"),
            "notes": f"residence_h={n.get('residence_h', 0)}",
            "provenance": Provenance.synthetic, "source_id": "synthetic_network",
            "source_ref": ref})
    write_table(site_rows, SILVER / "network_sites.parquet", Site)

    # full model json for the twin
    (SILVER / "campus_network.json").write_text(
        json.dumps({**model, "source_ref": ref}, indent=2), encoding="utf-8")

    return {"n_nodes": len(model["nodes"]), "n_edges": len(model["edges"]),
            "n_paths": len(model["paths"])}


if __name__ == "__main__":
    s = persist()
    print("synthetic network:", s)

"""Consumer-mode area water-quality picture (P5).

For a lat/lon, find the nearest CPCB groundwater stations (real, public) and the
nearest river station, report which parameters were tested, when, and which
exceeded BIS IS 10500 limits — always showing the data's age and distance so the
user sees how old/far the evidence is. Optionally folds in the virtual-sensor
river NDTI state when available (P7).

Safety judgement here is a deterministic BIS-limit comparison, not an LLM call.
We never call water "unsafe"; we report exceedances of a published standard with
their date and distance, and defer confirmation to an authority (Part A rule 9).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

SILVER = Path("data/silver")
GOLD = Path("data/gold")

# BIS IS 10500 drinking-water limits (acceptable, permissible). None = no limit
# for that direction. Coliform: any presence is a fail.
BIS_LIMITS = {
    "ph": {"lo": 6.5, "hi": 8.5, "unit": "pH"},
    "tds_mg_l": {"hi_accept": 500, "hi_permiss": 2000, "unit": "mg/L"},
    "fluoride_mg_l": {"hi_accept": 1.0, "hi_permiss": 1.5, "unit": "mg/L"},
    "arsenic_mg_l": {"hi_accept": 0.01, "hi_permiss": 0.05, "unit": "mg/L"},
    "nitrate_n_mg_l": {"hi_accept": 45.0, "unit": "mg/L"},  # NO3 as N proxy
    "total_coliform_mpn_100ml": {"hi_accept": 0.0, "unit": "MPN/100mL"},
    "fecal_coliform_mpn_100ml": {"hi_accept": 0.0, "unit": "MPN/100mL"},
}


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _load(name: str) -> Optional[pd.DataFrame]:
    p = SILVER / name
    return pd.read_parquet(p) if p.exists() else None


def _nearest_sites(sites: pd.DataFrame, lat: float, lon: float, k: int) -> pd.DataFrame:
    s = sites.dropna(subset=["lat", "lon"]).copy()
    s["distance_km"] = s.apply(
        lambda r: _haversine_km(lat, lon, r["lat"], r["lon"]), axis=1)
    return s.nsmallest(k, "distance_km")


def _bis_check(param_base: str, value: float) -> Optional[dict]:
    """Return an exceedance dict if `value` breaches a BIS limit, else None."""
    lim = BIS_LIMITS.get(param_base)
    if lim is None or value is None:
        return None
    if "lo" in lim and "hi" in lim:  # pH band
        if value < lim["lo"] or value > lim["hi"]:
            return {"limit": f"{lim['lo']}-{lim['hi']}", "value": value, "kind": "outside_band"}
        return None
    accept = lim.get("hi_accept")
    permiss = lim.get("hi_permiss")
    if accept is not None and value > accept:
        level = "above_permissible" if (permiss and value > permiss) else "above_acceptable"
        ref = permiss if (permiss and value > permiss) else accept
        return {"limit": ref, "value": value, "kind": level}
    return None


def _base(param: str) -> str:
    for suf in ("_min", "_max", "_mean"):
        if param.endswith(suf):
            return param[: -len(suf)]
    return param


def area_risk(lat: float, lon: float, k_gw: int = 3) -> dict:
    """Plain-language area water-quality picture for a location."""
    gw_sites = _load("cpcb_gw_sites.parquet")
    gw_obs = _load("cpcb_groundwater.parquet")
    river_sites = _load("cpcb_sites.parquet")

    out = {"query": {"lat": lat, "lon": lon},
           "generated_at": datetime.now(timezone.utc).isoformat(),
           "groundwater": [], "river": None,
           "what_this_cannot_tell_you": (
               "This uses the nearest CPCB monitoring stations, which may be far "
               "away and sampled only once or twice a year. It cannot tell you "
               "what is in YOUR tap today. Only a fresh local test can. NDTI (river) "
               "is a relative turbidity signal, not a bacterial or chemical result."),
           "sources": ["cpcb_nwmp_gw", "cpcb_nwmp_river"],
           "notes": []}

    if gw_sites is None or gw_obs is None:
        out["notes"].append("No CPCB groundwater data available.")
    else:
        near = _nearest_sites(gw_sites, lat, lon, k_gw)
        gw_obs = gw_obs.copy()
        gw_obs["year"] = pd.to_datetime(gw_obs["ts"]).dt.year
        for _, site in near.iterrows():
            sid = site["site_id"]
            srows = gw_obs[gw_obs["site_id"] == sid]
            if srows.empty:
                continue
            latest_year = int(srows["year"].max())
            latest = srows[srows["year"] == latest_year]
            params, exceed = {}, []
            for _, r in latest.iterrows():
                base = _base(r["parameter"])
                if r["value"] is None or pd.isna(r["value"]):
                    continue
                # use the max stat for exceedance checks (worst observed)
                params.setdefault(base, r["value"])
                if r["parameter"].endswith("_max"):
                    params[base] = r["value"]
            for base, val in params.items():
                ex = _bis_check(base, val)
                if ex:
                    exceed.append({"parameter": base, **ex,
                                   "unit": BIS_LIMITS[base]["unit"]})
            out["groundwater"].append({
                "site_id": sid, "name": site["name"],
                "distance_km": round(site["distance_km"], 1),
                "data_year": latest_year,
                "data_age_years": datetime.now(timezone.utc).year - latest_year,
                "parameters_tested": sorted(params.keys()),
                "bis_exceedances": exceed,
            })

    # nearest river station (context; virtual-sensor state folded in when P7 lands)
    if river_sites is not None:
        rnear = _nearest_sites(river_sites, lat, lon, 1)
        if not rnear.empty:
            rs = rnear.iloc[0]
            out["river"] = {"site_id": rs["site_id"], "name": rs["name"],
                            "distance_km": round(rs["distance_km"], 1)}
    vs = GOLD / "virtual_sensor_daily.parquet"
    if vs.exists():
        try:
            vdf = pd.read_parquet(vs)
            last = vdf.sort_values("date").iloc[-1]
            out["river"] = (out["river"] or {})
            out["river"]["virtual_sensor_ndti_p50"] = float(last.get("ndti_p50"))
            out["river"]["virtual_sensor_date"] = str(last.get("date"))
        except Exception:  # noqa: BLE001
            pass

    # plain-language summary
    n_ex = sum(len(g["bis_exceedances"]) for g in out["groundwater"])
    if not out["groundwater"]:
        out["summary"] = "No nearby CPCB groundwater station data found."
    elif n_ex == 0:
        g = out["groundwater"][0]
        out["summary"] = (
            f"Nearest tested groundwater is {g['distance_km']} km away "
            f"({g['name']}), last tested in {g['data_year']} "
            f"({g['data_age_years']} yr ago). No BIS IS 10500 exceedances in the "
            f"parameters tested ({', '.join(g['parameters_tested'])}). This is old, "
            f"distant evidence — not your tap today.")
    else:
        parts = []
        for g in out["groundwater"]:
            for e in g["bis_exceedances"]:
                parts.append(f"{e['parameter']}={e['value']} ({e['kind']}, "
                             f"limit {e['limit']}) at {g['name']} "
                             f"[{g['distance_km']} km, {g['data_year']}]")
        out["summary"] = ("Nearby CPCB groundwater shows BIS exceedances: "
                          + "; ".join(parts) + ". These are from past yearly "
                          "samples at distant stations, not your tap — get a "
                          "local test to confirm.")
    return out


if __name__ == "__main__":
    tests = {
        "Guwahati Pandu": (26.176, 91.684),
        "Guwahati Panbazar": (26.183, 91.746),
        "Guwahati Beltola": (26.126, 91.800),
        "IITG campus": (26.192, 91.699),
    }
    import json
    for name, (la, lo) in tests.items():
        r = area_risk(la, lo)
        print(f"\n=== {name} ({la},{lo}) ===")
        print(r["summary"])
        for g in r["groundwater"]:
            print(f"  - {g['name']} [{g['distance_km']} km, {g['data_year']}]: "
                  f"{len(g['bis_exceedances'])} exceedance(s)")

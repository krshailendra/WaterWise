"""Twin drivers (P6 steps 3-4): daily water temperature and chlorine demand.

water_temp (provenance=modelled): real Open-Meteo air temperature (P2), lagged
and smoothed, then CLIPPED to the NWMP seasonal envelope observed at the city
stations (real CPCB water-temp min/max, P1). Real data + model -> modelled.

chlorine_demand (provenance=modelled): D = d0 + a*norm(NDTI) + eps, using the
real Sentinel-2 NDTI (P3) forward-filled to daily. d0, a are team estimates
(params.yaml, Part B §5); eps noise is added by the twin's Monte Carlo, so the
daily driver here uses the mean relationship.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

SILVER = Path("data/silver")


def _params():
    return yaml.safe_load(open("config/params.yaml", encoding="utf-8"))


def nwmp_temp_envelope() -> tuple[float, float]:
    """(min,max) water temperature from real CPCB city-station records."""
    df = pd.read_parquet(SILVER / "cpcb_river.parquet")
    t = df[df["parameter"].isin(["water_temp_c_min", "water_temp_c_max"])]["value"].dropna()
    if t.empty:
        return (10.0, 32.0)
    return (float(max(2.0, t.min())), float(min(40.0, t.max())))


def water_temp_daily(site_id: str = "cpcb_pandu") -> pd.DataFrame:
    """Daily modelled water temperature series for a city/intake point."""
    p = _params()["water_temperature"]
    lag = int(p["air_to_water_lag_days"])
    win = int(p["smoothing_window_days"])
    lo, hi = nwmp_temp_envelope()

    hm = pd.read_parquet(SILVER / "hydromet.parquet")
    air = hm[(hm["parameter"] == "air_temp_c_mean") & (hm["site_id"] == site_id)].copy()
    if air.empty:  # fall back to any weather point
        air = hm[hm["parameter"] == "air_temp_c_mean"].copy()
    air["date"] = pd.to_datetime(air["ts"]).dt.tz_localize(None).dt.normalize()
    air = air.sort_values("date").drop_duplicates("date")
    s = air.set_index("date")["value"].astype(float)
    # lag then smooth
    water = s.shift(lag).rolling(win, min_periods=1).mean()
    water = water.clip(lower=lo, upper=hi)
    out = water.reset_index().rename(columns={"value": "water_temp_c"})
    out = out.dropna(subset=["water_temp_c"])
    out["site_id"] = site_id
    out["provenance"] = "modelled"
    out["source_id"] = "openmeteo_archive+cpcb_nwmp_river"
    out["source_ref"] = (f"modelled water temp: air_temp lag={lag}d smooth={win}d "
                         f"clipped to NWMP envelope [{lo:.1f},{hi:.1f}] degC")
    return out[["date", "site_id", "water_temp_c", "provenance", "source_id", "source_ref"]]


def _ndti_daily() -> pd.DataFrame:
    """Daily NDTI: prefer virtual-sensor (P7) if present, else forward-filled S2."""
    vs = Path("data/gold/virtual_sensor_daily.parquet")
    if vs.exists():
        v = pd.read_parquet(vs)
        v["date"] = pd.to_datetime(v["date"])
        return v[["date", "ndti_p50"]].rename(columns={"ndti_p50": "ndti"})
    s2 = pd.read_parquet(SILVER / "s2_ndti.parquet")
    med = s2[(s2["parameter"] == "ndti_median") & (s2["site_id"] == "guwahati_reach")].copy()
    med["date"] = pd.to_datetime(med["ts"]).dt.tz_localize(None).dt.normalize()
    med = med.sort_values("date").drop_duplicates("date")[["date", "value"]]
    med = med.rename(columns={"value": "ndti"})
    # daily index, forward-fill (honest: cloudy-day gaps filled by last clear scene)
    idx = pd.date_range(med["date"].min(), med["date"].max(), freq="D")
    med = med.set_index("date").reindex(idx).ffill().rename_axis("date").reset_index()
    return med


def chlorine_demand_daily() -> pd.DataFrame:
    """Daily modelled chlorine demand D = d0 + a*norm(NDTI) (mean relationship)."""
    cd = _params()["chlorine_demand"]
    d0 = (cd["d0"]["min"] + cd["d0"]["max"]) / 2.0
    a = (cd["a"]["min"] + cd["a"]["max"]) / 2.0
    ndti = _ndti_daily()
    n = ndti["ndti"].astype(float)
    # normalise NDTI to [0,1] over its observed range
    lo, hi = n.min(), n.max()
    norm = (n - lo) / (hi - lo) if hi > lo else n * 0.0
    ndti = ndti.assign(chlorine_demand_mg_l=(d0 + a * norm).round(4))
    ndti["provenance"] = "modelled"
    ndti["source_id"] = "s2_l2a+team_estimate"
    ndti["source_ref"] = (f"D=d0+a*norm(NDTI); d0={d0:.2f} a={a:.2f} (TEAM ESTIMATE, "
                          f"Part B §5); NDTI from Sentinel-2, forward-filled")
    return ndti[["date", "ndti", "chlorine_demand_mg_l", "provenance", "source_id", "source_ref"]]


def persist() -> dict:
    wt = water_temp_daily()
    cd = chlorine_demand_daily()
    wt.to_parquet(SILVER / "water_temp_daily.parquet", index=False)
    cd.to_parquet(SILVER / "chlorine_demand_daily.parquet", index=False)
    return {"water_temp_days": len(wt),
            "water_temp_range": [round(wt["water_temp_c"].min(), 1), round(wt["water_temp_c"].max(), 1)],
            "demand_days": len(cd),
            "demand_range": [round(cd["chlorine_demand_mg_l"].min(), 3), round(cd["chlorine_demand_mg_l"].max(), 3)]}


if __name__ == "__main__":
    print("drivers:", persist())

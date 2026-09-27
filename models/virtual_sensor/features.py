"""Virtual river sensor features (P7) — built from REAL data only.

Daily features: upstream rainfall lagged 0-10 d + rolling sums, GloFAS discharge
and its 1/3/7-day changes at upstream & city points, air temperature, and
day-of-year sin/cos. Target = Sentinel-2 NDTI median for the Guwahati reach on
clear-scene days (NaN otherwise). No synthetic inputs (Part B §4).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SILVER = Path("data/silver")

RAIN_POINTS = ["rain_pasighat", "rain_dibrugarh", "rain_tezpur", "rain_guwahati"]
FLOW_POINTS = ["flow_dibrugarh", "flow_tezpur", "flow_chandrapur", "flow_pandu"]
RAIN_LAGS = list(range(0, 11))          # 0..10 days
TARGET_SITE = "guwahati_reach"


def _pivot(param: str) -> pd.DataFrame:
    hm = pd.read_parquet(SILVER / "hydromet.parquet")
    d = hm[hm["parameter"] == param].copy()
    d["date"] = pd.to_datetime(d["ts"]).dt.tz_localize(None).dt.normalize()
    return d.pivot_table(index="date", columns="site_id", values="value").sort_index()


def build_features() -> pd.DataFrame:
    rain = _pivot("rain_mm")
    disch = _pivot("discharge_m3s")
    air = _pivot("air_temp_c_mean")

    idx = pd.date_range(min(rain.index.min(), disch.index.min()),
                        max(rain.index.max(), disch.index.max()), freq="D")
    feat = pd.DataFrame(index=idx)

    # rainfall lags + rolling sums at upstream points
    for pt in RAIN_POINTS:
        if pt not in rain.columns:
            continue
        s = rain[pt].reindex(idx)
        for lag in RAIN_LAGS:
            feat[f"{pt}_rain_lag{lag}"] = s.shift(lag)
        feat[f"{pt}_rain_roll3"] = s.rolling(3, min_periods=1).sum()
        feat[f"{pt}_rain_roll7"] = s.rolling(7, min_periods=1).sum()

    # discharge levels + 1/3/7-day changes
    for pt in FLOW_POINTS:
        if pt not in disch.columns:
            continue
        s = disch[pt].reindex(idx)
        feat[f"{pt}_disch"] = s
        feat[f"{pt}_disch_d1"] = s.diff(1)
        feat[f"{pt}_disch_d3"] = s.diff(3)
        feat[f"{pt}_disch_d7"] = s.diff(7)

    # air temperature (city/intake average)
    air_cols = [c for c in air.columns if c in ("cpcb_pandu", "iitg_intake", "rain_guwahati")]
    if air_cols:
        feat["air_temp_c"] = air[air_cols].reindex(idx).mean(axis=1)

    # seasonality
    doy = feat.index.dayofyear
    feat["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    feat["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    # target: S2 NDTI median (clear-scene days only)
    s2 = pd.read_parquet(SILVER / "s2_ndti.parquet")
    tgt = s2[(s2["parameter"] == "ndti_median") & (s2["site_id"] == TARGET_SITE)].copy()
    tgt["date"] = pd.to_datetime(tgt["ts"]).dt.tz_localize(None).dt.normalize()
    tgt = tgt.set_index("date")["value"].rename("ndti_target")
    feat = feat.join(tgt, how="left")

    feat.index.name = "date"
    return feat


if __name__ == "__main__":
    f = build_features()
    print("feature frame:", f.shape, "| features:", f.shape[1] - 1)
    print("labelled (clear-scene) days:", int(f["ndti_target"].notna().sum()))
    print("date range:", f.index.min().date(), "->", f.index.max().date())

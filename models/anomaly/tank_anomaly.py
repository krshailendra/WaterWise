"""Tank anomaly detection (P8) — DETERMINISTIC robust z-score.

A dirty tank raises the bulk decay in that tank (k_b x 2-4), so its residual falls
BELOW what the twin expects for that hostel on that day. We:

1. reconstruct the EXPECTED residual (no anomaly) for each hostel/day from the
   twin, using the dose/temperature/demand recorded in each reading's source_ref;
2. form the ratio observed/expected (isolates the tank state from shared daily
   dose/temp/demand);
3. flag hostel-days whose ratio is an outlier LOW via a robust z-score
   (median/MAD) of each hostel's own ratio series.

Evaluated against the labelled `anomaly_labels.parquet` (synthetic scenarios) →
precision/recall, reported honestly as "on synthetic scenarios".
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from models.twin.chlorine import k_bulk_per_day, load_network

SILVER = Path("data/silver")


def _params():
    return yaml.safe_load(open("config/params.yaml", encoding="utf-8"))


def _expected_residual(dose, demand, temp, path, k_b20, theta):
    kb = k_bulk_per_day(temp, k_b20, theta)
    c = max(0.0, dose - demand)
    for seg in path:
        t_days = max(0.0, seg["time_h"]) / 24.0
        k = kb + (seg["k_wall"] if seg["type"] == "pipe" else 0.0)
        c *= np.exp(-k * t_days)
    return c


def _parse(ref: str, key: str):
    m = re.search(rf"{key}=([0-9.]+)", ref or "")
    return float(m.group(1)) if m else None


def detect(z_threshold: float = 3.5, ratio_floor: float = 0.7) -> dict:
    params = _params()
    ch = params["chlorine"]
    k_b20, theta = ch["k_b20"]["median"], ch["theta"]["value"]
    model = load_network()

    df = pd.read_parquet(SILVER / "tap_readings.parquet")
    df = df[df["value"].notna() & (df["quality_flag"] != "suspect")].copy()
    df["date"] = pd.to_datetime(df["ts"]).dt.tz_localize(None).dt.normalize()
    df["dose"] = df["source_ref"].map(lambda r: _parse(r, "dose"))
    df["temp"] = df["source_ref"].map(lambda r: _parse(r, "temp"))
    df["demand"] = df["source_ref"].map(lambda r: _parse(r, "demand"))

    exp_vals = []
    for _, r in df.iterrows():
        path = model["paths"].get(r["site_id"])
        if path is None or r["dose"] is None:
            exp_vals.append(np.nan)
            continue
        exp_vals.append(_expected_residual(r["dose"], r["demand"], r["temp"],
                                           path, k_b20, theta))
    df["expected"] = exp_vals
    # Only assess where the expected residual is above the 0.1 mg/L kit resolution
    # by a margin: below that, rounding makes observed/expected meaningless and low
    # residual is caught by the low-residual alert, not the decay-anomaly detector.
    df = df[df["expected"] > 0.15]
    df["ratio"] = df["value"] / df["expected"]

    # robust z of each hostel's SMOOTHED ratio series. Dirty-tank anomalies are
    # sustained (3-10 d), so a centred 3-day rolling median suppresses the DPD
    # instrument-noise spikes that otherwise dominate low-residual far hostels.
    flags = []
    for hid, g in df.groupby("site_id"):
        g = g.sort_values("date")
        ratio_s = g["ratio"].rolling(3, center=True, min_periods=2).median()
        med = ratio_s.median()
        mad = (ratio_s - med).abs().median() * 1.4826
        if mad < 1e-6:
            mad = ratio_s.std() or 1e-6
        z = (ratio_s - med) / mad
        gg = g.assign(z=z, ratio_s=ratio_s)
        # anomaly = robustly low z AND a physically meaningful drop (ratio_floor):
        # a dirty tank (k x 2-4) drops the residual to ~0.3-0.55 of expected,
        # whereas DPD noise/rounding keeps the smoothed ratio near 1.
        flagged = gg[(gg["z"] < -z_threshold) & (gg["ratio_s"] < ratio_floor)]
        for _, r in flagged.iterrows():
            flags.append({"site_id": hid, "date": r["date"], "z": round(float(r["z"]), 2),
                          "ratio": round(float(r["ratio_s"]), 3)})
    pred = pd.DataFrame(flags)

    # evaluate vs labels
    labels = pd.read_parquet(SILVER / "anomaly_labels.parquet")
    labels["start_date"] = pd.to_datetime(labels["start_date"]).dt.tz_localize(None)
    labels["end_date"] = pd.to_datetime(labels["end_date"]).dt.tz_localize(None)

    def is_true(site, date):
        w = labels[labels["site_id"] == site]
        return bool(((w["start_date"] <= date) & (date < w["end_date"])).any())

    # true anomaly hostel-days present in the data
    true_days = set()
    for _, lab in labels.iterrows():
        for d in pd.date_range(lab["start_date"], lab["end_date"] - pd.Timedelta(days=1)):
            true_days.add((lab["site_id"], d.normalize()))
    data_days = set(zip(df["site_id"], df["date"]))
    true_present = true_days & data_days

    pred_days = set(zip(pred["site_id"], pred["date"])) if not pred.empty else set()
    tp = len(pred_days & true_present)
    fp = len(pred_days - true_present)
    fn = len(true_present - pred_days)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0

    return {"z_threshold": z_threshold, "flagged_hostel_days": len(pred_days),
            "true_anomaly_hostel_days": len(true_present),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 3), "recall": round(recall, 3),
            "note": "evaluated on SYNTHETIC anomaly scenarios only",
            "flagged_sites": sorted(pred["site_id"].unique().tolist()) if not pred.empty else []}


if __name__ == "__main__":
    import json
    for zt in (2.5, 3.0, 3.5):
        print(json.dumps(detect(zt), default=str))

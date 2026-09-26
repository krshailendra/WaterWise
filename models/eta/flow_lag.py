"""Flow-wave lag estimation (P2).

Cross-correlate GloFAS river discharge at upstream points against Guwahati
(flow_pandu) during the monsoon (Jun-Sep) to estimate the travel lag in days.

We correlate DAY-TO-DAY CHANGES (first differences), not raw series: raw
discharge is dominated by shared seasonality and would spuriously give lag 0.
First differences isolate the propagating flood wave.

HONEST NOTE (Part B §3, §8): flood-wave celerity is NOT the same as the velocity
of a dissolved pollutant. Incident ETAs (agents/incident_agent.py) use a separate
water-velocity range from params.yaml, not these lags.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SILVER = Path("data/silver")
GOLD = Path("data/gold")
FIGURES = Path("docs/figures")

DOWNSTREAM = "flow_pandu"                 # Guwahati reference
UPSTREAM = ["flow_dibrugarh", "flow_tezpur", "flow_chandrapur", "flow_iitg_intake"]
MAX_LAG_DAYS = 15
MONSOON_MONTHS = (6, 7, 8, 9)


def _discharge_wide() -> pd.DataFrame:
    df = pd.read_parquet(SILVER / "hydromet.parquet")
    df = df[df["parameter"] == "discharge_m3s"].copy()
    df["date"] = pd.to_datetime(df["ts"]).dt.tz_localize(None).dt.normalize()
    wide = df.pivot_table(index="date", columns="site_id", values="value")
    return wide.sort_index()


def _best_lag(up: pd.Series, down: pd.Series, max_lag: int) -> tuple[int, float, list]:
    """Return (best_lag_days, best_corr, per_lag_corr). Positive lag = upstream
    leads downstream by that many days."""
    curve = []
    best = (0, -np.inf)
    for k in range(0, max_lag + 1):
        # correlate up[t] with down[t+k]
        a = up.shift(k)
        common = pd.concat([a, down], axis=1).dropna()
        if len(common) < 30:
            curve.append((k, np.nan))
            continue
        c = float(np.corrcoef(common.iloc[:, 0], common.iloc[:, 1])[0, 1])
        curve.append((k, c))
        if c > best[1]:
            best = (k, c)
    return best[0], best[1], curve


def compute(save_plot: bool = True) -> pd.DataFrame:
    wide = _discharge_wide()
    monsoon = wide[wide.index.month.isin(MONSOON_MONTHS)]
    d_diff = monsoon[DOWNSTREAM].diff()

    results = []
    curves = {}
    for up in UPSTREAM:
        if up not in monsoon.columns:
            continue
        u_diff = monsoon[up].diff()
        lag, corr, curve = _best_lag(u_diff, d_diff, MAX_LAG_DAYS)
        results.append({
            "upstream_site_id": up, "downstream_site_id": DOWNSTREAM,
            "lag_days": lag, "correlation": round(corr, 4),
            "method": "xcorr of monsoon daily discharge first-differences (GloFAS)",
            "provenance": "modelled", "source_id": "openmeteo_flood",
            "source_ref": "flow-wave lag; NOT pollutant velocity (see params.yaml incident_eta)",
        })
        curves[up] = curve

    res = pd.DataFrame(results)
    GOLD.mkdir(parents=True, exist_ok=True)
    res.to_parquet(GOLD / "flow_lags.parquet", index=False)

    if save_plot and curves:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            FIGURES.mkdir(parents=True, exist_ok=True)
            fig, ax = plt.subplots(figsize=(7, 4.5))
            for up, curve in curves.items():
                ks = [k for k, _ in curve]
                cs = [c for _, c in curve]
                ax.plot(ks, cs, marker="o", label=up.replace("flow_", ""))
            ax.set_xlabel("lag (days), upstream leads →")
            ax.set_ylabel("corr of monsoon Δdischarge")
            ax.set_title("Flow-wave lag vs Guwahati (Pandu)\nGloFAS modelled discharge, Jun–Sep")
            ax.legend(); ax.grid(alpha=0.3)
            fig.tight_layout()
            fig.savefig(FIGURES / "flow_lags.png", dpi=120)
            plt.close(fig)
        except Exception as e:  # noqa: BLE001
            print(f"[flow_lag] plot skipped: {e}")

    return res


def gap_report(max_gap_days: int = 3) -> dict:
    """Report any gaps longer than `max_gap_days` per (site, parameter)."""
    df = pd.read_parquet(SILVER / "hydromet.parquet")
    df["date"] = pd.to_datetime(df["ts"]).dt.tz_localize(None).dt.normalize()
    out = {}
    for (sid, param), g in df.groupby(["site_id", "parameter"]):
        dates = pd.Series(sorted(g["date"].unique()))
        diffs = dates.diff().dt.days.dropna()
        big = diffs[diffs > max_gap_days]
        if len(big):
            out[f"{sid}/{param}"] = int(big.max())
    return out


if __name__ == "__main__":
    res = compute()
    print("=" * 60)
    print("Flow-wave lag (P2)")
    print("=" * 60)
    print(res.to_string(index=False))
    gaps = gap_report()
    print("\nGaps > 3 days:", gaps if gaps else "none")

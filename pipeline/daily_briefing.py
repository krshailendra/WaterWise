"""Daily briefing builder (P8): assemble the gold/daily_briefing.parquet row for
any date (historical replay or today) from the deterministic models.

Pulls the day's modelled water temperature + chlorine demand, solves the inverse
dose, ranks the next test (VOI), reads the virtual-sensor NDTI band, and derives a
risk level. Supports multiple dates for demo replay. All safety numbers come from
deterministic code (Part A rule 4).
"""
from __future__ import annotations

from datetime import date as _date
from pathlib import Path
from typing import Optional

import pandas as pd

from models.dose.solver import solve_dose
from models.twin.chlorine import load_network
from models.voi.test_next import rank_tests
from pipeline.schemas import DailyBriefing, Provenance, write_table

SILVER = Path("data/silver")
GOLD = Path("data/gold")
MODEL_VERSIONS = "twin@1.0.0;dose@1.0.0;voi@1.0.0;vsensor_lgbm_q@1.0.0(persistence-prod)"


def _driver_value(parquet: str, date: pd.Timestamp, col: str) -> Optional[float]:
    df = pd.read_parquet(SILVER / parquet)
    df["d"] = pd.to_datetime(df["date"]).dt.normalize()
    row = df[df["d"] == date.normalize()]
    if row.empty:  # nearest available day
        df["dist"] = (df["d"] - date.normalize()).abs()
        row = df.nsmallest(1, "dist")
    return float(row[col].iloc[0]) if not row.empty else None


def _ndti_band(date: pd.Timestamp):
    vs = GOLD / "virtual_sensor_daily.parquet"
    if not vs.exists():
        return (None, None, None, None)
    df = pd.read_parquet(vs)
    df["d"] = pd.to_datetime(df["date"]).dt.normalize()
    row = df[df["d"] == date.normalize()]
    if row.empty:
        return (None, None, None, None)
    r = row.iloc[0]
    p50_series = df["ndti_p50"]
    pct = float((p50_series <= r["ndti_p50"]).mean() * 100)
    return (float(r["ndti_p10"]), float(r["ndti_p50"]), float(r["ndti_p90"]), pct)


def _anomalies_on(date: pd.Timestamp) -> int:
    lab = SILVER / "anomaly_labels.parquet"
    if not lab.exists():
        return 0
    df = pd.read_parquet(lab)
    df["s"] = pd.to_datetime(df["start_date"]).dt.tz_localize(None)
    df["e"] = pd.to_datetime(df["end_date"]).dt.tz_localize(None)
    return int(((df["s"] <= date) & (date < df["e"])).sum())


def build(date_str: str, n_mc: int = 300) -> dict:
    date = pd.Timestamp(date_str)
    model = load_network()
    temp = _driver_value("water_temp_daily.parquet", date, "water_temp_c") or 25.0
    demand = _driver_value("chlorine_demand_daily.parquet", date, "chlorine_demand_mg_l") or 0.8

    dose = solve_dose(temp, demand, model=model, n_mc=n_mc)
    voi = rank_tests(temp, demand, dose["recommended_dose_mg_l"], model=model, n_mc=n_mc)
    p10, p50, p90, pct = _ndti_band(date)
    anoms = _anomalies_on(date)

    # risk level (deterministic): infeasible dose or high NDTI percentile -> higher
    if not dose["feasible"] or (pct is not None and pct >= 90):
        risk = "high"
    elif dose["recommended_dose_mg_l"] >= 3.0 or (pct is not None and pct >= 75) or anoms > 0:
        risk = "elevated"
    else:
        risk = "normal"

    active_alerts = anoms + (0 if dose["feasible"] else 1)

    row = {
        "date": date.date(),
        "raw_risk_level": risk,
        "ndti_p10": p10, "ndti_p50": p50, "ndti_p90": p90,
        "water_temp_c_est": round(temp, 2),
        "recommended_dose_mg_l": dose["recommended_dose_mg_l"],
        "dose_p90_needed": dose["dose_p90_needed_mg_l"],
        "worst_tap_site_id": dose["worst_tap_site_id"],
        "worst_tap_p10_residual_mg_l": dose["worst_tap_p10_residual_mg_l"],
        "test_next_site_id": voi["test_next_site_id"],
        "test_next_reason": voi["test_next_reason"],
        "active_alerts": active_alerts,
        "model_versions": MODEL_VERSIONS,
        "provenance": Provenance.modelled,
        "source_id": "waterwise_models",
        "source_ref": (f"dose+voi+twin on SIMULATED campus network; drivers modelled "
                       f"from real air-temp+NDTI; demand={demand:.2f} feasible={dose['feasible']}"),
    }
    return {"row": row, "dose": dose, "voi": voi}


def produce(dates: list[str], n_mc: int = 300) -> dict:
    rows, details = [], {}
    for ds in dates:
        b = build(ds, n_mc=n_mc)
        rows.append(b["row"])
        details[ds] = b
    write_table(rows, GOLD / "daily_briefing.parquet", DailyBriefing)
    return {"dates": dates, "rows": len(rows), "details": details}


if __name__ == "__main__":
    import sys, json
    dates = sys.argv[1:] or ["2024-07-15", "2024-01-15", _date.today().isoformat()]
    r = produce(dates)
    for ds in dates:
        row = r["details"][ds]["row"]
        print(f"{ds}: risk={row['raw_risk_level']} dose={row['recommended_dose_mg_l']} "
              f"worst={row['worst_tap_site_id']} p10={row['worst_tap_p10_residual_mg_l']} "
              f"test_next={row['test_next_site_id']} alerts={row['active_alerts']}")

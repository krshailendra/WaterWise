"""Synthetic field-kit tap residual readings (P6 step 5, Part B §5).

For the last 3 years we run the deterministic chlorine twin at each hostel tank
with a realistic historical dose policy, then apply DPD field-kit texture:
instrument noise (+/- max(0.05 mg/L, 10%)), 0.1 mg/L resolution, 5-10% missing
readings, and 0.5% transcription errors. Labelled dirty-tank anomalies (k_b x
2-4 for 3-10 days) are injected and recorded separately for evaluation only.

Everything is provenance=synthetic, method=simulated_sensor, fully reproducible
from the fixed seed (Part A rule 3).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from models.twin.chlorine import k_bulk_per_day, load_network
from pipeline.schemas import Method, Observation, Provenance, QualityFlag, write_table

SILVER = Path("data/silver")
YEARS_BACK = 3


def _params():
    return yaml.safe_load(open("config/params.yaml", encoding="utf-8"))


def _true_residual(dose, demand, temp, path, k_b20, theta, tank_k_mult=1.0):
    """Deterministic residual with an optional dirty-tank decay multiplier."""
    kb = k_bulk_per_day(temp, k_b20, theta)
    c = max(0.0, dose - demand)
    for seg in path:
        t_days = max(0.0, seg["time_h"]) / 24.0
        if seg["type"] == "pipe":
            k = kb + seg["k_wall"]
        else:  # tank/reservoir residence — anomaly inflates bulk decay here
            k = kb * tank_k_mult
        c *= np.exp(-k * t_days)
    return float(c)


def _dose_policy(demand: float, temp: float, rng: np.random.Generator,
                 lo: float, hi: float) -> float:
    """Realistic historical operator dose: cover demand + margin, temp bump."""
    base = demand + 0.8 + 0.02 * max(0.0, temp - 20.0)
    base += rng.normal(0.0, 0.1)  # day-to-day operator variation
    return float(np.clip(round(base / 0.1) * 0.1, lo, hi))


def _inject_anomalies(hostels: list[str], dates: pd.DatetimeIndex,
                      params: dict, rng: np.random.Generator) -> list[dict]:
    ta = params["tank_anomaly"]
    n_anom = max(3, len(hostels) // 3)
    anomalies = []
    for _ in range(n_anom):
        hid = hostels[int(rng.integers(0, len(hostels)))]
        start_i = int(rng.integers(0, len(dates) - 15))
        dur = int(rng.integers(ta["duration_days_min"], ta["duration_days_max"] + 1))
        kmult = float(rng.uniform(ta["k_multiplier_min"], ta["k_multiplier_max"]))
        start = dates[start_i]
        anomalies.append({"site_id": hid, "start_date": start,
                          "end_date": start + timedelta(days=dur),
                          "k_multiplier": round(kmult, 2), "kind": "dirty_tank"})
    return anomalies


def generate(seed: int = None) -> dict:
    params = _params()
    seed = seed if seed is not None else params["seed"]
    rng = np.random.default_rng(seed)
    ch = params["chlorine"]
    k_b20 = ch["k_b20"]["median"]
    theta = ch["theta"]["value"]
    tk = params["test_kit"]
    dlo, dhi = params["dose"]["min_mg_l"], params["dose"]["max_mg_l"]

    model = load_network()
    hostels = [n for n in model["paths"] if n.startswith("H") and "_" not in n]

    wt = pd.read_parquet(SILVER / "water_temp_daily.parquet").set_index("date")["water_temp_c"]
    cd = pd.read_parquet(SILVER / "chlorine_demand_daily.parquet").set_index("date")["chlorine_demand_mg_l"]

    end = pd.Timestamp(datetime.now(timezone.utc).date())
    start = end - pd.Timedelta(days=365 * YEARS_BACK)
    dates = pd.date_range(start, end, freq="D")
    dates = dates[dates.isin(wt.index) & dates.isin(cd.index)]

    anomalies = _inject_anomalies(hostels, dates, params, rng)
    anom_by_site = {}
    for a in anomalies:
        anom_by_site.setdefault(a["site_id"], []).append(a)

    gen_ref = (f"generator=pipeline.synthetic.tap_readings@{params['generator_version']} "
               f"seed={seed} | SIMULATED DPD field readings (Part B §5)")
    retrieved = datetime.now(timezone.utc)

    rows = []
    for hid in hostels:
        path = model["paths"][hid]
        site_anoms = anom_by_site.get(hid, [])
        for d in dates:
            temp = float(wt.loc[d]); demand = float(cd.loc[d])
            dose = _dose_policy(demand, temp, rng, dlo, dhi)
            kmult = 1.0
            for a in site_anoms:
                if a["start_date"] <= d < a["end_date"]:
                    kmult = a["k_multiplier"]
                    break
            true_res = _true_residual(dose, demand, temp, path, k_b20, theta, kmult)

            # --- field-kit texture ---
            if rng.random() < rng.uniform(tk["missing_frac_min"], tk["missing_frac_max"]):
                value, qflag = None, QualityFlag.imputed  # missing reading
            else:
                err = max(tk["dpd_abs_error_mg_l"], tk["dpd_rel_error"] * true_res)
                meas = true_res + rng.normal(0.0, err)
                meas = max(0.0, round(meas / tk["resolution_mg_l"]) * tk["resolution_mg_l"])
                if rng.random() < tk["transcription_error_frac"]:
                    meas = round(meas * rng.choice([0.1, 10.0]), 1)  # transcription slip
                    qflag = QualityFlag.suspect
                else:
                    qflag = QualityFlag.ok
                value = round(float(meas), 2)

            rows.append({
                "site_id": hid, "ts": d.to_pydatetime().replace(tzinfo=timezone.utc),
                "parameter": "residual_cl_mg_l", "value": value, "unit": "mg/L",
                "method": Method.simulated_sensor, "provenance": Provenance.synthetic,
                "source_id": "synthetic_tap_readings",
                "source_ref": f"{gen_ref} | dose={dose} temp={temp:.1f} demand={demand:.2f} anomaly_k={kmult}",
                "retrieved_or_generated_at": retrieved, "quality_flag": qflag,
            })

    write_table(rows, SILVER / "tap_readings.parquet", Observation)

    # anomaly labels (evaluation only)
    adf = pd.DataFrame([{**a, "provenance": "synthetic",
                         "source_id": "synthetic_tap_readings",
                         "source_ref": gen_ref} for a in anomalies])
    adf.to_parquet(SILVER / "anomaly_labels.parquet", index=False)

    n_missing = sum(1 for r in rows if r["value"] is None)
    return {"readings": len(rows), "hostels": len(hostels), "days": len(dates),
            "missing": n_missing, "anomalies": len(anomalies),
            "anomaly_sites": sorted({a["site_id"] for a in anomalies})}


if __name__ == "__main__":
    print("tap readings:", generate())

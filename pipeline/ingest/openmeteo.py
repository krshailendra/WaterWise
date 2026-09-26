"""Open-Meteo ingestion (P2): daily rainfall + air temperature (historical
archive/reanalysis) and daily river discharge (Flood API / GloFAS model).

Verified API parameters (P2, logged in REPORT):
  archive-api  daily=precipitation_sum (mm), temperature_2m_mean (degC)
  flood-api    daily=river_discharge (m3/s)  -- MODELLED (GloFAS), not a gauge.

Everything is provenance=public_observed. Weather method=reanalysis; discharge
method=model with source_ref stating it is modelled discharge, not a gauge.
Supports incremental fetch (only new days) for the live demo pipeline.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import pandas as pd
import yaml

from pipeline.ingest.common import USER_AGENT, sha256_bytes, utcnow_iso
from pipeline.schemas import Method, Observation, Provenance, QualityFlag, write_table

BRONZE = Path("data/bronze/openmeteo")
SILVER = Path("data/silver")
HYDROMET = SILVER / "hydromet.parquet"

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"

START_DATE = "2016-01-01"

# small nudges (deg) to try if a discharge point returns an all-null series
_NUDGES = [(0, 0), (0.02, 0), (-0.02, 0), (0, 0.02), (0, -0.02),
           (0.04, 0), (-0.04, 0), (0, 0.04), (0, -0.04)]


def _load_locations() -> dict:
    return yaml.safe_load(open("config/locations.yaml", encoding="utf-8"))


def _weather_points(cfg: dict) -> list[dict]:
    pts = list(cfg.get("rain_points", []))
    # also pull weather at the city + intake points (used as model features)
    for s in cfg.get("river_stations", []):
        if s["site_id"] in ("cpcb_pandu", "cpcb_kacharighat"):
            pts.append(s)
    pts.extend(cfg.get("intake", []))
    return pts


def _discharge_points(cfg: dict) -> list[dict]:
    return list(cfg.get("discharge_points", []))


def _get(url: str, params: dict) -> Optional[dict]:
    try:
        r = httpx.get(url, params=params, timeout=60,
                      headers={"User-Agent": USER_AGENT})
        if r.status_code != 200:
            print(f"[openmeteo] HTTP {r.status_code} for {url} {params.get('latitude')},{params.get('longitude')}")
            return None
        return r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[openmeteo] error {type(e).__name__}: {e}")
        return None


def _save_bronze(kind: str, site_id: str, payload: dict) -> None:
    d = BRONZE / kind
    d.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload).encode("utf-8")
    (d / f"{site_id}.json").write_bytes(raw)
    meta = {"site_id": site_id, "retrieved_at": utcnow_iso(),
            "sha256": sha256_bytes(raw), "n_bytes": len(raw)}
    (d / f"{site_id}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def fetch_weather(lat: float, lon: float, start: str, end: str) -> Optional[dict]:
    return _get(ARCHIVE_URL, {
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "daily": "precipitation_sum,temperature_2m_mean", "timezone": "UTC",
    })


def fetch_discharge(lat: float, lon: float, start: str, end: str) -> Optional[dict]:
    return _get(FLOOD_URL, {
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "daily": "river_discharge", "timezone": "UTC",
    })


def _series_all_null(daily: dict, key: str) -> bool:
    vals = daily.get(key, [])
    return len(vals) == 0 or all(v is None for v in vals)


def _existing_max_date() -> Optional[str]:
    if not HYDROMET.exists():
        return None
    df = pd.read_parquet(HYDROMET, columns=["ts"])
    if df.empty:
        return None
    return pd.to_datetime(df["ts"]).max().date().isoformat()


def run(incremental: bool = False, end: Optional[str] = None) -> dict:
    cfg = _load_locations()
    retrieved_at = datetime.now(timezone.utc)
    end = end or date.today().isoformat()

    start = START_DATE
    if incremental:
        mx = _existing_max_date()
        if mx:
            start = (pd.to_datetime(mx) + pd.Timedelta(days=1)).date().isoformat()
    if start > end:
        return {"status": "up_to_date", "start": start, "end": end, "rows": 0}

    rows: list[dict] = []
    summary = {"weather_points": {}, "discharge_points": {}, "nudged": [],
               "gaps": [], "start": start, "end": end}

    # --- weather (rainfall + air temp) ---
    for pt in _weather_points(cfg):
        sid = pt["site_id"]
        j = fetch_weather(pt["lat"], pt["lon"], start, end)
        if not j or "daily" not in j:
            summary["gaps"].append(f"weather {sid}: no data")
            continue
        _save_bronze("weather", sid, j)
        daily = j["daily"]
        times = daily.get("time", [])
        for i, t in enumerate(times):
            ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            for key, pname, unit in (
                ("precipitation_sum", "rain_mm", "mm"),
                ("temperature_2m_mean", "air_temp_c_mean", "degC"),
            ):
                v = daily.get(key, [None] * len(times))[i]
                rows.append({
                    "site_id": sid, "ts": ts, "parameter": pname,
                    "value": None if v is None else float(v), "unit": unit,
                    "method": Method.reanalysis, "provenance": Provenance.public_observed,
                    "source_id": "openmeteo_archive",
                    "source_ref": f"{ARCHIVE_URL} | {key} | reanalysis (ERA5), not a rain gauge",
                    "retrieved_or_generated_at": retrieved_at,
                    "quality_flag": QualityFlag.ok if v is not None else QualityFlag.imputed,
                })
        summary["weather_points"][sid] = len(times)

    # --- river discharge (GloFAS, modelled) ---
    for pt in _discharge_points(cfg):
        sid = pt["site_id"]
        chosen = None
        for dlat, dlon in _NUDGES:
            lat, lon = pt["lat"] + dlat, pt["lon"] + dlon
            j = fetch_discharge(lat, lon, start, end)
            if j and "daily" in j and not _series_all_null(j["daily"], "river_discharge"):
                chosen = (lat, lon, j)
                if (dlat, dlon) != (0, 0):
                    summary["nudged"].append({"site_id": sid, "from": [pt["lat"], pt["lon"]],
                                              "to": [lat, lon]})
                break
        if not chosen:
            summary["gaps"].append(f"discharge {sid}: no channel data even after nudging")
            continue
        lat, lon, j = chosen
        _save_bronze("discharge", sid, j)
        daily = j["daily"]
        times = daily.get("time", [])
        for i, t in enumerate(times):
            ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            v = daily.get("river_discharge", [None] * len(times))[i]
            rows.append({
                "site_id": sid, "ts": ts, "parameter": "discharge_m3s",
                "value": None if v is None else float(v), "unit": "m3/s",
                "method": Method.model, "provenance": Provenance.public_observed,
                "source_id": "openmeteo_flood",
                "source_ref": f"{FLOOD_URL} | river_discharge | MODELLED discharge (GloFAS), not a gauge | pt {lat:.3f},{lon:.3f}",
                "retrieved_or_generated_at": retrieved_at,
                "quality_flag": QualityFlag.ok if v is not None else QualityFlag.imputed,
            })
        summary["discharge_points"][sid] = len(times)

    # --- write / append ---
    if rows:
        if incremental and HYDROMET.exists():
            old = pd.read_parquet(HYDROMET)
            # validate new rows through the writer to a temp, then concat
            tmp = SILVER / "_hydromet_new.parquet"
            write_table(rows, tmp, Observation)
            new = pd.read_parquet(tmp)
            tmp.unlink(missing_ok=True)
            combined = pd.concat([old, new], ignore_index=True)
            combined = combined.drop_duplicates(subset=["site_id", "ts", "parameter"], keep="last")
            combined.to_parquet(HYDROMET, index=False)
            summary["rows"] = len(new)
            summary["total_rows"] = len(combined)
        else:
            write_table(rows, HYDROMET, Observation)
            summary["rows"] = len(rows)
            summary["total_rows"] = len(rows)
    else:
        summary["rows"] = 0
    return summary


if __name__ == "__main__":
    import sys
    inc = "--incremental" in sys.argv
    s = run(incremental=inc)
    print("=" * 60)
    print("Open-Meteo ingestion (P2) — summary")
    print("=" * 60)
    print(f"window: {s['start']} .. {s['end']}  new_rows={s.get('rows')}  total={s.get('total_rows')}")
    if s.get("status") == "up_to_date":
        print("already up to date — nothing to fetch.")
    else:
        print("weather points:", s.get("weather_points"))
        print("discharge points:", s.get("discharge_points"))
        if s.get("nudged"):
            print("nudged onto channel:", s["nudged"])
        if s.get("gaps"):
            print("GAPS:", s["gaps"])

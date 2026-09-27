# SCHEMA — WaterWise tables

Authoritative pydantic definitions: [`pipeline/schemas.py`](../pipeline/schemas.py).
Timestamps are UTC in storage (`Asia/Kolkata` in the UI). Column names are snake_case
with units in the name. Every persisted row carries `provenance`, `source_id`,
`source_ref` (enforced by the single writer `write_table`).

## `observations` (long) — cpcb_river, cpcb_groundwater, hydromet, s2_ndti, tap_readings

| column | type | notes |
|---|---|---|
| site_id | str | station / node id (see `sites`) |
| ts | datetime (UTC) | observation time; CPCB yearly rows use Jan-1 of the year |
| parameter | str | e.g. `ph_max`, `rain_mm`, `discharge_m3s`, `ndti_median`, `residual_cl_mg_l` (unit in name; CPCB yearly stats carry `_min`/`_max`) |
| value | float / null | null = missing / below-detection (flagged) |
| unit | str | `mg/L`, `mm`, `m3/s`, `degC`, `pH`, `umho/cm`, `MPN/100mL`, `index`, … |
| method | enum | lab \| satellite \| reanalysis \| model \| simulated_sensor |
| provenance | enum | public_observed \| modelled \| synthetic |
| source_id | str | e.g. `cpcb_nwmp_river`, `openmeteo_archive`, `s2_l2a`, `synthetic_tap_readings` |
| source_ref | str | URL / page / generator@version+seed, with quotes/notes |
| quality_flag | enum | ok \| suspect \| out_of_range \| imputed (validators flag, never delete) |
| retrieved_or_generated_at | datetime | fetch/generation timestamp |

## `sites` — cpcb_sites, cpcb_gw_sites, network_sites

`site_id, name, kind (river_station|intake|wtp|reservoir|hostel_tank|cooler|ro_unit|household_area), lat, lon, upstream_site_id, population_served, notes` + provenance trio.

## `network_edges` (synthetic)

`from_site_id, to_site_id, travel_time_h_mean, travel_time_h_sd, pipe_k_wall_per_day` + provenance trio.

## `daily_briefing` (gold)

`date, raw_risk_level, ndti_p10/p50/p90, water_temp_c_est, recommended_dose_mg_l, dose_p90_needed, worst_tap_site_id, worst_tap_p10_residual_mg_l, test_next_site_id, test_next_reason, active_alerts, model_versions` + provenance trio.

## `virtual_sensor_daily` (gold, modelled)

`date, ndti_p10/p50/p90, interval_width, ndti_persistence, days_since_last_clear, ndti_observed` + provenance trio.

## events / complaints / anomaly_labels

- `events` (incidents): `event_id, ts_reported, ts_event_est, kind (spill|discharge|flood|…), lat, lon, site_id, text_summary, confidence, human_confirmed(bool)` + provenance trio.
- `complaints`: `complaint_id, ts, site_guess, text, language(en|hi|as), category_true` + provenance trio.
- `anomaly_labels`: `site_id, start_date, end_date, k_multiplier, kind` (evaluation only).

Allowed values for enums are defined in `pipeline/schemas.py`.

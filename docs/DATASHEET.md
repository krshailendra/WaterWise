# DATASHEET — WaterWise dataset

WaterWise builds a source-to-tap drinking-water picture for the IIT Guwahati water
treatment plant from **public** river/weather/satellite data, with the parts we
cannot yet measure (the campus pipe network and tap chlorine residuals) **simulated
from documented physics** and clearly labelled. Every row carries a `provenance`
class and a `source_ref`.

## Row counts per provenance class

Total across the tables below: **≈ 104,800 rows**.

| provenance | rows | % |
|---|---:|---:|
| `public_observed` (real public data, fetched during the build) | 84,057 | **80.2%** |
| `modelled` (our model outputs derived from real data) | 7,470 | 7.1% |
| `synthetic` (simulated from documented parameters, seed-reproducible) | 13,273 | 12.7% |

**Grounded in real measurements (observed + modelled): 87.3%.** Synthetic = 12.7%.

### Per-table breakdown

| table | provenance | rows | what it is |
|---|---|---:|---|
| `hydromet` | public_observed | 74,518 | Daily rainfall + air temp (Open-Meteo ERA5) & river discharge (GloFAS), 12 points, 2016→today |
| `cpcb_river` | public_observed | 3,938 | Brahmaputra/Bharalu yearly min/max water quality (CPCB NWMP), 7 years, 74 stations |
| `cpcb_groundwater` | public_observed | 3,820 | Assam groundwater yearly min/max (CPCB NWMP), 2020–2022, 67 stations |
| `s2_ndti` | public_observed | 1,640 | Sentinel-2 turbidity index (NDTI) per scene, 2 river reaches, 410 clear scenes 2017→today |
| `virtual_sensor_daily` | modelled | 3,922 | Daily NDTI estimate with p10/p50/p90 (LightGBM quantile; persistence in production) |
| `water_temp_daily` | modelled | 3,919 | Water temp from real air temp, clipped to CPCB envelope |
| `chlorine_demand_daily` | modelled | 3,551 | Chlorine demand from real NDTI (team-estimate relationship) |
| `tap_readings` | synthetic | 13,092 | Simulated DPD field-kit residuals, 12 hostels × 3 yr, + labelled anomalies |
| `network_edges`+`network_sites` | synthetic | 75 | Simulated campus distribution network |
| `complaints` | synthetic | 102 | Simulated complaints (en/hi/as), KRITI '25 category priors |

## Collection windows & cadence per source

| source | window | cadence | retrieved |
|---|---|---|---|
| Open-Meteo archive (ERA5) rain+temp | 2016-01-01 → today | daily | 2026-09-26/27 |
| Open-Meteo Flood (GloFAS) discharge | 2016-01-01 → today | daily (modelled, not a gauge) | 2026-09-26/27 |
| Sentinel-2 L2A (Planetary Computer) | 2017 → today | every 2–5 d, cloud-limited | 2026-09-27 |
| CPCB NWMP river | 2016, 2018–2023 | yearly min/max (published) | 2026-09-26 |
| CPCB NWMP groundwater | 2020–2022 | yearly min/max | 2026-09-26 |
| GDELT news | — | continuous | **unreachable this build (logged; 0 events)** |
| JJM-WQMIS | — | — | **not machine-accessible (JS grid app); logged, skipped** |

## Observed vs modelled vs synthetic

- **Observed (real):** everything fetched from public APIs/PDFs during the build —
  CPCB river & groundwater, Open-Meteo weather, GloFAS discharge, Sentinel-2 NDTI.
  (GloFAS discharge is a *modelled reanalysis product* upstream of us but is public
  data; we label it "modelled discharge, not a gauge" in its `source_ref`.)
- **Modelled (ours, from real):** water temperature, chlorine demand, and the daily
  virtual-sensor NDTI — all derived from the real data above.
- **Synthetic:** the campus network, tap residuals, and complaints — generated only by
  code in `pipeline/synthetic/` from documented physics with a fixed seed
  (`config/params.yaml`), fully reproducible (see `docs/SYNTHETIC_METHOD.md`, with
  content hashes). Nothing synthetic is presented as a real measurement.

## How AI was used

- **Ingestion agent** (Claude, built): fallback extraction of CPCB PDF tables when
  deterministic parsing fails — *not needed here* (100% deterministic parse achieved).
- **Incident agent** (Claude + deterministic keyword fallback): classify GDELT news
  into structured incidents; geocode + ETA are deterministic.
- **Complaint generation** (Claude, with template fallback used this build).
- **ML model:** LightGBM quantile virtual sensor (real features → NDTI band).
- **Safety numbers are never produced by an LLM** — dose, residuals, risk levels and
  ETAs come only from deterministic, unit-tested Python (72 tests).

## Known gaps & biases (kept honest)

- CPCB NWMP is published as **yearly min/max**, not a daily series — this sparsity is
  the core problem we address.
- Sentinel-2 has a **monsoon cloud gap**; NDTI is a *relative* turbidity index, **not
  NTU**, and says nothing about bacteria or dissolved chemicals.
- GloFAS discharge is **modelled**, not a CWC gauge; flow-wave lag is ≈0 d at daily
  resolution (reported).
- The **campus layer is simulated** until the WTP shares real logs.
- **GDELT** was unreachable and **JJM-WQMIS** not machine-accessible this build — both
  logged, neither fabricated.

## Reproducibility

Silver/gold tables regenerate from `data/bronze/` + code + the fixed seed. Synthetic
tables are byte-identical on regeneration (hashes in `docs/SYNTHETIC_METHOD.md`). A
stratified `data/release/sample_1000_rows.csv` and `data/release/provenance_summary.csv`
are provided for quick inspection; `data/release/load_example.py` prints the split.

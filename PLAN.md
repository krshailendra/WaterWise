# PLAN.md — WaterWise: source-to-tap water intelligence

The single source of truth for this project. Part A is the rules and architecture, Part B the data specification, Part C the build phases in order, Part D the two config files to create verbatim.

References like "Part A §8" point to sections of this file. The repository also gets a short `CLAUDE.md` that points here, so the rules persist across Claude Code sessions.

---

# Part A — Mission, rules and architecture

## 1. Mission (never lose sight of this)

**User:** the chemist at the IIT Guwahati water treatment plant (WTP), plus estates staff and hostel caretakers. Secondary user: ordinary households in Guwahati.

**Their decision:** how much chlorine to dose each morning, and which hostel tanks / RO units need attention first.

**Our question:** *Can public data tell the WTP chemist, every morning, what chlorine dose keeps every hostel tap safe — and where to test next?*

**Evidence the need is real:** during our KRITI '25 investigation, the IITG WTP chemist told us a system that calculates and monitors chlorine doses would be valuable. IITG draws raw water from the Brahmaputra (via a barge in the low-water months, Dec–Mar).

Judging context: Granica × IIT Guwahati "Bring the Physical World to AI" hackathon. Judges score Idea, Data collection process, Data collected, Impact (25% each). They penalise **claiming more than the data supports** and **datasets nobody else can interpret**. They reward **honesty about gaps** and **a pipeline still running while we present**.

## 2. Non-negotiable rules

1. **Never fabricate data.** If a source fails, log it in `REPORT.md`, show an honest "no data" state, and move on. Never fill with invented "real-looking" values.
2. **Every row carries provenance.** Column `provenance` ∈ {`public_observed`, `modelled`, `synthetic`}. Plus `source_id`, `source_url` (or generator name + version), `retrieved_at` / `generated_at`.
3. **Synthetic data is auditable, not disguised.** It is generated only by code in `pipeline/synthetic/`, from physical models with parameters listed (with citation or "team estimate") in Part B, with a fixed seed. It must look realistic (instrument noise, resolution, missing values) *and* be fully reproducible. If a judge reverse-engineers it, they must find our cited parameters — that is the goal. Never strip or hide the `synthetic` flag, anywhere, including the app.
4. **Safety numbers never come from an LLM.** Chlorine dose, residuals, risk levels, and ETAs are computed by deterministic, unit-tested Python. LLM agents only extract, classify, and explain. The explainer must pass a numeric-consistency guard (every number in its text must appear in the input payload).
5. **Log every change in `REPORT.md`** using the template in §8, at the end of every task. This file is how we explain our process to the judges.
6. **The demo must work offline.** The app ships with a bundled snapshot so it runs even if the network or backend fails.
7. **Secrets:** `ANTHROPIC_API_KEY` lives only in `.env` on the backend. Never in the app, never committed.
8. **Scope discipline.** Finish the core loop (data → models → API → app) before any stretch goal.
9. **We never declare water "unfit" on our own.** Our models can only raise a *suspicion* and request verification. Only a result entered by an authority (lab/field test) can move a site to `confirmed_unsafe`, and only the authority issues the public advisory. Until then the app says "under verification" and shows precautions + alternatives. Every state change is logged with who, when and evidence.
10. **Alternatives must be trustworthy.** Only show water alternatives with a source and a last-verified date; unverified entries are labelled as such and ranked last. Never imply boiling fixes chemical contamination.
11. **All authorities are dummy.** `config/authorities.yaml` uses fictional names and undeliverable `.invalid` emails. Never add a real contact without the team's explicit instruction. Routing is automatic from geography (campus geofence → city → district → state, plus PIN code and river reach) via `config/routing_rules.yaml`; every routing decision records the rule and confidence.

## 3. Architecture

```
Sources (real, public)          Synthetic (documented)
  CPCB/NWMP river + groundwater    IITG distribution network
  Open-Meteo rain + temperature    Chlorine decay parameters
  Open-Meteo Flood (GloFAS) flow   Tank/tap residual readings
  Sentinel-2 L2A (turbidity idx)   Anomaly scenarios (labelled)
  GDELT news                       Complaint texts
  JJM-WQMIS (if accessible)
            │
            ▼
  Ingestion agents + validators  ──►  Parquet lakehouse (bronze/silver/gold)
            │
            ▼
  Models (deterministic unless stated)
   1. Virtual river sensor  – quantile ML: daily turbidity index + p10/p90
   2. Upstream ETA          – lag estimated from real flow series + incident agent
   3. Source-to-tap twin    – first-order chlorine decay, Monte Carlo uncertainty
   4. Inverse dose solver   – min dose s.t. P10 residual at worst tap ≥ 0.2 mg/L
   5. Test-next (VOI)       – which single test reduces the most risk today
            │
            ▼
  Agents (LangGraph + Claude API): ingestion, incident, complaint triage, explainer,
                                   escalation (evidence packets)
            │
            ▼
  Safety loop
   6. Escalation state machine – watch → verify_requested → sample_collected →
                                 confirmed_unsafe | cleared → advisory → resolved
   7. Alternatives engine      – households: nearest verified safe water points,
                                 registered tankers, precautions
                                 campus: pause intake & run on storage, isolate
                                 tank/reroute, emergency supply plan
            │
            ▼
  FastAPI + DuckDB  ──►  Expo mobile app (Campus console + Consumer + Authority modes)
                          Verified lab results flow back in as ground truth
```

## 4. Repository layout

```
waterwise/
  PLAN.md  CLAUDE.md (pointer)  REPORT.md  README.md  .env.example
  docs/        DATASHEET.md  SCHEMA.md  JUDGE_NOTES.md
  config/      locations.yaml  campus.yaml  params.yaml
  data/        bronze/ (raw downloads, untouched)
               silver/ (clean, typed, validated Parquet)
               gold/   (model outputs, daily briefings)
               release/ (submission package: parquet + sample CSV + schema)
  pipeline/    ingest/  synthetic/  validate/  run_daily.py
  models/      virtual_sensor/  eta/  twin/  dose/  voi/
  agents/      graph.py  ingestion_agent.py  incident_agent.py
               complaint_agent.py  explainer_agent.py  guards.py
  api/         main.py  routes/  snapshot.py
  app/         (Expo, TypeScript, expo-router)
  notebooks/   (exploration only; nothing the app depends on)
  tests/
```

## 5. Stack

- Python 3.11+, `uv` or `pip` + `venv`. Libraries: pandas, pyarrow, duckdb, pydantic, httpx, pdfplumber, lightgbm, scikit-learn, numpy, scipy, pystac-client, planetary-computer, rioxarray/rasterio, langgraph, anthropic, fastapi, uvicorn, pytest.
- Claude API models: `claude-sonnet-5` for extraction/triage/explanations; `claude-haiku-4-5-20251001` for cheap bulk classification. Read the model from env (`WW_MODEL_MAIN`, `WW_MODEL_FAST`) so it can be changed.
- Mobile: Expo (latest SDK), TypeScript, expo-router, react-native-svg (schematic network view — no map API keys), expo-location (consumer mode, with manual fallback). Must run in **Expo Go** on Android and iOS.
- Exposure to phone: local FastAPI + `cloudflared tunnel --url http://localhost:8000` (no account needed) or a free-tier deploy. Bundled snapshot as fallback.

## 6. Data conventions

- Timestamps: UTC in storage, `Asia/Kolkata` in the UI. Column names snake_case. Units in the column name (`residual_cl_mg_l`, `rain_mm`, `discharge_m3s`).
- Long "observations" table: `site_id, ts, parameter, value, unit, method, provenance, source_id, source_url_or_generator, quality_flag, retrieved_or_generated_at`.
- `quality_flag` ∈ {`ok`, `suspect`, `out_of_range`, `imputed`}. Validators never delete rows; they flag.
- Bronze is immutable. Every silver/gold file is reproducible from bronze + code + seed.

## 7. Coding conventions

- Small modules, type hints, pydantic models at boundaries, docstrings stating units.
- Each model has a `tests/` file with at least: a physics/plausibility test and a regression test on a fixed input.
- Any function that returns a safety number returns it **with** its uncertainty and the inputs used.
- Prefer boring, reliable code. The demo must not crash in front of judges.

## 8. REPORT.md protocol (mandatory after every task)

Append (never rewrite history) an entry:

```
## Entry NNN — <short title>  (<YYYY-MM-DD HH:MM IST>)
**Prompt/phase:** Pxx
**Goal:** one sentence
**What changed:** files created/modified (paths)
**Data:** sources touched, rows added per provenance class, time window, cadence
**Decisions & why:** key choices, alternatives rejected
**Validation:** tests run, metrics, sanity checks, with numbers
**Honest limits found:** what this step cannot tell us / what failed
**Next:** the next step
```

If something failed, say so plainly. Failed attempts are part of the story judges want to hear.

---

# Part B — Data specification

Status legend: **verify** = Claude Code must confirm the endpoint/format works before relying on it, and log the result in REPORT.md.

## 1. Real public sources

| id | Source | What we take | Access | Cadence / window | Known gap |
|---|---|---|---|---|---|
| `cpcb_nwmp_river` | CPCB National Water Quality Monitoring Programme — river data | Brahmaputra + Bharalu station values (temp, DO, pH, conductivity, BOD, nitrate, coliforms…) | Yearly pages, e.g. `https://cpcb.nic.in/nwmp-data-2022/`, `https://cpcb.nic.in/wqm/2021/WQuality_River-Data-2021.pdf`, 2014 HTML table `https://cpcb.nic.in/wqm/2014/RIVERWATER%20DATA%202014_10.htm` (verify each year 2012–2023) | Sampled monthly by PCB Assam; **published mostly as yearly min/max(/mean)** | Too coarse for daily decisions — this gap is our core argument |
| `cpcb_station_list` | CPCB monitoring station list | Station codes, names, lat/lon | `https://cpcb.nic.in/wqm/WQMN_list.pdf` | Static | — |
| `cpcb_nwmp_gw` | CPCB NWMP groundwater | Guwahati groundwater stations (pH, conductivity, TDS, fluoride, arsenic, coliforms…) | `https://cpcb.nic.in/wqm/2022/NWMP_DATA_2022.pdf` (+ other years) | Half-yearly | Few stations; used for consumer mode |
| `openmeteo_archive` | Open-Meteo historical weather API | Daily precipitation, mean air temperature | `https://archive-api.open-meteo.com/v1/archive` (verify params in docs) | Daily, 2016→today | Reanalysis, not rain gauges |
| `openmeteo_flood` | Open-Meteo Flood API (GloFAS) | Daily modelled river discharge at river points | `https://flood-api.open-meteo.com/v1/flood` (verify) | Daily, historical + forecast | Modelled discharge, not CWC gauge readings — say so |
| `s2_l2a` | Sentinel-2 L2A via Microsoft Planetary Computer STAC | Red/green/NIR reflectance + SCL cloud mask over river polygons → NDTI | `pystac-client` + `planetary-computer`, collection `sentinel-2-l2a` | Every 2–5 days, clouds permitting, 2017→today | Heavy cloud in monsoon |
| `gdelt_doc` | GDELT DOC 2.0 API | News articles on Brahmaputra pollution/spill/discharge/oil/flood near Assam | `https://api.gdeltproject.org/api/v2/doc/doc` (verify) | Continuous | Sparse, delayed, noisy |
| `jjm_wqmis` | Jal Jeevan Mission WQMIS | Assam drinking-water test results | `https://ejalshakti.gov.in/WQMIS/Main/report` (verify what is downloadable) | Continuous | Mostly rural; may not be machine-readable — if blocked, log and skip |
| `kriti25_survey` | Our KRITI '25 campus survey (team-owned) | Complaint category shares, purifier status shares | Local file | One-time, pre-event | Small, self-reported; used only as priors |

| `osm_water_points` | OpenStreetMap via Overpass API | Public drinking-water points, water taps, water points, water ATMs/kiosks in Guwahati | `https://overpass-api.de/api/interpreter` (verify; cache results) | Snapshot at build + weekly refresh | Coverage in Guwahati may be thin; OSM entries are not quality-tested — label "location only, not tested" |

| `pin_boundaries` | Dept. of Posts — All India PIN Code Boundary GeoJSON (Open Government Data platform) | PIN polygons with office, circle, region, division names | `https://www.data.gov.in/catalog/all-india-pincode-boundary-geo-json` (verify download; keep Assam subset only) | Static release | Postal zones, not administrative or water-service areas |
| `district_boundaries` | District polygons (e.g. DataMeet maps repo; verify licence/currency) | Assam district polygons | `https://github.com/datameet/maps` (verify) | Static | May lag new districts — check Assam's current list |
| `osm_boundaries` | OpenStreetMap via Overpass | IITG campus polygon; city/municipal boundary for Guwahati if mapped | Overpass (verify tags) | Static + refresh | Municipal boundary may be missing or approximate |
| `digipin` | Dept. of Posts DIGIPIN (open source grid address code) | Optional: encode report locations as DIGIPIN for coarse, shareable location | `https://github.com/CEPT-VZG/digipin` | Library | Optional |

Never scrape anything behind a login. Respect robots/terms. Cache every raw download in `data/bronze/` with retrieval timestamp and URL.

## 2. Locations (`config/locations.yaml`)

Coordinates for CPCB stations come from the CPCB station list (take them from the PDF, don't trust these approximations). Starting values:

| site_id | Name | lat | lon | Role |
|---|---|---|---|---|
| `cpcb_pandu` | Brahmaputra at Pandu | 26.176 | 91.684 | City reach |
| `cpcb_chandrapur` | Brahmaputra at Chandrapur | 26.248 | 91.918 | Upstream (east) of city |
| `cpcb_bharalu` | Bharalu river, Guwahati | 26.168 | 91.765 | Urban tributary |
| `cpcb_kacharighat` | Brahmaputra near intake, Kacharighat | from PDF | from PDF | City intake reach |
| `cpcb_dibrugarh` | Brahmaputra at Dibrugarh | 27.510 | 94.953 | Far upstream |
| `iitg_intake` | IITG raw-water intake (barge) | ~26.19 (confirm) | ~91.69 (confirm) | **Our user's intake — confirm location with WTP chemist** |
| `rain_*` | Upstream catchment points (e.g. Pasighat, Dibrugarh, Tezpur, Guwahati) | set in config | set in config | Rainfall features |

## 3. Core tables (Parquet, `data/silver` and `data/gold`)

**`sites`** — `site_id, name, kind` (river_station | intake | wtp | reservoir | hostel_tank | cooler | ro_unit | household_area), `lat, lon, upstream_site_id, population_served, provenance, notes`

**`observations`** (long format) — `site_id, ts, parameter, value, unit, method` (lab | satellite | reanalysis | model | simulated_sensor), `provenance, source_id, source_ref, quality_flag, retrieved_or_generated_at`

**`events`** — `event_id, ts_reported, ts_event_est, kind` (spill | discharge | flood | advisory | complaint | maintenance | anomaly_injected), `lat, lon, site_id, text_summary, confidence, human_confirmed (bool), provenance, source_ref`

**`daily_briefing`** (gold) — `date, raw_risk_level, ndti_p10, ndti_p50, ndti_p90, water_temp_c_est, recommended_dose_mg_l, dose_p90_needed, worst_tap_site_id, worst_tap_p10_residual_mg_l, test_next_site_id, test_next_reason, active_alerts, model_versions`

**`network_edges`** (synthetic) — `from_site_id, to_site_id, travel_time_h_mean, travel_time_h_sd, pipe_k_wall_per_day`

## 4. Derived real-data signals (the "innovative reading")

1. **Turbidity index (NDTI)** = (Red − Green) / (Red + Green) from Sentinel-2 bands B04, B03, using only water pixels (SCL = 6) inside a river polygon near Guwahati/intake; drop scenes with < N clear water pixels. This is a *relative* index, not NTU — label it that way everywhere.
2. **Virtual river sensor:** quantile LightGBM (p10/p50/p90) predicting NDTI from lagged upstream rainfall (0–10 d), GloFAS discharge and its 1/3/7-day changes, air temperature, day-of-year. Fills cloudy days. Time-split validation (train ≤ 2023, test ≥ 2024). Must report MAE vs **persistence** and **climatology** baselines, and p10–p90 interval coverage. If it doesn't beat baselines, say so.
3. **Flow-wave lag:** cross-correlate GloFAS discharge at upstream points vs Guwahati to estimate lag (days). Note honestly: flood-wave celerity ≠ water (pollutant) velocity; incident ETA uses a separate velocity range (§5).
4. **Seasonal priors from NWMP:** month/season envelopes for water temperature, pH, BOD, coliforms at city stations → used to bound synthetic water temperature and chlorine demand.

## 5. Synthetic parameters (things we cannot measure now)

All sampled per scenario from the ranges below with fixed seeds. "Team estimate" = to be replaced by WTP chemist's real values when available; the app shows these as "assumed".

| Parameter | Symbol | Range / model | Basis |
|---|---|---|---|
| Chlorine bulk decay at 20 °C | k_b20 | 0.5–1.5 day⁻¹ (median ~0.9) | First-order decay is the standard model; simulation studies commonly use ~0.85–1 day⁻¹ |
| Temperature correction | θ | k_b(T) = k_b20 · θ^(T−20), θ ≈ 1.096 | Literature reports a 10 °C rise can raise k_b ~2.5× → θ = 2.5^0.1 |
| Pipe wall decay (effective) | k_w,eff | 0.05–0.5 day⁻¹ added in pipes only | Wall reactions add to bulk decay in pipes (EPANET convention); range is a team estimate |
| Water temperature | T_w | Derived from Open-Meteo air temp (lagged smoothing), clipped to NWMP seasonal envelope for city stations | Real data + model → `modelled` |
| Chlorine demand vs turbidity | D | D = d0 + a·norm(NDTI) + ε; d0 0.3–0.8 mg/L, a 0.2–1.0 mg/L, ε ~ N(0, 0.1) | **Team estimate**, clearly flagged; calibratable by chemist |
| Plant dose range | C_dose | 0.5–4.0 mg/L allowed; solver picks | Operational bound, team estimate |
| Target residual at tap | — | ≥ 0.2 mg/L free chlorine (BIS IS 10500 minimum) | Standard |
| Pipe travel time WTP→hostel | t_p | 0.25–3 h depending on distance | Team estimate |
| Overhead tank residence | t_r | 6–24 h | Team estimate |
| Test-kit reading noise | — | DPD: ±max(0.05 mg/L, 10%), resolution 0.1 mg/L; 5–10% missing readings; 0.5% transcription errors | Typical field-kit behaviour, team estimate |
| Biofilm/dirty tank anomaly | — | k_b × 2–4 for a tank over 3–10 days | Team estimate; stored as labelled `anomaly_injected` events for evaluation only |
| Complaints | — | 60–150 short texts (English/Hindi/Assamese mix) with category shares from our KRITI survey | LLM-generated, provenance = synthetic |
| Hostel list & population | — | `config/campus.yaml`; default H01…H12, 300–900 residents each | Replace with real names/numbers if confirmed |

## 6. Synthetic realism and audit checks (`pipeline/validate/synthetic_checks.py`)

- Physical: residual ≥ 0; residual ≤ dose; decay monotone within a segment; temperature within NWMP envelope.
- Texture: instrument resolution respected; realistic missingness; autocorrelation of day-to-day readings within plausible bounds.
- Anchoring: where a synthetic variable overlaps a real one (e.g. water temperature), compare distributions (KS test) and report.
- Reproducibility: regenerating with the same seed gives byte-identical Parquet (hash logged in REPORT.md).
- Disclosure: `docs/DATASHEET.md` states row counts per provenance class. The app shows a "synthetic" badge wherever synthetic data drives a number.

## 7. Escalation and alternatives data

**`cases`** — one row per suspected-unsafe situation: `case_id, site_id or area_id, audience` (campus | public), `state` (watch | verify_requested | sample_collected | confirmed_unsafe | cleared | advisory_issued | resolved), `trigger` (model | complaint_cluster | incident | user_report), `evidence_json` (numbers + sources that triggered it), `requested_tests` (parameter list), `assigned_authority_id, created_at, updated_at, sla_due_at`.

**`case_log`** — append-only: `case_id, ts, from_state, to_state, actor` (system | authority_user | chemist), `note, attachment_ref`.

**`verification_results`** — results entered by an authority: `case_id, site_id, sampled_at, parameter, value, unit, method` (lab | FTK | H2S_vial | DPD), `lab_or_tester, provenance`. Real entries = `public_observed` (authority-verified); demo entries = `synthetic` and badged. **These rows feed back into model calibration** (they are the ground truth our models otherwise lack).

**`authorities` (`config/authorities.yaml`)** — **all dummy for now.** Role-based fictional entries (campus WTP chemist, estates, wardens, health centre; public urban utility, rural water division per district, pollution regional office per river reach, district health surveillance, state catch-all). Emails use the reserved, undeliverable `.invalid` domain. Messages go to the in-app Authority inbox + a local outbox folder. Replacing a dummy with a real, officially published route is a logged REPORT.md change.

**`jurisdictions`** (output of the resolver, stored on every case): `case_id, lat, lon, geofence, area_type, city, district, state, pincode, post_office, postal_division, river_reach, water_source` (piped | community_source | own_borewell | private_tanker | home_ro | unknown), `method` (gps_polygon | pincode_fallback | user_confirmed | manual), `confidence, near_boundary (bool)`.
Routing is decided by `config/routing_rules.yaml` (most specific rule wins; low confidence → user confirmation or catch-all).
Privacy: case records keep PIN/ward-level location by default; exact coordinates only when the user consents, and are dropped once the case is resolved.

**Alternatives — households (`alternatives_public`)**: `alt_id, kind` (public_tap | water_point | water_atm | registered_tanker | tested_source | distribution_point), `name, lat, lon, operator, last_verified_at, verified_by, test_status` (tested_ok | untested | failed), `hours, cost_note, provenance, source_ref`.
- Real: OSM water points (location only, untested).
- Real if accessible: JJM-WQMIS tested sources.
- Synthetic for demo: a few registered-tanker and relief distribution entries, badged "demo", until an authority registers real ones.

**Alternatives — campus (`campus_resilience`, synthetic until WTP confirms)**:
| Parameter | Range | Basis |
|---|---|---|
| Raw/clear-water storage | 4–24 h of campus demand | Team estimate — confirm with WTP |
| Campus demand | 0.8–2.0 ML/day | Team estimate — confirm |
| Minimum safe storage reserve | 25% | Team estimate |
| Tank isolation / reroute options | per `campus.yaml` edges with `can_isolate`, `alt_feed_from` | Team estimate |
| Emergency supply | bottled/tanker for hostels on isolated tanks, litres/person/day: 3–5 drinking+cooking | Emergency planning estimate — label as such |

**Intake-pause decision (campus "change the source" logic):** if the virtual sensor forecasts a raw-water spike lasting *S* hours (p90) and current storage covers *H* hours of demand above the reserve, recommend **pause intake and run on storage** when *H* > *S*; otherwise recommend partial intake + higher dose, or emergency supply for the hostels at the end of the network. Always show the numbers behind the recommendation.

## 8. What this data cannot tell us (put this on slide 3)

- NDTI is a relative turbidity signal, not NTU, and says nothing about bacteria or dissolved chemicals (metals, solvents).
- GloFAS discharge is modelled, not gauged.
- The campus network and all tap residuals are simulated until the WTP shares real logs.
- News-based incident detection is incomplete by nature.

---

# Part C — Build phases (execute in order)

Time budget (48 h): P0–P5 ≈ 11 h · P6–P9 ≈ 10 h · P9A–P9C ≈ 6 h · P10–P12 ≈ 13 h · P13–P15 ≈ 5 h · buffer ≈ 3 h.
Core demo loop (never cut): P1, P2, P3, P6, P7, P8, P9A, P10, P11, P12. Cuttable if late: tanker registration, real email, P14 polish.

## P0 — Project skeleton

Read this PLAN.md fully before doing anything.

Set up the repository exactly as described in Part A §4:
- Create all folders, a Python project (pyproject.toml) with the libraries in Part A §5, a .env.example (ANTHROPIC_API_KEY, WW_MODEL_MAIN=claude-sonnet-5, WW_MODEL_FAST=claude-haiku-4-5-20251001, WW_API_BASE), a .gitignore (ignore .env, data/bronze raw binaries over 50 MB, node_modules, caches).
- Create config/locations.yaml from Part B §2, config/campus.yaml (12 placeholder hostels H01–H12 with population 300–900, a WTP node, a campus reservoir node, and approximate distances in metres — mark every value `assumed: true`), and config/params.yaml holding every synthetic parameter range from Part B §5 with its basis string.
- Create pydantic schemas for the tables in Part B §3 in pipeline/schemas.py, and a single writer helper that refuses to write a row without provenance, source_id and source_ref.
- Add a Makefile or justfile with targets: ingest, synth, validate, train, daily, api, test.
- Add a minimal pytest that checks the writer rejects rows missing provenance.

Acceptance: `pytest` passes; tree matches Part A §4.
Then append REPORT.md Entry per Part A §8.

---

## P1 — Real data: CPCB NWMP river + station list (with an ingestion agent)

Goal: build the real historical water-quality record for the Brahmaputra around Guwahati from CPCB NWMP publications.

1. Write pipeline/ingest/cpcb.py that downloads (with polite retries and a user agent) the CPCB NWMP river data for every year you can find from 2012 to the latest (start from the URLs in Part B §1; discover other years from the yearly index pages), plus WQMN_list.pdf. Save raw files unchanged to data/bronze/cpcb/<year>/ with a sidecar JSON {url, retrieved_at, sha256}.
2. Parse the station list PDF with pdfplumber into sites (all Assam river stations; at minimum Pandu, Chandrapur, Kacharighat/intake point, Bharalu, Dibrugarh, Sualkuchi, Jogighopa). Use the real lat/lon from the PDF and update config/locations.yaml.
3. Parse the river data tables. First try deterministic table extraction (pdfplumber/pandas.read_html). Tables differ by year, so build agents/ingestion_agent.py: when a table can't be parsed deterministically, send the page text/table to the Claude API (WW_MODEL_MAIN) with a strict JSON schema (station_code, station_name, parameter, stat ∈ {min,max,mean}, value, unit, year). 
4. Validate every extracted value in pipeline/validate/cpcb_checks.py: known units, plausible ranges (e.g. pH 4–10, temp 5–40 °C, DO 0–15 mg/L), station code must exist in the station list. Flag, never delete. For every LLM-extracted row, keep the source page number and a quoted snippet so a human can verify. Randomly sample 20 LLM-extracted values and write them to data/silver/cpcb_audit_sample.csv for manual checking.
5. Write data/silver/cpcb_river.parquet in the long observations format, provenance=public_observed, method=lab.

Also parse the groundwater PDFs for Guwahati stations into data/silver/cpcb_groundwater.parquet (for consumer mode later).

Acceptance: print a summary — years covered, stations, parameters, row counts, % rows parsed deterministically vs by agent, % flagged. Do NOT invent values for missing years; list them as gaps.
Append the REPORT.md entry (Part A §8), including the honest statement that published data is mostly yearly min/max, not a monthly series.

---

## P2 — Real data: rainfall, temperature, river discharge

Goal: daily hydro-meteorological history and near-real-time updates.

1. pipeline/ingest/openmeteo.py: first read the Open-Meteo docs for the historical archive API and the Flood API to confirm exact parameter names; log the confirmed parameters in REPORT.md.
2. Pull daily precipitation_sum and mean 2 m air temperature from 2016-01-01 to today for every rain_* point and the city/intake points in config/locations.yaml. Pull daily river_discharge (GloFAS) for river points: Dibrugarh, Tezpur-area point on the river, Chandrapur, Pandu/Guwahati, and the IITG intake. If a point returns no discharge, nudge coordinates onto the river channel and log it.
3. Save raw JSON to bronze, typed Parquet to data/silver/hydromet.parquet, provenance=public_observed (reanalysis/model products: set method accordingly and note "modelled discharge (GloFAS), not a gauge" in source_ref).
4. Build an incremental mode (fetch only new days) — this will run daily during the presentation.
5. Estimate the flow-wave lag: cross-correlate discharge at each upstream point with Guwahati for monsoon seasons; save lag_days and correlation to data/gold/flow_lags.parquet. Add a plot to docs/figures/.

Acceptance: no gaps longer than 3 days (else logged), lag estimates are physically sensible (upstream leads downstream), incremental run works.
Append the REPORT.md entry (Part A §8).

---

## P3 — Real data: Sentinel-2 turbidity index (the satellite "observation")

Goal: a real time series of a relative turbidity index (NDTI) for the Brahmaputra near Guwahati and near the IITG intake.

1. Define two river polygons in config (Guwahati reach near Pandu–Kacharighat; IITG intake reach). Keep them inside the main channel, away from banks and sandbars; save as GeoJSON in config/.
2. pipeline/ingest/sentinel2.py: query Microsoft Planetary Computer STAC (collection sentinel-2-l2a) for 2017→today over each polygon, sign assets with planetary_computer, read B03 (green), B04 (red) and SCL at the lowest resolution that works, only for the polygon window (don't download full tiles).
3. Keep only water pixels (SCL == 6). Skip scenes with fewer than a minimum count of clear water pixels (choose a threshold, justify it in REPORT.md). Compute per-scene NDTI = (B04 − B03)/(B04 + B03): median, IQR, n_pixels, cloud fraction.
4. Save to data/silver/s2_ndti.parquet (provenance=public_observed, method=satellite). Save a few quick-look PNGs of high- and low-NDTI scenes into docs/figures/ for the slides.
5. Report: scenes per year, per month (show the monsoon cloud gap), NDTI range.

Acceptance: at least a few hundred clear scenes across years (if far fewer, log why); monsoon months visibly higher NDTI than winter in the plot. Cache results so we never re-download during the demo.
Append the REPORT.md entry (Part A §8). Clearly note NDTI is a relative index, not NTU.

---

## P4 — Real data: news incidents (incident agent)

Goal: a structured, human-reviewable log of pollution-related incidents upstream of Guwahati.

1. pipeline/ingest/gdelt.py: query the GDELT DOC 2.0 API (confirm parameters from its docs first) for recent years with queries like Brahmaputra + (oil spill | effluent | discharge | pollution | contamination | fish death | flood) and Assam/Guwahati/Dibrugarh/Tezpur. Store raw results in bronze.
2. agents/incident_agent.py: for each article, fetch the page text if allowed, and have the LLM return strict JSON {is_relevant, kind, place_name, date_of_event, summary_1_sentence, confidence}. Geocode place_name with a simple offline gazetteer of Assam river towns in config (avoid paid geocoders). Compute river distance to the IITG intake along a simplified river polyline and an ETA range using water velocity 0.8–2.5 m/s (team estimate, in params.yaml) — output ETA as a range, never a single number.
3. Write data/silver/events_incidents.parquet with human_confirmed=false. Build a tiny CLI `python -m agents.review_incidents` to confirm/reject events; only confirmed events can trigger alerts.
4. Report counts: articles fetched, judged relevant, confirmed.

Acceptance: pipeline runs end-to-end; at least a handful of real, confirmed historical incidents (if none found, say so honestly and keep the pipeline — do not fabricate incidents).
Append the REPORT.md entry (Part A §8).

---

## P5 — Real data for consumer mode: JJM-WQMIS + groundwater

Goal: give households a local water-quality picture from real public tests.

1. Try to access JJM-WQMIS public reports for Assam (start at the URL in Part B §1). Only use public, no-login pages. If data is downloadable (tables/CSV/Excel), ingest Assam district-level results (samples tested, contaminated, parameters) into data/silver/jjm_wqmis.parquet. If it's not machine-accessible, stop after 45 minutes, log exactly what you tried in REPORT.md, and continue without it.
2. Build models/consumer/area_risk.py: for a lat/lon, find the nearest CPCB groundwater stations and (if available) district WQMIS stats, plus the river virtual-sensor state; return a plain-language summary listing which parameters were tested, when, and which exceeded BIS limits — with dates and distances so the user sees how old/far the evidence is.

Acceptance: area_risk returns a sensible answer for 3 test points in Guwahati and one on the IITG campus; outputs always show data age and source.
Append the REPORT.md entry (Part A §8).

---

## P6 — Synthetic IITG network + chlorine twin data (auditable)

Goal: simulate what we cannot measure — the campus distribution network and tap residuals — using documented physics, so the dose and alert logic can be built and tested.

Follow Part B §5 and §6 exactly.

1. pipeline/synthetic/network.py: build the campus graph from config/campus.yaml (WTP → reservoir → hostel tanks → coolers/RO units). Sample travel and residence times from params.yaml. Save data/silver/network_edges.parquet and sites (provenance=synthetic, generator name + version + seed in source_ref).
2. models/twin/chlorine.py (deterministic, unit-tested): first-order decay C(t) = C0·exp(−k·t), with k = k_b(T) in tanks and k_b(T)+k_w,eff in pipes, k_b(T) = k_b20·θ^(T−20). Monte Carlo over parameter uncertainty → p10/p50/p90 residual at every node for a given dose, water temperature and chlorine demand.
3. Water temperature: modelled from real Open-Meteo air temperature (lagged smoothing), clipped to the NWMP seasonal envelope → provenance=modelled.
4. Chlorine demand: from the virtual-sensor NDTI (P7; until then use raw NDTI where available) via the flagged team-estimate relationship in Part B §5.
5. pipeline/synthetic/tap_readings.py: generate daily "field kit" readings at each hostel for the last 3 years by running the twin with a realistic historical dose policy, then applying Part B §5 instrument noise, resolution, missingness and transcription errors. Inject labelled anomalies (dirty tanks) into a separate evaluation file data/silver/anomaly_labels.parquet.
6. Complaints: generate 60–150 short synthetic complaints (English/Hindi/Assamese mix) using the Claude API, category shares from our KRITI survey priors; provenance=synthetic.
7. Run pipeline/validate/synthetic_checks.py (all Part B §6 checks). Regenerate with the same seed and confirm identical hashes. Write docs/SYNTHETIC_METHOD.md explaining every formula, parameter, citation/estimate and seed — this is the document that makes our synthetic data defensible if a judge tries to reverse-engineer it.

Acceptance: all checks pass; hashes identical on regeneration; row counts per provenance class logged.
Append the REPORT.md entry (Part A §8).

---

## P7 — Virtual river sensor (quantile ML on real data)

Goal: a daily turbidity-index estimate with uncertainty, including cloudy days.

1. models/virtual_sensor/features.py: build daily features from real data only — rainfall at each upstream point lagged 0–10 days and rolling sums, GloFAS discharge and its 1/3/7-day changes at upstream and city points (use the P2 lag estimates to choose lags), air temperature, day-of-year sin/cos.
2. Target: S2 NDTI (median) for the Guwahati/intake polygon on clear-scene days.
3. Train LightGBM quantile models (alpha 0.1, 0.5, 0.9). Time-based split: train ≤ 2023-12-31, test ≥ 2024-01-01. Baselines: persistence (last clear value) and monthly climatology.
4. Report on the test set: MAE (p50) vs both baselines, p10–p90 coverage, and performance by season. Save plots to docs/figures/. Save predictions for every day 2017→today to data/gold/virtual_sensor_daily.parquet (provenance=modelled, model version in source_ref).
5. Add a "how confident today?" field: interval width and days since last clear satellite observation.

Acceptance: metrics logged with real numbers. If the model does not beat persistence, say so plainly, keep the baseline in production, and explain why in REPORT.md. Honesty beats a fake win.
Append the REPORT.md entry (Part A §8).

---

## P8 — Inverse dose solver + test-next (VOI)

Goal: the two decision outputs the chemist actually uses.

1. models/dose/solver.py: for a given day, find the minimum plant dose (0.5–4.0 mg/L, 0.05 steps) such that the p10 residual at the worst hostel tap ≥ 0.2 mg/L (BIS minimum), given the day's modelled water temperature and chlorine demand distribution. Return dose, the binding (worst) tap, its p10/p50 residual, and the p90 dose needed under a pessimistic scenario. Pure Python, deterministic, with tests: higher temperature → higher dose; higher demand → higher dose; never outside bounds.
2. models/voi/test_next.py: rank sites by expected risk reduction from one test today: P(residual < 0.2) × population_served × current uncertainty width (explain the formula in code docstring). Return the top site with a one-line reason made of numbers.
3. models/anomaly/tank_anomaly.py: flag tanks whose observed decay rate (from field readings) is abnormally high vs their neighbours at similar travel times (robust z-score). Evaluate against anomaly_labels.parquet: precision/recall, reported honestly as "on synthetic scenarios".
4. pipeline/run_daily.py: produces data/gold/daily_briefing.parquet (schema in Part B §3) for any date (supports historical replay) and for today.

Acceptance: tests pass; run_daily works for today and for a chosen historical monsoon date; results logged.
Append the REPORT.md entry (Part A §8).

---

## P9 — Agent graph (LangGraph) + guards

Goal: one orchestrated agent workflow the judges can see working, with safety guards.

1. agents/complaint_agent.py: input free text (any of English/Hindi/Assamese). Output strict JSON {site_guess, category ∈ [taste_odour, colour_turbidity, low_pressure, no_water, illness_report, purifier_fault, other], urgency 1–3, language, summary_en}. Cluster complaints by site and 48-hour window; a cluster of ≥3 opens an investigation event.
2. agents/explainer_agent.py: takes the daily_briefing row + active events and writes a 3–4 sentence plain-language briefing for the chemist and a 2-sentence version for households. agents/guards.py enforces: every number in the text must exist in the input payload (tolerance for rounding), no medical claims, synthetic-driven numbers must be labelled "assumed/simulated". If the guard fails twice, fall back to a deterministic template.
3. agents/graph.py (LangGraph): nodes = fetch_updates → ingest/validate → incident_scan → run_daily_models → complaint_triage → explain → publish. Log each node's inputs/outputs to data/gold/agent_runs/ for traceability.
4. Add a tiny eval: 30 hand-written complaint examples (write them, mark as test fixtures) with expected categories; report accuracy.

Acceptance: `python -m agents.graph --date today` runs end-to-end; guard test proves an invented number is rejected; eval accuracy logged.
Append the REPORT.md entry (Part A §8).

---

## P9A — Escalation: from "suspicion" to "authority verified"

Read Part A rules 9–11 and Part B §7 before starting.

Goal: when our system suspects water at a site/area may be unsafe, the right authority gets a clear verification request, and the case is tracked until it is confirmed, cleared and resolved. We never declare water unsafe ourselves.

1. models/escalation/state_machine.py (deterministic, unit-tested): states watch → verify_requested → sample_collected → confirmed_unsafe | cleared → advisory_issued → resolved. Only an authority actor can move to confirmed_unsafe, cleared or advisory_issued. Illegal transitions raise errors. Every transition writes case_log.
2. models/escalation/triggers.py: open or escalate cases from (a) campus: p10 tap residual < 0.2 mg/L at any site for 2 consecutive runs, or tank_anomaly flag, or complaint cluster ≥ 3 in 48 h; (b) public: confirmed incident with ETA reaching an intake, virtual-sensor p90 above its historical 95th percentile, cluster of user reports in an area. Triggers configurable in params.yaml; each case stores the exact numbers that fired it.
3. Priority score = severity × population exposed × confidence; set an SLA due time per priority (config).
4. agents/escalation_agent.py: builds an evidence packet per case — deterministic facts table (site, readings, forecast band, trigger rule, sources, provenance badges, map/schematic reference), a suggested test list (e.g. free chlorine DPD, turbidity, H2S bacteria vial / coliform lab test, and for suspected industrial incidents: request lab analysis for the relevant parameters), suggested sampling points upstream/downstream of the suspected source, plus an LLM-written cover note (guard: no numbers not in the facts table; no claim that water IS unsafe). Route by config/authorities.yaml. Deliver to the in-app Authority inbox and write an outbox file; real email only if WW_SEND_EMAIL=true.
5. Authority actions: acknowledge, record sample collected, upload results (values + method + tester), mark confirmed_unsafe / cleared, publish advisory text (authority-written; our agent may draft, the authority must approve).
6. Feedback loop: verification_results are written into observations (authority-verified results as public_observed; demo results as synthetic) and used by models/calibration.py to update chlorine-decay/demand parameters for that site (simple Bayesian update, logged). Show before/after parameter values.
7. Tests: illegal transitions blocked; guard rejects "the water is unsafe" language before confirmation; an end-to-end demo case can run from trigger to resolved with synthetic authority actions.

Acceptance: `python -m models.escalation.demo_case` runs one campus case and one public case end-to-end and prints the full case_log.
Append the REPORT.md entry (Part A §8).

---

## P9B — Alternatives: what people should do meanwhile

Goal: whenever a case is open, both audiences get safe, trustworthy options.

HOUSEHOLDS
1. pipeline/ingest/osm_water.py: fetch Guwahati drinking-water points from OpenStreetMap via Overpass (amenity=drinking_water, amenity=water_point, man_made=water_tap, and vending/water-ATM tags you find in the data). Cache to bronze; silver rows are provenance=public_observed, test_status=untested ("location only").
2. If JJM-WQMIS gave source-level tested results in P5, add them as tested alternatives with their test dates.
3. Seed a small, clearly badged "demo" set of registered tankers/relief distribution points (synthetic) so the flow is demonstrable; add an Authority action "register verified supply point" that creates real, verified entries.
4. models/alternatives/public.py: given a location and case, rank options by: verified & tested first, then distance, then recency of verification; always show last_verified_at and who verified. Attach precaution cards chosen by case type: microbial suspicion → boil water (rolling boil ~1 min) or use tested source; chemical/oil suspicion → do NOT rely on boiling, use an alternative source; turbidity → let settle/filter AND disinfect, or use alternative. Precaution texts are fixed, reviewed templates — never LLM-generated.

CAMPUS
5. models/alternatives/campus.py (deterministic, tested):
   a. Intake-pause decision per Part B §7: compare forecast spike duration (p90) with storage hours above reserve → "pause intake and run on storage for N hours" or "partial intake + higher dose" or "emergency supply".
   b. Tank isolation / reroute: if a tank case is open, find alternative feeds via campus.yaml (`can_isolate`, `alt_feed_from`), check the twin still keeps p10 residual ≥ 0.2 mg/L on the rerouted path, and list affected hostels.
   c. Emergency supply plan: for hostels without a safe feed, litres/day needed (population × 3–5 L), suggested distribution points (mess, hostel lobby), and a checklist for estates.
   All inputs marked assumed until WTP confirms.
6. Tests: pause recommended only when storage covers the spike; rerouting never chosen if it breaks the residual target; chemical cases never show "boil" as the sole remedy.

Acceptance: for the replay date and for a demo case, both audiences get ranked alternatives with sources, dates and badges.
Append the REPORT.md entry (Part A §8).

---

## P9C — Automatic routing by geography and PIN code

Goal: every case automatically reaches the right (dummy) authority from the location alone, with a confidence score and a safe fallback.

Read config/authorities.yaml (all dummy; keep it that way), config/routing_rules.yaml and Part B §1 geography sources and §7 jurisdictions.

1. pipeline/ingest/geo.py:
   - Download the Dept. of Posts "All India PIN Code Boundary geo-json" from the Open Government Data platform (verify the download route; if it needs a manual click, tell me exactly which file to place in data/bronze/geo/). Keep only Assam PIN polygons → data/silver/geo/pin_assam.parquet (GeoParquet).
   - Assam district polygons (verify source/licence) → district_assam.
   - From OpenStreetMap (Overpass): IITG campus polygon (geofence iitg_campus) and the Guwahati city/municipal boundary if mapped (else approximate it from the urban PIN polygons and label the method "approximate").
   - River reaches: split the Brahmaputra centreline into named reaches (e.g. Dibrugarh, Tezpur, Guwahati-upstream, Guwahati, Guwahati-downstream) → river_reaches.
   - Build a spatial index; everything must work offline once built.
2. models/routing/resolver.py (deterministic, unit-tested):
   resolve(lat, lon | pincode | digipin, water_source) → Jurisdiction.
   Order: campus geofence → city boundary → district → state; attach PIN, post office and postal division from the PIN polygon; nearest river reach within 2 km for river incidents.
   Confidence: 1.0 point-in-polygon well inside; reduced near boundaries (within boundary_buffer_m → near_boundary=true); PIN-only input gives lower confidence because a PIN can cross district/city lines — when the PIN polygon intersects more than one district/city, return all candidates.
3. models/routing/router.py: apply routing_rules.yaml (most specific match wins; ties notify all; near_boundary notifies both sides; confidence < auto_route_min → ask the user to confirm their area in the app, or send to state_catch_all). Add cc_downstream_intakes for river incidents using the ETA model. Write the chosen route + the rule id that fired into the case, so every routing decision is explainable.
4. Consumer flow: when a user reports or checks their area, ask ONE question — "Where does your drinking water come from?" (piped supply / community tap or well / own borewell / tanker / home RO) — because the responsible authority depends on it.
5. Evaluation: create 40 labelled test locations (campus hostels, central Guwahati, city edge, rural Kamrup, points near district boundaries, river-bank incidents, a PIN that spans two districts). Report routing accuracy, how many went to catch-all, and every miss with its reason.
6. Keep an append-only routing_feedback table: an authority can mark "not my jurisdiction" and reassign; these corrections are reported as a data-quality metric.

Acceptance: resolver + router tests pass; evaluation table logged; the app shows "Sent to: <dummy authority> — because <rule, area, confidence>" on every case.
Append the REPORT.md entry (Part A §8).

---

## P10 — Backend API (FastAPI) + snapshot

Goal: a small, fast, reliable API for the phone.

Endpoints (JSON, typed with pydantic, all include provenance badges):
- GET /health
- GET /campus/today?date=YYYY-MM-DD (default today): briefing, dose, worst tap, test-next, explanation, confidence
- GET /campus/network?date=: every node with p10/p50 residual, status colour, anomaly flag, synthetic badge
- GET /alerts?date=: confirmed incidents with ETA ranges, complaint clusters
- POST /complaints: runs complaint_agent, stores event, returns structured result
- GET /consumer/area?lat=&lon=: area_risk output + river state + relevant alerts
- GET /replay/events: list of notable historical dates (highest NDTI days, confirmed incidents) for demo replay
- GET /meta/datasheet: row counts per provenance, sources, last update time (shows the pipeline is live)
- GET /cases?audience=campus|public&state=: open cases with priority, SLA, evidence summary
- GET /cases/{id}: full evidence packet + case_log timeline
- POST /cases/{id}/actions: authority actions (acknowledge, sample_collected, upload_results, confirm_unsafe, clear, publish_advisory, resolve) — enforce the state machine; require an `actor_role` header (simple demo PIN per role, not real auth — say so in docs)
- GET /alternatives/public?lat=&lon=&case_id=: ranked safe-water options + precaution cards
- GET /alternatives/campus?date=&case_id=: intake-pause decision, reroute plan, emergency supply plan
- POST /supply-points: authority registers a verified supply point
- GET /resolve?lat=&lon=|pincode=&water_source=: jurisdiction + routed (dummy) authorities + rule id + confidence

Use DuckDB over the Parquet files; precompute where possible so every call returns in < 500 ms. Add CORS for the Expo app. Add api/snapshot.py that exports a complete JSON snapshot (today + 3 replay dates + network + consumer answers for 5 preset locations) to app/assets/snapshot.json. Include one complete demo case (campus) and one (public) with every state of their case_log, plus alternatives, so the full safety loop can be demoed offline.

Acceptance: pytest for each endpoint; p95 latency < 500 ms locally; snapshot file generated.
Append the REPORT.md entry (Part A §8).

---

## P11 — Mobile app (Expo, runs in Expo Go on my phone)

Read Part A §5 again. Build app/ with Expo (latest SDK), TypeScript, expo-router. It must run in Expo Go on Android and iPhone without custom native modules.

Two modes chosen on first launch (switchable in settings):

CAMPUS CONSOLE (for the WTP chemist / estates / wardens)
- Today: big risk level, recommended dose with p10–p90 band, "why" explanation from the explainer agent, confidence (days since last satellite pass), "assumed parameters" badge.
- Network: schematic source-to-tap diagram drawn with react-native-svg (river → intake → WTP → reservoir → hostels), each node coloured by p10 residual; tap a node for its chart and details. No map API keys.
- Test next: the single recommended test with its numeric reason.
- Alerts: incidents with ETA ranges; complaint clusters; tap to see sources.
- Replay: pick a historical date (from /replay/events) and the whole console re-renders for that day — this is the demo's centrepiece.

CONSUMER (for households)
- My area: uses expo-location (with manual location picker fallback) → /consumer/area; shows what's known, how old and how far the evidence is, and clear "what this can't tell you" text.
- Alerts near me.
- Report a problem: free text in any language → POST /complaints → shows how the agent understood it.
- Learn: short cards on chlorine residual, turbidity, when to boil water.

SAFETY LOOP (in both modes above)
- Campus console: a "Cases" tab (priority, state, SLA countdown) and an "If unsafe" panel showing the intake-pause decision, reroute plan and emergency supply plan with their numbers.
- Consumer: when a case covers the user's area, a banner "Under verification by <authority>" (never "unsafe" unless confirmed), precaution cards, and a ranked list of safe-water options with distance, last-verified date and badges; one tap opens directions in the phone's maps app via a geo: / maps URL (no map SDK needed). After an authority advisory, show it verbatim with the authority's name.

AUTHORITY MODE (third mode, PIN-protected for the demo)
- Inbox of verification requests with the evidence packet.
- Buttons for each allowed action (acknowledge → sample collected → upload results → confirm unsafe / clear → publish advisory → resolve).
- Register a verified supply point (name, location from phone GPS, operator, test status).
- This lets me demo the full loop on one phone: consumer report → case → authority verifies → advisory + alternatives appear for the consumer and campus.

Reliability requirements:
- API base URL set in settings (for the cloudflared URL) and via EXPO_PUBLIC_API_BASE.
- If the API is unreachable within 3 s, automatically use assets/snapshot.json and show an "offline demo data" banner.
- Every screen shows provenance badges (public / modelled / synthetic).
- Clean, calm design; large readable numbers; works in dark mode.

Acceptance: `npx expo start`, scan QR with Expo Go, every screen works online and in airplane mode (snapshot). Record which phone/OS you tested on.
Append the REPORT.md entry (Part A §8).

---

## P12 — Make it live on my phone + keep the pipeline running during the presentation

1. Write scripts/demo_up.sh (and .ps1 for Windows): activate env → run pipeline incremental update → start uvicorn → start `cloudflared tunnel --url http://localhost:8000` → print the public URL and a QR code for it → regenerate the app snapshot.
2. Schedule pipeline/run_daily.py (incremental fetch of Open-Meteo, GloFAS, Sentinel-2 new scenes, GDELT) every 3 hours via cron (Linux/macOS) or Task Scheduler (Windows), logging each run to data/gold/run_log.parquet. /meta/datasheet must show "last updated" so judges see collection still running.
3. Write docs/DEMO_CHECKLIST.md: phone charged, Expo Go installed, snapshot fresh, tunnel URL set in app, airplane-mode fallback tested, backup screen recording made.
4. Record a 3-minute screen recording of the demo flow as backup (instructions only; I'll record it).

Acceptance: from a different network (mobile data), the phone loads live data through the tunnel; with the laptop off, the app still runs on the snapshot.
Append the REPORT.md entry (Part A §8).

---

## P13 — Submission data package (judged at 25% + 25%)

Goal: a dataset a stranger can load and understand without us in the room.

Create data/release/:
- Parquet files: sites, observations (all provenance classes), events, daily_briefing, virtual_sensor_daily, s2_ndti, hydromet, network_edges.
- sample_1000_rows.csv from observations, stratified by provenance.
- docs/SCHEMA.md: every column, type, unit, allowed values.
- docs/DATASHEET.md: row counts (total and per provenance class), collection windows, cadence per source, retrieval dates, where each observation came from, what is observed vs modelled vs synthetic, how AI was used (ingestion agent, incident agent, complaint agent, explainer, ML model), known gaps and biases (monsoon cloud gap, yearly-only NWMP publication, GloFAS is modelled, campus layer simulated).
- A load_example.py that loads everything with DuckDB and prints the provenance split.
- A zip of the release.

Acceptance: a fresh Python environment can run load_example.py from the zip alone.
Append the REPORT.md entry (Part A §8).

---

## P14 — Slide assets + judge notes

From our real outputs, produce docs/figures/ for exactly 3 slides:
1. Problem/user/question: timeline showing sparse NWMP samples vs our daily estimate with uncertainty band.
2. Workflow + method: the architecture (source → lakehouse → models → agents → apps) with the provenance split numbers.
3. Result: virtual-sensor test metrics vs baselines; dose recommendation on the replay date; what changes for the chemist; the "what this data can't tell us" box.

Write docs/JUDGE_NOTES.md: a 3-minute talk track, and prepared answers to hard questions (Is the synthetic data real? How would you validate the dose? Why not just install sensors? What if the model is wrong? What does it cost to run? What if you raise a false alarm? Who is liable if someone follows your alternatives? Why would an authority act on your request?). The false-alarm answer: we only request verification, authorities confirm, and every verified result recalibrates the model. Every answer must be consistent with REPORT.md.
Append the REPORT.md entry (Part A §8).

---

## P15 — Final hardening

Run the full test suite, run the whole pipeline from bronze on a clean clone, fix anything flaky, remove dead code, make sure no secret is committed (scan the repo), update README.md with a 5-minute quickstart, and write the final REPORT.md entry summarising the whole build: timeline, what we built, key numbers, what failed and how we handled it, and honest limits.

---

## Emergency prompts

- **Source down:** "Source <x> is failing. Don't fabricate. Use cached bronze data if present, mark the gap in the datasheet and REPORT.md, and continue."
- **Running out of time:** "Freeze features. Make the Today, Network, Replay and Consumer My-area screens flawless on the snapshot. Skip everything else. Log what was cut in REPORT.md."
- **Model underperforms:** "Keep the better baseline in production, report both honestly, and make the app show the baseline's uncertainty."

---

# Part D — Config files to create verbatim

## D1. `config/authorities.yaml`

```yaml
# config/authorities.yaml — DUMMY DIRECTORY (demo only)
#
# Every entry is fictional. Emails use the reserved `.invalid` top-level domain
# (RFC 2606), which can never be delivered, so nothing can reach a real office
# even if WW_SEND_EMAIL is switched on by mistake.
# To go live later: replace an entry with an officially published contact route,
# set dummy: false, and log the change + its source in REPORT.md.

global:
  all_dummy: true
  send_email_default: false

authorities:
  # ---------- CAMPUS (IITG geofence) ----------
  - id: campus_wtp_chemist
    name: "Demo — Campus WTP Chemist"
    audience: campus
    role: wtp_operator
    jurisdiction: {geofence: iitg_campus}
    channels: {inbox: true, email: "wtp-chemist@campus.demo.invalid"}
    handles: [low_residual, raw_water_spike, dose_review, incident_upstream]
    dummy: true

  - id: campus_estates
    name: "Demo — Campus Estates / Plumbing Section"
    audience: campus
    role: estates
    jurisdiction: {geofence: iitg_campus}
    channels: {inbox: true, email: "estates@campus.demo.invalid"}
    handles: [tank_anomaly, pipeline_fault, reroute, emergency_supply]
    dummy: true

  - id: campus_hostel_warden
    name: "Demo — Hostel Warden ({hostel_id})"   # one virtual entry per hostel
    audience: campus
    role: warden
    jurisdiction: {geofence: iitg_campus, per_site: hostel}
    channels: {inbox: true, email: "warden-{hostel_id}@campus.demo.invalid"}
    handles: [complaint_cluster, purifier_fault, emergency_supply]
    dummy: true

  - id: campus_health_centre
    name: "Demo — Campus Health Centre"
    audience: campus
    role: health
    jurisdiction: {geofence: iitg_campus}
    channels: {inbox: true, email: "health@campus.demo.invalid"}
    handles: [illness_cluster]
    dummy: true

  # ---------- PUBLIC ----------
  - id: city_water_utility
    name: "Demo — City Water Utility"
    audience: public
    role: urban_water_supplier
    jurisdiction: {area_type: urban, boundary: city_limits_guwahati}
    channels: {inbox: true, email: "quality@cityutility.demo.invalid"}
    handles: [piped_supply_contamination, low_residual, complaint_cluster]
    dummy: true

  - id: rural_water_division
    name: "Demo — Rural Water Supply Division ({district})"
    audience: public
    role: rural_water_supplier
    jurisdiction: {area_type: rural, per: district}
    channels: {inbox: true, email: "division-{district_slug}@ruralwater.demo.invalid"}
    handles: [piped_supply_contamination, community_source_contamination, complaint_cluster]
    dummy: true

  - id: pollution_regional_office
    name: "Demo — Pollution Control Regional Office ({river_reach})"
    audience: public
    role: pollution_regulator
    jurisdiction: {per: river_reach}
    channels: {inbox: true, email: "ro-{reach_slug}@pollution.demo.invalid"}
    handles: [industrial_discharge, oil_spill, incident_upstream]
    dummy: true

  - id: district_health_surveillance
    name: "Demo — District Disease Surveillance ({district})"
    audience: public
    role: health
    jurisdiction: {per: district}
    channels: {inbox: true, email: "surveillance-{district_slug}@health.demo.invalid"}
    handles: [illness_cluster]
    dummy: true

  - id: state_catch_all
    name: "Demo — State Water Quality Desk (catch-all)"
    audience: public
    role: fallback
    jurisdiction: {per: state}
    channels: {inbox: true, email: "desk@statewater.demo.invalid"}
    handles: ["*"]
    dummy: true
```

## D2. `config/routing_rules.yaml`

```yaml
# config/routing_rules.yaml — who gets a case, decided from geography + case type
#
# The resolver (models/routing/resolver.py) turns a location into a Jurisdiction:
#   {geofence, area_type (urban|rural|campus), city, district, state,
#    pincode, post_office, postal_division, river_reach, confidence, method}
# Rules below are matched top to bottom; the MOST SPECIFIC matching rule wins
# (more matched keys = more specific). Ties → notify all tied authorities.

rules:
  # Campus: anything inside the IITG geofence stays on campus first
  - match: {geofence: iitg_campus, case_type: [low_residual, raw_water_spike, dose_review]}
    notify: [campus_wtp_chemist]
    cc: [campus_estates]
  - match: {geofence: iitg_campus, case_type: [tank_anomaly, pipeline_fault]}
    notify: [campus_estates]
    cc: [campus_wtp_chemist, campus_hostel_warden]
  - match: {geofence: iitg_campus, case_type: [complaint_cluster, purifier_fault]}
    notify: [campus_hostel_warden]
    cc: [campus_estates]
  - match: {geofence: iitg_campus, case_type: [illness_cluster]}
    notify: [campus_health_centre]
    cc: [campus_wtp_chemist]

  # Public, piped supply: depends on urban vs rural
  - match: {area_type: urban, water_source: piped, case_type: [piped_supply_contamination, low_residual, complaint_cluster]}
    notify: [city_water_utility]
  - match: {area_type: rural, water_source: [piped, community_source], case_type: [piped_supply_contamination, community_source_contamination, complaint_cluster]}
    notify: [rural_water_division]

  # Private sources (own borewell / RO / tanker): utility isn't responsible,
  # so we advise the household and log area-level patterns for the division
  - match: {water_source: [own_borewell, private_tanker, home_ro]}
    notify: []
    household_guidance: private_source
    aggregate_to: rural_water_division   # only if ≥3 reports in same PIN/ward in 7 days

  # River incidents route by river reach, plus every intake downstream
  - match: {case_type: [industrial_discharge, oil_spill, incident_upstream]}
    notify: [pollution_regional_office]
    cc_downstream_intakes: true          # campus_wtp_chemist, city_water_utility if intake is downstream within ETA window

  # Health signals always also go to surveillance
  - match: {case_type: [illness_cluster]}
    notify: [district_health_surveillance]

  # Nothing matched or low-confidence location → human-routed catch-all
  - match: {}
    notify: [state_catch_all]

confidence:
  auto_route_min: 0.8          # below this, ask user to confirm area, or send to catch-all
  boundary_buffer_m: 250       # point within 250 m of a boundary → notify both sides

escalation_ladder:             # if SLA missed, move up one step
  campus: [campus_wtp_chemist, campus_estates, state_catch_all]
  public: [city_water_utility, rural_water_division, state_catch_all]

sla_hours: {high: 6, medium: 24, low: 72}
```

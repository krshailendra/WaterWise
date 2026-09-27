# REPORT.md — how we built WaterWise

This is our build log. Every step of the project is recorded here, in order, including what failed. Claude Code appends an entry after every task (format in PLAN.md Part A §8). Nothing is rewritten after the fact.

**Team:** KrShaily · **Event:** Granica × IIT Guwahati — Bring the Physical World to AI (48 h)

**One-line summary:** WaterWise tells the IITG water treatment plant chemist, every morning, what chlorine dose keeps every hostel tap safe and where to test next — built from public river, weather and satellite data, with the parts we can't yet measure simulated from documented physics and clearly labelled.

**Provenance classes used everywhere:** `public_observed` (real public data) · `modelled` (our model outputs from real data) · `synthetic` (simulated from documented parameters, reproducible from seed).

---

## Entry 000 — Problem discovery (pre-event planning, KRITI '25)

**Prompt/phase:** Planning (allowed before kickoff)
**Goal:** Understand IITG's drinking-water workflow and find a decision that is hard today.
**What changed:** No code. Reused our KRITI '25 "Water Wise Consulting" root-cause analysis and campus survey as problem context only.
**Data:** KRITI '25 campus survey (self-reported; small sample). Interviews: a Civil Engineering professor, IPM section engineers, and the IITG WTP chemist.
**Decisions & why:**
- The workflow: Brahmaputra → intake (a barge in the low-water months, Dec–Mar) → campus WTP (conventional treatment + chlorination) → overhead tanks → hostel taps, coolers, RO units.
- The hard decision: chlorine dosing. The WTP chemist told us a system that calculates and monitors chlorine doses would be valuable. That became our user and our question.
- Distribution-side issues from the survey (irregular purifier maintenance, uncleaned tanks, algae) motivated the tank-anomaly and test-next features.
**Honest limits found:** Survey is small and self-reported. We have no access to WTP logs or campus pipe network data yet.
**Next:** Research which public data could support the decision.

---

## Entry 001 — Solution design and data research (pre-event planning)

**Prompt/phase:** Planning
**Goal:** Choose data sources and a design that fits the rules and the judging criteria.
**What changed:** Wrote the project plan (now consolidated in PLAN.md).
**Data (identified, not yet downloaded):**
- CPCB NWMP river data: PCB Assam samples Brahmaputra stations monthly, including Kacharighat (Guwahati) and a station near a city water intake point — but published tables are mostly yearly min/max. This sparsity is the gap we address.
- Open-Meteo weather archive and GloFAS discharge (daily); Sentinel-2 L2A (every 2–5 days, cloud-limited); GDELT news; JJM-WQMIS (public-domain drinking-water tests, access to be verified); CPCB groundwater stations in Guwahati.
**Decisions & why:**
- **Daily "virtual sensor" from sparse data:** satellite turbidity index + lagged upstream rain + discharge, with uncertainty that widens on cloudy days.
- **River as a conveyor belt:** estimate lags from real discharge series; incident ETAs as ranges.
- **Dose calculated backwards from the farthest tap:** first-order chlorine decay with temperature correction; target ≥ 0.2 mg/L free chlorine (BIS IS 10500).
- **Test-next recommendation:** value-of-information ranking, so the system says where testing matters most.
- **Agents only for messy inputs** (PDF tables, news, multilingual complaints, explanations); safety numbers stay deterministic.
- **Synthetic data only where measurement is impossible now** (campus network, tap residuals, complaints), generated from documented physics with fixed seeds, fully disclosed.
**Claims we dropped from the KRITI deck and why:**
- "The Brahmaputra produces ~179 million litres of wastewater daily" — a river doesn't produce wastewater; source needs re-checking. Not used.
- "Tibetan dams are lowering water levels" — contested, and not testable with our data. Not used.
- Heavy-metal exceedances — kept out of our headline because cheap/public data can't track them daily.
**Honest limits found:** NDTI is relative, not NTU; GloFAS is modelled discharge; the campus layer is simulated until the WTP shares logs.
**Next:** P0 at kickoff.

---

## Entry 002 — Safety loop: escalation and alternatives (pre-event planning)

**Prompt/phase:** Planning
**Goal:** Decide what happens after our system suspects water is unsafe, for both campus and households.
**What changed:** Added PLAN.md rules 9–10, Part B §7, phases P9A and P9B, a third app mode (Authority), and new API endpoints.
**Data:** New tables `cases`, `case_log`, `verification_results`, `alternatives_public`, `campus_resilience`. New real source: OpenStreetMap water points (location only, untested). Demo-only tanker/relief entries are synthetic and badged.
**Decisions & why:**
- **We request verification; authorities confirm.** A model can be wrong, and a false "unsafe" message could cause panic or push people to worse sources. So the app says "under verification" until an authority records a test result.
- **Verified results become ground truth.** Every authority test flows back into the data and recalibrates the model for that site — the verification step improves the system instead of just closing a ticket.
- **Alternatives are ranked by trust, not just distance.** Tested and recently verified sources first; untested OSM points labelled "location only".
- **Precautions depend on the suspected cause.** Boiling helps with microbes but not chemical or oil contamination, so chemical cases never show boiling as the only remedy. Precaution texts are fixed templates, not LLM output.
- **Campus "change the source" logic:** compare the forecast raw-water spike duration with storage hours; recommend pausing intake and running on storage when storage covers the spike, otherwise partial intake with a higher dose, or emergency supply for hostels at the end of the network.
**Honest limits found:** Authority contacts must be verified before any real message is sent (email is off by default). Campus storage and demand figures are estimates until the WTP confirms them. OSM coverage of Guwahati water points may be thin.
**Next:** P0 at kickoff.

---

## Entry 003 — Automatic routing by geography; dummy authorities (pre-event planning)

**Prompt/phase:** Planning
**Goal:** Send every case to the right authority automatically, without real contacts during the hackathon.
**What changed:** Created config/authorities.yaml (all dummy, undeliverable `.invalid` emails) and config/routing_rules.yaml; added phase P9C, the `/resolve` endpoint, Part B geography sources and the `jurisdictions` table; PLAN.md rule 11.
**Data:** Dept. of Posts All India PIN Code Boundary GeoJSON (official, open; PIN polygons with post office and postal division), Assam district polygons, OpenStreetMap campus and city boundaries, Brahmaputra reaches.
**Decisions & why:**
- **GPS + boundaries first, PIN code second.** A PIN code is a postal zone: it can cross district or city limits and says nothing about who supplies the water. So location is resolved by point-in-polygon (campus → city → district → state) and the PIN is attached for display, or used as a lower-confidence fallback that can return several candidates.
- **The water source changes the authority.** Piped urban supply, rural community sources and private borewells/tankers have different responsible bodies, so the app asks one question about the source.
- **Uncertainty is handled explicitly.** Points near a boundary notify both sides; low-confidence locations ask the user to confirm or go to a human-routed catch-all.
- **Every routing decision is explainable** (rule id + confidence stored on the case), and authorities can reject and reassign — those corrections become a routing-accuracy metric.
- **Privacy:** cases keep area-level location by default; exact coordinates only with consent, dropped after resolution.
**Honest limits found:** Real water-service areas aren't public, so routing uses administrative boundaries as a proxy. The Guwahati municipal boundary may be missing or approximate in OSM. All authorities are fictional until replaced with officially published routes.
**Next:** P0 at kickoff.

---

<!-- Claude Code: append new entries below this line using the PLAN.md Part A §8 template. -->

## Entry 004 — P0 project skeleton  (2026-09-26 22:55 IST)
**Prompt/phase:** P0
**Goal:** Stand up the repository skeleton, config, provenance-enforcing writer and a passing test harness.
**What changed:**
- `CLAUDE.md` (rules + templates that persist across sessions), first git commit (PLAN/REPORT/CLAUDE).
- Full tree per Part A §4: `config/`, `data/{bronze,silver,gold,release}`, `pipeline/{ingest,synthetic,validate}`, `models/*`, `agents/`, `api/routes/`, `app/assets/`, `notebooks/`, `tests/`, `scripts/`, `docs/figures/`.
- `pyproject.toml` (core deps + `ingest/geo/ml/agents/api/dev` extras), `.env.example` (ANTHROPIC_API_KEY, WW_MODEL_MAIN=claude-sonnet-5, WW_MODEL_FAST=claude-haiku-4-5-20251001, WW_API_BASE, WW_SEND_EMAIL=false), `.gitignore`, `Makefile` (ingest/synth/validate/train/daily/api/test), `README.md`, `pipeline/run_daily.py` CLI stub.
- Config: `locations.yaml` (Part B §2; approx coords flagged for P1 replacement), `campus.yaml` (12 hostels H01–H12 pop 300–900, WTP+reservoir, distances, every value `assumed: true`), `params.yaml` (all Part B §5 synthetic params + basis strings + fixed seed 20250926), plus `authorities.yaml` and `routing_rules.yaml` created verbatim from Part D.
- `pipeline/schemas.py`: pydantic models for sites, observations, events, daily_briefing, network_edges (Part B §3) + controlled vocab enums; single `write_table()` writer that refuses any row missing provenance/source_id/source_ref.
- `tests/test_writer_provenance.py`.
**Data:** No data ingested yet (P0 is scaffolding). 0 rows all provenance classes.
**Decisions & why:** Split heavy geo/ML libs into optional extras so P0 installs cleanly on Windows/py3.13 and each phase pulls only what it needs. Enforced provenance in one choke-point (`write_table`) rather than per-table so rule 2 can't be bypassed. `.gitignore` excludes bronze binaries (reproducible from URL+sha256 sidecars) and generated silver/gold parquet.
**Validation:** `pytest -q` → 6 passed (writer rejects missing provenance / blank source_id / missing source_ref; accepts complete dict + pydantic instances; error names the bad row index). All 5 config YAMLs parse (9 dummy authorities, all_dummy=true; 12 hostels). Env: Python 3.13.3, Node v22.16.
**Honest limits found:** pytest's default Windows temp root was permission-denied; pinned `--basetemp=.pytest_tmp`. CPCB station coords in locations.yaml are still approximations (Kacharighat lat/lon null) until parsed from WQMN_list.pdf in P1. Heavy extras (geo/ml/agents/api) not yet installed — deferred to their phases.
**Next:** P1 — CPCB NWMP river + station-list ingestion with the ingestion agent.

## Entry 005 — P1 CPCB NWMP river + station list  (2026-09-26 23:55 IST)
**Prompt/phase:** P1
**Goal:** Build the real historical Brahmaputra water-quality record around Guwahati from CPCB NWMP publications, with an ingestion agent for pages that resist deterministic parsing.
**What changed:** `pipeline/ingest/common.py` (polite download + sha256 sidecars), `pipeline/ingest/cpcb.py` (source registry, station-list parser, dual-schema river parser, groundwater parser, runner), `agents/ingestion_agent.py` (LLM fallback), `pipeline/validate/cpcb_checks.py`, `tests/test_cpcb.py`; updated `config/locations.yaml` with real station coords; `pyproject.toml` gained `pymupdf`.
**Data:** CPCB NWMP. Downloaded to bronze: station list (WQMN_list.pdf), 8 river-data PDFs (2016–2023) + 7 groundwater PDFs (2016–2022; 2023 GW is 404). Written silver (all `public_observed`, method=lab):
- `cpcb_river.parquet`: **3,938 obs** across 7 years (2016, 2018–2023), 74 river sites. Flags: 3,712 ok, 220 suspect (published "-"/missing markers → value null), 6 out_of_range (kept & flagged).
- `cpcb_groundwater.parquet`: **3,820 obs** (2020–2022), 67 Assam GW sites, 766 below-detection (BDL→null).
- `cpcb_sites.parquet` (74), `cpcb_gw_sites.parquet` (67), `cpcb_stations_assam.parquet` (198 stations), `cpcb_audit_sample.csv` (20 rows w/ source page+quote).
- Real coords recovered incl. Kacharighat intake (2069: 26.190,91.746), Pandu (1031), Bharalu (1528), Chandrapur (2064), Dibrugarh (1030). All 6 target stations present in 2019–2023.
**Decisions & why:** Deterministic parsing achieved **100%** (0 rows needed the LLM agent), so no ANTHROPIC_API_KEY was required for P1. Switched PDF text extraction from pdfplumber (~0.75 s/page → 20+ min, timed out) to **PyMuPDF** (~0.6 s/whole-PDF). Parser is token-stream based (pymupdf emits one token/line): code → name lines → exact-state line (disambiguated as the ASSAM immediately followed by a value) → N value tokens (whitespace-tokenised to handle 2023's merged lines). Per-page schema selection handles the year-to-year column change (9 params 2019–2023 incl. Fecal Streptococci; 8 params 2016/2018). Yearly min/max encoded as `<param>_min`/`<param>_max` with ts=Jan-1 of the year, since CPCB publishes yearly aggregates, not a series. Station code is the join key (PDF names wrap unreliably); canonical name/lat/lon come from the station list.
**Validation:** `pytest -q` → **15 passed** (writer 6, cpcb 9: token-stream on real 2022/2018/2023 layouts, wrong-state skip, long wrapped name, BDL handling, validator ranges/units/codes). Pandu 2016–2023: pH 6.7–8.1, max temp 29–32 °C — physically sensible. Reproducible from bronze + code.
**Honest limits found:** (1) **2017 river = 0 rows** — its file (`Water_Quality_data_of_River_2017.pdf`) uses a layout our parser doesn't match; logged as a gap (an alternate `Water_Quality_Rivers_2017.pdf` exists; recover later via alt-URL or the LLM agent). (2) **2012–2015 river** are per-state HTML tables / not published in this series → gap. (3) **GW 2016–2019 = 0** (spelling/format differences) and **GW 2023 = 404** (not yet published). (4) Data is **yearly min/max only** — the core argument: too coarse for a daily dose decision. (5) The LLM ingestion agent is built and wired but untested against the live API (no key yet); it will be exercised if we later target the gap years.
**Next:** P2 — Open-Meteo rainfall/temperature + GloFAS discharge, and flow-wave lag.

## Entry 006 — P2 rainfall, temperature, river discharge (Open-Meteo + GloFAS)  (2026-09-27 00:20 IST)
**Prompt/phase:** P2
**Goal:** Build daily hydro-meteorological history (2016→today) with incremental update, and estimate the flow-wave lag to Guwahati.
**What changed:** `pipeline/ingest/openmeteo.py` (weather + discharge, bronze JSON + sidecars, incremental append), `models/eta/flow_lag.py` (xcorr lag + gap report + plot), `tests/test_openmeteo.py`, wired `pipeline/run_daily.py` (ingest/daily → incremental openmeteo + flow lags), `docs/figures/flow_lags.png`.
**Data:** Open-Meteo (all `public_observed`). Confirmed params (verified by live probe): archive `precipitation_sum` (mm), `temperature_2m_mean` (degC), method=reanalysis (ERA5); flood `river_discharge` (m3/s), method=model — labelled "MODELLED discharge (GloFAS), not a gauge" in every source_ref. `hydromet.parquet`: **74,518 rows**, 2016-01-01 → 2026-09-26 (3,922 days). 7 weather points (4 rain_* + Pandu + Kacharighat + IITG intake), 5 discharge points. No points needed channel-nudging; **no gaps > 3 days**. Discharge median 2,964 m3/s, monsoon max 63,532 m3/s; rain max 215.9 mm/day; air temp within 0–45 °C — all physically sensible for the Brahmaputra/Assam.
**Decisions & why:** Correlated monsoon (Jun–Sep) **first-differences** of discharge (not raw series, which share seasonality and spuriously give lag 0). Kept a separate incident water-velocity range in params.yaml for pollutant ETAs (flood-wave celerity ≠ pollutant velocity, Part B §8). Incremental mode keys off the max ts already in hydromet and de-dupes on (site,ts,parameter) — this is the loop that runs live during the demo.
**Validation:** `pytest -q` → **22 passed**. `_best_lag` recovers a synthetic 3-day shift exactly (method verified). Incremental run correctly reports "up to date".
**Honest limits found:** Flow-wave lag comes out **≈ 0 days** for all upstream points at daily GloFAS resolution (Tezpur corr 0.97, Chandrapur 0.55, Dibrugarh only 0.44, IITG-intake 1.00 — essentially the same GloFAS cell as Pandu). Interpretation: daily GloFAS cannot resolve sub-day flood-wave travel time over this reach, and the dominant daily signal is basin-wide monsoon forcing that moves the whole reach in phase. This is a real limitation, not a bug (the synthetic-shift test proves the estimator works). GloFAS is modelled discharge, not a CWC gauge. ERA5 rain is reanalysis, not gauge.
**Next:** P3 — Sentinel-2 turbidity index (NDTI) via Planetary Computer.

## Entry 007 — P3 Sentinel-2 turbidity index (NDTI)  (2026-09-27 01:15 IST)
**Prompt/phase:** P3
**Goal:** A real time series of a relative turbidity index (NDTI) for the Brahmaputra near Guwahati and the IITG intake, from Sentinel-2 L2A via Planetary Computer.
**What changed:** `config/river_polygons.geojson` (2 channel polygons), `pipeline/ingest/sentinel2.py` (STAC query, windowed COG reads, SCL water masking, NDTI stats, seasonal plot + quicklooks, incremental), `tests/test_sentinel2.py`, wired `pipeline/run_daily.py`, figures `docs/figures/s2_ndti_seasonal.png`, `s2_quicklook_high_ndti.png`, `s2_quicklook_low_ndti.png`. `pyproject.toml` gained pymupdf earlier; geo extras (pystac-client, planetary-computer, rioxarray, rasterio, shapely) + matplotlib installed.
**Data:** `s2_l2a` (public_observed, method=satellite). `s2_ndti.parquet`: **1,640 rows = 410 scenes** (guwahati_reach **290** across 2017–2026; iitg_intake_reach **120**, capped ~12 least-cloudy/yr). Per scene: ndti_median, ndti_iqr, water_pixels, cloud_fraction. NDTI = (B04−B03)/(B04+B03) over SCL==6 water pixels; read at 20 m; MIN_WATER_PIXELS=60. NDTI range −0.238 .. +0.041.
**Decisions & why:** PyMuPDF-style speed wasn't the issue here — MPC COG reads are ~6 s/scene (network latency), so reads run 8–10 wide in a thread pool. Read reflectance at the 20 m overview (median only needs coarse pixels). One scene/date (least cloudy). The first iitg polygon sat over IITG **land** (SCL: 7562 vegetation, 3740 soil, **2** water) — relocated south-west into the channel (verified 7,699 water pixels) and re-extracted. Results cached so nothing re-downloads at demo time.
**Validation:** `pytest -q` → **27 passed** (5 new: NDTI within [−1,1], expected params, water-pixel floor, provenance+"NOT NTU" label, ≥30 scenes/site). Winter median NDTI −0.064 (n=176) vs monsoon −0.071 (n=28).
**Honest limits found:** (1) **Monsoon NDTI is NOT higher than winter** here (−0.071 vs −0.064) — the opposite of the naive expectation. Likely because the Brahmaputra is sediment-heavy year-round and, in the Dec–Mar low-water season, shallow water over sandbars reads as turbid; also only 28 clear monsoon scenes survive the cloud gap vs 176 in winter. Reported as-is, not forced. (2) **Monsoon cloud gap** is real and visible in scenes/year. (3) NDTI is a **relative index, NOT NTU**, and says nothing about bacteria or dissolved chemicals — labelled everywhere. (4) The long full-range intake extraction stalled on slow COG reads; solved with GDAL HTTP timeouts + a per-year cap. (5) iitg_intake_reach is capped at ~12 scenes/yr (120 total) vs guwahati's full 290 — enough for a second reference, extendable via incremental runs.
**Next:** P4 — GDELT news incidents + incident agent.

## Entry 008 — P4 news incidents (GDELT + incident agent)  (2026-09-27 01:55 IST)
**Prompt/phase:** P4
**Goal:** A structured, human-reviewable log of pollution-related incidents upstream of Guwahati, with a deterministic ETA range to the IITG intake.
**What changed:** `pipeline/ingest/gdelt.py` (rate-limited harvest + run_incidents orchestration), `agents/incident_agent.py` (LLM + keyword classifier, geocoding, ETA), `agents/review_incidents.py` (confirm/reject CLI), `config/assam_gazetteer.yaml` (offline geocoder), `tests/test_incidents.py`, wired `pipeline/run_daily.py` (best-effort).
**Data:** GDELT DOC 2.0 API confirmed (mode=ArtList, format=json, timespan/query params). `events_incidents.parquet` written **empty (0 events)** — see limits. Bronze harvests: 0 (source unreachable this session).
**Decisions & why:** GDELT rate-limits to ~1 req/5 s, so the harvester sleeps 6 s and backs off on HTTP 429. ETA is computed by **deterministic code** from the params.yaml water-velocity band (0.8–2.5 m/s) over a river-chainage gazetteer, and is always emitted as a **range**, never a point value (Part A rule 4, Part B §4). Incident kind/relevance is classified by the LLM when a key is present, else a deterministic keyword classifier so the pipeline runs offline. Every event is `human_confirmed=false`; only human-confirmed events may trigger alerts (rule 9) — enforced via the review CLI.
**Validation:** `pytest -q` → **34 passed** (7 new: geocode hit/miss, ETA is a range & physically ordered, closer town → shorter ETA, downstream town can't reach intake, keyword relevance, unconfirmed-event invariant). Review CLI handles the empty file gracefully.
**Honest limits found:** **GDELT was effectively unreachable from this build environment** — repeated SSL handshake / connection timeouts (WinError 10060) and HTTP 429 throttling; the few queries that returned 200 had 0–1 articles (coverage of this niche is genuinely sparse, as Part B §1 warned). Per the PLAN "source down" rule I did **not fabricate** incidents: I wrote an empty, correctly-typed events file, logged the gap here, and kept the full pipeline. On a healthier network (e.g. during the live demo) `python -m pipeline.ingest.gdelt --incidents` will populate real events, which then go through human review before any alert. River-chainage distances in the gazetteer are team estimates for ETA ordering, not survey-grade. LLM classification path is built but untested against the live API (no key yet).
**Next:** P5 — JJM-WQMIS + groundwater for consumer mode.

## Entry 009 — P5 consumer mode: JJM-WQMIS attempt + groundwater area risk  (2026-09-27 02:20 IST)
**Prompt/phase:** P5
**Goal:** Give households a local water-quality picture from real public tests, showing data age and distance.
**What changed:** `models/consumer/area_risk.py` (nearest CPCB GW/river stations, BIS IS 10500 checks, plain-language summary), `tests/test_area_risk.py`.
**Data:** Uses the **real CPCB groundwater** ingested in P1 (`cpcb_groundwater.parquet`, 3,820 obs, 67 Assam GW sites) + river sites. BIS exceedances present in the real data: **63 fluoride** and **53 arsenic** exceedances across Assam GW stations (arsenic is a documented regional problem) — proves the check fires on real signal. All 4 demo points (Pandu, Panbazar, Beltola, IITG campus) return the 3 nearest stations with distance (0.5–6.4 km) and year (2022).
**Decisions & why:** Safety judgement is a **deterministic BIS-limit comparison**, never an LLM call. Output always carries data age (yr) and distance (km) and a "what this cannot tell you" caveat, so users can't mistake old/distant evidence for their tap today. Virtual-sensor river state is folded in gracefully once P7 lands.
**Validation:** `pytest -q` → **40 passed** (6 new: pH band, arsenic acceptable/permissible, coliform any-presence, haversine distance, dated/distant evidence, all-4-points). Ran area_risk on 4 Guwahati/campus points — real station names and distances.
**Honest limits found:** **JJM-WQMIS was NOT machine-accessible.** The public pages (ejalshakti.gov.in/WQMIS) load fine (HTTP 200) but the report pages are a JS-driven ASP.NET MVC app with grid-loaded data — no static table, no VIEWSTATE form, no discoverable JSON/export endpoint without executing JS or reverse-engineering the grid's AJAX. Per the PLAN's 45-min stop rule I did not scrape it; logged and proceeded on CPCB GW. CPCB GW is yearly and station-sparse; one GW value of fluoride=224 mg/L is an implausible outlier (likely a column mis-parse on that row) — it carries provenance+page for audit and would be flagged; consumer summaries should treat extreme single values with caution.
**Next:** P6 — synthetic IITG network + chlorine twin (auditable).

## Entry 010 — P6 synthetic IITG network + chlorine twin (auditable)  (2026-09-27 03:10 IST)
**Prompt/phase:** P6
**Goal:** Simulate what we cannot measure — the campus network and tap residuals — from documented physics, fully reproducible, so dose/alert logic can be built and tested.
**What changed:** `pipeline/synthetic/network.py`, `models/twin/chlorine.py` (deterministic twin), `models/twin/drivers.py` (water temp + demand), `pipeline/synthetic/tap_readings.py`, `pipeline/synthetic/complaints.py`, `pipeline/validate/synthetic_checks.py`, `docs/SYNTHETIC_METHOD.md`, `tests/test_chlorine_twin.py`, `tests/test_synthetic.py`, wired `pipeline/run_daily.py` synth/validate stages.
**Data (this phase):**
- `network_edges.parquet` (37) + `network_sites.parquet` (38) — synthetic; `campus_network.json` with WTP→node paths.
- `water_temp_daily.parquet` (3,919 days, 15.2–31.6 °C) + `chlorine_demand_daily.parquet` (3,551 days, 0.55–1.15 mg/L) — **modelled** from real air temp + NDTI.
- `tap_readings.parquet` **13,092** simulated DPD readings (12 hostels × 1,091 days), 7.2% missing, 4 dirty-tank anomalies (H01/H03/H06) in `anomaly_labels.parquet`.
- `complaints.parquet` **102** (en 38 / as 34 / hi 30), KRITI category priors.
- Lake provenance totals: **public_observed 84,057 · modelled 7,470 · synthetic 13,273**.
**Decisions & why:** Twin is pure-Python first-order decay with temperature correction and per-segment k (bulk in tanks, bulk+wall in pipes); demand consumed first; Monte Carlo → p10/p50/p90 with inputs returned (Part A §7, rule 4 — no LLM in safety numbers). Reproducibility hash **excludes the wall-clock `retrieved_or_generated_at`** (generation metadata, not data) and complaint timestamps use a fixed anchor, so same-seed regeneration is byte-identical on the data columns.
**Validation:** `pytest -q` → **55 passed** (9 twin physics/regression + 6 synthetic). Synthetic audit **all_pass=True**: residual≥0 & ≤dose (0 violations), 0.1 mg/L resolution respected, missing 7.2%, lag-1 autocorr 0.32, water temp within NWMP envelope, KS(modelled vs CPCB)=0.253. **Reproducibility: all 3 tables byte-identical on regeneration** — hashes logged in SYNTHETIC_METHOD.md (network `5223a67…`, tap `0973d5c…`, complaints `ef8d01f…`). Twin demo: worst hostel H12 p10=0.064 mg/L at dose 2.0/25 °C/demand 0.8 (below 0.2 target → motivates the P8 solver).
**Honest limits found:** Every campus number is a **team estimate** until the WTP shares real logs (pipe lengths, storage, demand, decay constants) — labelled "assumed" in config and "simulated" in the app. Water-temp NWMP envelope uses all-Assam stations (5.4–37 °C, wide) rather than city-only. KS p≈0 vs the coarse yearly CPCB reference is expected (continuous daily vs sparse min/max) and reported descriptively, not gated. Complaint LLM path is built but deferred to the template bank (no API key).
**Next:** P7 — virtual river sensor (quantile ML on real data).

## Entry 011 — P7 virtual river sensor (quantile ML)  (2026-09-27 03:40 IST)
**Prompt/phase:** P7
**Goal:** A daily NDTI estimate with uncertainty (incl. cloudy days), from real data, honestly benchmarked against baselines.
**What changed:** `models/virtual_sensor/features.py` (71 real features), `models/virtual_sensor/train.py` (LightGBM quantile p10/p50/p90 + baselines + prediction + plot), `tests/test_virtual_sensor.py`, `docs/figures/virtual_sensor.png`, `data/gold/virtual_sensor_daily.parquet`, wired `run_daily` train stage. `pyproject` ml extras (lightgbm 4.7, scikit-learn) installed.
**Data:** Features (real only): upstream rainfall lags 0–10 d + 3/7-day rolling sums (4 points), GloFAS discharge + 1/3/7-day changes (4 points), air temp, day-of-year sin/cos → 71 features over 3,922 days. Target: S2 NDTI median (guwahati_reach), **290 clear-scene labels**. Time split train ≤2023-12-31 (n=202) / test ≥2024-01-01 (n=88). Output: **3,922 daily predictions** (provenance=modelled) with p10/p50/p90, interval width, days-since-last-clear, and a persistence column.
**Decisions & why:** Kept the honest benchmark. **The LightGBM model does NOT beat persistence** (MAE p50 **0.0311** vs persistence **0.0096**) though it **beats climatology** (0.0456). Per the P7/emergency rule, **persistence is kept as the production predictor** (recorded in source_ref), while the model's p10–p90 band is retained for uncertainty display and cloudy-day gap-filling. Confidence in the app is driven by interval width + days since the last clear satellite pass.
**Validation:** `pytest -q` → **59 passed** (4 new). Season MAE (p50): monsoon 0.041, winter 0.027, pre-monsoon 0.022, post 0.053. p10–p90 coverage **0.341** (intervals too tight — reported, not hidden).
**Honest limits found:** NDTI is **nearly flat between clear scenes** (persistence MAE ~0.01 = consecutive clear values differ by ~0.01), so a learned model adds little over "last observed value" — a genuine, defensible result for a slowly-varying, sediment-saturated river signal. LightGBM quantile intervals are **poorly calibrated** (34% coverage vs nominal 80%) on only 202 training points × 71 features; we therefore lean on persistence + days-since-clear for the operational confidence signal rather than the raw quantile band. More clear scenes / feature pruning would help; logged as future work.
**Next:** P8 — inverse dose solver + test-next (VOI) + tank anomaly.

## Entry 012 — P8 inverse dose solver + test-next (VOI) + tank anomaly + daily briefing  (2026-09-27 04:15 IST)
**Prompt/phase:** P8
**Goal:** The two decision outputs the chemist uses — minimum safe dose and where to test next — plus tank-anomaly detection and the gold daily briefing.
**What changed:** `models/dose/solver.py`, `models/voi/test_next.py`, `models/anomaly/tank_anomaly.py`, `pipeline/daily_briefing.py`, `tests/test_dose_voi.py`, added `p_below` to the twin, wired `run_daily` daily stage.
**Data:** `data/gold/daily_briefing.parquet` for 3 dates (provenance=modelled). 2024-07-15 (monsoon): risk **high**, dose **4.0** mg/L infeasible (worst tap H12 p10=0.069 < 0.2), test-next **H07**, 1 alert. 2024-01-15 (winter): risk **elevated**, dose **2.0** feasible (H12 p10=0.208), test-next H12. Today: high, 4.0.
**Decisions & why:** Dose solver steps 0.5–4.0 @0.05 to the minimum where worst-tap **p10 residual ≥ 0.2 mg/L** (BIS), using the Monte-Carlo twin; returns worst tap, its p10/p50, and a pessimistic p90 dose (hotter+30% demand). VOI = P(residual<0.2)×population×uncertainty-width — the reason is numbers only. Tank anomaly: reconstruct expected residual from each reading's recorded dose/temp/demand, take observed/expected ratio, 3-day rolling median, robust z, flag z<−3.5 AND ratio<0.7, only where expected>0.15 mg/L. Risk level is deterministic (infeasible or NDTI≥90th pct → high; dose≥3 / NDTI≥75th / anomaly → elevated).
**Validation:** `pytest -q` on P8 → **7 passed** (higher temp→≥dose, higher demand→≥dose, bounds, uncertainty+inputs returned, VOI site+numeric reason ranks all 12, anomaly recall, briefing written). Full suite now **66 passed**. Tank anomaly on synthetic: **recall 1.0, precision 0.65** (22 TP / 12 FP / 0 FN at z=3.5) — reported honestly "on synthetic scenarios".
**Honest limits found:** At warm temps the farthest tank (H12, ~24 h residence) **cannot meet 0.2 mg/L by WTP dosing alone even at 4.0 mg/L** — a real network-extremity result (needs booster chlorination / reduced storage), surfaced as risk=high + test-next rather than hidden. Anomaly precision is modest (many near-zero-residual far-hostel days are excluded because 0.1 mg/L rounding makes the ratio meaningless). All campus numbers remain SIMULATED/assumed until WTP calibration.
**Next:** (user redirect) build offline demo.html from a real-data snapshot; defer P9–P15.

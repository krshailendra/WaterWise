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

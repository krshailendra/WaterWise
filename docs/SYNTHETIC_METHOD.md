# SYNTHETIC_METHOD.md — how WaterWise generates (and discloses) synthetic data

This document makes our synthetic data **defensible**. Everything simulated here
exists because we cannot yet measure it (the IITG campus pipe network, tap
chlorine residuals, complaint texts). It is generated **only** by code in
`pipeline/synthetic/` from documented physical models with parameters listed in
`config/params.yaml` (each tagged with a citation or "team estimate"), using a
**fixed seed** so it is byte-reproducible. If a judge reverse-engineers it, they
will find exactly these parameters — that is the goal (Part A rule 3).

Nothing here is presented as a real measurement. Every row carries
`provenance = synthetic` (or `modelled` for the physics-derived drivers built
from real data), and the app shows a "simulated"/"assumed" badge wherever a
synthetic number drives a result.

**Global seed:** `20250926` · **generator version:** `1.0.0` (both in
`config/params.yaml`).

---

## 1. Campus network — `pipeline/synthetic/network.py`

Topology from `config/campus.yaml` (all values `assumed: true`):
`WTP → reservoir → 12 hostel tanks (H01–H12) → cooler + RO per hostel` = 38 nodes,
37 edges. Pipe travel times are mapped from assumed pipe lengths into the
team-estimate band **0.25–3.0 h**; tank residence times sampled from **6–24 h**;
pipe wall-decay `k_w,eff` sampled from **0.05–0.5 day⁻¹** (EPANET convention;
range is a team estimate). Output: `network_edges.parquet`, `network_sites.parquet`,
`campus_network.json` (with WTP→node segment paths for the twin).

## 2. Chlorine twin — `models/twin/chlorine.py` (deterministic, unit-tested)

First-order decay: **C(t) = C₀·exp(−k·t)**.
- Bulk decay at temperature: **k_b(T) = k_b20 · θ^(T−20)**, with
  **k_b20 ∈ 0.5–1.5 day⁻¹** (median 0.9; standard first-order model, sim studies
  ~0.85–1.0) and **θ = 1.096** (a 10 °C rise ≈ 2.5× k_b → θ = 2.5^0.1).
- In tanks/reservoir: k = k_b(T). In pipes: k = k_b(T) + k_w,eff.
- Immediate **chlorine demand D** is consumed first: starting residual =
  max(0, dose − D). Then residual decays segment by segment along the path.
- **Monte Carlo** over k_b20, demand noise (±0.1 mg/L), segment times (per-edge
  mean±sd) and wall-decay noise (±20%) → **p10/p50/p90** residual at every node.

Every result is returned **with its uncertainty and the inputs used** (Part A §7),
and it is pure Python — no LLM ever produces a safety number (Part A rule 4).

## 3. Drivers — `models/twin/drivers.py` (provenance = **modelled**, from real data)

- **Water temperature:** real Open-Meteo air temp (P2), lagged 3 d and smoothed
  7 d, then **clipped to the NWMP seasonal envelope** from real CPCB city-station
  water temps (P1). Real data + model → `modelled`. Modelled range ≈ 15–32 °C.
- **Chlorine demand:** **D = d0 + a·norm(NDTI) + ε**, with **d0 ∈ 0.3–0.8**,
  **a ∈ 0.2–1.0 mg/L** (team estimate, calibratable by the chemist), NDTI from
  real Sentinel-2 (P3) forward-filled to daily. ε (~N(0,0.1)) is added by the
  twin's Monte Carlo, not the daily driver.

## 4. Field-kit tap readings — `pipeline/synthetic/tap_readings.py`

For the last 3 years, per hostel per day: run the deterministic twin with a
realistic historical dose policy (cover demand + ~0.8 mg/L margin + temperature
bump + small operator variation, clipped to 0.5–4.0 mg/L), producing the "true"
residual, then apply **DPD field-kit texture**:
- instrument noise ±max(0.05 mg/L, 10%), **0.1 mg/L resolution**,
- **5–10% missing** readings, **0.5% transcription errors** (×0.1 or ×10 slips,
  flagged `suspect`).

**Dirty-tank anomalies** (`k_b × 2–4` for 3–10 days) are injected and recorded in
`anomaly_labels.parquet` for **evaluation only** (P8 tank-anomaly precision/recall).

## 5. Complaints — `pipeline/synthetic/complaints.py`

60–150 short complaints in an English/Hindi/Assamese mix, category shares from our
**KRITI '25 survey priors** (team estimate). Uses the Claude API (WW_MODEL_FAST)
when a key is present; otherwise a deterministic template bank. The true category
label is kept for the P9 triage eval. Timestamps use a fixed anchor (not
wall-clock) so output is byte-reproducible.

## 6. Audit checks — `pipeline/validate/synthetic_checks.py` (Part B §6)

- **Physical:** residual ≥ 0; residual ≤ dose; decay monotone within a segment;
  water temperature within the NWMP envelope. ✅
- **Texture:** 0.1 mg/L resolution respected; missingness 7.2% (in 5–10%);
  mean lag-1 autocorrelation ≈ 0.32 (plausible day-to-day persistence). ✅
- **Anchoring:** KS test of modelled water temp vs real CPCB water temp
  (descriptive; real reference is coarse yearly min/max). Reported, not gated.
- **Reproducibility:** regenerating with the same seed gives **identical DATA**
  (content hash, excluding the wall-clock generation timestamp). ✅

### Content hashes (seed 20250926, generator 1.0.0)

| table | sha256 (content) |
|---|---|
| `network_edges.parquet` | `5223a6718cfee86b51e59521a953f224041de7d2f7c0823f1395267d52fc6533` |
| `tap_readings.parquet`  | `0973d5c0ac35ab3f2f35b9ab00acbcb75c408a60174eb734b157969d1e084e7d` |
| `complaints.parquet`    | `ef8d01f8d597aed33606d8dbdaf7b0b3fab67e5acb11dd9eac5cbbbd492250ed` |

(These are hashes of the sorted data columns, excluding `retrieved_or_generated_at`,
which is generation metadata, not data.)

## 7. Disclosure

`docs/DATASHEET.md` states row counts per provenance class. As of P6 the lake
holds roughly **public_observed 84,057 · modelled 7,470 · synthetic 13,273** rows.
The app shows a synthetic/assumed badge wherever a simulated number drives a
displayed value. Replacing any team-estimate parameter with the WTP chemist's
calibrated value is a logged REPORT.md change.

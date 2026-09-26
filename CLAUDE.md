# CLAUDE.md — WaterWise (rules that persist across sessions)

WaterWise tells the IIT Guwahati water treatment plant chemist, every morning, what chlorine dose keeps every hostel tap safe and where to test next — from public river, weather and satellite data.
The parts we can't yet measure (campus network, tap residuals) are simulated from documented physics with fixed seeds and clearly labelled `synthetic`.

**The full plan is in PLAN.md — re-read the relevant Part before starting each phase.**

---

## The 11 non-negotiable rules (PLAN.md Part A §2, verbatim)

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

---

## REPORT.md entry template (PLAN.md Part A §8) — append after EVERY task

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

## Quick reminders

- Timestamps: UTC in storage, `Asia/Kolkata` in the UI. snake_case columns; units in the name (`residual_cl_mg_l`).
- Bronze is immutable; silver/gold reproducible from bronze + code + seed.
- Models return safety numbers **with** uncertainty and inputs used.
- Core demo loop (never cut): P1, P2, P3, P6, P7, P8, P9A, P10, P11, P12.
- Claude models: `WW_MODEL_MAIN=claude-sonnet-5`, `WW_MODEL_FAST=claude-haiku-4-5-20251001` (read from env).

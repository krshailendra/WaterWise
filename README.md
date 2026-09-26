# WaterWise — source-to-tap water intelligence

WaterWise tells the IIT Guwahati water treatment plant (WTP) chemist, every
morning, what chlorine dose keeps every hostel tap safe — and where to test
next. It is built from **public** river, weather and satellite data, with the
parts we can't yet measure (the campus network, tap residuals) **simulated from
documented physics** and clearly labelled `synthetic`.

Built for the Granica × IIT Guwahati "Bring the Physical World to AI" hackathon.

> **The plan of record is [PLAN.md](PLAN.md). The build log is [REPORT.md](REPORT.md).**
> Rules that must persist across sessions live in [CLAUDE.md](CLAUDE.md).

## Provenance, always

Every data row carries `provenance ∈ {public_observed, modelled, synthetic}`,
plus `source_id` and `source_ref`. Safety numbers (dose, residuals, ETAs, risk)
come only from deterministic, unit-tested Python — never an LLM. The app never
calls water "unsafe" unless an authority confirms it.

## Quickstart (dev)

```bash
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash;  .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"              # add extras as needed: .[ingest,geo,ml,agents,api]
cp .env.example .env                 # then add ANTHROPIC_API_KEY
make test
```

## Layout

See [PLAN.md](PLAN.md) Part A §4. Key directories: `config/` (locations, campus,
params, dummy authorities, routing rules), `pipeline/` (ingest, synthetic,
validate), `models/`, `agents/`, `api/`, `app/` (Expo), `data/` (bronze → silver
→ gold → release).

A full 5-minute quickstart is added in P15.

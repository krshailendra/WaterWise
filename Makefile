# WaterWise task runner. On Windows, run these under Git Bash, or call the
# underlying `python -m ...` commands directly. PY points at the venv python.

PY ?= python

.PHONY: ingest synth validate train daily api test help

help:
	@echo "targets: ingest synth validate train daily api test"

ingest:      ## Run all real-data ingestion (P1-P5, P9B, P9C)
	$(PY) -m pipeline.run_daily --stage ingest

synth:       ## Generate documented synthetic data (P6)
	$(PY) -m pipeline.run_daily --stage synth

validate:    ## Run validators (real + synthetic checks)
	$(PY) -m pipeline.run_daily --stage validate

train:       ## Train the virtual river sensor (P7)
	$(PY) -m models.virtual_sensor.train

daily:       ## Build gold/daily_briefing for a date (default: today)
	$(PY) -m pipeline.run_daily --stage daily

api:         ## Start the FastAPI backend (P10)
	$(PY) -m uvicorn api.main:app --reload --port 8000

test:        ## Run the test suite
	$(PY) -m pytest -q

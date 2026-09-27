"""WaterWise daily pipeline orchestrator (skeleton — filled out across P1-P8).

Stages are wired in as each phase lands. For P0 this just provides the CLI the
Makefile targets call, so `make ingest/synth/validate/daily` are valid commands.

Usage:
    python -m pipeline.run_daily --stage {ingest,synth,validate,daily} [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
from datetime import date


STAGES = ("ingest", "synth", "validate", "train", "daily")


def main() -> None:
    parser = argparse.ArgumentParser(description="WaterWise daily pipeline")
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="target date YYYY-MM-DD (default: today)")
    parser.add_argument("--incremental", action="store_true",
                        help="fetch only new days where supported")
    args = parser.parse_args()

    print(f"[run_daily] stage={args.stage} date={args.date} "
          f"incremental={args.incremental}")

    if args.stage == "daily":
        from pipeline.daily_briefing import produce
        r = produce([args.date])
        print(f"[run_daily] daily_briefing written for {args.date}")

    if args.stage in ("ingest", "daily"):
        # incremental hydro-met fetch (Open-Meteo + GloFAS) — safe to run often
        from pipeline.ingest import openmeteo
        s = openmeteo.run(incremental=True)
        print(f"[run_daily] openmeteo: new_rows={s.get('rows')} "
              f"status={s.get('status', 'ok')}")
        from models.eta import flow_lag
        flow_lag.compute(save_plot=False)
        print("[run_daily] flow lags recomputed")
        try:
            from pipeline.ingest import sentinel2
            s2s = sentinel2.run(incremental=True)
            print(f"[run_daily] sentinel2: new_rows={s2s.get('new_rows')}")
        except Exception as e:  # noqa: BLE001 — never crash the live loop on S2
            print(f"[run_daily] sentinel2 skipped: {type(e).__name__}: {e}")
        try:
            from pipeline.ingest import gdelt
            gr = gdelt.run_incidents(use_llm=True)
            print(f"[run_daily] gdelt incidents: fetched={gr['articles_fetched']} "
                  f"events={gr['events_written']}")
        except Exception as e:  # noqa: BLE001 — GDELT is flaky; never crash the loop
            print(f"[run_daily] gdelt skipped: {type(e).__name__}: {e}")
    if args.stage == "synth":
        from pipeline.synthetic import network, tap_readings, complaints
        from models.twin import drivers
        network.persist()
        drivers.persist()
        tap_readings.generate()
        complaints.generate()
        print("[run_daily] synthetic network + drivers + tap readings + complaints regenerated")

    if args.stage == "validate":
        from pipeline.validate.synthetic_checks import run_all, provenance_counts
        r = run_all()
        print(f"[run_daily] synthetic checks all_pass={r['all_pass']}")
        print(f"[run_daily] provenance counts: {provenance_counts()}")

    if args.stage == "train":
        from models.virtual_sensor.train import train_and_predict
        r = train_and_predict()
        print(f"[run_daily] virtual sensor: MAE p50={r.get('mae_p50_model')} "
              f"vs persistence {r.get('mae_persistence')} -> production={r.get('production_predictor')}")

    if args.stage not in ("ingest", "daily", "synth", "validate", "train"):
        print("[run_daily] stage not yet wired — added in later phases (P8).")


if __name__ == "__main__":
    main()

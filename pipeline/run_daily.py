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
    else:
        print("[run_daily] stage not yet wired — added in later phases (P3-P8).")


if __name__ == "__main__":
    main()

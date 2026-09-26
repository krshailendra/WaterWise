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
    print("[run_daily] not yet implemented for this stage — added in later phases (P1-P8).")


if __name__ == "__main__":
    main()

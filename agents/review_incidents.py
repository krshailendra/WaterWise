"""Human review CLI for incident events (P4): only human-confirmed events may
trigger alerts (Part A rule 9). Usage:

    python -m agents.review_incidents            # interactive confirm/reject
    python -m agents.review_incidents --list     # just list current events
    python -m agents.review_incidents --confirm <event_id>
    python -m agents.review_incidents --reject  <event_id>
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

EVENTS = Path("data/silver/events_incidents.parquet")


def _load() -> pd.DataFrame:
    if not EVENTS.exists():
        print("no events file yet — run `python -m pipeline.ingest.gdelt --incidents`")
        sys.exit(0)
    return pd.read_parquet(EVENTS)


def _save(df: pd.DataFrame) -> None:
    df.to_parquet(EVENTS, index=False)


def _list(df: pd.DataFrame) -> None:
    if df.empty:
        print("(no incident events — GDELT returned nothing relevant; this is honest, not an error)")
        return
    for _, r in df.iterrows():
        print(f"[{r.get('human_confirmed')}] {r['event_id']} | {r['kind']} | "
              f"conf={r.get('confidence')} | {str(r.get('text_summary'))[:70]}")


def _set_flag(df: pd.DataFrame, event_id: str, value: bool) -> pd.DataFrame:
    mask = df["event_id"] == event_id
    if not mask.any():
        print(f"no such event: {event_id}")
        return df
    df.loc[mask, "human_confirmed"] = value
    print(f"{'confirmed' if value else 'rejected'}: {event_id}")
    return df


def main() -> None:
    df = _load()
    args = sys.argv[1:]
    if "--list" in args or not args:
        _list(df)
        if "--list" in args:
            return
    if "--confirm" in args:
        df = _set_flag(df, args[args.index("--confirm") + 1], True)
        _save(df)
        return
    if "--reject" in args:
        df = _set_flag(df, args[args.index("--reject") + 1], False)
        _save(df)
        return
    # interactive
    if df.empty:
        return
    for idx, r in df.iterrows():
        if bool(r.get("human_confirmed")):
            continue
        print(f"\n{r['event_id']} | {r['kind']} | conf={r.get('confidence')}")
        print(f"  {str(r.get('text_summary'))[:200]}")
        print(f"  {str(r.get('source_ref'))[:200]}")
        ans = input("  confirm? [y/N/q] ").strip().lower()
        if ans == "q":
            break
        if ans == "y":
            df.loc[idx, "human_confirmed"] = True
    _save(df)
    print("saved.")


if __name__ == "__main__":
    main()

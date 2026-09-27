"""GDELT DOC 2.0 ingestion (P4): harvest news articles about Brahmaputra /
Assam water pollution, spills, discharge, floods. Raw results cached to bronze.

GDELT rate-limits to ~1 request / 5 s, so we sleep between queries and back off
on HTTP 429. Coverage of this niche is sparse/noisy by nature (Part B §1) — we
never fabricate incidents; zero real hits is an honest, logged outcome.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from pipeline.ingest.common import USER_AGENT, sha256_bytes, utcnow_iso

BRONZE = Path("data/bronze/gdelt")
DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

QUERIES = [
    "Brahmaputra pollution",
    "Brahmaputra contamination",
    "Brahmaputra oil spill",
    "Brahmaputra fish death",
    "Brahmaputra flood Assam",
    "Bharalu river",
    "Kopili river pollution",
    "Guwahati water contamination",
    "Assam industrial discharge river",
]

SLEEP_S = 6.0
MAX_RETRY = 2
HTTP_TIMEOUT = 15.0   # fail fast: GDELT can be flaky/throttled from some networks


def _fetch(query: str, timespan: str = "36months", maxrecords: int = 50) -> list[dict]:
    params = {"query": query, "mode": "ArtList", "format": "json",
              "maxrecords": str(maxrecords), "timespan": timespan}
    for attempt in range(1, MAX_RETRY + 1):
        try:
            r = httpx.get(DOC_URL, params=params, timeout=HTTP_TIMEOUT,
                          headers={"User-Agent": USER_AGENT})
            if r.status_code == 429:
                time.sleep(SLEEP_S * (attempt + 1))
                continue
            if r.status_code != 200:
                return []
            txt = r.text.strip()
            if not txt or txt[0] not in "{[":
                return []  # rate-limit / error message in plain text
            return r.json().get("articles", [])
        except Exception:  # noqa: BLE001
            time.sleep(SLEEP_S * attempt)
    return []


def harvest(queries: Optional[list[str]] = None, timespan: str = "36months") -> dict:
    """Fetch all queries (rate-limited), dedupe by URL, cache raw to bronze."""
    queries = queries or QUERIES
    BRONZE.mkdir(parents=True, exist_ok=True)
    seen: dict[str, dict] = {}
    per_query = {}
    for q in queries:
        arts = _fetch(q, timespan=timespan)
        n_new = 0
        for a in arts:
            u = a.get("url")
            if u and u not in seen:
                a["_query"] = q
                seen[u] = a
                n_new += 1
        per_query[q] = {"raw": len(arts), "new": n_new}
        time.sleep(SLEEP_S)

    articles = list(seen.values())
    raw = json.dumps(articles, ensure_ascii=False).encode("utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (BRONZE / f"articles_{stamp}.json").write_bytes(raw)
    (BRONZE / f"articles_{stamp}.meta.json").write_text(json.dumps({
        "retrieved_at": utcnow_iso(), "sha256": sha256_bytes(raw),
        "n_articles": len(articles), "queries": queries, "timespan": timespan,
    }, indent=2), encoding="utf-8")
    return {"articles": articles, "per_query": per_query, "n_unique": len(articles)}


# --------------------------------------------------------------------------- #
# Orchestration: harvest -> classify -> data/silver/events_incidents.parquet
# --------------------------------------------------------------------------- #
def run_incidents(use_llm: bool = True, timespan: str = "36months") -> dict:
    """Harvest GDELT, classify to incident events (human_confirmed=false),
    write data/silver/events_incidents.parquet. Never fabricates events."""
    from pathlib import Path as _P
    import pandas as pd
    from agents.incident_agent import (
        classify_article, _load_gazetteer, _load_velocity_bounds)
    from pipeline.schemas import Event, write_table

    h = harvest(timespan=timespan)
    gaz = _load_gazetteer()
    vbounds = _load_velocity_bounds()

    events, relevant = [], 0
    for art in h["articles"]:
        ev = classify_article(art, gaz, vbounds, use_llm=use_llm)
        if ev is None:
            continue
        relevant += 1
        events.append(ev)

    out = _P("data/silver/events_incidents.parquet")
    if events:
        clean = [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]
        write_table(clean, out, Event)
    else:
        # write an empty, correctly-typed file so downstream code always loads
        import pyarrow as pa, pyarrow.parquet as pq
        cols = ["event_id", "ts_reported", "ts_event_est", "kind", "lat", "lon",
                "site_id", "text_summary", "confidence", "human_confirmed",
                "provenance", "source_ref"]
        pq.write_table(pa.table({c: pa.array([], type=pa.string()) for c in cols}), out)

    return {"articles_fetched": h["n_unique"], "relevant": relevant,
            "events_written": len(events),
            "confirmed": sum(1 for e in events if e["human_confirmed"])}


if __name__ == "__main__":
    import sys
    if "--incidents" in sys.argv:
        r = run_incidents(use_llm=("--no-llm" not in sys.argv))
        print("=" * 60)
        print("GDELT incidents (P4)")
        print("=" * 60)
        print(f"articles fetched: {r['articles_fetched']}")
        print(f"judged relevant:  {r['relevant']}")
        print(f"events written:   {r['events_written']} (human_confirmed={r['confirmed']})")
    else:
        res = harvest()
        print("UNIQUE ARTICLES:", res["n_unique"])

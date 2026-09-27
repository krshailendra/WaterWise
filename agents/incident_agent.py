"""Incident agent (P4): classify GDELT news articles into structured incident
events, geocode with an offline Assam gazetteer, and compute a river-distance
ETA RANGE to the IITG intake.

LLM (WW_MODEL_MAIN) does the relevance/kind classification when a key is present;
otherwise a deterministic keyword classifier runs so the pipeline still works
(clearly lower confidence). No safety number is produced by the LLM — the ETA is
computed by deterministic code from params.yaml water-velocity bounds (Part A
rule 4). ETA is always a RANGE, never a single number (Part B §4).

All events are written human_confirmed=false; only human-confirmed events may
trigger alerts (P4 step 3, Part A rule 9).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

import yaml

KIND_KEYWORDS = {
    "spill": ["oil spill", "oil-spill", "spill", "leak", "crude"],
    "discharge": ["effluent", "discharge", "sewage", "industrial waste",
                  "contaminat", "pollut", "toxic", "chemical"],
    "flood": ["flood", "inundat", "deluge", "overflow"],
}
RELEVANCE_HINTS = ["brahmaputra", "bharalu", "kopili", "assam", "guwahati",
                   "dibrugarh", "tezpur", "dhubri", "river", "water"]


def _load_gazetteer() -> dict:
    return yaml.safe_load(open("config/assam_gazetteer.yaml", encoding="utf-8"))


def _load_velocity_bounds() -> tuple[float, float]:
    p = yaml.safe_load(open("config/params.yaml", encoding="utf-8"))
    ie = p["incident_eta"]
    return float(ie["water_velocity_m_s_min"]), float(ie["water_velocity_m_s_max"])


def geocode(text: str, gaz: dict) -> Optional[dict]:
    """Return the best-matching gazetteer place for `text`, or None."""
    up = (text or "").lower()
    best = None
    for place in gaz["places"]:
        for alias in place["aliases"]:
            if alias.lower() in up:
                # prefer more specific (has river_km) and longer alias matches
                score = (place.get("river_km") is not None, len(alias))
                if best is None or score > best[0]:
                    best = (score, place)
    return best[1] if best else None


def eta_range_hours(place: dict, gaz: dict, vmin: float, vmax: float) -> Optional[dict]:
    """Deterministic ETA range from an upstream place to the IITG intake."""
    intake_km = gaz["intake_river_km"]
    km = place.get("river_km")
    if km is None:
        return None
    dist_km = intake_km - km
    if dist_km <= 0:
        return {"note": "at or downstream of intake — cannot reach intake",
                "distance_km": round(dist_km, 1)}
    d_m = dist_km * 1000.0
    # slower velocity -> longer ETA
    eta_hi = d_m / vmin / 3600.0
    eta_lo = d_m / vmax / 3600.0
    return {"distance_km": round(dist_km, 1),
            "eta_hours_low": round(eta_lo, 1), "eta_hours_high": round(eta_hi, 1),
            "velocity_m_s_range": [vmin, vmax]}


def _keyword_classify(title: str, snippet: str) -> dict:
    text = f"{title} {snippet}".lower()
    relevant = any(h in text for h in ("brahmaputra", "bharalu", "kopili")) and \
        any(h in text for h in ("pollut", "contaminat", "spill", "effluent",
                                 "discharge", "toxic", "flood", "fish death", "sewage"))
    kind = "discharge"
    for k, kws in KIND_KEYWORDS.items():
        if any(kw in text for kw in kws):
            kind = k
            break
    place = None
    for p in ("Dibrugarh", "Tezpur", "Guwahati", "Dhubri", "Nimatighat",
              "Kopili", "Bharalu", "Digboi", "Sivasagar", "Assam"):
        if p.lower() in text:
            place = p
            break
    return {"is_relevant": relevant, "kind": kind, "place_name": place,
            "summary_1_sentence": (title or snippet)[:200],
            "confidence": 0.4 if relevant else 0.1,
            "classifier": "keyword_fallback"}


def _llm_classify(title: str, snippet: str, model: Optional[str]) -> Optional[dict]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    model = model or os.environ.get("WW_MODEL_MAIN", "claude-sonnet-5")
    client = anthropic.Anthropic(api_key=key)
    sys_prompt = (
        "Classify a news article about possible water pollution near the "
        "Brahmaputra/Assam. Return ONLY JSON with keys: is_relevant (bool), "
        "kind (one of spill, discharge, flood, other), place_name (a town/city "
        "name mentioned, or null), date_of_event (YYYY-MM-DD or null), "
        "summary_1_sentence (string), confidence (0..1). Do not invent facts."
    )
    try:
        msg = client.messages.create(
            model=model, max_tokens=500, system=sys_prompt,
            messages=[{"role": "user",
                       "content": f"TITLE: {title}\nSNIPPET: {snippet}"}])
        txt = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
        if txt.startswith("```"):
            txt = txt.strip("`"); txt = txt[txt.find("{"):]
        d = json.loads(txt)
        d["classifier"] = f"llm:{model}"
        return d
    except Exception as e:  # noqa: BLE001
        print(f"[incident_agent] LLM failed: {type(e).__name__}: {e}")
        return None


def classify_article(article: dict, gaz: dict, vbounds: tuple[float, float],
                     use_llm: bool = True) -> Optional[dict]:
    """Return an incident event dict for one article, or None if not relevant."""
    title = article.get("title", "")
    snippet = article.get("snippet", article.get("excerpt", ""))
    result = (_llm_classify(title, snippet, None) if use_llm else None) \
        or _keyword_classify(title, snippet)
    if not result.get("is_relevant"):
        return None

    place = geocode(result.get("place_name") or title or snippet, gaz)
    eta = eta_range_hours(place, gaz, *vbounds) if place else None

    seendate = article.get("seendate")
    ts_reported = None
    if seendate:
        try:
            ts_reported = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            ts_reported = None

    kind = result.get("kind", "discharge")
    if kind not in ("spill", "discharge", "flood"):
        kind = "discharge"

    ev_id = "inc_" + re.sub(r"\W+", "", (article.get("url") or title))[-24:]
    return {
        "event_id": ev_id,
        "ts_reported": ts_reported,
        "ts_event_est": ts_reported,
        "kind": kind,
        "lat": place["lat"] if place else None,
        "lon": place["lon"] if place else None,
        "site_id": None,
        "text_summary": result.get("summary_1_sentence", title)[:300],
        "confidence": float(result.get("confidence", 0.3)),
        "human_confirmed": False,
        "provenance": "public_observed",
        "source_ref": (f"GDELT | {article.get('domain','')} | {article.get('url','')} | "
                       f"classifier={result.get('classifier')} | "
                       f"place={place['name'] if place else 'unknown'} | "
                       f"eta={eta}"),
        "_eta": eta,
        "_place": place["name"] if place else None,
    }

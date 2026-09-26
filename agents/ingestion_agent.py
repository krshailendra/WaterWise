"""Ingestion agent (P1): LLM fallback for CPCB pages that don't parse
deterministically. Extraction only — it never invents values, and every row it
returns keeps the source page number and a quoted snippet so a human can verify
(Part A rule 4: agents extract/classify/explain, never produce safety numbers).

If ANTHROPIC_API_KEY is absent, `extract_page()` returns [] and records the page
as a gap; the caller logs it. We NEVER fabricate to fill the gap (rule 1).
"""
from __future__ import annotations

import json
import os
from typing import Optional

_SYSTEM = (
    "You extract water-quality values from a single page of a CPCB NWMP river "
    "data PDF. Return ONLY valid JSON: a list of objects with keys "
    "station_code (string), station_name (string), parameter (one of "
    "water_temp_c, do_mg_l, ph, conductivity_umho_cm, bod_mg_l, nitrate_mg_l, "
    "fecal_coliform_mpn_100ml, total_coliform_mpn_100ml, fecal_strep_mpn_100ml), "
    "stat (one of min, max, mean), value (number), unit (string), "
    "quote (the exact substring of the page the value came from). "
    "Extract ONLY rows where the state is ASSAM. Never guess or fill missing "
    "values — omit anything not clearly present. If nothing matches, return []."
)


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=key)


def extract_page(page_text: str, page_number: int, year: int,
                model: Optional[str] = None) -> list[dict]:
    """Extract Assam river rows from one page's text via the LLM.

    Returns a list of row dicts (each tagged with source_page and year), or []
    if no API key / client / usable response. Never raises for the missing-key
    case — the caller treats [] as a logged gap.
    """
    client = _client()
    if client is None:
        return []
    model = model or os.environ.get("WW_MODEL_MAIN", "claude-sonnet-5")
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=4000,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Year: {year}. Page: {page_number}.\n\n"
                    f"PAGE TEXT:\n{page_text[:12000]}"
                ),
            }],
        )
        text = "".join(
            b.text for b in msg.content if getattr(b, "type", None) == "text"
        ).strip()
        # tolerate code fences
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("["):]
        rows = json.loads(text)
        if not isinstance(rows, list):
            return []
        out = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            r["source_page"] = page_number
            r["year"] = year
            r["extracted_by"] = f"ingestion_agent:{model}"
            out.append(r)
        return out
    except Exception as e:  # noqa: BLE001 — extraction is best-effort
        print(f"[ingestion_agent] page {page_number} ({year}) failed: "
              f"{type(e).__name__}: {e}")
        return []


def is_available() -> bool:
    return _client() is not None

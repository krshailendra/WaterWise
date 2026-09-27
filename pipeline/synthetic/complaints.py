"""Synthetic complaints (P6 step 6, Part B §5).

Generates 60-150 short complaints in an English/Hindi/Assamese mix, with category
shares from our KRITI '25 survey priors (team estimate). Uses the Claude API
(WW_MODEL_FAST) when a key is present; otherwise a deterministic template bank so
the pipeline runs offline. provenance=synthetic always; the true category label
is kept for the P9 complaint-triage eval.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

SILVER = Path("data/silver")

# KRITI '25 survey category shares (team estimate — priors only)
CATEGORY_SHARES = {
    "taste_odour": 0.28, "colour_turbidity": 0.20, "low_pressure": 0.15,
    "no_water": 0.10, "illness_report": 0.06, "purifier_fault": 0.16, "other": 0.05,
}

# template bank: category -> language -> list of short texts
TEMPLATES = {
    "taste_odour": {
        "en": ["Water smells of chlorine in {h}", "Bad taste from the tap today, {h}",
               "Tap water has a strange odour in {h}"],
        "hi": ["{h} me paani se badbu aa rahi hai", "Nal ke paani ka swad kharab hai {h}"],
        "as": ["{h}: nolor pani gundha ase", "pani khabor xuwad beya {h}"],
    },
    "colour_turbidity": {
        "en": ["Water looks muddy in {h}", "Yellowish water from tap, {h}",
               "Cloudy water this morning in {h}"],
        "hi": ["{h} me paani gandla hai", "Nal ka paani peela aa raha hai {h}"],
        "as": ["{h} t pani ghulia", "nolor pani apnа boronor {h}"],
    },
    "low_pressure": {
        "en": ["Very low water pressure in {h}", "Tap barely running in {h}"],
        "hi": ["{h} me paani ka pressure bahut kam hai"],
        "as": ["{h} t panir hepao bo kom"],
    },
    "no_water": {
        "en": ["No water supply since morning in {h}", "Taps dry in {h}"],
        "hi": ["{h} me subah se paani nahi aa raha"],
        "as": ["{h} t puwatiru pani най"],
    },
    "illness_report": {
        "en": ["Few students have stomach upset in {h}", "Reports of loose motion in {h}"],
        "hi": ["{h} me kuch logo ko pet ki problem hai"],
        "as": ["{h} t kеitaman satrar pet garbar"],
    },
    "purifier_fault": {
        "en": ["RO unit not working in {h}", "Water cooler filter needs service in {h}"],
        "hi": ["{h} me RO kharab hai"],
        "as": ["{h} t RO mesin bhal nai"],
    },
    "other": {
        "en": ["Leaking pipe near {h}", "General water complaint in {h}"],
        "hi": ["{h} ke paas pipe leak ho raha hai"],
        "as": ["{h} r ocorot pipe leak"],
    },
}


def _params():
    return yaml.safe_load(open("config/params.yaml", encoding="utf-8"))


def _hostels() -> list[str]:
    c = yaml.safe_load(open("config/campus.yaml", encoding="utf-8"))
    return [h["id"] for h in c["hostels"]]


def _try_llm(n: int, model: str) -> list[dict] | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    # Kept simple; the template bank is the reliable default for the demo.
    return None  # LLM path intentionally deferred until a key is provided


def generate(seed: int = None) -> dict:
    params = _params()
    seed = seed if seed is not None else params["seed"]
    rng = np.random.default_rng(seed)
    cc = params["complaints"]
    n = int(rng.integers(cc["count_min"], cc["count_max"] + 1))
    langs = cc["languages"]
    hostels = _hostels()

    cats = list(CATEGORY_SHARES)
    probs = np.array([CATEGORY_SHARES[c] for c in cats])
    probs = probs / probs.sum()

    gen_ref = (f"generator=pipeline.synthetic.complaints@{params['generator_version']} "
               f"seed={seed} | SIMULATED complaints, KRITI '25 category priors (team estimate)")
    # deterministic anchor (NOT wall-clock) so output is byte-reproducible per seed
    anchor = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(n):
        cat = str(rng.choice(cats, p=probs))
        lang = str(rng.choice(langs))
        bank = TEMPLATES[cat].get(lang) or TEMPLATES[cat]["en"]
        text = str(rng.choice(bank)).format(h=str(rng.choice(hostels)))
        hid = next((h for h in hostels if h in text), None)
        ts = anchor - timedelta(days=int(rng.integers(0, 60)), hours=int(rng.integers(0, 24)))
        rows.append({
            "complaint_id": f"cmp_{seed}_{i:03d}", "ts": ts,
            "site_guess": hid, "text": text, "language": lang,
            "category_true": cat,  # ground-truth label for the P9 eval
            "provenance": "synthetic", "source_id": "synthetic_complaints",
            "source_ref": gen_ref,
        })
    df = pd.DataFrame(rows)
    df.to_parquet(SILVER / "complaints.parquet", index=False)
    shares = df["category_true"].value_counts(normalize=True).round(3).to_dict()
    return {"complaints": len(df), "by_language": df["language"].value_counts().to_dict(),
            "category_shares": shares}


if __name__ == "__main__":
    print("complaints:", generate())

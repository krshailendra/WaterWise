"""CPCB NWMP ingestion (P1): download the yearly river & groundwater data plus
the monitoring-station list, parse the Brahmaputra-basin stations around
Guwahati, and write the long-format observations table.

Deterministic parsing first (pdfplumber text lines). Pages that don't parse
deterministically are handed to the ingestion agent (agents/ingestion_agent.py)
when an ANTHROPIC_API_KEY is available; otherwise they are logged as gaps.

Rule 1: never fabricate. Missing years/values are reported, never invented.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import csv
import random
from datetime import date, datetime, timezone

import pandas as pd
import pdfplumber
import pymupdf  # fast text extraction for the large river/GW PDFs

from pipeline.ingest.common import download
from pipeline.schemas import (
    Method,
    Observation,
    Provenance,
    QualityFlag,
    Site,
    SiteKind,
    write_table,
)
from pipeline.validate.cpcb_checks import validate_observations

BRONZE = Path("data/bronze/cpcb")
SILVER = Path("data/silver")

# --------------------------------------------------------------------------- #
# Source registry — discovered by probing cpcb.nic.in (logged in REPORT P1).
# river = national "Water Quality of Rivers" file; gw = groundwater file.
# --------------------------------------------------------------------------- #
RIVER_SOURCES: dict[int, str] = {
    2016: "https://cpcb.nic.in/wqm/2016/Water_Quality_data_of_River_2016.pdf",
    2017: "https://cpcb.nic.in/wqm/2017/Water_Quality_data_of_River_2017.pdf",
    2018: "https://cpcb.nic.in/wqm/2018/WQuality_River-Data-2018.pdf",
    2019: "https://cpcb.nic.in/wqm/2019/WQuality_River-Data-2019.pdf",
    2020: "https://cpcb.nic.in/wqm/2020/WQuality_River-Data-2020.pdf",
    2021: "https://cpcb.nic.in/wqm/2021/WQuality_River-Data-2021.pdf",
    2022: "https://cpcb.nic.in/wqm/2022/WQuality_River-Data-2022.pdf",
    2023: "https://cpcb.nic.in/wqm/2023/WQuality_River-Data-2023.pdf",
}

# 2012-2014 are per-state HTML tables; 2015 river file not clearly published.
# These are recorded as known gaps (see REPORT P1) unless discovered later.
RIVER_HTML_2014 = "https://cpcb.nic.in/wqm/2014/RIVERWATER%20DATA%202014_10.htm"

GW_SOURCES: dict[int, str] = {
    2016: "https://cpcb.nic.in/wqm/2016/Water_Ground_Water_2016.pdf",
    2017: "https://cpcb.nic.in/wqm/2017/Water_Ground_Water_2017.pdf",
    2018: "https://cpcb.nic.in/wqm/2018/NWMP_DATA_2018.pdf",
    2019: "https://cpcb.nic.in/wqm/2019/NWMP_DATA_2019.pdf",
    2020: "https://cpcb.nic.in/wqm/2020/NWMP_DATA_2020.pdf",
    2021: "https://cpcb.nic.in/wqm/2021/NWMP_DATA_2021.pdf",
    2022: "https://cpcb.nic.in/wqm/2022/NWMP_DATA_2022.pdf",
    2023: "https://cpcb.nic.in/wqm/2023/NWMP_DATA_2023.pdf",
}

STATION_LIST_URL = "https://cpcb.nic.in/wqm/WQMN_list.pdf"

# Parameter schema used in the 2018-2023 river tables (verified against 2022).
# Order matters: columns appear left-to-right, each with MIN then MAX.
RIVER_PARAMS_2018PLUS = [
    ("water_temp_c", "degC", "temperature"),
    ("do_mg_l", "mg/L", "dissolved oxygen"),
    ("ph", "pH", "ph"),
    ("conductivity_umho_cm", "umho/cm", "conductivity"),
    ("bod_mg_l", "mg/L", "bio-chemical"),
    ("nitrate_mg_l", "mg/L", "nitrate"),
    ("fecal_coliform_mpn_100ml", "MPN/100mL", "fecal coliform"),
    ("total_coliform_mpn_100ml", "MPN/100mL", "total coliform"),
    ("fecal_strep_mpn_100ml", "MPN/100mL", "fecal"),
]

# Stations we care about (Brahmaputra around Guwahati). Match on name substrings.
TARGET_NAME_HINTS = [
    "BRAHMAPUTRA", "BHARALU", "PANDU", "KACHARI", "CHANDRAPUR",
    "DIBRUGARH", "GUWAHATI", "SUALKUCHI", "JOGIGHOPA", "TEZPUR",
]


def _norm(s: str) -> str:
    """Normalise unicode + whitespace for robust matching."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def download_all(years: Optional[list[int]] = None) -> dict:
    """Download station list + river/groundwater files for the given years.
    Returns a report dict listing what succeeded and what failed (gaps)."""
    report = {"station_list": None, "river": {}, "groundwater": {}, "gaps": []}

    m = download(STATION_LIST_URL, BRONZE / "station_list" / "WQMN_list.pdf",
                expect_content_type="pdf")
    report["station_list"] = bool(m)
    if not m:
        report["gaps"].append(f"station_list: {STATION_LIST_URL} download failed")

    yrs = years or sorted(RIVER_SOURCES)
    for y in yrs:
        if y in RIVER_SOURCES:
            dest = BRONZE / str(y) / Path(RIVER_SOURCES[y]).name
            mm = download(RIVER_SOURCES[y], dest, expect_content_type="pdf")
            report["river"][y] = bool(mm)
            if not mm:
                report["gaps"].append(f"river {y}: {RIVER_SOURCES[y]} failed")
        else:
            report["gaps"].append(f"river {y}: no known URL")
        if y in GW_SOURCES:
            dest = BRONZE / str(y) / Path(GW_SOURCES[y]).name
            mm = download(GW_SOURCES[y], dest, expect_content_type="pdf")
            report["groundwater"][y] = bool(mm)
            if not mm:
                report["gaps"].append(f"gw {y}: {GW_SOURCES[y]} failed")
    return report


# --------------------------------------------------------------------------- #
# Station list parser
# --------------------------------------------------------------------------- #
@dataclass
class Station:
    code: str
    name: str
    state: str
    kind: str          # RIVER | GROUND WATER | ...
    frequency: str
    lat: Optional[float]
    lon: Optional[float]


def parse_station_list(path: Path = BRONZE / "station_list" / "WQMN_list.pdf",
                       state: str = "ASSAM") -> list[Station]:
    """Parse the station-list PDF, returning stations for `state`.
    Only pages whose text mentions the state are table-extracted (speed)."""
    stations: list[Station] = []
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            txt = (pg.extract_text() or "").upper()
            if state not in txt:
                continue
            table = pg.extract_table()
            if not table:
                continue
            for row in table:
                if not row or len(row) < 7:
                    continue
                code = _norm(row[0] or "")
                if not re.fullmatch(r"\d{1,6}", code):
                    continue
                st = _norm(row[2] or "")
                if state not in st.upper():
                    continue
                def _f(v):
                    v = _norm(v or "")
                    try:
                        return float(v)
                    except ValueError:
                        return None
                stations.append(Station(
                    code=code,
                    name=_norm(row[1] or ""),
                    state=st,
                    kind=_norm(row[3] or ""),
                    frequency=_norm(row[4] or ""),
                    lat=_f(row[5]),
                    lon=_f(row[6]),
                ))
    return stations


# --------------------------------------------------------------------------- #
# River data parser (deterministic, text-line based)
# --------------------------------------------------------------------------- #
@dataclass
class ParseResult:
    observations: list[dict] = field(default_factory=list)
    n_rows_deterministic: int = 0
    pages_for_agent: list[int] = field(default_factory=list)
    audit_snippets: list[dict] = field(default_factory=list)


_CODE_LINE = re.compile(r"^\d{2,6}$")
_HEADER_TOKENS = re.compile(r"MIN|MAX|MPN|MG/L|PWQC|CRITERIA|TABLE|STATION|CODE|"
                            r"MONITOR|LOCATION|TEMPERATURE|COLIFORM|CONDUCTIVITY|"
                            r"NITRATE|OXYGEN|FLUORIDE|ARSENIC|SOLIDS|DEMAND|"
                            r"NOTIFIED|RULES|MOEF")


def _iter_records(text: str, n_expected: int, value_ok, state: str = "ASSAM"):
    """Parse pymupdf token-per-line text into (code, name, [values]) records.

    Layout per station:  <code> / <name lines...> / <STATE> / <n_expected tokens>
    `value_ok(tok)` decides whether a token is a value (numbers, and BDL/ND for
    groundwater). Only records whose state column == `state` are yielded.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    n = len(lines)
    i = 0
    while i < n:
        if not _CODE_LINE.match(lines[i]):
            i += 1
            continue
        code = lines[i]
        j = i + 1
        name_parts: list[str] = []
        # collect name lines until we hit the state token. The state is the
        # `state` line IMMEDIATELY followed by a value — this disambiguates the
        # case where the name itself ends in ", ASSAM" on its own line (2018).
        found_state = False
        while j < n and (j - i) < 16:
            if lines[j].upper() == state:
                nxt = lines[j + 1].split()[0] if j + 1 < n else ""
                if value_ok(nxt):
                    found_state = True
                    j += 1
                    break
                name_parts.append(lines[j])  # a "<place>, ASSAM" name fragment
                j += 1
                continue
            if _CODE_LINE.match(lines[j]):
                break  # ran into the next station without a state → not our state
            name_parts.append(lines[j])
            j += 1
        if not found_state:
            i += 1
            continue
        # collect exactly the next n_expected value tokens. Each line may hold one
        # token (2019-2022 layout) or several space-separated tokens (2023), so we
        # tokenise every line. Numbers, and for GW also BDL/ND, count as values.
        vals: list[str] = []
        while j < n and len(vals) < n_expected:
            subtoks = lines[j].split()
            consumed_any = False
            stop = False
            for t in subtoks:
                if len(vals) >= n_expected:
                    break
                if value_ok(t):
                    vals.append(t)
                    consumed_any = True
                else:
                    stop = True  # hit a non-value (e.g. next station name)
                    break
            if not consumed_any:
                break  # this line held no values → row ended
            j += 1
            if stop:
                break
        if len(vals) == n_expected:
            name = _norm(" ".join(name_parts)) or f"STATION_{code}"
            yield code, name, vals
            i = j
        else:
            i += 1


def _is_num(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def parse_river_pdf(path: Path, year: int) -> ParseResult:
    """Parse Brahmaputra + Bharalu (tributary) data rows for `year` (ASSAM only).
    Emits long-format observation dicts with stat in {min,max}. Fast: one
    pymupdf get_text() per page, only on Brahmaputra/Bharalu data pages.
    """
    # Load all candidate pages once (fast), then try each schema on them.
    with pymupdf.open(path) as pdf:
        page_texts = []
        for i in range(pdf.page_count):
            text = pdf[i].get_text("text") or ""
            up = text.upper()
            # "BRAH" covers spellings BRAHMAPUTRA / BRAHMPUTRA / BRAHAMPUTRA.
            if ("BRAH" in up or "BHARALU" in up) and "MIN" in up and "MAX" in up and "ASSAM" in up:
                page_texts.append((i, text))

    # Column schema varies by year AND sometimes by page: 9 params (2019-2023)
    # or 8 params (2016/2018, no Fecal Streptococci). The 8-param set is a strict
    # prefix of the 9-param set, so per page we take whichever yields more rows
    # (ties -> 9-param, keeping fecal_strep).
    res = ParseResult()
    for i, text in page_texts:
        candidates = []
        for params in (RIVER_PARAMS_2018PLUS, RIVER_PARAMS_2018PLUS[:8]):
            recs = list(_iter_records(text, len(params) * 2, _gw_tok_ok))
            candidates.append((params, recs))
        params, recs = max(candidates, key=lambda c: len(c[1]))
        for code, name, vals in recs:
            for pi, (pname, unit, _hint) in enumerate(params):
                for stat, raw in (("min", vals[pi * 2]), ("max", vals[pi * 2 + 1])):
                    val = _gw_value(raw)
                    rec = {
                        "station_code": code, "station_name": name,
                        "state": "ASSAM", "parameter": pname, "unit": unit,
                        "stat": stat, "value": val,
                        "year": year, "source_page": i + 1,
                    }
                    if val is None:
                        rec["missing_marker"] = raw
                    res.observations.append(rec)
            res.n_rows_deterministic += 1
            if len(res.audit_snippets) < 40:
                res.audit_snippets.append({
                    "year": year, "page": i + 1, "station_code": code,
                    "station_name": name, "raw_line": " ".join(vals),
                })
    return res


# --------------------------------------------------------------------------- #
# Pipeline runner
# --------------------------------------------------------------------------- #
def _load_site_id_map() -> dict[str, str]:
    """station_code -> configured site_id, from config/locations.yaml."""
    import yaml
    cfg = yaml.safe_load(open("config/locations.yaml", encoding="utf-8"))
    out = {}
    for s in cfg.get("river_stations", []):
        code = str(s.get("cpcb_station_code") or "").strip()
        if code:
            out[code] = s["site_id"]
    return out


def _site_id_for(code: str, mapping: dict[str, str]) -> str:
    return mapping.get(code, f"cpcb_{code}")


def run(years: Optional[list[int]] = None) -> dict:
    """Full P1 CPCB ingestion. Returns a summary dict (printed by __main__)."""
    from agents.ingestion_agent import extract_page, is_available

    retrieved_at = datetime.now(timezone.utc)
    dl = download_all(years)

    # --- stations ---
    stations = parse_station_list()
    code_to_station = {s.code: s for s in stations}
    known_codes = set(code_to_station)
    site_id_map = _load_site_id_map()

    # cache full Assam station list for reference/consumer mode
    SILVER.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([s.__dict__ for s in stations]).to_parquet(
        SILVER / "cpcb_stations_assam.parquet", index=False)

    # --- river observations ---
    obs_rows: list[dict] = []
    audit_snippets: list[dict] = []
    per_year = {}
    agent_used = is_available()
    agent_rows_total = 0
    pages_for_agent_total = 0

    yrs = years or sorted(RIVER_SOURCES)
    for y in yrs:
        if not dl["river"].get(y):
            per_year[y] = {"status": "no_download"}
            continue
        pdf_path = BRONZE / str(y) / Path(RIVER_SOURCES[y]).name
        pr = parse_river_pdf(pdf_path, y)
        audit_snippets.extend(pr.audit_snippets)

        year_rows = list(pr.observations)
        pages_for_agent_total += len(pr.pages_for_agent)
        if pr.pages_for_agent and agent_used:
            with pdfplumber.open(pdf_path) as pdf:
                for pi in pr.pages_for_agent:
                    txt = pdf.pages[pi].extract_text() or ""
                    ag = extract_page(txt, pi + 1, y)
                    for r in ag:
                        r.setdefault("state", "ASSAM")
                        year_rows.append(r)
                    agent_rows_total += len(ag)

        per_year[y] = {
            "status": "ok",
            "deterministic_station_rows": pr.n_rows_deterministic,
            "observations": len(pr.observations),
            "pages_for_agent": pr.pages_for_agent,
        }

        for r in year_rows:
            code = str(r["station_code"])
            st = code_to_station.get(code)
            canonical_name = st.name if st else r.get("station_name", "")
            lat = st.lat if st else None
            lon = st.lon if st else None
            site_id = _site_id_for(code, site_id_map)
            param = f"{r['parameter']}_{r['stat']}"
            src = RIVER_SOURCES[y]
            extra = f" | extracted_by={r['extracted_by']}" if r.get("extracted_by") else ""
            quote = f" | quote={r['quote'][:80]!r}" if r.get("quote") else ""
            source_ref = (
                f"{src} | p{r.get('source_page', '?')} | station {code} "
                f"{r.get('station_name', '')[:40]!r} | yearly {r['stat']}{extra}{quote}"
            )
            obs_rows.append({
                "_station_code": code,
                "_canonical_name": canonical_name,
                "_lat": lat, "_lon": lon,
                "site_id": site_id,
                "ts": datetime(y, 1, 1, tzinfo=timezone.utc),
                "parameter": param,
                "value": r["value"],
                "unit": r["unit"],
                "method": Method.lab,
                "provenance": Provenance.public_observed,
                "source_id": "cpcb_nwmp_river",
                "source_ref": source_ref,
                "retrieved_or_generated_at": retrieved_at,
                "station_code": code,
            })

    # --- validate (flag, never delete) ---
    flag_counts = validate_observations(obs_rows, known_codes)
    for r in obs_rows:
        r["quality_flag"] = QualityFlag(r["quality_flag"])

    # --- write sites (unique stations appearing in observations) ---
    seen = {}
    for r in obs_rows:
        code = r["_station_code"]
        if code in seen:
            continue
        seen[code] = {
            "site_id": r["site_id"],
            "name": r["_canonical_name"] or f"CPCB station {code}",
            "kind": SiteKind.river_station,
            "lat": r["_lat"], "lon": r["_lon"],
            "population_served": None,
            "notes": f"CPCB NWMP station {code}",
            "provenance": Provenance.public_observed,
            "source_id": "cpcb_station_list",
            "source_ref": STATION_LIST_URL,
        }
    if seen:
        write_table(list(seen.values()), SILVER / "cpcb_sites.parquet", Site)

    # --- write observations (strip helper cols) ---
    clean = []
    for r in obs_rows:
        clean.append({k: v for k, v in r.items()
                      if not k.startswith("_") and k != "station_code"})
    if clean:
        write_table(clean, SILVER / "cpcb_river.parquet", Observation)

    # --- audit sample: 20 rows (prefer LLM-extracted; else deterministic) ---
    llm_rows = [r for r in obs_rows if "extracted_by=" in r["source_ref"]]
    pool = llm_rows if llm_rows else obs_rows
    rng = random.Random(20250926)
    sample = rng.sample(pool, min(20, len(pool))) if pool else []
    audit_path = SILVER / "cpcb_audit_sample.csv"
    with open(audit_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["site_id", "station_code", "parameter", "value", "unit",
                    "quality_flag", "source_ref"])
        for r in sample:
            w.writerow([r["site_id"], r["_station_code"], r["parameter"],
                        r["value"], r["unit"], r["quality_flag"].value,
                        r["source_ref"]])

    summary = {
        "download": dl,
        "assam_stations": len(stations),
        "years_requested": yrs,
        "per_year": per_year,
        "total_observations": len(clean),
        "unique_river_sites": len(seen),
        "flag_counts": flag_counts,
        "pages_for_agent": pages_for_agent_total,
        "agent_available": agent_used,
        "agent_rows": agent_rows_total,
        "audit_sample_n": len(sample),
        "parameters": sorted({r["parameter"] for r in clean}),
    }
    return summary


def _print_summary(s: dict) -> None:
    print("=" * 64)
    print("CPCB NWMP river ingestion (P1) - summary")
    print("=" * 64)
    print(f"Assam stations in list: {s['assam_stations']}")
    print(f"Years requested: {s['years_requested']}")
    for y, info in sorted(s["per_year"].items()):
        if info.get("status") == "ok":
            print(f"  {y}: {info['deterministic_station_rows']} station-rows, "
                  f"{info['observations']} obs, pages_for_agent={info['pages_for_agent']}")
        else:
            print(f"  {y}: {info['status']}")
    print(f"Total observations written: {s['total_observations']}")
    print(f"Unique river sites: {s['unique_river_sites']}")
    print(f"Quality flags: {s['flag_counts']}")
    pct_det = 100.0 * (1 - s['agent_rows'] / max(1, s['total_observations']))
    print(f"% parsed deterministically: {pct_det:.1f}%  "
          f"(agent rows: {s['agent_rows']}, agent available: {s['agent_available']})")
    print(f"Pages deferred to agent: {s['pages_for_agent']}")
    print(f"Parameters: {s['parameters']}")
    if s["download"]["gaps"]:
        print("GAPS (never fabricated):")
        for g in s["download"]["gaps"]:
            print("  -", g)


# --------------------------------------------------------------------------- #
# Groundwater parser (P1 / consumer mode P5)
# --------------------------------------------------------------------------- #
# NWMP_DATA_<year>.pdf groundwater table columns (verified against 2022):
GW_PARAMS = [
    ("water_temp_c", "degC"),
    ("ph", "pH"),
    ("conductivity_umho_cm", "umho/cm"),
    ("bod_mg_l", "mg/L"),
    ("nitrate_n_mg_l", "mg/L"),
    ("fecal_coliform_mpn_100ml", "MPN/100mL"),
    ("total_coliform_mpn_100ml", "MPN/100mL"),
    ("tds_mg_l", "mg/L"),
    ("fluoride_mg_l", "mg/L"),
    ("arsenic_mg_l", "mg/L"),
]

_GW_MARKERS = {"BDL", "ND", "NIL", "-"}


def _gw_value(tok: str):
    try:
        return float(tok)
    except ValueError:
        return None  # BDL/ND/NIL/-


def _gw_tok_ok(tok: str) -> bool:
    return _is_num(tok) or tok.upper() in _GW_MARKERS


def parse_gw_pdf(path: Path, year: int) -> list[dict]:
    """Parse Assam groundwater rows for `year`. Returns observation dicts with
    stat in {min,max}. BDL/ND stored as value=None (flagged later)."""
    rows: list[dict] = []
    n_expected = len(GW_PARAMS) * 2
    with pymupdf.open(path) as pdf:
        for i in range(pdf.page_count):
            text = pdf[i].get_text("text") or ""
            up = text.upper()
            if "ASSAM" not in up or "MIN" not in up or "MAX" not in up:
                continue
            for code, name, toks in _iter_records(text, n_expected, _gw_tok_ok):
                for pi, (pname, unit) in enumerate(GW_PARAMS):
                    for stat, tok in (("min", toks[pi * 2]), ("max", toks[pi * 2 + 1])):
                        rows.append({
                            "station_code": code, "station_name": name,
                            "state": "ASSAM", "parameter": pname, "unit": unit,
                            "stat": stat, "value": _gw_value(tok),
                            "raw_token": tok, "year": year, "source_page": i + 1,
                        })
    return rows


def run_groundwater(years: Optional[list[int]] = None) -> dict:
    """Parse groundwater PDFs (Assam) -> data/silver/cpcb_groundwater.parquet."""
    retrieved_at = datetime.now(timezone.utc)
    stations = parse_station_list()
    code_to_station = {s.code: s for s in stations}
    known_codes = set(code_to_station)

    yrs = years or sorted(GW_SOURCES)
    obs_rows: list[dict] = []
    per_year = {}
    for y in yrs:
        pdf_path = BRONZE / str(y) / Path(GW_SOURCES[y]).name if y in GW_SOURCES else None
        if not pdf_path or not pdf_path.exists():
            per_year[y] = {"status": "no_download"}
            continue
        parsed = parse_gw_pdf(pdf_path, y)
        per_year[y] = {"status": "ok", "rows": len(parsed)}
        for r in parsed:
            code = str(r["station_code"])
            st = code_to_station.get(code)
            bdl = "" if r["value"] is not None else f" | {r['raw_token']}(below-detection)"
            obs_rows.append({
                "site_id": f"cpcb_gw_{code}",
                "ts": datetime(y, 1, 1, tzinfo=timezone.utc),
                "parameter": f"{r['parameter']}_{r['stat']}",
                "value": r["value"],
                "unit": r["unit"],
                "method": Method.lab,
                "provenance": Provenance.public_observed,
                "source_id": "cpcb_nwmp_gw",
                "source_ref": (f"{GW_SOURCES[y]} | p{r['source_page']} | station {code} "
                               f"{r['station_name'][:40]!r} | yearly {r['stat']}{bdl}"),
                "retrieved_or_generated_at": retrieved_at,
                "quality_flag": (QualityFlag.suspect if r["value"] is None else QualityFlag.ok),
                "_code": code, "_name": st.name if st else r["station_name"],
                "_lat": st.lat if st else None, "_lon": st.lon if st else None,
            })

    # write GW sites
    seen = {}
    for r in obs_rows:
        c = r["_code"]
        if c in seen:
            continue
        seen[c] = {
            "site_id": r["site_id"], "name": r["_name"] or f"GW {c}",
            "kind": SiteKind.household_area, "lat": r["_lat"], "lon": r["_lon"],
            "population_served": None, "notes": f"CPCB NWMP groundwater station {c}",
            "provenance": Provenance.public_observed,
            "source_id": "cpcb_station_list", "source_ref": STATION_LIST_URL,
        }
    if seen:
        write_table(list(seen.values()), SILVER / "cpcb_gw_sites.parquet", Site)
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in obs_rows]
    if clean:
        write_table(clean, SILVER / "cpcb_groundwater.parquet", Observation)

    return {"per_year": per_year, "total_gw_observations": len(clean),
            "unique_gw_sites": len(seen),
            "n_below_detection": sum(1 for r in obs_rows if r["value"] is None)}


if __name__ == "__main__":
    _print_summary(run())

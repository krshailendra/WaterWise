"""Validators for CPCB-extracted values (P1). Validators FLAG, never delete
(Part A §6). Returns a quality_flag per row and a summary of counts.
"""
from __future__ import annotations

from typing import Optional

# Plausible physical ranges by base parameter (yearly min/max should sit within).
PLAUSIBLE = {
    "water_temp_c": (2.0, 45.0),
    "do_mg_l": (0.0, 20.0),
    "ph": (3.0, 11.0),
    "conductivity_umho_cm": (5.0, 20000.0),
    "bod_mg_l": (0.0, 200.0),
    "nitrate_mg_l": (0.0, 200.0),
    "fecal_coliform_mpn_100ml": (0.0, 1.0e8),
    "total_coliform_mpn_100ml": (0.0, 1.0e8),
    "fecal_strep_mpn_100ml": (0.0, 1.0e8),
}

KNOWN_UNITS = {
    "degC", "mg/L", "pH", "umho/cm", "MPN/100mL",
}


def base_parameter(param: str) -> str:
    """Strip a trailing _min/_max stat suffix to get the base parameter."""
    for suf in ("_min", "_max", "_mean"):
        if param.endswith(suf):
            return param[: -len(suf)]
    return param


def check_value(parameter: str, unit: str, value: Optional[float],
                station_code: str, known_codes: set[str]) -> str:
    """Return a quality_flag in {ok, suspect, out_of_range}."""
    if unit not in KNOWN_UNITS:
        return "suspect"
    if station_code not in known_codes:
        return "suspect"  # code not in the official station list
    if value is None:
        return "suspect"
    base = base_parameter(parameter)
    lo, hi = PLAUSIBLE.get(base, (float("-inf"), float("inf")))
    if not (lo <= value <= hi):
        return "out_of_range"
    return "ok"


def validate_observations(rows: list[dict], known_codes: set[str]) -> dict:
    """Annotate each row dict with `quality_flag` in place; return a summary."""
    counts = {"ok": 0, "suspect": 0, "out_of_range": 0}
    for r in rows:
        flag = check_value(
            r.get("parameter", ""), r.get("unit", ""), r.get("value"),
            str(r.get("station_code", "")), known_codes,
        )
        r["quality_flag"] = flag
        counts[flag] = counts.get(flag, 0) + 1
    return counts

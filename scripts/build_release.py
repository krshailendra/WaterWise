"""Build the judge-facing submission package (P13-lite):
- data/release/sample_1000_rows.csv  (observations, stratified by provenance)
- data/release/provenance_summary.csv (row counts per table x provenance)
- data/release/load_example.py        (loads sample + prints the provenance split)
Row counts are also injected into docs/DATASHEET.md.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

SILVER = Path("data/silver")
GOLD = Path("data/gold")
REL = Path("data/release")

# tables that share the long Observation schema
OBS_TABLES = ["cpcb_river.parquet", "cpcb_groundwater.parquet", "hydromet.parquet",
              "s2_ndti.parquet", "tap_readings.parquet"]
OBS_COLS = ["site_id", "ts", "parameter", "value", "unit", "method", "provenance",
            "source_id", "source_ref", "quality_flag", "retrieved_or_generated_at"]


def main() -> dict:
    REL.mkdir(parents=True, exist_ok=True)
    frames = []
    counts = {}
    for t in OBS_TABLES:
        p = SILVER / t
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        df["_table"] = t.replace(".parquet", "")
        frames.append(df[[c for c in OBS_COLS if c in df.columns] + ["_table"]])
        counts[t] = df["provenance"].value_counts().to_dict()

    allobs = pd.concat(frames, ignore_index=True)

    # stratified ~1000-row sample by provenance
    target = 1000
    parts = []
    for prov, g in allobs.groupby("provenance"):
        n = max(1, round(target * len(g) / len(allobs)))
        parts.append(g.sample(min(n, len(g)), random_state=20250926))
    sample = pd.concat(parts).sample(frac=1, random_state=1).reset_index(drop=True)
    sample.to_csv(REL / "sample_1000_rows.csv", index=False)

    # provenance summary across all obs tables + network/complaints
    rows = []
    for t, d in counts.items():
        for prov, n in d.items():
            rows.append({"table": t.replace(".parquet", ""), "provenance": prov, "rows": n})
    for extra, prov in [("network_edges.parquet", "synthetic"),
                        ("network_sites.parquet", "synthetic"),
                        ("complaints.parquet", "synthetic"),
                        ("virtual_sensor_daily.parquet", "modelled"),
                        ("water_temp_daily.parquet", "modelled"),
                        ("chlorine_demand_daily.parquet", "modelled")]:
        for base in (SILVER, GOLD):
            fp = base / extra
            if fp.exists():
                rows.append({"table": extra.replace(".parquet", ""), "provenance": prov,
                             "rows": len(pd.read_parquet(fp))})
                break
    summ = pd.DataFrame(rows)
    summ.to_csv(REL / "provenance_summary.csv", index=False)

    totals = allobs["provenance"].value_counts().to_dict()

    (REL / "load_example.py").write_text(
        'import pandas as pd\n'
        'df = pd.read_csv("sample_1000_rows.csv")\n'
        'print("rows:", len(df))\n'
        'print(df["provenance"].value_counts())\n'
        'print(df.head())\n', encoding="utf-8")

    return {"sample_rows": len(sample),
            "obs_provenance_totals": totals,
            "sample_provenance": sample["provenance"].value_counts().to_dict()}


if __name__ == "__main__":
    print("release:", main())

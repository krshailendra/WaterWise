"""Sentinel-2 L2A turbidity index (NDTI) via Microsoft Planetary Computer (P3).

For each river polygon we query the `sentinel-2-l2a` STAC collection, read only
the polygon window of B04 (red), B03 (green) and SCL, keep water pixels
(SCL == 6), and compute a RELATIVE turbidity index:

    NDTI = (B04 - B03) / (B04 + B03)

per scene: median, IQR, n_water_pixels, cloud fraction. NDTI is a RELATIVE index,
NOT NTU, and says nothing about bacteria or dissolved chemicals (labelled so
everywhere). provenance=public_observed, method=satellite.

Results are cached to data/silver/s2_ndti.parquet so we never re-download during a
demo. Incremental mode fetches only dates after the latest cached scene.
"""
from __future__ import annotations

import json
import warnings
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from pipeline.schemas import Method, Observation, Provenance, QualityFlag, write_table

warnings.filterwarnings("ignore", category=RuntimeWarning)

SILVER = Path("data/silver")
FIGURES = Path("docs/figures")
S2_PARQUET = SILVER / "s2_ndti.parquet"
POLYGONS = Path("config/river_polygons.geojson")

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
START_DATE = "2017-01-01"

# A scene must have at least this many clear water pixels (SCL==6) inside the
# polygon to be trusted. We read at 20 m (reflectance overview + native SCL), so
# our ~2 km x 1.3 km polygons hold up to ~a few hundred water pixels in high
# water and fewer in the Dec-Mar low-water/sandbar season. 60 is a conservative
# floor that still rejects mostly-cloud/edge/sandbar scenes (REPORT P3).
MIN_WATER_PIXELS = 60
MAX_CLOUD_COVER = 60  # scene-level prefilter (%)
SCL_WATER = 6


def _load_polygons() -> list[dict]:
    gj = json.loads(POLYGONS.read_text(encoding="utf-8"))
    out = []
    for f in gj["features"]:
        out.append({
            "polygon_id": f["properties"]["polygon_id"],
            "role": f["properties"].get("role", ""),
            "geometry": f["geometry"],
            "bbox": _bbox(f["geometry"]),
        })
    return out


def _bbox(geometry: dict) -> list[float]:
    xs, ys = [], []
    for ring in geometry["coordinates"]:
        for x, y in ring:
            xs.append(x)
            ys.append(y)
    return [min(xs), min(ys), max(xs), max(ys)]


def _catalog():
    import planetary_computer
    import pystac_client
    return pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)


def _read_window(href: str, geometry, overview_level: Optional[int] = None):
    """Open a COG and clip to the polygon window (reads only that window).

    `overview_level=0` reads the first internal overview (20 m for the 10 m
    reflectance bands), cutting the data read ~4x — plenty for a spatial median.
    """
    import rioxarray  # noqa: F401
    import rasterio.warp
    from shapely.geometry import shape, mapping

    kwargs = {"masked": True, "chunks": None}
    if overview_level is not None:
        kwargs["overview_level"] = overview_level
    da = rioxarray.open_rasterio(href, **kwargs)
    geom = shape(geometry)
    geom_r = rasterio.warp.transform_geom("EPSG:4326", da.rio.crs.to_string(), mapping(geom))
    clipped = da.rio.clip([geom_r], crs=da.rio.crs, from_disk=True, drop=True)
    return clipped


def _scene_ndti(item, geometry) -> Optional[dict]:
    """Compute NDTI stats for one STAC item over a polygon. None if unusable."""
    try:
        # reflectance at 20 m overview; SCL is natively 20 m
        red = _read_window(item.assets["B04"].href, geometry, overview_level=0).squeeze()
        green = _read_window(item.assets["B03"].href, geometry, overview_level=0).squeeze()
        scl = _read_window(item.assets["SCL"].href, geometry).squeeze()
    except Exception as e:  # noqa: BLE001
        print(f"[s2] read failed {item.id}: {type(e).__name__}: {e}")
        return None

    # resample SCL (20 m) to the red grid (10 m) with nearest neighbour
    try:
        scl_m = scl.rio.reproject_match(red)
    except Exception:
        return None

    red_v = red.values.astype("float32")
    green_v = green.values.astype("float32")
    scl_v = scl_m.values

    water = (scl_v == SCL_WATER) & np.isfinite(red_v) & np.isfinite(green_v)
    n_water = int(np.count_nonzero(water))
    total = int(np.count_nonzero(np.isfinite(scl_v)))
    if n_water < MIN_WATER_PIXELS:
        return None

    r = red_v[water]
    g = green_v[water]
    denom = r + g
    ok = denom != 0
    ndti = (r[ok] - g[ok]) / denom[ok]
    if ndti.size < MIN_WATER_PIXELS:
        return None

    # scene cloud fraction inside the polygon: SCL 8,9,10 = cloud med/high/thin
    cloud = np.isin(scl_v, [8, 9, 10])
    cloud_frac = float(np.count_nonzero(cloud) / max(1, total))

    p25, p50, p75 = np.percentile(ndti, [25, 50, 75])
    return {
        "ndti_median": float(p50),
        "ndti_iqr": float(p75 - p25),
        "n_water_pixels": n_water,
        "cloud_fraction": round(cloud_frac, 3),
        "scene_cloud_cover": item.properties.get("eo:cloud_cover"),
    }


def _existing_max_date() -> Optional[str]:
    if not S2_PARQUET.exists():
        return None
    df = pd.read_parquet(S2_PARQUET, columns=["ts"])
    if df.empty:
        return None
    return pd.to_datetime(df["ts"]).max().date().isoformat()


def run(incremental: bool = False, end: Optional[str] = None,
        max_scenes: Optional[int] = None) -> dict:
    polygons = _load_polygons()
    retrieved_at = datetime.now(timezone.utc)
    end = end or date.today().isoformat()
    start = START_DATE
    if incremental:
        mx = _existing_max_date()
        if mx:
            start = (pd.to_datetime(mx) + pd.Timedelta(days=1)).date().isoformat()

    catalog = _catalog()
    rows: list[dict] = []
    summary = {"start": start, "end": end, "per_polygon": {}, "gaps": []}

    from concurrent.futures import ThreadPoolExecutor

    for poly in polygons:
        pid = poly["polygon_id"]
        geom = poly["geometry"]
        search = catalog.search(
            collections=[COLLECTION], bbox=poly["bbox"],
            datetime=f"{start}/{end}",
            query={"eo:cloud_cover": {"lt": MAX_CLOUD_COVER}},
        )
        items = list(search.items())
        # one candidate per date: the least cloudy
        by_date: dict = {}
        for it in items:
            d = it.datetime.date()
            cc = it.properties.get("eo:cloud_cover", 100)
            if d not in by_date or cc < by_date[d].properties.get("eo:cloud_cover", 100):
                by_date[d] = it
        candidates = [by_date[d] for d in sorted(by_date)]
        if max_scenes:
            candidates = candidates[:max_scenes]

        def _work(it):
            return it, _scene_ndti(it, geom)

        kept = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            for it, stats in ex.map(_work, candidates):
                if stats is None:
                    continue
                d = it.datetime.date()
                ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
                src = (f"MPC {COLLECTION} {it.id} | NDTI=(B04-B03)/(B04+B03), "
                       f"SCL==6 water pixels | RELATIVE turbidity index, NOT NTU")
                for pname, val, unit in (
                    ("ndti_median", stats["ndti_median"], "index"),
                    ("ndti_iqr", stats["ndti_iqr"], "index"),
                    ("water_pixels", stats["n_water_pixels"], "count"),
                    ("cloud_fraction", stats["cloud_fraction"], "fraction"),
                ):
                    rows.append({
                        "site_id": pid, "ts": ts, "parameter": pname,
                        "value": float(val), "unit": unit, "method": Method.satellite,
                        "provenance": Provenance.public_observed, "source_id": "s2_l2a",
                        "source_ref": src, "retrieved_or_generated_at": retrieved_at,
                        "quality_flag": QualityFlag.ok,
                    })
                kept += 1
        summary["per_polygon"][pid] = {"scanned": len(candidates), "kept": kept,
                                       "candidates": len(items)}

    if rows:
        if incremental and S2_PARQUET.exists():
            old = pd.read_parquet(S2_PARQUET)
            tmp = SILVER / "_s2_new.parquet"
            write_table(rows, tmp, Observation)
            new = pd.read_parquet(tmp)
            tmp.unlink(missing_ok=True)
            combined = pd.concat([old, new], ignore_index=True).drop_duplicates(
                subset=["site_id", "ts", "parameter"], keep="last")
            combined.to_parquet(S2_PARQUET, index=False)
            summary["new_rows"] = len(new)
            summary["total_rows"] = len(combined)
        else:
            write_table(rows, S2_PARQUET, Observation)
            summary["new_rows"] = len(rows)
            summary["total_rows"] = len(rows)
    else:
        summary["new_rows"] = 0
    return summary


def report() -> str:
    if not S2_PARQUET.exists():
        return "no s2_ndti.parquet yet"
    df = pd.read_parquet(S2_PARQUET)
    med = df[df["parameter"] == "ndti_median"].copy()
    med["date"] = pd.to_datetime(med["ts"])
    med["year"] = med["date"].dt.year
    med["month"] = med["date"].dt.month
    lines = [f"scenes (ndti_median rows): {len(med)}",
             f"NDTI median range: {med['value'].min():.3f} .. {med['value'].max():.3f}"]
    by_year = med.groupby(["site_id", "year"]).size().unstack(fill_value=0)
    lines.append("scenes per year:\n" + by_year.to_string())
    return "\n".join(lines)


def plot_seasonal(save: bool = True) -> Optional[str]:
    """Plot NDTI median over time + a monthly boxplot (monsoon vs winter)."""
    if not S2_PARQUET.exists():
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    df = pd.read_parquet(S2_PARQUET)
    med = df[df["parameter"] == "ndti_median"].copy()
    med["date"] = pd.to_datetime(med["ts"])
    med["month"] = med["date"].dt.month
    FIGURES.mkdir(parents=True, exist_ok=True)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5), width_ratios=[2, 1])
    for pid, g in med.groupby("site_id"):
        ax1.scatter(g["date"], g["value"], s=10, alpha=0.5, label=pid)
    ax1.set_title("Sentinel-2 NDTI (relative turbidity, NOT NTU) over time")
    ax1.set_ylabel("NDTI median"); ax1.legend(fontsize=8); ax1.grid(alpha=0.3)

    monsoon = med[med["month"].isin([6, 7, 8, 9])]["value"]
    winter = med[med["month"].isin([12, 1, 2])]["value"]
    ax2.boxplot([winter.dropna(), monsoon.dropna()], tick_labels=["winter\n(DJF)", "monsoon\n(JJAS)"])
    ax2.set_title(f"monsoon NDTI higher?\nwinter median {winter.median():.3f} vs "
                  f"monsoon {monsoon.median():.3f}")
    ax2.set_ylabel("NDTI median"); ax2.grid(alpha=0.3)
    fig.tight_layout()
    out = FIGURES / "s2_ndti_seasonal.png"
    fig.savefig(out, dpi=120); plt.close(fig)
    return str(out)


def save_quicklooks() -> list[str]:
    """Render true-colour thumbnails of the highest- and lowest-NDTI scenes."""
    if not S2_PARQUET.exists():
        return []
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    df = pd.read_parquet(S2_PARQUET)
    med = df[df["parameter"] == "ndti_median"].copy()
    med["date"] = pd.to_datetime(med["ts"])
    if med.empty:
        return []
    catalog = _catalog()
    polys = {p["polygon_id"]: p for p in _load_polygons()}
    picks = []
    hi = med.loc[med["value"].idxmax()]
    lo = med.loc[med["value"].idxmin()]
    for tag, row in (("high_ndti", hi), ("low_ndti", lo)):
        picks.append((tag, row["site_id"], row["date"].date()))
    saved = []
    FIGURES.mkdir(parents=True, exist_ok=True)
    for tag, pid, d in picks:
        try:
            poly = polys[pid]
            it = next(iter(catalog.search(
                collections=[COLLECTION], bbox=poly["bbox"],
                datetime=f"{d}/{d}").items()), None)
            if it is None:
                continue
            import numpy as np
            bands = []
            for b in ("B04", "B03", "B02"):
                arr = _read_window(it.assets[b].href, poly["geometry"], overview_level=0).squeeze().values.astype("float32")
                bands.append(arr)
            rgb = np.dstack(bands)
            rgb = np.clip(rgb / 3000.0, 0, 1)  # simple stretch
            fig, ax = plt.subplots(figsize=(4, 4))
            ax.imshow(rgb); ax.set_title(f"{tag} {pid} {d}"); ax.axis("off")
            out = FIGURES / f"s2_quicklook_{tag}.png"
            fig.savefig(out, dpi=120, bbox_inches="tight"); plt.close(fig)
            saved.append(str(out))
        except Exception as e:  # noqa: BLE001
            print(f"[s2] quicklook {tag} failed: {e}")
    return saved


if __name__ == "__main__":
    import sys
    inc = "--incremental" in sys.argv
    ms = None
    for a in sys.argv:
        if a.startswith("--max-scenes="):
            ms = int(a.split("=")[1])
    s = run(incremental=inc, max_scenes=ms)
    print("=" * 60)
    print("Sentinel-2 NDTI (P3) — summary")
    print("=" * 60)
    print(f"window {s['start']}..{s['end']} new_rows={s.get('new_rows')} total={s.get('total_rows')}")
    for pid, info in s["per_polygon"].items():
        print(f"  {pid}: kept {info['kept']} scenes (scanned {info['scanned']} of {info['candidates']} candidates)")
    print(report())

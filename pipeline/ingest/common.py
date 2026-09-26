"""Shared ingestion helpers: polite HTTP download into the immutable bronze
layer, with a sidecar JSON recording {url, retrieved_at, sha256} for every file
(Part A §6 — bronze is immutable and reproducible from URL + timestamp + hash).
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

BRONZE = Path("data/bronze")

USER_AGENT = (
    "WaterWise/0.1 (Granica x IITG hackathon; research; "
    "contact kr.shailendra23@gmail.com)"
)

DEFAULT_HEADERS = {"User-Agent": USER_AGENT}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sidecar_path(dest: Path) -> Path:
    return dest.with_suffix(dest.suffix + ".meta.json")


def download(
    url: str,
    dest: Path,
    *,
    retries: int = 3,
    backoff_s: float = 2.0,
    timeout_s: float = 60.0,
    force: bool = False,
    expect_content_type: Optional[str] = None,
) -> Optional[dict]:
    """Download `url` to `dest` (under bronze) with polite retries.

    Writes a sidecar `<dest>.meta.json` with {url, retrieved_at, sha256,
    status_code, content_type, n_bytes}. Returns the sidecar dict, or None if all
    attempts failed (caller logs the gap; NEVER fabricate — Part A rule 1).

    If the file already exists and `force` is False, the existing sidecar is
    returned unchanged (bronze is immutable; we don't re-download during a demo).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sidecar = _sidecar_path(dest)

    if dest.exists() and sidecar.exists() and not force:
        return json.loads(sidecar.read_text(encoding="utf-8"))

    last_err: Optional[str] = None
    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(
                timeout=timeout_s, follow_redirects=True, headers=DEFAULT_HEADERS
            ) as client:
                r = client.get(url)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                time.sleep(backoff_s * attempt)
                continue
            ct = r.headers.get("content-type", "")
            if expect_content_type and expect_content_type not in ct:
                # Not the expected type (often an error/redirect HTML page).
                last_err = f"unexpected content-type '{ct}' (wanted '{expect_content_type}')"
                time.sleep(backoff_s * attempt)
                continue

            data = r.content
            dest.write_bytes(data)
            meta = {
                "url": url,
                "retrieved_at": utcnow_iso(),
                "sha256": sha256_bytes(data),
                "status_code": r.status_code,
                "content_type": ct,
                "n_bytes": len(data),
            }
            sidecar.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return meta
        except Exception as e:  # network error, timeout, DNS, ...
            last_err = f"{type(e).__name__}: {e}"
            time.sleep(backoff_s * attempt)

    print(f"[download] FAILED after {retries} attempts: {url} ({last_err})")
    return None


def head_ok(url: str, timeout_s: float = 20.0) -> Optional[dict]:
    """Cheap probe: does `url` exist and what content-type? Returns metadata or
    None. Used to discover which yearly URLs are actually published."""
    try:
        with httpx.Client(
            timeout=timeout_s, follow_redirects=True, headers=DEFAULT_HEADERS
        ) as client:
            # Some servers reject HEAD; use a ranged GET to avoid full download.
            r = client.get(url, headers={**DEFAULT_HEADERS, "Range": "bytes=0-2047"})
        if r.status_code in (200, 206):
            return {
                "url": url,
                "status_code": r.status_code,
                "content_type": r.headers.get("content-type", ""),
                "content_length": r.headers.get("content-length"),
            }
    except Exception:
        return None
    return None

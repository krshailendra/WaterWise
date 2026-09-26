"""Pydantic schemas for WaterWise core tables (PLAN.md Part B §3) and a single
writer helper that refuses to persist any row lacking provenance, source_id or
source_ref (Part A rules 1 & 2).

Units are stated in column names or docstrings. Timestamps are UTC in storage
(Part A §6). All persisted tables flow through :func:`write_table`, which is the
one place provenance is enforced.
"""
from __future__ import annotations

from datetime import datetime, date
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence, Type, TypeVar, Union

import pandas as pd
from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Controlled vocabularies
# --------------------------------------------------------------------------- #
class Provenance(str, Enum):
    """The only three provenance classes allowed anywhere (Part A rule 2)."""

    public_observed = "public_observed"
    modelled = "modelled"
    synthetic = "synthetic"


class SiteKind(str, Enum):
    river_station = "river_station"
    intake = "intake"
    wtp = "wtp"
    reservoir = "reservoir"
    hostel_tank = "hostel_tank"
    cooler = "cooler"
    ro_unit = "ro_unit"
    household_area = "household_area"


class Method(str, Enum):
    lab = "lab"
    satellite = "satellite"
    reanalysis = "reanalysis"
    model = "model"
    simulated_sensor = "simulated_sensor"


class QualityFlag(str, Enum):
    ok = "ok"
    suspect = "suspect"
    out_of_range = "out_of_range"
    imputed = "imputed"


class EventKind(str, Enum):
    spill = "spill"
    discharge = "discharge"
    flood = "flood"
    advisory = "advisory"
    complaint = "complaint"
    maintenance = "maintenance"
    anomaly_injected = "anomaly_injected"


# --------------------------------------------------------------------------- #
# Provenance mixin — the fields the writer enforces
# --------------------------------------------------------------------------- #
class ProvenanceFields(BaseModel):
    """Every persisted row must carry these. Missing/blank -> rejected."""

    provenance: Provenance
    source_id: str = Field(min_length=1)
    # source_url for real data OR "generator_name@version" for synthetic.
    source_ref: str = Field(min_length=1)

    @field_validator("source_id", "source_ref")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if v is None or str(v).strip() == "":
            raise ValueError("must be a non-empty string")
        return v


# --------------------------------------------------------------------------- #
# Core tables (Part B §3)
# --------------------------------------------------------------------------- #
class Site(ProvenanceFields):
    site_id: str = Field(min_length=1)
    name: str
    kind: SiteKind
    lat: Optional[float] = None
    lon: Optional[float] = None
    upstream_site_id: Optional[str] = None
    population_served: Optional[int] = None
    notes: Optional[str] = None


class Observation(ProvenanceFields):
    """Long-format observation. `value` unit is given by `unit`."""

    site_id: str = Field(min_length=1)
    ts: datetime
    parameter: str = Field(min_length=1)
    value: Optional[float] = None
    unit: str
    method: Method
    quality_flag: QualityFlag = QualityFlag.ok
    retrieved_or_generated_at: datetime


class Event(ProvenanceFields):
    event_id: str = Field(min_length=1)
    ts_reported: Optional[datetime] = None
    ts_event_est: Optional[datetime] = None
    kind: EventKind
    lat: Optional[float] = None
    lon: Optional[float] = None
    site_id: Optional[str] = None
    text_summary: Optional[str] = None
    confidence: Optional[float] = None
    human_confirmed: bool = False


class DailyBriefing(ProvenanceFields):
    date: date
    raw_risk_level: str
    ndti_p10: Optional[float] = None
    ndti_p50: Optional[float] = None
    ndti_p90: Optional[float] = None
    water_temp_c_est: Optional[float] = None
    recommended_dose_mg_l: Optional[float] = None
    dose_p90_needed: Optional[float] = None
    worst_tap_site_id: Optional[str] = None
    worst_tap_p10_residual_mg_l: Optional[float] = None
    test_next_site_id: Optional[str] = None
    test_next_reason: Optional[str] = None
    active_alerts: int = 0
    model_versions: Optional[str] = None


class NetworkEdge(ProvenanceFields):
    from_site_id: str = Field(min_length=1)
    to_site_id: str = Field(min_length=1)
    travel_time_h_mean: float
    travel_time_h_sd: float
    pipe_k_wall_per_day: float


TModel = TypeVar("TModel", bound=ProvenanceFields)

# Required provenance columns, checked defensively even for plain dict rows.
REQUIRED_PROVENANCE_COLUMNS = ("provenance", "source_id", "source_ref")


class ProvenanceError(ValueError):
    """Raised when a row is missing provenance / source_id / source_ref."""


# --------------------------------------------------------------------------- #
# The one writer helper
# --------------------------------------------------------------------------- #
def _check_provenance_dict(row: dict, index: int) -> None:
    for col in REQUIRED_PROVENANCE_COLUMNS:
        val = row.get(col, None)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            raise ProvenanceError(
                f"row {index}: missing or blank required provenance field '{col}'. "
                "Every persisted row must carry provenance, source_id and source_ref "
                "(PLAN.md Part A rule 2)."
            )


def validate_rows(
    rows: Sequence[Union[dict, BaseModel]],
    model: Type[TModel],
) -> list[TModel]:
    """Validate rows against `model`, enforcing provenance first.

    Raises ProvenanceError before any pydantic coercion so the message is clear.
    """
    validated: list[TModel] = []
    for i, row in enumerate(rows):
        data = row.model_dump() if isinstance(row, BaseModel) else dict(row)
        _check_provenance_dict(data, i)
        validated.append(model.model_validate(data))
    return validated


def write_table(
    rows: Sequence[Union[dict, BaseModel]],
    path: Union[str, Path],
    model: Type[TModel],
) -> Path:
    """Validate `rows` against `model` and write Parquet to `path`.

    This is the ONLY sanctioned path to persist a core table. It refuses to write
    if any row lacks provenance, source_id or source_ref.

    Returns the written path. Raises ProvenanceError / pydantic ValidationError
    on bad input (nothing is written in that case).
    """
    validated = validate_rows(rows, model)  # raises before any file is touched
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for m in validated:
        d = m.model_dump()
        # store enums as their string values
        for k, v in list(d.items()):
            if isinstance(v, Enum):
                d[k] = v.value
        records.append(d)

    df = pd.DataFrame.from_records(records)
    df.to_parquet(path, index=False)
    return path

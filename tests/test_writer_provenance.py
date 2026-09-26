"""P0 acceptance: the writer must reject any row missing provenance metadata."""
import pytest

from pipeline.schemas import (
    Observation,
    Provenance,
    ProvenanceError,
    Site,
    SiteKind,
    write_table,
    validate_rows,
)


def _good_site_row():
    return {
        "site_id": "cpcb_pandu",
        "name": "Brahmaputra at Pandu",
        "kind": "river_station",
        "lat": 26.176,
        "lon": 91.684,
        "provenance": "public_observed",
        "source_id": "cpcb_station_list",
        "source_ref": "https://cpcb.nic.in/wqm/WQMN_list.pdf",
    }


def test_writer_rejects_missing_provenance(tmp_path):
    row = _good_site_row()
    del row["provenance"]
    with pytest.raises(ProvenanceError):
        write_table([row], tmp_path / "sites.parquet", Site)
    assert not (tmp_path / "sites.parquet").exists(), "nothing must be written on failure"


def test_writer_rejects_blank_source_id(tmp_path):
    row = _good_site_row()
    row["source_id"] = "   "
    with pytest.raises(ProvenanceError):
        write_table([row], tmp_path / "sites.parquet", Site)


def test_writer_rejects_missing_source_ref(tmp_path):
    row = _good_site_row()
    del row["source_ref"]
    with pytest.raises(ProvenanceError):
        write_table([row], tmp_path / "sites.parquet", Site)


def test_writer_accepts_complete_row(tmp_path):
    out = write_table([_good_site_row()], tmp_path / "sites.parquet", Site)
    assert out.exists()


def test_writer_accepts_pydantic_model_instances(tmp_path):
    obs = Observation(
        site_id="cpcb_pandu",
        ts="2023-06-01T00:00:00Z",
        parameter="ph",
        value=7.4,
        unit="pH",
        method="lab",
        retrieved_or_generated_at="2026-09-26T00:00:00Z",
        provenance=Provenance.public_observed,
        source_id="cpcb_nwmp_river",
        source_ref="https://cpcb.nic.in/nwmp-data-2022/",
    )
    out = write_table([obs], tmp_path / "obs.parquet", Observation)
    assert out.exists()


def test_validate_rows_reports_row_index():
    rows = [_good_site_row(), {**_good_site_row(), "source_ref": ""}]
    with pytest.raises(ProvenanceError) as exc:
        validate_rows(rows, Site)
    assert "row 1" in str(exc.value)

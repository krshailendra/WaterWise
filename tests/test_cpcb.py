"""P1 tests: CPCB parsing (token-stream) + validators (plausibility + regression)."""
from pipeline.ingest.cpcb import _iter_records, _is_num, _gw_tok_ok
from pipeline.validate.cpcb_checks import check_value, validate_observations, base_parameter


# real 2022 layout: code / name lines / exact-state line / 18 min-max tokens
_RIVER_2022_DIBRUGARH = "\n".join([
    "1030", "RIVER BRAHMAPUTRA AT", "DIBRUGARH, ASSAM", "ASSAM",
    "23", "23", "6", "10.4", "7", "7.9", "150", "230", "2", "2.5",
    "0.7", "1.6", "360", "940", "720", "2000", "95", "290",
])


def test_iter_records_parses_brahmaputra_station():
    recs = list(_iter_records(_RIVER_2022_DIBRUGARH, 18, _is_num))
    assert len(recs) == 1
    code, name, vals = recs[0]
    assert code == "1030"
    assert "BRAHMAPUTRA" in name.upper()
    assert len(vals) == 18            # 9 parameters x (min, max)
    assert vals[0] == "23" and vals[3] == "10.4"


def test_iter_records_skips_wrong_state():
    txt = "\n".join(["1030", "SOME RIVER", "BIHAR", "1", "2", "3", "4"])
    assert list(_iter_records(txt, 4, _is_num)) == []


def test_iter_records_handles_long_wrapped_name():
    # station 2069 Kacharighat: 9 name lines before the state token
    txt = "\n".join([
        "2069", "RIVER", "BRAHMPUTRA", "NEAR", "WATER", "INTAKE",
        "POINT AT KACHARIGHAT,", "PANBAZAR,", "GUWAHATI, ASSAM", "ASSAM",
        "18", "34", "7", "9.6", "7.2", "7.9", "132", "199", "2.1", "2.7",
        "0.7", "1", "300", "500", "600", "700", "80", "90",
    ])
    recs = list(_iter_records(txt, 18, _is_num))
    assert len(recs) == 1 and recs[0][0] == "2069"


def test_iter_records_gw_handles_bdl():
    txt = "\n".join(["4392", "WELL X", "ASSAM"] + ["BDL", "BDL"] + ["1"] * 18)
    recs = list(_iter_records(txt, 20, _gw_tok_ok))
    assert len(recs) == 1
    assert recs[0][2][0] == "BDL"


def test_base_parameter_strips_stat_suffix():
    assert base_parameter("ph_min") == "ph"
    assert base_parameter("do_mg_l_max") == "do_mg_l"
    assert base_parameter("water_temp_c") == "water_temp_c"


def test_validator_flags_out_of_range_ph():
    known = {"1031"}
    # pH of 14 is chemically implausible for river water -> out_of_range
    assert check_value("ph_max", "pH", 14.0, "1031", known) == "out_of_range"
    assert check_value("ph_min", "pH", 7.2, "1031", known) == "ok"


def test_validator_flags_unknown_station_code():
    assert check_value("ph_min", "pH", 7.0, "999999", {"1031"}) == "suspect"


def test_validator_flags_unknown_unit():
    assert check_value("ph_min", "weird_unit", 7.0, "1031", {"1031"}) == "suspect"


def test_validate_observations_counts():
    rows = [
        {"parameter": "ph_min", "unit": "pH", "value": 7.0, "station_code": "1031"},
        {"parameter": "ph_max", "unit": "pH", "value": 20.0, "station_code": "1031"},
        {"parameter": "do_mg_l_min", "unit": "mg/L", "value": 6.0, "station_code": "999"},
    ]
    counts = validate_observations(rows, {"1031"})
    assert counts["ok"] == 1
    assert counts["out_of_range"] == 1   # pH 20
    assert counts["suspect"] == 1        # unknown code
    assert rows[0]["quality_flag"] == "ok"

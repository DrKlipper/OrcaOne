import json

import pytest

from orcaone.profile_schema import load_catalog, validate_value


def option(type_, **overrides):
    return {"type": type_, "nullable": False, "min": None, "max": None,
            "enums": [], "dimension": "scalar", "complete": True, **overrides}


def code(type_, value, **overrides):
    issues = validate_value(option(type_, **overrides), value)
    return [issue["code"] for issue in issues]


def test_future_version_is_not_guessed():
    assert load_catalog("OrcaSlicer", "999.0.0") is None


def test_manifest_requires_exact_slicer_version_and_safe_file(monkeypatch, tmp_path):
    import orcaone.profile_schema as schema

    monkeypatch.setattr(schema, "SCHEMA_DIR", tmp_path)
    (tmp_path / "orca-2.4.2.json").write_text(json.dumps({
        "id": "OrcaSlicer@2.4.2", "slicer": "OrcaSlicer", "version": "2.4.2",
        "source_commit": "abc", "complete": False, "options": {},
    }), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"catalogs": [
        {"slicer": "OrcaSlicer", "version": "2.4.2", "file": "orca-2.4.2.json"},
    ]}), encoding="utf-8")
    assert load_catalog("OrcaSlicer", "2.4.2")["id"] == "OrcaSlicer@2.4.2"
    assert load_catalog("OrcaSlicer", "2.4.3") is None
    assert load_catalog("Snapmaker_Orca", "2.4.2") is None
    assert load_catalog("../OrcaSlicer", "2.4.2") is None

    (tmp_path / "manifest.json").write_text(json.dumps({"catalogs": [
        {"slicer": "OrcaSlicer", "version": "2.4.2", "file": "../outside.json"},
    ]}), encoding="utf-8")
    assert load_catalog("OrcaSlicer", "2.4.2") is None


@pytest.mark.parametrize("type_,valid,invalid,bad_code", [
    ("coBool", "1", "true", "invalid_bool"),
    ("coInt", "-2", "2.5", "invalid_number"),
    ("coFloat", "0.2", "nan", "invalid_number"),
    ("coPercent", "25%", "25", "invalid_number"),
    ("coFloatOrPercent", "25%", "inf", "invalid_number"),
    ("coString", "hello", ["hello"], "invalid_type"),
    ("coEnum", "draft", "unknown", "invalid_enum"),
    ("coPoint", "0.5x2", "0.5", "invalid_point"),
    ("coBools", ["0", "1"], "1", "invalid_type"),
    ("coInts", ["1", "-2"], ["1", "2.5"], "invalid_number"),
    ("coFloats", ["0.2"], ["Infinity"], "invalid_number"),
    ("coPercents", ["25%"], ["25"], "invalid_number"),
    ("coFloatsOrPercents", ["0.2", "25%"], ["nan"], "invalid_number"),
    ("coStrings", ["a", ""], "a", "invalid_type"),
    ("coEnums", ["draft"], ["unknown"], "invalid_enum"),
    ("coPoints", ["0x0", "2x3"], ["2x"], "invalid_point"),
    ("coPointsGroups", ["0x0,2x3"], ["2x"], "invalid_point"),
])
def test_each_source_type(type_, valid, invalid, bad_code):
    extra = {"enums": ["draft", "fine"]} if "Enum" in type_ else {}
    assert code(type_, valid, **extra) == []
    assert code(type_, invalid, **extra) == [bad_code]


def test_numeric_limits_are_decimal_and_finite():
    assert code("coFloat", "0.2", min=0, max=1) == []
    assert code("coFloat", "1.01", min=0, max=1) == ["out_of_range"]
    assert code("coFloat", "-0.01", min=0) == ["out_of_range"]
    assert code("coFloat", "Infinity") == ["invalid_number"]
    assert code("coFloatOrPercent", "101%", min=0, max=100) == ["out_of_range"]


def test_scalar_point_accepts_slicer_comma_format_and_legacy_x():
    assert code("coPoint", "0.5,2") == []
    assert code("coPoint", "0.5x2") == []
    assert code("coPoints", ["0.5x2"]) == []
    assert code("coPoints", ["0.5,2"]) == ["invalid_point"]


def test_points_groups_accepts_homogeneous_two_level_source_arrays():
    # Orca Config.cpp parse_str_arr / coPointsGroups accepts both depths.
    value = [["0x0,2x3"], ["4x5", "6x7,8x9"]]
    assert code("coPointsGroups", value) == []
    assert value == [["0x0,2x3"], ["4x5", "6x7,8x9"]]
    assert code("coPointsGroups", [[], []]) == []


@pytest.mark.parametrize("value", [["0x0", ["1x1"]], [[["0x0"]]], [[1]], [None]])
def test_points_groups_rejects_mixed_types_and_deeper_arrays(value):
    assert code("coPointsGroups", value) == ["invalid_type"]


def test_points_group_nested_error_reports_both_indices():
    assert validate_value(option("coPointsGroups"), [["0x0"], ["2x"]]) == [{"code": "invalid_point", "indices": [1, 0]}]


@pytest.mark.parametrize("type_,value", [
    ("coInt", "1_0"),
    ("coInt", "1.0"),
    ("coFloat", "１２"),
    ("coPercent", "1_0%"),
    ("coFloatOrPercent", "１２%"),
])
def test_number_requires_ascii_slicer_syntax(type_, value):
    assert code(type_, value) == ["invalid_number"]


def test_float_exponent_remains_valid():
    assert code("coFloat", "1.25e-2") == []


def test_nullable_and_empty_states_are_distinct():
    assert code("coFloats", ["nil", "0.2"], nullable=True) == []
    assert code("coFloats", ["nil"], nullable=False) == ["nil_not_allowed"]
    assert code("coFloat", "nil", nullable=True) == []
    assert code("coFloat", "", nullable=True) == ["invalid_number"]
    assert code("coFloat", []) == ["invalid_type"]
    assert code("coFloats", []) == []
    assert code("coString", "") == []


def test_unknown_type_is_blocked():
    assert code("coMystery", "x") == ["unsupported_type"]

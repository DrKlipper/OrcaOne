"""Duesen associations never silently change printer settings or other profiles."""

from copy import deepcopy
import pytest

from orcaone.profile_variants import group_profiles, suggest_nozzle_changes, variant_changes


def machine(id_, host, model="Custom"):
    return {"id": id_, "kind": "machine", "name": id_, "own": {}, "effective": {
        "printer_model": model, "nozzle_diameter": ["0.4"], "print_host": host,
        "machine_start_gcode": "G28"}, "complete": True}


def test_ambiguous_custom_models_are_not_automatically_joined():
    docs = [machine("a", "http://printer-a"), machine("b", "http://printer-b")]
    groups = group_profiles(docs)
    assert len(groups) == 2
    members = [p for g in groups for p in g["profiles"]]
    assert {p["id"] for p in members} == {"a", "b"}
    assert {p["effective"]["print_host"] for p in members} == {"http://printer-a", "http://printer-b"}


def test_explicit_group_retains_same_diameter_variants():
    docs = [machine("a", "http://printer-a"), machine("b", "http://printer-a")]
    for doc in docs:
        doc["model_group"] = "my-printer"
    groups = group_profiles(docs)
    assert len(groups) == 1
    assert len(groups[0]["profiles"]) == 2


def test_variant_changes_only_explicit_configuration():
    src = machine("a", "http://printer-a")
    before = deepcopy(src)
    result = variant_changes(src, "My Printer", {"nozzle_diameter": ["0.5"], "name": "0.5 Standard"}, {})
    assert result["issues"] == []
    assert result["document"]["effective"]["nozzle_diameter"] == ["0.5"]
    assert result["document"]["effective"]["machine_start_gcode"] == "G28"
    assert result["document"]["effective"]["print_host"] == "http://printer-a"
    assert src == before


def test_invalid_nozzle_cannot_create_partial_variant():
    result = variant_changes(machine("a", "http://printer-a"), "Printer", {"nozzle_diameter": ["nan"]}, {})
    assert result["issues"]
    assert result["document"] is None


@pytest.mark.parametrize("value", ["0_5", "٠.٥", " 0.5", "0.5 "])
def test_nozzle_uses_slicer_number_grammar(value):
    result = variant_changes(machine("a", "host"), "Printer", {"nozzle_diameter": [value]}, {})
    assert result["document"] is None


def test_suggestions_require_matching_target_values_and_do_not_apply():
    src = {"kind": "process", "effective": {"layer_height": "0.2", "outer_wall_speed": "100"}}
    target = {"kind": "process", "name": "Target process", "effective": {"layer_height": "0.3", "outer_wall_speed": "150"}}
    catalog = {"options": {"process": {"layer_height": {"type": "coFloat", "complete": True,
                      "role": "parameter", "min": 0, "max": None}}}}
    got = suggest_nozzle_changes(src, target, catalog)
    assert [s["key"] for s in got] == ["layer_height"]
    assert got[0]["after"] == "0.3" and got[0]["source"] == "Target process"
    assert src["effective"]["layer_height"] == "0.2"
    assert suggest_nozzle_changes(src, {"kind": "process", "effective": {}}, catalog) == []

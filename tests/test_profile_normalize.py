from copy import deepcopy
import json
from pathlib import Path

from orcaone.profile_normalize import resolve_values


def test_orca_filament_variant_declaration_is_not_truncated_to_filament_count():
    from orcaone.profile_schema import load_catalog
    cat = load_catalog("OrcaSlicer", "2.4.2")
    variants = ["Direct Drive Standard", "Direct Drive High Flow"]
    result = resolve_values(cat, "filament", [{"id": "profile", "values": {
        "filament_diameter": ["1.75"], "filament_extruder_variant": variants}}], {"chain_complete": True})
    assert result["complete"]
    assert result["values"]["filament_extruder_variant"] == variants


def option(default="0.2", type_="coFloat", dimension="scalar", **extra):
    return dict(type=type_, default=default, dimension=dimension, role="parameter", complete=True, **extra)


def catalog(fields, slicer="Snapmaker_Orca", kind="process"):
    return {"id": "test", "slicer": slicer, "complete": True, "options": {kind: fields}}


def test_defaults_parent_order_unknown_and_inputs_preserved():
    cat = catalog({"height": option(), "width": option("50%", "coFloatOrPercent")})
    layers = [{"id": "root", "values": {"height": "0.3"}}, {"id": "parent", "values": {"height": "0.4"}}, {"id": "child", "values": {"future": ["x"]}}]
    before = deepcopy(layers)
    result = resolve_values(cat, "process", layers, {"chain_complete": True})
    assert result["values"] == {"height": "0.4", "width": "50%"}
    assert result["unknown"] == {"future": ["x"]}
    assert result["origins"]["height"]["profile_id"] == "parent"
    assert result["origins"]["width"]["schema_id"] == "test"
    assert layers == before


def test_missing_chain_cycle_default_and_type_block_complete():
    for layers, context, fields, code in [
        ([], {"chain_complete": False}, {}, "parent_missing"),
        ([{"id": "a", "values": {}}, {"id": "a", "values": {}}], {}, {}, "inheritance_cycle"),
        ([], {}, {"x": option(None)}, "default_missing"),
        ([{"id": "a", "values": {"x": ["1"]}}], {}, {"x": option()}, "invalid_type"),
    ]:
        result = resolve_values(catalog(fields), "process", layers, context)
        assert not result["complete"]
        assert code in [i["code"] for i in result["issues"]]


def test_flow_declaration_is_not_head_count_and_grows_with_first_value():
    cat = catalog({"process_flow_support": option(["standard", "high_flow", "extra"], "coStrings", "list"), "speed": option(["10", "20"], "coFloats", "flow")})
    result = resolve_values(cat, "process", [], {"chain_complete": True, "extruder_count": 4})
    assert result["values"]["speed"] == ["10", "20", "10"]


def test_filament_presets_resize_differently_by_release():
    fields = {"filament_diameter": option(["1.75"], "coFloats", "filament"), "temperature": option(["200", "210"], "coInts", "list"), "compatible_printers": option(["a", "b"], "coStrings", "list", role_override="reference")}
    for slicer, expected in [("OrcaSlicer", ["200"]), ("Snapmaker_Orca", ["200", "210"])]:
        result = resolve_values(catalog(fields, slicer, "filament"), "filament", [], {"chain_complete": True})
        assert result["values"]["temperature"] == expected
        assert result["values"]["compatible_printers"] == ["a", "b"]


def test_source_classified_filament_option_is_resized_before_grow_only_pass():
    fields = {"filament_diameter": option(["1.75"], "coFloats", "filament"), "temperature": option(["200", "210"], "coInts", "list")}
    cat = catalog(fields, kind="filament")
    cat["normalization_rules"] = {"filament_option_keys": ["temperature"], "extruder_option_keys": [], "filament_options": list(fields)}
    result = resolve_values(cat, "filament", [], {})
    assert result["values"]["temperature"] == ["200"]


def test_orca_machine_flow_variants_are_expanded_from_each_extruder():
    fields = {"single_extruder_multi_material": option("0", "coBool"), "nozzle_diameter": option(["0.4", "0.6"], "coFloats", "extruder"), "extruder_variant_list": option(["standard,high_flow", "standard"], "coStrings", "extruder"), "printer_extruder_variant": option([], "coStrings", "list"), "printer_extruder_id": option([], "coInts", "list"), "offset": option(["1", "2"], "coFloats", "flow", dimension_context={"kind": "machine", "multiplier": 2})}
    cat = catalog(fields, "OrcaSlicer", "machine")
    cat["normalization_rules"] = {"extruder_option_keys": ["offset", "nozzle_diameter"], "filament_option_keys": [], "filament_options": []}
    result = resolve_values(cat, "machine", [], {})
    assert result["values"]["printer_extruder_variant"] == ["standard", "high_flow", "standard"]
    assert result["values"]["printer_extruder_id"] == ["1", "1", "2"]
    assert result["values"]["offset"] == ["1", "2", "1", "1", "1", "1"]


def test_snorca_segmented_flow_uses_steps_and_preserves_extra_values():
    fields = {"filament_diameter": option(["1.75", "1.75"], "coFloats", "filament"), "filament_flow_step_size": option(["2", "3"], "coInts", "list"), "speed": option(["10", "20"], "coFloats", "flow")}
    result = resolve_values(catalog(fields, kind="filament"), "filament", [], {"extruder_count": 4})
    assert result["values"]["speed"] == ["10", "20", "10", "10", "10"]


def test_source_derived_normalization_fixtures():
    fixture = json.loads((Path(__file__).parent / "fixtures/profile_editor/normalization.json").read_text(encoding="utf-8"))
    assert fixture["provenance"] == "source-derived, not Slicer roundtrip"
    for case in fixture["cases"]:
        fields = {key: option(data["default"], data["type"], data["dimension"]) for key, data in case["options"].items()}
        result = resolve_values(catalog(fields, case["slicer"], case["kind"]), case["kind"], [], case.get("context", {}))
        for key, value in case["expected"].items():
            assert result["values"][key] == value, case["name"]

from copy import deepcopy

from orcaone.profile_transfer import conversion_report, confirm_conversion


def catalog(**fields):
    return {"id": "OrcaSlicer@2.4.2", "complete": True,
            "options": {"process": fields}}


def option(type_="coFloat", default="10", **extra):
    return {"type": type_, "default": default, "dimension": "scalar", "complete": True,
            "nullable": False, "role": "parameter", "min": None, "max": None, "enums": [], **extra}


def source(**values):
    return {"id": "source-id", "name": "Quality", "kind": "process", "complete": True,
            "schema_id": "Snapmaker_Orca@2.4.0", "effective": values, "own": {},
            "parents": ["old-parent"], "base_state": "old-state"}


def test_scalar_target_reports_every_discarded_vector_value():
    report = conversion_report(source(speed=["100", "200"]), catalog(speed=option()))
    assert report["document"]["effective"]["speed"] == "100"
    loss = report["losses"][0]
    assert (loss["key"], loss["code"], loss["before"], loss["after"]) == ("speed", "vector_truncated", ["100", "200"], "100")
    assert report["ready"] is False


def test_known_nested_point_groups_preserve_their_representation():
    from orcaone.profile_schema import load_catalog
    source_doc = {"id": "a" * 32, "name": "Printer", "kind": "machine", "complete": True,
                  "schema_id": "OrcaSlicer@2.4.2", "effective": {
                      "extruder_printable_area": [["0x0,200x0,200x200"], ["0x0,100x0,100x100"]]}}
    report = conversion_report(source_doc, load_catalog("OrcaSlicer", "2.4.2"))
    assert not report["issues"]
    assert report["document"]["effective"] == source_doc["effective"]


def test_unknown_fields_enum_changes_and_nil_are_reported():
    target = catalog(mode=option("coEnum", "draft", enums=["draft", "fine"]), speed=option())
    report = conversion_report(source(gone="1", mode="unknown", speed="nil"), target)
    assert {x["code"] for x in report["losses"]} == {"unknown_field", "enum_changed", "nil_replaced"}
    assert report["document"]["effective"] == {"mode": "draft", "speed": "10"}


def test_loss_confirmation_is_per_field_and_report_is_not_mutated():
    report = conversion_report(source(speed=["100", "200"], gone="1"), catalog(speed=option()))
    original = deepcopy(report)
    partial = confirm_conversion(report, [report["losses"][0]["id"]])
    assert partial["ready"] is False
    complete = confirm_conversion(report, [loss["id"] for loss in report["losses"]])
    assert complete["ready"] is True
    assert complete["document"]["complete"] is True
    assert report == original


def test_copy_has_provenance_but_no_shared_history_or_parent():
    report = conversion_report(source(speed="25"), catalog(speed=option()))
    document = report["document"]
    assert document["id"] != "source-id"
    assert document["provenance"]["source_profile_id"] == "source-id"
    assert document["inherits"] == ""
    assert "parents" not in document and "base_state" not in document
    assert document["own"] == {"speed": "25"}


def test_secrets_never_appear_in_document_losses_or_issues():
    report = conversion_report(source(printhost_apikey="sentinel-secret", password="sentinel-secret"), catalog())
    assert "sentinel-secret" not in str(report)


def test_invalid_numbers_are_blocked_even_after_confirming_losses():
    report = conversion_report(source(speed="not-a-number"), catalog(speed=option()))
    assert report["issues"][0]["code"] == "invalid_number"
    assert confirm_conversion(report, [])["ready"] is False


def test_vector_target_preserves_values_without_guessing_length():
    target = catalog(speed=option("coFloats", ["10"], dimension="flow"))
    report = conversion_report(source(speed=["100", "200"]), target)
    assert report["document"]["effective"]["speed"] == ["100", "200"]
    assert report["losses"] == []


def test_incomplete_catalog_blocks_conversion():
    target = catalog(speed=option())
    target["complete"] = False
    report = conversion_report(source(speed="100"), target)
    assert report["ready"] is False
    assert any(x["code"] == "catalog_incomplete" for x in report["issues"])


def test_enum_vector_changes_only_invalid_element_and_preserves_source():
    original = source(mode=["fine", "removed", "draft"])
    before = deepcopy(original)
    report = conversion_report(original, catalog(mode=option("coEnums", ["draft"], dimension="flow", enums=["draft", "fine"])))
    assert report["document"]["effective"]["mode"] == ["fine", "draft", "draft"]
    assert original == before
    assert report["losses"][0]["before"] == ["fine", "removed", "draft"]


def test_actual_release_flow_vector_to_scalar_loss_is_visible():
    from orcaone.profile_schema import load_catalog

    report = conversion_report(source(outer_wall_speed=["100", "200"]), load_catalog("OrcaSlicer", "2.4.2"))
    assert report["document"]["effective"]["outer_wall_speed"] == "100"
    assert report["losses"][0]["code"] == "vector_truncated"
    assert report["ready"] is False


def test_dimension_change_requires_its_own_confirmation():
    from orcaone.profile_schema import load_catalog

    # In the source this is a flow-indexed vector; the target uses a filament axis.
    document = source(fan_min_speed=["20", "40"])
    document["kind"] = "filament"
    report = conversion_report(document, load_catalog("OrcaSlicer", "2.4.2"))
    assert report["document"]["effective"]["fan_min_speed"] == ["20", "40"]
    assert any(x["code"] == "dimension_changed" for x in report["losses"])


def test_unknown_source_version_and_incomplete_chain_block_ready():
    document = source(speed="100")
    document["schema_id"] = "Snapmaker_Orca@99.0.0"
    document["context"] = {"chain_complete": False}
    report = conversion_report(document, catalog(speed=option()))
    assert report["ready"] is False
    assert {x["code"] for x in report["issues"]} >= {"source_catalog_unavailable", "document_incomplete"}

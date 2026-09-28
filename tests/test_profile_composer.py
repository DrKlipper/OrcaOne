import json

import pytest

from orcaone import operations, profile_history
from test_operations import isolated, snorca, orca, edit_conf, instance_of
from test_profile_printer_merge import machines, add_process


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_compatibility_conversion_is_explicit_and_publishable(snorca, mode):
    from orcaone.profile_composer import prepare_preview, create_branch
    from orcaone.profile_publish import prepare_changes, current_target
    body = configuration(snorca)
    body["variants"][0]["mode"] = mode
    path = snorca.data_dir / "user/default/machine/base/Voron 1.json"
    values = json.loads(path.read_text())
    values["z_hop_types"] = "Normal Lift"
    path.write_text(json.dumps(values), encoding="utf-8")
    before = operations._tree_snapshot(snorca)
    with pytest.raises(operations.OperationError) as error:
        prepare_preview(snorca, body)
    assert error.value.code == "profile_incomplete"
    assert error.value.params["repairable"] is True
    issue = next(i for i in error.value.params["issues"] if i["key"] == "z_hop_types")
    assert issue["value"] == "Normal Lift" and issue["expected"] == "coEnums" and issue["origin"]
    body["repair_compatibility"] = True
    preview = prepare_preview(snorca, body)
    assert any(i["key"] == "z_hop_types" and i["before"] == "Normal Lift"
               and i["after"] == ["Normal Lift"] for i in preview["impacts"])
    assert operations._tree_snapshot(snorca) == before
    branch = create_branch(snorca, preview["preview_id"])
    plan = operations.make_plan(snorca, [], prepare_changes(snorca,
        {"state_id": branch["state"], "selected": branch["selected"]}, current_target(snorca)))
    assert plan["blocked"] is None, plan
    result = operations.apply(snorca.id, plan["id"])
    assert result["receipt_state"] == "verified"
    target = snorca.data_dir / "user/default/machine/base/Target 1.json"
    assert json.loads(target.read_text(encoding="utf-8"))["z_hop_types"] == ["Normal Lift"]


@pytest.mark.parametrize("missing_parent", [False, True])
def test_compatibility_conversion_does_not_guess_unknown_enum_or_parent(snorca, missing_parent):
    from orcaone.profile_composer import prepare_preview
    body = configuration(snorca)
    body["repair_compatibility"] = True
    path = snorca.data_dir / "user/default/machine/base/Voron 1.json"
    values = json.loads(path.read_text())
    values["z_hop_types"] = "Normal Lift" if missing_parent else "Unknown lift"
    if missing_parent:
        values["inherits"] = "Missing parent"
    path.write_text(json.dumps(values), encoding="utf-8")
    before = operations._tree_snapshot(snorca)
    with pytest.raises(operations.OperationError) as error:
        prepare_preview(snorca, body)
    assert error.value.params["repairable"] is False
    assert operations._tree_snapshot(snorca) == before


@pytest.mark.parametrize("inherited", [False, True])
def test_repair_only_preserves_original_name_and_does_not_merge(snorca, inherited):
    from orcaone.profile_composer import prepare_preview, prepare_repair_plan
    body = configuration(snorca)
    path = snorca.data_dir / "user/default/machine/base/Voron 1.json"
    original = json.loads(path.read_text())
    original["z_hop_types"] = "Normal Lift"
    path.write_text(json.dumps(original), encoding="utf-8")
    if inherited:
        parent = {**original, "name": "Legacy parent"}
        (path.parent / "Legacy parent.json").write_text(json.dumps(parent), encoding="utf-8")
        path.unlink()
        path = path.parent.parent / path.name
        original.pop("z_hop_types")
        original["inherits"] = "Legacy parent"
        path.write_text(json.dumps(original), encoding="utf-8")
    body["repair_compatibility"] = True
    preview = prepare_preview(snorca, body)
    plan = prepare_repair_plan(snorca, [], preview["preview_id"])
    assert plan["blocked"] is None, plan
    result = operations.apply(snorca.id, plan["id"])
    assert result["receipt_state"] == "verified"
    repaired = json.loads(path.read_text(encoding="utf-8"))
    assert repaired["name"] == original["name"]
    assert repaired["inherits"] == original["inherits"]
    assert repaired["z_hop_types"] == ["Normal Lift"]
    assert repaired.get("printer_model") == original.get("printer_model")
    assert not list(snorca.data_dir.rglob("Target 1.json"))
    body.pop("repair_compatibility")
    assert prepare_preview(snorca, body)["repairs"] == []


def configuration(instance, count=1):
    machines(instance, count)
    return {"group_name": "Workbench", "target_model": "Unified", "variants": [
        {"key": str(i), "source_name": f"Voron {i + 1}", "name": f"Target {i + 1}",
         "mode": "move", "nozzle_diameter": ["0.4"]} for i in range(count)], "assignments": []}


def test_native_composition_uses_saved_name_and_distinct_nozzles(orca):
    from orcaone.profile_composer import prepare_preview
    edit_conf(orca, lambda conf: conf.update(header="OrcaSlicer 2.4.2"))
    orca = instance_of(orca.data_dir)
    (orca.data_dir / "user/default/machine").mkdir(parents=True, exist_ok=True)
    body = configuration(orca, 2)
    body["variants"][1]["nozzle_diameter"] = ["0.50"]
    preview = prepare_preview(orca, body)
    assert preview["group"]["native_model"] is True
    assert preview["group"]["target_model"] == body["group_name"]
    documents = list(preview["documents"].values())
    assert {d["effective"]["printer_model"] for d in documents} == {body["group_name"]}
    assert {d["effective"]["printer_variant"] for d in documents} == {"0.4", "0.5"}


def test_native_composition_reports_both_duplicate_nozzle_names(orca):
    from orcaone.profile_composer import prepare_preview
    edit_conf(orca, lambda conf: conf.update(header="OrcaSlicer 2.4.2"))
    orca = instance_of(orca.data_dir)
    (orca.data_dir / "user/default/machine").mkdir(parents=True, exist_ok=True)
    body = configuration(orca, 2)
    body["variants"][1]["nozzle_diameter"] = ["0.40"]
    with pytest.raises(operations.OperationError) as error:
        prepare_preview(orca, body)
    assert error.value.code == "native_nozzle_conflict"
    assert set(error.value.params["names"]) == {"Target 1", "Target 2"}


def test_refresh_replays_composition_without_writing_slicer(snorca):
    from orcaone.profile_composer import prepare_preview, create_branch, refresh_branch
    body = configuration(snorca)
    branch = create_branch(snorca, prepare_preview(snorca, body)["preview_id"])
    path = snorca.data_dir / "user/default/machine/base/Voron 1.json"
    values = json.loads(path.read_text())
    values["printer_notes"] = "external update"
    path.write_text(json.dumps(values), encoding="utf-8")
    before = operations._tree_snapshot(snorca)
    refreshed = refresh_branch(snorca, branch["id"])
    doc = profile_history.get_revision(snorca.id, next(iter(refreshed["profiles"].values())))["document"]
    assert doc["name"] == "Target 1"
    assert doc["effective"]["printer_notes"] == "external update"
    assert operations._tree_snapshot(snorca) == before


@pytest.mark.parametrize("count", [1, 4])
def test_composer_real_rename_identity_and_multiple_equal_nozzles(snorca, count):
    from orcaone.profile_composer import prepare_preview, create_branch
    body = configuration(snorca, count)
    before = operations._tree_snapshot(snorca)
    preview = prepare_preview(snorca, body)
    assert len(preview["documents"]) == count
    assert len(set(preview["group"]["labels"].values())) == count
    assert "credential-" not in json.dumps(preview)
    branch = create_branch(snorca, preview["preview_id"])
    for pid, revision in branch["profiles"].items():
        doc = profile_history.get_revision(snorca.id, revision)["document"]
        assert doc["rename_from"].startswith("Voron")
        assert doc["id"] == pid
        assert not doc.get("copied_from")
        assert set(doc["workbench"]["required_profile_ids"]) == set(preview["documents"])
    assert operations._tree_snapshot(snorca) == before


def test_composer_copy_assignment_and_reference_closure(snorca):
    from orcaone.profile_composer import prepare_preview, create_branch
    body = configuration(snorca)
    add_process(snorca, "Fine", ["Voron 1"])
    add_process(snorca, "Child", ["Voron 1"])
    child = snorca.data_dir / "user/default/process/base/Child.json"
    data = json.loads(child.read_text())
    data["inherits"] = "Fine"
    child.unlink()
    (child.parent.parent / "Child.json").write_text(json.dumps(data))
    body["assignments"] = [{"kind": "process", "source_name": "Fine", "name": "Renamed Fine",
                            "action": "rename", "targets": ["0"]}]
    preview = prepare_preview(snorca, body)
    docs = {d["name"]: d for d in preview["documents"].values()}
    assert docs["Child"]["inherits"] == "Renamed Fine"
    assert docs["Child"]["effective"]["compatible_printers"] == ["Target 1"]
    assert preview["impacts"]
    body["variants"][0].update(mode="copy", name="Copied machine")
    body["assignments"] = []
    preview = prepare_preview(snorca, body)
    branch = create_branch(snorca, preview["preview_id"])
    doc = profile_history.get_revision(snorca.id, next(iter(branch["profiles"].values())))["document"]
    assert doc["copied_from"] != doc["id"]
    assert doc["source_revision"]


def test_composer_stale_preview_rejects_branch(snorca):
    from orcaone.profile_composer import prepare_preview, create_branch
    preview = prepare_preview(snorca, configuration(snorca))
    path = snorca.data_dir / "user/default/machine/base/Voron 1.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(operations.OperationError, match="plan_outdated"):
        create_branch(snorca, preview["preview_id"])


@pytest.mark.parametrize("kind", ["process", "filament"])
@pytest.mark.parametrize("action", ["copy", "move", "share"])
def test_assignment_targets_unknown_fields_and_sparse_own(snorca, kind, action):
    from orcaone.profile_composer import prepare_preview
    body = configuration(snorca)
    body["variants"][0]["mode"] = "copy"
    folder = snorca.data_dir / f"user/default/{kind}/base"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Source.json").write_text(json.dumps({"name": "Source", "inherits": "", "version": "2.4.0",
        "from": "User", "compatible_printers": ["Voron 1", "Other"], "custom_unknown": {"keep": True}}))
    body["assignments"] = [{"kind": kind, "source_name": "Source", "name": "Copy" if action == "copy" else "Source",
                            "action": action, "targets": ["0"], "from": ["Voron 1"]}]
    preview = prepare_preview(snorca, body)
    doc = next(d for d in preview["documents"].values() if d["kind"] == kind)
    expected = {"copy": ["Target 1"], "move": ["Other", "Target 1"],
                "share": ["Voron 1", "Other", "Target 1"]}[action]
    assert doc["effective"]["compatible_printers"] == expected
    assert doc["own_unknown"]["custom_unknown"] == {"keep": True}


def test_condition_and_invalid_decimal_block_visible(snorca):
    from orcaone.profile_composer import prepare_preview
    body = configuration(snorca)
    body["variants"][0]["nozzle_diameter"] = ["1_0"]
    with pytest.raises(operations.OperationError, match="invalid_nozzle"):
        prepare_preview(snorca, body)
    body["variants"][0]["nozzle_diameter"] = ["0.4"]
    add_process(snorca, "Conditional")
    path = snorca.data_dir / "user/default/process/base/Conditional.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["compatible_printers_condition"] = 'printer_model == "Old"'
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(operations.OperationError, match="condition_unknown"):
        prepare_preview(snorca, body)


def test_vendor_source_copy_only_and_fresh_identity(snorca):
    from orcaone.profile_composer import prepare_preview, create_branch
    from orcaone import scanner
    body = configuration(snorca)
    profile = next(p for p in scanner.scan(snorca.data_dir, snorca.slicer).profiles.values()
                   if p.name == "Snapmaker U1 (0.4 nozzle)")
    path = snorca.data_dir / profile.file
    data = json.loads(path.read_text(encoding="utf-8"))
    data["nozzle_diameter"] = ["0.4"]
    path.write_text(json.dumps(data), encoding="utf-8")
    body["variants"][0].update(source_name="Snapmaker U1 (0.4 nozzle)", mode="copy")
    preview = prepare_preview(snorca, body)
    branch = create_branch(snorca, preview["preview_id"])
    doc = profile_history.get_revision(snorca.id, next(iter(branch["profiles"].values())))["document"]
    assert doc["origin_kind"] == "user"
    assert doc["copied_from"] != doc["id"]
    assert doc["source_revision"]
    body["variants"][0]["mode"] = "move"
    with pytest.raises(operations.OperationError, match="process_copy_required"):
        prepare_preview(snorca, body)


def test_api_accepts_intents_and_ignores_client_documents(snorca, monkeypatch):
    from orcaone import profile_api
    monkeypatch.setattr(profile_api, "_instance", lambda _: snorca)
    body = configuration(snorca)
    body["documents"] = {"forged": {"effective": {"machine_start_gcode": "forged"}}}
    preview = profile_api.composer_preview(snorca.id, body)
    assert "forged" not in json.dumps(preview)
    assert profile_api.composer_branch(snorca.id, {"preview_id": preview["preview_id"]})["created"]


def test_move_and_rename_assignment_preserves_identity_and_from_scope(snorca):
    from orcaone.profile_composer import prepare_preview
    body = configuration(snorca)
    add_process(snorca, "Fine", ["Voron 1", "Other"])
    body["assignments"] = [{"kind": "process", "source_name": "Fine", "name": "Renamed",
                            "action": "move", "targets": ["0"], "from": ["Voron 1"]}]
    preview = prepare_preview(snorca, body)
    doc = next(d for d in preview["documents"].values() if d["name"] == "Renamed")
    assert doc["rename_from"] == "Fine"
    assert not doc.get("copied_from")
    assert doc["effective"]["compatible_printers"] == ["Other", "Target 1"]


def test_multiple_copies_from_one_source_and_publish_composer(snorca):
    from orcaone.profile_composer import prepare_preview, create_branch
    from orcaone.profile_publish import prepare_changes, current_target
    body = configuration(snorca)
    add_process(snorca, "Fine", ["Voron 1"])
    body["assignments"] = [{"kind": "process", "source_name": "Fine", "name": f"Copy {i}",
                            "action": "copy", "targets": ["0"]} for i in range(2)]
    preview = prepare_preview(snorca, body)
    assert {d["name"] for d in preview["documents"].values()} == {"Target 1", "Copy 0", "Copy 1", "Fine"}
    branch = create_branch(snorca, preview["preview_id"])
    plan = operations.make_plan(snorca, [], prepare_changes(snorca,
        {"state_id": branch["state"], "selected": branch["selected"]}, current_target(snorca)))
    assert plan["blocked"] is None, plan
    result = operations.apply(snorca.id, plan["id"])
    assert result["receipt_state"] == "verified"
    path = snorca.data_dir / "user/default/machine/base/Target 1.json"
    assert json.loads(path.read_text(encoding="utf-8"))["printhost_apikey"] == "credential-0"

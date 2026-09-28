import json

import pytest

from orcaone import operations, profile_history, scanner
from orcaone.profile_native import _variant
from orcaone.profile_publish import current_target, prepare_changes
from test_operations import isolated, orca, edit_conf, instance_of
from test_profile_printer_merge import machines


@pytest.fixture
def native_orca(orca):
    edit_conf(orca, lambda conf: conf.update(header="OrcaSlicer 2.4.2"))
    instance = instance_of(orca.data_dir)
    (instance.data_dir / "user/default/machine").mkdir(parents=True, exist_ok=True)
    machines(instance, 2)
    return instance


def composition(instance, mode="copy", related=False):
    from orcaone.profile_composer import prepare_preview, create_branch
    body = {"group_name": "Workshop Voron", "target_model": "Workshop Voron", "variants": [
        {"key": str(i), "source_name": f"Voron {i+1}", "name": f"Workshop {size}", "mode": mode,
         "nozzle_diameter": [size]} for i, size in enumerate(["0.4", "0.6"])], "assignments": []}
    if related:
        for kind in ("process", "filament"):
            folder = instance.data_dir / f"user/default/{kind}/base"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "Source.json").write_text(json.dumps({"name": "Source", "version": "2.4.2", "inherits": "",
                "compatible_printers": ["Voron 1"], "from": "User"}), encoding="utf-8")
            body["assignments"].append({"kind": kind, "source_name": "Source", "name": "Shared", "action": "copy", "targets": ["0", "1"]})
    preview = prepare_preview(instance, body)
    assert preview["group"]["native_model"]
    branch = create_branch(instance, preview["preview_id"])
    plan = operations.make_plan(instance, [], prepare_changes(instance,
        {"state_id": branch["state"], "selected": branch["selected"]}, current_target(instance)))
    assert plan["blocked"] is None, plan
    return plan, preview, branch


@pytest.mark.parametrize("mode", ["copy", "move"])
def test_native_publish_one_model_no_duplicate_user_machines(native_orca, mode):
    plan, preview, branch = composition(native_orca, mode)
    assert "credential-" not in json.dumps(plan)
    result = operations.apply(native_orca.id, plan["id"])
    assert result["receipt_state"] == "verified"
    scan = scanner.scan(native_orca.data_dir, native_orca.slicer)
    vendor = "OrcaOne_" + preview["group"]["id"]
    members = [p for p in scan.profiles.values() if p.package == vendor]
    assert len(members) == 2
    assert {p.values["printer_model"] for p in members} == {"Workshop Voron"}
    assert {p.values["printer_variant"] for p in members} == {"0.4", "0.6"}
    assert not any(p.name.startswith("Workshop") for p in scan.own)
    assert len([p for p in scan.own if p.name in {"Voron 1", "Voron 2"}]) == (2 if mode == "copy" else 0)
    assert all("inherits" not in json.loads((native_orca.data_dir / p.file).read_text()) for p in members)
    assert {p.values["printhost_apikey"] for p in members} == {"credential-0", "credential-1"}
    assert any(m["vendor"] == vendor and m["model"] == "Workshop Voron" for m in scan.conf["models"])


def test_native_failed_write_restores_sources_and_removes_package(native_orca, monkeypatch):
    plan, preview, _ = composition(native_orca, "move")
    before = {p.relative_to(native_orca.data_dir).as_posix(): p.read_bytes() for p in native_orca.data_dir.rglob("*") if p.is_file()}
    execute = operations._execute
    def fail(root, steps):
        if any(s.path.endswith("machine/model.json") for s in steps):
            raise OSError("synthetic failure")
        return execute(root, steps)
    monkeypatch.setattr(operations, "_execute", fail)
    with pytest.raises(operations.OperationError) as error:
        operations.apply(native_orca.id, plan["id"])
    assert error.value.params["rolled_back"] is True
    after = {p.relative_to(native_orca.data_dir).as_posix(): p.read_bytes() for p in native_orca.data_dir.rglob("*") if p.is_file()}
    assert after == before
    assert not (native_orca.data_dir / "system" / ("OrcaOne_" + preview["group"]["id"])).exists()


def test_native_variant_normalization_preserves_extruder_order():
    assert _variant({"nozzle_diameter": ["0.40", "0.60"]}) == "0.4+0.6"
    with pytest.raises(operations.Blocked):
        _variant({"nozzle_diameter": ["0_4"]})


def test_copy_managed_nozzle_preserves_live_connection_and_original(native_orca):
    from orcaone.profile_composer import prepare_preview, create_branch
    plan, original, _ = composition(native_orca)
    operations.apply(native_orca.id, plan["id"])
    body = {"group_name": "Second model", "target_model": "Second model", "variants": [
        {"key": "a", "source_name": "Workshop 0.4", "name": "Second 0.5", "mode": "copy",
         "nozzle_diameter": ["0.5"]}], "assignments": []}
    preview = prepare_preview(native_orca, body)
    branch = create_branch(native_orca, preview["preview_id"])
    plan = operations.make_plan(native_orca, [], prepare_changes(native_orca,
        {"state_id": branch["state"], "selected": branch["selected"]}, current_target(native_orca)))
    assert plan["blocked"] is None, plan
    assert "credential-" not in json.dumps(plan)
    assert operations.apply(native_orca.id, plan["id"])["receipt_state"] == "verified"
    scan = scanner.scan(native_orca.data_dir, native_orca.slicer)
    copied = next(p for p in scan.profiles.values() if p.name == "Second 0.5")
    assert copied.values["printhost_apikey"] == "credential-0"
    assert len([p for p in scan.profiles.values() if p.package == "OrcaOne_" + original["group"]["id"]]) == 2
    body["variants"][0]["mode"] = "move"
    body["variants"][0]["name"] = "Third 0.5"
    with pytest.raises(operations.OperationError) as error:
        prepare_preview(native_orca, body)
    assert error.value.code == "native_source_move_unsupported"


@pytest.mark.parametrize("rename", [False, True])
def test_managed_machine_edit_reuses_native_path(native_orca, rename):
    from orcaone.profile_api import _read_document
    plan, preview, _ = composition(native_orca)
    operations.apply(native_orca.id, plan["id"])
    document = _read_document(native_orca, "machine", "Workshop 0.4")
    assert document["native_package"] == "OrcaOne_" + preview["group"]["id"]
    document["own"]["printer_notes"] = "edited native"
    document["effective"]["printer_notes"] = "edited native"
    if rename:
        document.update(name="Named native", rename_from="Workshop 0.4")
    rid = profile_history.save_revision(native_orca.id, document, [], {})
    sid = profile_history.save_state(native_orca.id, {document["id"]: rid}, [], "edit")
    plan = operations.make_plan(native_orca, [], prepare_changes(native_orca,
        {"state_id": sid, "selected": [document["id"]]}, current_target(native_orca)))
    assert plan["blocked"] is None, plan
    assert operations.apply(native_orca.id, plan["id"])["receipt_state"] == "verified"
    fresh = _read_document(native_orca, "machine", document["name"])
    assert fresh["id"] == document["id"]
    assert fresh["effective"]["printer_notes"] == "edited native"
    assert len([p for p in scanner.scan(native_orca.data_dir, native_orca.slicer).profiles.values()
                if p.package == document["native_package"]]) == 2


def test_native_verification_failure_rolls_back_deleted_sources(native_orca, monkeypatch):
    from orcaone import profile_publish
    plan, preview, _ = composition(native_orca, "move")
    before = {p.relative_to(native_orca.data_dir).as_posix(): p.read_bytes() for p in native_orca.data_dir.rglob("*") if p.is_file()}
    monkeypatch.setattr(profile_publish, "_loaded", lambda *args: False)
    with pytest.raises(operations.OperationError) as error:
        operations.apply(native_orca.id, plan["id"])
    assert error.value.params["rolled_back"] is True
    assert {p.relative_to(native_orca.data_dir).as_posix(): p.read_bytes() for p in native_orca.data_dir.rglob("*") if p.is_file()} == before


def test_native_editor_api_branch_patch_checkpoint_publish(native_orca):
    from orcaone import profile_api
    plan, _, _ = composition(native_orca)
    operations.apply(native_orca.id, plan["id"])
    branch = profile_api.create_branch(native_orca.id, {"name": "Edit", "profiles": [{"kind": "machine", "name": "Workshop 0.4"}]})
    pid = branch["selected"][0]
    staged = profile_api.save_draft(native_orca.id, branch["id"], {"expected_generation": 0, "selected": [pid],
        "patches": [{"profile_id": pid, "op": "set", "key": "printer_notes", "value": "API change"}]})
    assert staged["saved"] is True
    assert staged["documents"][pid]["native_package"]
    committed = profile_api.checkpoint(native_orca.id, {"branch_id": branch["id"], "selected": [pid],
        "expected_generation": staged["generation"], "expected_branch_generation": branch["generation"]})
    current = profile_history.get_branch(native_orca.id, branch["id"])
    published = profile_api.publish_preview(native_orca.id, {"branch_id": branch["id"], "state_id": current["state"], "selected": [pid]})
    assert published["blocked"] is None, published
    assert operations.apply(native_orca.id, published["id"])["receipt_state"] == "verified"
    assert profile_api._read_document(native_orca, "machine", "Workshop 0.4")["effective"]["printer_notes"] == "API change"


def test_native_replay_uses_existing_package(native_orca):
    plan, _, branch = composition(native_orca, "move")
    operations.apply(native_orca.id, plan["id"])
    replay = operations.make_plan(native_orca, [], prepare_changes(native_orca,
        {"state_id": branch["state"], "selected": branch["selected"]}, current_target(native_orca)))
    assert replay["blocked"] is None, replay
    assert operations.apply(native_orca.id, replay["id"])["receipt_state"] == "verified"


def test_native_process_filament_shared_references_remain_user_profiles(native_orca):
    plan, _, _ = composition(native_orca, related=True)
    assert operations.apply(native_orca.id, plan["id"])["receipt_state"] == "verified"
    from orcaone.resolver import Resolver
    scan = scanner.scan(native_orca.data_dir, native_orca.slicer)
    resolver = Resolver(scan)
    for kind in ("process", "filament"):
        profiles = [p for p in scan.own if p.kind == kind and p.name == "Shared"]
        assert len(profiles) == 1
        assert profiles[0].values["compatible_printers"] == ["Workshop 0.4", "Workshop 0.6"]
        assert resolver.loaded(profiles[0])

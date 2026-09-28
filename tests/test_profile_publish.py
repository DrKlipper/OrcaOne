import json

import pytest

from orcaone import operations, profile_history
from orcaone import profile_publish
from orcaone.profile_edit import make_document
from orcaone.profile_publish import check_target, current_target, prepare_changes, recover_receipt
from orcaone.profile_schema import load_catalog
from orcaone.scanner import Profile
from orcaone import scanner
from orcaone.resolver import Resolver
from orcaone.profile_edit import apply_patches
from test_operations import isolated, snorca, orca, edit_conf, instance_of


def revision(instance, kind="process", name="Published", values=None):
    class Resolver:
        def chain(self, profile):
            return [], True
    document = make_document("a" * 32, Profile(name, kind, "", values=values or {}), Resolver(), load_catalog(instance.slicer, instance.version))
    document["context"]["user_folder"] = instance.active_user_folder
    existing = next((instance.data_dir / f"user/{instance.active_user_folder}/{kind}").rglob(f"{name}.json"), None)
    if existing is not None:
        from orcaone.profile_observe import bind_identity
        bind_identity(instance.id, document["id"], instance.active_user_folder, kind,
                      existing.relative_to(instance.data_dir).as_posix(), name)
    rid = profile_history.save_revision(instance.id, document, [], {})
    sid = profile_history.save_state(instance.id, {document["id"]: rid}, [], "publish")
    return {"state_id": sid, "selected": [document["id"]]}


def preview(instance, selection):
    return operations.make_plan(instance, [], prepare_changes(instance, selection, current_target(instance)))


def test_changed_user_folder_blocks_before_writing():
    expected = {"folder": "default", "schema_id": "OrcaSlicer@2.4.2", "fingerprint": "a"}
    with pytest.raises(operations.OperationError) as exc:
        check_target(expected, {**expected, "folder": "account"})
    assert exc.value.code == "plan_outdated"


@pytest.mark.parametrize("kind", ["process", "filament", "machine"])
def test_selected_fixed_revision_publishes_and_verifies_receipt(snorca, kind):
    selection = revision(snorca, kind)
    made = preview(snorca, selection)
    assert made["blocked"] is None, made
    result = operations.apply(snorca.id, made["id"])
    assert result["ok"]
    assert result["receipt_state"] == "verified"
    target = snorca.data_dir / f"user/default/{kind}/base/Published.json"
    data = json.loads(target.read_text())
    assert data["inherits"] == ""
    assert data.get("is_custom_defined") != "1"
    assert recover_receipt(snorca, result["receipt_id"])["state"] == "verified"


def test_changed_file_blocks_publish(snorca):
    made = preview(snorca, revision(snorca))
    (snorca.data_dir / "user/default/new.txt").write_text("external")
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.code == "plan_outdated"


def test_version_change_and_vendor_name_are_blocked(snorca):
    selection = revision(snorca)
    expected = current_target(snorca)
    snorca.version = "999.0"
    with pytest.raises(operations.OperationError):
        prepare_changes(snorca, selection, expected)
    snorca.version = "2.4.0"
    made = preview(snorca, revision(snorca, "machine", "Snapmaker U1 (0.4 nozzle)"))
    assert made["blocked"] in {"name_taken", "references_outside_selection"}


def test_failure_between_json_and_info_rolls_back_owned_bytes(snorca, monkeypatch):
    made = preview(snorca, revision(snorca))
    original = operations.write_atomic
    def fail_info(path, content):
        if path.name == "Published.info":
            raise OSError("disk full")
        original(path, content)
    monkeypatch.setattr(operations, "write_atomic", fail_info)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.params["receipt_state"] == "rolled_back"
    assert not (snorca.data_dir / "user/default/process/base/Published.json").exists()
    assert recover_receipt(snorca, exc.value.params["receipt_id"])["state"] == "rolled_back"


def test_foreign_write_is_never_overwritten_by_rollback(snorca, monkeypatch):
    made = preview(snorca, revision(snorca))
    target = snorca.data_dir / "user/default/process/base/Published.json"
    original = operations._execute
    def interrupted(data_dir, steps):
        original(data_dir, steps[:1])
        target.write_text("foreign update", encoding="utf-8")
        raise OSError("interrupted")
    monkeypatch.setattr(operations, "_execute", interrupted)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.params["receipt_state"] == "needs_review"
    assert target.read_text() == "foreign update"
    assert recover_receipt(snorca, exc.value.params["receipt_id"])["state"] == "needs_review"


def test_rescan_failure_cannot_report_success(snorca, monkeypatch):
    made = preview(snorca, revision(snorca))
    monkeypatch.setattr(profile_publish, "_loaded", lambda *args: False)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.params["receipt_state"] == "rolled_back"


def test_receipt_disk_full_stops_before_destination_write(snorca, monkeypatch):
    made = preview(snorca, revision(snorca))
    def disk_full(*args):
        raise OSError("disk full")
    monkeypatch.setattr(profile_publish, "write_receipt", disk_full)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.code == "receipt_write_failed"
    assert not (snorca.data_dir / "user/default/process/base/Published.json").exists()


def test_system_parent_change_invalidates_preview(snorca):
    made = preview(snorca, revision(snorca))
    path = next((snorca.data_dir / "system").rglob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["description"] = "external update"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.code == "plan_outdated"


def test_destination_connection_and_unselected_files_are_preserved(snorca):
    target = snorca.data_dir / "user/default/machine/Mein U1.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    data.update(print_host="192.0.2.2", printhost_apikey="current-key", printhost_port="7125")
    target.write_text(json.dumps(data), encoding="utf-8")
    untouched = snorca.data_dir / "user/default/filament/Mein PLA.json"
    before = untouched.read_bytes()
    made = preview(snorca, revision(snorca, "machine", "Mein U1"))
    assert made["blocked"] is None
    operations.apply(snorca.id, made["id"])
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result["printhost_apikey"] == "current-key"
    assert result["print_host"] == "192.0.2.2"
    assert result["printhost_port"] == "7125"
    assert untouched.read_bytes() == before


def test_unknown_reference_blocks_without_expanding_selection(snorca):
    made = preview(snorca, revision(snorca, "filament", values={"compatible_printers": ["Absent printer"]}))
    assert made["blocked"] == "reference_missing"


def test_running_slicer_blocks_apply(snorca, monkeypatch):
    made = preview(snorca, revision(snorca))
    monkeypatch.setattr(operations, "run_block", lambda *args: "slicer_running")
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.code == "slicer_running"
    assert not (snorca.data_dir / "user/default/process/base/Published.json").exists()


def test_recovery_after_rescan_exception_marks_needs_review(snorca, monkeypatch):
    made = preview(snorca, revision(snorca))
    result = operations.apply(snorca.id, made["id"])
    def broken_scan(*args):
        raise RuntimeError("scan failed")
    monkeypatch.setattr(profile_publish, "_loaded", broken_scan)
    assert recover_receipt(snorca, result["receipt_id"])["state"] == "needs_review"


def test_failed_rollback_marks_needs_review(snorca, monkeypatch):
    made = preview(snorca, revision(snorca, "machine", "Mein U1"))
    original = operations.write_atomic
    count = 0
    def fail_after_first(path, content):
        nonlocal count
        count += 1
        if count >= 2:
            raise OSError("disk unavailable")
        original(path, content)
    monkeypatch.setattr(operations, "write_atomic", fail_after_first)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert not exc.value.params["rolled_back"]
    assert exc.value.params["receipt_state"] == "needs_review"


def test_interrupted_receipt_can_recover_complete_after_state(snorca, monkeypatch):
    made = preview(snorca, revision(snorca))
    original = profile_publish.write_receipt
    def simulated_crash(instance_id, receipt):
        if receipt["state"] == "verified":
            raise KeyboardInterrupt("process stopped")
        return original(instance_id, receipt)
    monkeypatch.setattr(profile_publish, "write_receipt", simulated_crash)
    with pytest.raises(KeyboardInterrupt):
        operations.apply(snorca.id, made["id"])
    monkeypatch.setattr(profile_publish, "write_receipt", original)
    receipt_path = next((profile_publish._root(snorca.id) / "receipts").glob("*.json"))
    assert json.loads(receipt_path.read_text())["state"] == "writing"
    assert recover_receipt(snorca, receipt_path.stem)["state"] == "verified"


def test_dimension_mismatch_in_fixed_revision_is_rejected(snorca):
    selection = revision(snorca, "filament")
    state = profile_history.get_state(snorca.id, selection["state_id"])
    document = profile_history.get_revision(snorca.id, next(iter(state["profiles"].values())))["document"]
    document["effective"]["filament_flow_ratio"] = []
    rid = profile_history.save_revision(snorca.id, document, [], {})
    selection["state_id"] = profile_history.save_state(snorca.id, {document["id"]: rid}, [], "malformed")
    made = preview(snorca, selection)
    assert made["blocked"] == "profile_dimension_invalid"


def test_new_machine_variant_uses_current_source_connection(snorca):
    target = snorca.data_dir / "user/default/machine/Mein U1.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    data.update(print_host="192.0.2.10", printhost_apikey="live-secret", printhost_port="7125")
    target.write_text(json.dumps(data), encoding="utf-8")
    selection = revision(snorca, "machine", "Mein U1")
    state = profile_history.get_state(snorca.id, selection["state_id"])
    source_id, source_revision = next(iter(state["profiles"].items()))
    document = profile_history.get_revision(snorca.id, source_revision)["document"]
    document.update(id="b" * 32, name="Mein U1 High Flow", copied_from=source_id, source_revision=source_revision)
    copied_revision = profile_history.save_revision(snorca.id, document, [], {})
    sid = profile_history.save_state(snorca.id, {document["id"]: copied_revision}, [], "variant")
    before = target.read_bytes()
    made = preview(snorca, {"state_id": sid, "selected": [document["id"]]})
    assert made["blocked"] is None
    operations.apply(snorca.id, made["id"])
    result = json.loads((target.parent / "base/Mein U1 High Flow.json").read_text(encoding="utf-8"))
    assert result["print_host"] == "192.0.2.10"
    assert result["printhost_apikey"] == "live-secret"
    assert target.read_bytes() == before
    repeated = preview(snorca, {"state_id": sid, "selected": [document["id"]]})
    assert repeated["blocked"] is None
    from orcaone.profile_observe import identity_at
    assert identity_at(snorca.id, "default", "machine", "user/default/machine/base/Mein U1 High Flow.json") == document["id"]


def test_unchanged_publication_still_checks_loadability(snorca, monkeypatch):
    selection = revision(snorca)
    made = preview(snorca, selection)
    operations.apply(snorca.id, made["id"])
    second = preview(snorca, selection)
    assert second["ops"] == []
    received = []
    def not_loaded(instance, names):
        received.extend(names)
        return not names
    monkeypatch.setattr(profile_publish, "_loaded", not_loaded)
    with pytest.raises(operations.OperationError):
        operations.apply(snorca.id, second["id"])
    assert received == [("process", "Published")]


@pytest.mark.parametrize("kind", ["machine", "filament", "process"])
def test_pinned_orca_catalog_publishes_synthetic_root(orca, kind):
    # Synthetic fixture version binding; this is not a real Slicer roundtrip.
    edit_conf(orca, lambda data: data.update(header="OrcaSlicer 2.4.2"))
    instance = instance_of(orca.data_dir)
    made = preview(instance, revision(instance, kind))
    assert made["blocked"] is None, made
    result = operations.apply(instance.id, made["id"])
    assert result["receipt_state"] == "verified"


def test_rollback_success_requires_restored_bytes(snorca, monkeypatch):
    made = preview(snorca, revision(snorca, "machine", "Mein U1"))
    original = operations.write_atomic
    count = 0
    def failed_restore(path, content):
        nonlocal count
        count += 1
        if count == 1:
            original(path, content)
        elif count == 2:
            raise OSError("failed info")
        # Simulate an unsuccessful restore without a reported OS error.
    monkeypatch.setattr(operations, "write_atomic", failed_restore)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.params["receipt_state"] == "needs_review"


def test_copied_profile_cannot_replace_existing_name(snorca):
    selection = revision(snorca, "machine", "Mein U1")
    state = profile_history.get_state(snorca.id, selection["state_id"])
    rid = next(iter(state["profiles"].values()))
    document = profile_history.get_revision(snorca.id, rid)["document"]
    document.update(id="b" * 32, copied_from="a" * 32, source_revision=rid)
    new_rid = profile_history.save_revision(snorca.id, document, [], {})
    sid = profile_history.save_state(snorca.id, {document["id"]: new_rid}, [], "copy collision")
    made = preview(snorca, {"state_id": sid, "selected": [document["id"]]})
    assert made["blocked"] == "name_taken"


def test_historical_user_folder_mismatch_blocks_target(snorca):
    selection = revision(snorca)
    state = profile_history.get_state(snorca.id, selection["state_id"])
    document = profile_history.get_revision(snorca.id, next(iter(state["profiles"].values())))["document"]
    document["context"]["user_folder"] = "other-account"
    rid = profile_history.save_revision(snorca.id, document, [], {})
    selection["state_id"] = profile_history.save_state(snorca.id, {document["id"]: rid}, [], "other account")
    assert preview(snorca, selection)["blocked"] == "source_folder_mismatch"


def test_source_connection_from_other_account_is_blocked(snorca):
    selection = revision(snorca, "machine", "Mein U1")
    state = profile_history.get_state(snorca.id, selection["state_id"])
    source = profile_history.get_revision(snorca.id, next(iter(state["profiles"].values())))["document"]
    source["context"]["user_folder"] = "other-account"
    source_rid = profile_history.save_revision(snorca.id, source, [], {})
    source.update(id="b" * 32, name="New copy", copied_from="a" * 32, source_revision=source_rid)
    source["context"]["user_folder"] = "default"
    rid = profile_history.save_revision(snorca.id, source, [], {})
    sid = profile_history.save_state(snorca.id, {source["id"]: rid}, [], "wrong connection source")
    assert preview(snorca, {"state_id": sid, "selected": [source["id"]]})["blocked"] == "source_folder_mismatch"


def test_orca_nested_points_group_survives_planner_write_and_rescan(orca):
    edit_conf(orca, lambda data: data.update(header="OrcaSlicer 2.4.2"))
    instance = instance_of(orca.data_dir)
    value = [["0x0,2x3"], ["4x5,6x7"]]
    selection = revision(instance, "machine", values={"extruder_printable_area": value})
    made = preview(instance, selection)
    assert made["blocked"] is None, made
    operations.apply(instance.id, made["id"])
    target = instance.data_dir / "user/default/machine/base/Published.json"
    assert json.loads(target.read_text())["extruder_printable_area"] == value


def test_rollback_checks_running_state_after_backup_read(snorca, monkeypatch):
    made = preview(snorca, revision(snorca, "machine", "Mein U1"))
    original_write = operations.write_atomic
    original_read = profile_publish.backup.restorable
    running = False
    calls = 0
    def read_backup(*args):
        nonlocal running
        result = original_read(*args)
        running = True
        return result
    def fail_info(path, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("info failure")
        original_write(path, content)
    monkeypatch.setattr(profile_publish.backup, "restorable", read_backup)
    monkeypatch.setattr(operations, "run_block", lambda *args: "slicer_running" if running else None)
    monkeypatch.setattr(operations, "write_atomic", fail_info)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.params["receipt_state"] == "needs_review"
    assert calls == 2


def test_rollback_stops_if_slicer_starts_between_restore_steps(snorca, monkeypatch):
    made = preview(snorca, revision(snorca, "machine", "Mein U1"))
    original_write = operations.write_atomic
    running = False
    calls = 0
    def start_during_restore(path, content):
        nonlocal running, calls
        calls += 1
        original_write(path, content)
        if calls == 3:
            running = True
    monkeypatch.setattr(operations, "write_atomic", start_during_restore)
    monkeypatch.setattr(operations, "run_block", lambda *args: "slicer_running" if running else None)
    monkeypatch.setattr(profile_publish, "_loaded", lambda *args: False)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.params["receipt_state"] == "needs_review"
    assert calls == 3


def test_copy_connection_requires_exact_live_source_identity(snorca, monkeypatch):
    selection = revision(snorca, "machine", "Mein U1")
    state = profile_history.get_state(snorca.id, selection["state_id"])
    source_rid = next(iter(state["profiles"].values()))
    doc = profile_history.get_revision(snorca.id, source_rid)["document"]
    doc.update(id="b" * 32, name="New copy", copied_from="a" * 32, source_revision=source_rid)
    rid = profile_history.save_revision(snorca.id, doc, [], {})
    sid = profile_history.save_state(snorca.id, {doc["id"]: rid}, [], "copy")
    monkeypatch.setattr(profile_publish, "identity_at", lambda *args: "c" * 32)
    assert preview(snorca, {"state_id": sid, "selected": [doc["id"]]})["blocked"] == "connection_source_mismatch"


def inherited_selection(instance, operation):
    scan = scanner.scan(instance.data_dir, instance.slicer)
    resolver = Resolver(scan)
    profile = next(p for p in scan.own if p.kind == "filament" and p.name == "Mein PLA")
    from orcaone.profile_observe import identity_for
    pid = identity_for(instance.id, scan.active_folder, profile.kind, profile.file, profile.name)
    catalog = load_catalog(instance.slicer, instance.version)
    doc = make_document(pid, profile, resolver, catalog)
    doc["context"]["user_folder"] = scan.active_folder
    patch = {"profile_id": pid, "key": "nozzle_temperature", "op": operation, "indices": None}
    if operation == "set":
        patch["value"] = ["220"]
    result = apply_patches({pid: doc}, [patch], {catalog["id"]: catalog})
    assert result["issues"] == []
    rid = profile_history.save_revision(instance.id, result["documents"][pid], [], {})
    sid = profile_history.save_state(instance.id, {pid: rid}, [], "inherited edit")
    return {"state_id": sid, "selected": [pid]}, resolver.parent(profile)


@pytest.mark.parametrize("operation", ["set", "reset"])
def test_regular_inherited_edit_preserves_parent_and_sparse_own_values(snorca, operation):
    target = snorca.data_dir / "user/default/filament/Mein PLA.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    data.update(filament_cost=["17"], own_future="keep me")
    target.write_text(json.dumps(data), encoding="utf-8")
    scan = scanner.scan(snorca.data_dir, snorca.slicer)
    parent = next(p for p in scan.profiles.values() if p.name == data["inherits"])
    parent_path = snorca.data_dir / parent.file
    parent_data = json.loads(parent_path.read_text(encoding="utf-8"))
    parent_data["inherited_future"] = "never own this"
    parent_path.write_text(json.dumps(parent_data), encoding="utf-8")
    base_id = scanner.read_info(target.with_suffix(".info")).get("base_id")
    selection, _ = inherited_selection(snorca, operation)
    made = preview(snorca, selection)
    assert made["blocked"] is None, made
    operations.apply(snorca.id, made["id"])
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result["inherits"] == data["inherits"]
    assert result["filament_cost"] == ["17"]
    assert result["own_future"] == "keep me"
    assert "inherited_future" not in result
    assert result["version"] == data["version"]
    assert scanner.read_info(target.with_suffix(".info")).get("base_id") == base_id
    assert "filament_density" not in result
    if operation == "reset":
        assert "nozzle_temperature" not in result
    else:
        assert result["nozzle_temperature"] == ["220"]


def test_changed_parent_before_preview_conflicts_with_historical_inheritance(snorca):
    selection, parent = inherited_selection(snorca, "set")
    path = snorca.data_dir / parent.file
    data = json.loads(path.read_text(encoding="utf-8"))
    data["filament_density"] = ["1.4"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert preview(snorca, selection)["blocked"] == "parent_basis_changed"


def test_explicit_materialized_result_still_publishes_independent_root(snorca):
    selection, _ = inherited_selection(snorca, "set")
    state = profile_history.get_state(snorca.id, selection["state_id"])
    doc = profile_history.get_revision(snorca.id, next(iter(state["profiles"].values())))["document"]
    doc.update(own=doc["effective"], inherits="", inherited={}, inherited_origins={}, inherited_unknown={})
    rid = profile_history.save_revision(snorca.id, doc, [], {"source": "merge"})
    selection["state_id"] = profile_history.save_state(snorca.id, {doc["id"]: rid}, [], "materialized merge")
    made = preview(snorca, selection)
    assert made["blocked"] is None
    operations.apply(snorca.id, made["id"])
    target = snorca.data_dir / "user/default/filament/Mein PLA.json"
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result["inherits"] == ""
    assert result["filament_density"] == doc["effective"]["filament_density"]
    assert result["nozzle_temperature"] == ["220"]


def test_selected_parent_change_cannot_silently_change_selected_child(snorca):
    folder = snorca.data_dir / "user/default/filament"
    (folder / "base").mkdir(exist_ok=True)
    (folder / "base/Own Parent.json").write_text(json.dumps({"name": "Own Parent", "version": "2.4.0", "inherits": "", "from": "User", "filament_density": ["1.2"]}), encoding="utf-8")
    child_path = folder / "Mein PLA.json"
    child_data = json.loads(child_path.read_text(encoding="utf-8"))
    child_data["inherits"] = "Own Parent"
    child_path.write_text(json.dumps(child_data), encoding="utf-8")
    scan = scanner.scan(snorca.data_dir, snorca.slicer)
    resolver = Resolver(scan)
    catalog = load_catalog(snorca.slicer, snorca.version)
    from orcaone.profile_observe import identity_for
    revisions = {}
    for name, key, value in [("Own Parent", "filament_density", ["1.4"]), ("Mein PLA", "nozzle_temperature", ["220"])]:
        profile = next(p for p in scan.own if p.name == name)
        pid = identity_for(snorca.id, "default", "filament", profile.file, name)
        doc = make_document(pid, profile, resolver, catalog)
        doc["context"]["user_folder"] = "default"
        edited = apply_patches({pid: doc}, [{"profile_id": pid, "op": "set", "key": key, "value": value}], {catalog["id"]: catalog})
        assert edited["issues"] == []
        revisions[pid] = profile_history.save_revision(snorca.id, edited["documents"][pid], [], {})
    sid = profile_history.save_state(snorca.id, revisions, [], "parent and child")
    made = preview(snorca, {"state_id": sid, "selected": list(revisions)})
    assert made["blocked"] == "parent_basis_changed"

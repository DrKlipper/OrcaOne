import json

import pytest

from orcaone import operations, profile_history, profile_publish, scanner
from orcaone.profile_edit import make_document
from orcaone.profile_observe import identity_for, identity_at
from orcaone.profile_schema import load_catalog
from orcaone.resolver import Resolver
from test_operations import isolated, snorca, edit_conf, conf_of
from test_profile_publish import preview


def renamed(instance, old="Mein PLA", new="Renamed PLA", kind="filament"):
    scan = scanner.scan(instance.data_dir, instance.slicer)
    source = next(p for p in scan.own if p.name == old and p.kind == kind)
    pid = identity_for(instance.id, scan.active_folder, kind, source.file, old)
    doc = make_document(pid, source, Resolver(scan), load_catalog(instance.slicer, instance.version))
    doc["context"]["user_folder"] = scan.active_folder
    doc.update(name=new, rename_from=old)
    rid = profile_history.save_revision(instance.id, doc, [], {})
    sid = profile_history.save_state(instance.id, {pid: rid}, [], "rename")
    return {"state_id": sid, "selected": [pid]}, source.file


def test_publish_rename_moves_files_identity_and_conf_and_replays(snorca):
    edit_conf(snorca, lambda conf: conf.update(presets={"filament": "Mein PLA"}))
    selection, old = renamed(snorca)
    made = preview(snorca, selection)
    assert made["blocked"] is None, made
    result = operations.apply(snorca.id, made["id"])
    new = old.replace("Mein PLA", "Renamed PLA")
    assert not (snorca.data_dir / old).exists()
    assert (snorca.data_dir / new).exists()
    assert conf_of(snorca)["presets"]["filament"] == "Renamed PLA"
    assert identity_at(snorca.id, "default", "filament", new) == selection["selected"][0]
    assert profile_publish.recover_receipt(snorca, result["receipt_id"])["state"] == "verified"
    assert preview(snorca, selection)["blocked"] is None


def test_rename_failure_rolls_back_both_paths(snorca, monkeypatch):
    selection, old = renamed(snorca)
    original = (snorca.data_dir / old).read_bytes()
    made = preview(snorca, selection)
    monkeypatch.setattr(profile_publish, "_loaded", lambda *args: False)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.params["rolled_back"]
    assert (snorca.data_dir / old).read_bytes() == original
    assert not (snorca.data_dir / old.replace("Mein PLA", "Renamed PLA")).exists()


def test_failed_write_after_physical_rename_restores_source(snorca, monkeypatch):
    selection, old = renamed(snorca)
    original = (snorca.data_dir / old).read_bytes()
    made = preview(snorca, selection)
    write = operations.write_atomic
    calls = 0
    def fail_once(path, content):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated disk error")
        return write(path, content)
    monkeypatch.setattr(operations, "write_atomic", fail_once)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, made["id"])
    assert exc.value.params["rolled_back"]
    assert (snorca.data_dir / old).read_bytes() == original
    assert not (snorca.data_dir / old.replace("Mein PLA", "Renamed PLA")).exists()


def test_rename_requires_all_referencing_own_profiles(snorca):
    source = snorca.data_dir / "user/default/filament/Child.json"
    source.write_text(json.dumps({"name": "Child", "inherits": "Mein PLA", "from": "User"}), encoding="utf-8")
    selection, _ = renamed(snorca)
    assert preview(snorca, selection)["blocked"] == "references_outside_selection"


def test_case_only_rename_is_explicitly_blocked(snorca):
    selection, _ = renamed(snorca, new="mein pla")
    assert preview(snorca, selection)["blocked"] == "name_taken"


def test_machine_rename_keeps_live_secret_and_updates_group_labels(snorca):
    from orcaone.profile_groups import save_group, list_groups
    target = snorca.data_dir / "user/default/machine/Mein U1.json"
    data = json.loads(target.read_text())
    data.update(printhost_apikey="live-secret", print_host="192.0.2.20", default_print_profile="", default_filament_profile=[])
    target.write_text(json.dumps(data), encoding="utf-8")
    save_group(snorca.id, "existing", ["Mein U1"], "Printer", {"Mein U1": "Standard"}, user_folder="default")
    selection, old = renamed(snorca, "Mein U1", "Renamed U1", "machine")
    made = preview(snorca, selection)
    assert made["blocked"] is None, made
    result = operations.apply(snorca.id, made["id"])
    data = json.loads((snorca.data_dir / old.replace("Mein U1", "Renamed U1")).read_text())
    assert data["printhost_apikey"] == "live-secret"
    assert data["print_host"] == "192.0.2.20"
    group = list_groups(snorca.id, "default")[0]
    assert group["names"] == ["Renamed U1"]
    assert group["labels"] == {"Renamed U1": "Standard"}
    assert profile_publish.recover_receipt(snorca, result["receipt_id"])["state"] == "verified"


def test_workbench_snapshot_stays_bound_before_first_publish(snorca):
    from orcaone.profile_store import put_object
    selection, _ = renamed(snorca)
    state = profile_history.get_state(snorca.id, selection["state_id"])
    doc = profile_history.get_revision(snorca.id, next(iter(state["profiles"].values())))["document"]
    preview_id = put_object(snorca.id, {"type": "composer_preview", "expected": profile_publish.current_target(snorca)})
    doc["workbench"] = {"preview_id": preview_id, "required_profile_ids": [doc["id"]]}
    rid = profile_history.save_revision(snorca.id, doc, [], {})
    selection["state_id"] = profile_history.save_state(snorca.id, {doc["id"]: rid}, [], "workbench")
    edit_conf(snorca, lambda conf: conf.update(unrelated="changed"))
    assert preview(snorca, selection)["blocked"] == "plan_outdated"


def test_group_move_releases_previous_membership_and_replays(snorca):
    from orcaone.profile_groups import save_group, list_groups
    save_group(snorca.id, "old", ["A", "B"], "Old", user_folder="default")
    for _ in range(2):
        save_group(snorca.id, "new", ["C"], "New", moved_names=["A"], user_folder="default")
    groups = {group["id"]: group["names"] for group in list_groups(snorca.id, "default")}
    assert groups == {"old": ["B"], "new": ["C"]}


@pytest.mark.parametrize("extend_parent", [False, True])
def test_composer_publish_machine_process_child_and_new_nozzle(snorca, extend_parent):
    from orcaone.profile_composer import prepare_preview, create_branch
    from test_profile_composer import configuration
    from test_profile_printer_merge import add_process
    body = configuration(snorca)
    body["variants"].append({"key": "new", "source_name": "Voron 1", "name": "New nozzle",
                              "mode": "copy", "nozzle_diameter": ["0.6"]})
    add_process(snorca, "Fine", ["Voron 1"])
    add_process(snorca, "Child", ["Voron 1"])
    child = snorca.data_dir / "user/default/process/base/Child.json"
    data = json.loads(child.read_text())
    data["inherits"] = "Fine"
    child.unlink()
    child = child.parent.parent / "Child.json"
    child.write_text(json.dumps(data), encoding="utf-8")
    body["assignments"] = [{"kind": "process", "source_name": "Fine", "name": "Renamed Fine",
                             "action": "rename", "targets": ["0", "new"] if extend_parent else ["0"]}]
    result = prepare_preview(snorca, body)
    branch = create_branch(snorca, result["preview_id"])
    made = preview(snorca, {"state_id": branch["state"], "selected": branch["selected"]})
    assert made["blocked"] is None, made
    applied = operations.apply(snorca.id, made["id"])
    assert applied["receipt_state"] == "verified"
    assert json.loads(child.read_text())["inherits"] == ("" if extend_parent else "Renamed Fine")
    assert json.loads(child.read_text())["compatible_printers"] == ["Target 1"]
    machine = snorca.data_dir / "user/default/machine/base"
    assert not (machine / "Voron 1.json").exists()
    assert json.loads((machine / "Target 1.json").read_text())["printhost_apikey"] == "credential-0"
    assert json.loads((machine / "New nozzle.json").read_text())["printhost_apikey"] == "credential-0"

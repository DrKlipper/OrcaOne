from copy import deepcopy
import json

import pytest

from orcaone import operations, profile_history, scanner
from orcaone.profile_edit import make_document
from orcaone.profile_printer_merge import build_merge, prepare_preview, create_merge_branch
from orcaone.profile_schema import load_catalog
from orcaone.resolver import Resolver
from test_operations import isolated, snorca


def machines(instance, count=4):
    folder = instance.data_dir / "user/default/machine/base"
    folder.mkdir(exist_ok=True)
    for index in range(count):
        name = f"Voron {index + 1}"
        (folder / f"{name}.json").write_text(json.dumps({"name": name, "inherits": "", "version": "2.4.0", "from": "User",
            "printer_model": f"Old model {index}", "nozzle_diameter": ["0.4"], "machine_start_gcode": f"; unique {index}",
            "print_host": f"192.0.2.{index + 1}", "printhost_apikey": f"credential-{index}"}), encoding="utf-8")
    return {"profiles": [{"kind": "machine", "name": f"Voron {index + 1}"} for index in range(count)],
            "group_name": "My Voron", "target_model": "Voron unified",
            "variants": [{"name": f"Voron {index + 1}", "label": f"Variant {index + 1}", "nozzle_diameter": ["0.4"]} for index in range(count)]}


def test_preview_has_no_three_printer_limit_and_preserves_individual_values(snorca):
    body = machines(snorca)
    before = operations._tree_snapshot(snorca)
    result = prepare_preview(snorca, body)
    assert result["issues"] == []
    assert len(result["documents"]) == 4
    assert result["preview_id"]
    for index, document in enumerate(result["documents"].values()):
        assert document["name"] == f"Voron {index + 1}"
        assert document["effective"]["printer_model"] == "Voron unified"
        assert document["effective"]["machine_start_gcode"] == f"; unique {index}"
        assert document["inherits"] == ""
        assert document["own"] == document["effective"]
    assert "credential-" not in json.dumps(result)
    assert operations._tree_snapshot(snorca) == before


@pytest.mark.parametrize("mutation,code", [
    (lambda body: body.update(profiles=body["profiles"][:1]), "invalid_scope"),
    (lambda body: body["variants"][1].update(label=body["variants"][0]["label"]), "variant_label_duplicate"),
    (lambda body: body["variants"][0].update(nozzle_diameter=["1_0"]), "invalid_nozzle"),
])
def test_invalid_merge_cannot_produce_preview(snorca, mutation, code):
    body = machines(snorca, 2)
    mutation(body)
    with pytest.raises(operations.OperationError) as exc:
        prepare_preview(snorca, body)
    assert exc.value.code == code


def test_preview_is_bound_to_live_fingerprint_and_server_documents(snorca):
    result = prepare_preview(snorca, machines(snorca, 2))
    path = snorca.data_dir / "user/default/machine/base/Voron 1.json"
    path.write_text(path.read_text() + "\n", encoding="utf-8")
    with pytest.raises(operations.OperationError) as exc:
        create_merge_branch(snorca, result["preview_id"], "Merge")
    assert exc.value.code == "plan_outdated"
    assert profile_history.list_branches(snorca.id) == []


def test_group_registers_only_after_complete_verified_publication(snorca):
    from orcaone.profile_groups import list_groups
    from orcaone.profile_publish import current_target, prepare_changes
    preview = prepare_preview(snorca, machines(snorca, 2))
    branch = create_merge_branch(snorca, preview["preview_id"], "Merge")
    assert list_groups(snorca.id, user_folder="default") == []
    changes = prepare_changes(snorca, {"state_id": branch["state"], "selected": branch["selected"][:1]}, current_target(snorca))
    assert operations.make_plan(snorca, [], changes)["blocked"] == "printer_group_incomplete"
    changes = prepare_changes(snorca, {"state_id": branch["state"], "selected": branch["selected"]}, current_target(snorca))
    plan = operations.make_plan(snorca, [], changes)
    assert plan["blocked"] is None
    result = operations.apply(snorca.id, plan["id"])
    assert result["receipt_state"] == "verified"
    assert list_groups(snorca.id, user_folder="default")[0]["names"] == ["Voron 1", "Voron 2"]
    for index in range(2):
        data = json.loads((snorca.data_dir / f"user/default/machine/base/Voron {index + 1}.json").read_text())
        assert data["printer_model"] == "Voron unified"
        assert data["print_host"] == f"192.0.2.{index + 1}"
        assert data["printhost_apikey"] == f"credential-{index}"


def add_process(instance, name, printers=None):
    folder = instance.data_dir / "user/default/process/base"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"name": name, "inherits": "", "version": "2.4.0", "from": "User",
        "compatible_printers": printers or [], "layer_height": "0.18"}), encoding="utf-8")


def test_process_choices_share_copy_leave_and_no_implicit_profile_expansion(snorca):
    body = machines(snorca, 2)
    add_process(snorca, "Shared", ["Mein U1"])
    add_process(snorca, "Copied")
    add_process(snorca, "Untouched")
    before = (snorca.data_dir / "user/default/process/base/Untouched.json").read_bytes()
    body["process_choices"] = [{"name": "Shared", "action": "share", "targets": ["Voron 1", "Voron 2"]},
                               {"name": "Copied", "action": "copy", "targets": ["Voron 2"], "copy_name": "Copy for Voron"},
                               {"name": "Untouched", "action": "leave"}]
    result = prepare_preview(snorca, body)
    docs = {doc["name"]: doc for doc in result["documents"].values()}
    assert set(docs) == {"Voron 1", "Voron 2", "Shared", "Copy for Voron"}
    assert docs["Shared"]["effective"]["compatible_printers"] == ["Mein U1", "Voron 1", "Voron 2"]
    assert docs["Copy for Voron"]["effective"]["compatible_printers"] == ["Voron 2"]
    assert docs["Copy for Voron"]["inherits"] == ""
    assert docs["Copy for Voron"]["effective"]["layer_height"] == "0.18"
    assert {c["name"] for c in result["process_candidates"]}.issuperset({"Shared", "Copied", "Untouched"})
    assert (snorca.data_dir / "user/default/process/base/Untouched.json").read_bytes() == before


def test_share_does_not_narrow_previously_unrestricted_process(snorca):
    body = machines(snorca, 2)
    add_process(snorca, "Anywhere")
    body["process_choices"] = [{"name": "Anywhere", "action": "share", "targets": ["Voron 1"]}]
    result = prepare_preview(snorca, body)
    doc = next(doc for doc in result["documents"].values() if doc["name"] == "Anywhere")
    assert doc["effective"]["compatible_printers"] == []


def test_group_failure_never_registers_and_verified_recovery_replays_registry(snorca, monkeypatch):
    from orcaone import profile_publish, profile_groups
    body = machines(snorca, 2)
    result = prepare_preview(snorca, body)
    branch = create_merge_branch(snorca, result["preview_id"])
    changes = profile_publish.prepare_changes(snorca, {"state_id": branch["state"], "selected": branch["selected"]}, profile_publish.current_target(snorca))
    plan = operations.make_plan(snorca, [], changes)
    original = profile_groups.save_group
    def disk_full(*args, **kwargs):
        raise OSError("settings unavailable")
    monkeypatch.setattr(profile_groups, "save_group", disk_full)
    with pytest.raises(operations.OperationError) as exc:
        operations.apply(snorca.id, plan["id"])
    assert exc.value.params["receipt_state"] == "needs_review"
    assert profile_groups.list_groups(snorca.id, user_folder="default") == []
    monkeypatch.setattr(profile_groups, "save_group", original)
    receipt = profile_publish.recover_receipt(snorca, exc.value.params["receipt_id"])
    assert receipt["state"] == "verified"
    assert profile_groups.list_groups(snorca.id, user_folder="default")[0]["id"] == result["group"]["id"]


def test_changed_source_after_branch_blocks_first_group_publication(snorca):
    from orcaone.profile_publish import current_target, prepare_changes
    result = prepare_preview(snorca, machines(snorca, 2))
    branch = create_merge_branch(snorca, result["preview_id"])
    path = snorca.data_dir / "user/default/machine/base/Voron 1.json"
    data = json.loads(path.read_text())
    data["machine_start_gcode"] = "; edited after merging"
    path.write_text(json.dumps(data), encoding="utf-8")
    plan = operations.make_plan(snorca, [], prepare_changes(snorca, {"state_id": branch["state"], "selected": branch["selected"]}, current_target(snorca)))
    assert plan["blocked"] == "plan_outdated"


def test_materialized_machine_keeps_current_inherited_connection(snorca):
    from orcaone.profile_publish import current_target, prepare_changes
    body = machines(snorca, 2)
    folder = snorca.data_dir / "user/default/machine"
    source = json.loads((folder / "base/Voron 1.json").read_text())
    source.update(name="Connection Parent")
    (folder / "base/Connection Parent.json").write_text(json.dumps(source), encoding="utf-8")
    child = json.loads((folder / "base/Voron 1.json").read_text())
    child.pop("print_host")
    child.pop("printhost_apikey")
    child["inherits"] = "Connection Parent"
    (folder / "base/Voron 1.json").unlink()
    (folder / "Voron 1.json").write_text(json.dumps(child), encoding="utf-8")
    preview = prepare_preview(snorca, body)
    assert "credential-" not in json.dumps(preview)
    branch = create_merge_branch(snorca, preview["preview_id"])
    plan = operations.make_plan(snorca, [], prepare_changes(snorca, {"state_id": branch["state"], "selected": branch["selected"]}, current_target(snorca)))
    assert plan["blocked"] is None
    operations.apply(snorca.id, plan["id"])
    result = json.loads((folder / "Voron 1.json").read_text())
    assert result["inherits"] == ""
    assert result["print_host"] == "192.0.2.1"
    assert result["printhost_apikey"] == "credential-0"

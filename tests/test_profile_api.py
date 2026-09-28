import json

import pytest

from conftest import call, copy_fixture
from orcaone import profile_history as history


@pytest.fixture
def editor(server, fake_home):
    copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    instance = json.loads(call(server + "/api/instances")[1])["instances"][0]
    return instance["id"], server + f"/api/instances/{instance['id']}/profile-editor"


def seed(instance):
    document = {"id": "a" * 32, "kind": "process", "name": "Trial",
                "schema_id": "Snapmaker_Orca@2.4.0", "own": {"layer_height": "0.2"},
                "effective": {"layer_height": "0.2"}, "inherited": {}, "origins": {},
                "unknown": {}, "context": {}, "references": [], "complete": True}
    revision = history.save_revision(instance, document, [], {})
    state = history.save_state(instance, {document["id"]: revision}, [], "Initial")
    return document, state


def test_unknown_instance_never_creates_history(server, data_dir):
    status, _ = call(server + "/api/instances/does-not-exist/profile-editor/branches",
                     "POST", {"name": "Trial", "selected": []})
    assert status == 404
    assert not (data_dir / "snapshots" / "profiles").exists()


def test_branch_has_explicit_scope_and_can_be_read(editor):
    instance, url = editor
    document, state = seed(instance)
    status, body = call(url + "/branches", "POST",
                        {"name": "Trial", "state_id": state, "selected": [document["id"]]})
    assert status == 200
    branch = json.loads(body)
    assert branch["selected"] == [document["id"]]
    status, body = call(url + "/branches/" + branch["id"])
    assert status == 200
    assert json.loads(body)["documents"][document["id"]]["name"] == "Trial"


def test_foreign_state_and_excessive_scope_rejected(editor):
    instance, url = editor
    document, state = seed("b" * 12)
    assert call(url + "/branches", "POST", {"name": "Trial", "state_id": state,
                "selected": [document["id"]]})[0] == 404
    assert call(url + "/branches", "POST", {"name": "Trial", "state_id": state,
                "selected": ["a" * 32] * 201})[0] == 400


def test_invalid_history_cursor_rejected(editor):
    _, url = editor
    assert call(url + "/history?cursor=not-a-cursor")[0] == 400


def test_two_clients_cannot_overwrite_a_draft(editor, monkeypatch):
    from orcaone import profile_api
    instance, url = editor
    document, state = seed(instance)
    branch = history.create_branch(instance, "Trial", state, [document["id"]])
    monkeypatch.setattr(profile_api, "_patched", lambda inst, body: {
        "documents": {document["id"]: document}, "issues": [], "branch_generation": branch["generation"]})
    endpoint = url + "/drafts/" + branch["id"]
    assert call(endpoint, "PUT", {"expected_generation": 0, "patches": []})[0] == 200
    status, body = call(endpoint, "PUT", {"expected_generation": 0, "patches": []})
    assert status == 409 and json.loads(body)["error"] == "draft_conflict"
    assert history.get_draft(instance, branch["id"])["generation"] == 1


def test_diff_does_not_expose_secret_values(editor):
    instance, url = editor
    document, before = seed(instance)
    document["effective"]["printhost_apikey"] = "never-expose-this"
    document["effective"]["layer_height"] = "0.3"
    revision = history.save_revision(instance, document, [], {})
    after = history.save_state(instance, {document["id"]: revision}, [], "")
    status, body = call(url + "/diff", "POST", {"before": before, "after": after,
                                               "selected": [document["id"]]})
    assert status == 200
    assert b"never-expose-this" not in body and b"apikey" not in body
    assert b"layer_height" in body


def test_real_catalog_document_and_local_patch_never_write_slicer(editor, fake_home):
    instance, url = editor
    folder = fake_home / ".config" / "Snapmaker_Orca"
    own = folder / "user" / "default" / "process" / "Editor Test.json"
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text(json.dumps({"name": "Editor Test", "from": "User", "version": "2.4.0.0",
                              "inherits": "", "layer_height": "0.2"}), encoding="utf-8")
    before = {str(p): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    status, body = call(url + "/branches", "POST", {"name": "Local test",
        "profiles": [{"kind": "process", "name": "Editor Test"}]})
    assert status == 200, body
    branch = json.loads(body)
    profile_id = branch["selected"][0]
    status, body = call(url + "/drafts/" + branch["id"], "PUT", {"expected_generation": 0,
        "patches": [{"profile_id": profile_id, "key": "layer_height", "op": "set", "value": "0.25"}]})
    assert status == 200 and json.loads(body)["saved"], body
    assert json.loads(body)["documents"][profile_id]["effective"]["layer_height"] == "0.25"
    result = json.loads(body)
    status, body = call(url + "/states", "POST", {"branch_id": branch["id"], "selected": [profile_id],
        "expected_generation": result["generation"], "expected_branch_generation": branch["generation"], "note": "Quality"})
    assert status == 200, body
    assert {str(p): p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before
    committed = json.loads(body)["branch"]
    status, body = call(url + "/publish-preview", "POST", {"branch_id": branch["id"],
        "state_id": committed["state"], "selected": [profile_id]})
    assert status == 200, body
    plan = json.loads(body)
    assert not plan["blocked"], body
    assert {str(p): p.read_bytes() for p in folder.rglob("*") if p.is_file()} == before
    status, body = call(url.removesuffix("/profile-editor") + "/apply", "POST", {"plan_id": plan["id"]})
    assert status == 200, body
    assert json.loads(body)["receipt_state"] == "verified"
    assert json.loads(own.read_text(encoding="utf-8"))["layer_height"] == "0.25"


def test_nozzle_variant_copies_only_explicit_related_profile(editor, fake_home):
    instance, url = editor
    folder = fake_home / ".config" / "Snapmaker_Orca" / "user" / "default"
    for kind, name, values in [("machine", "Variant source", {"printer_model": "Custom", "nozzle_diameter": ["0.4"]}),
                               ("process", "Process source", {"layer_height": "0.2", "compatible_printers": ["Variant source"]})]:
        (folder / kind).mkdir(parents=True, exist_ok=True)
        (folder / kind / (name + ".json")).write_text(json.dumps({"name": name, "from": "User", "version": "2.4.0.0", "inherits": "", **values}), encoding="utf-8")
    status, body = call(url + "/branches", "POST", {"name": "Source", "profiles": [
        {"kind": "machine", "name": "Variant source"}, {"kind": "process", "name": "Process source"}]})
    assert status == 200, body
    branch = json.loads(body)
    documents = json.loads(call(url + "/branches/" + branch["id"])[1])["documents"]
    machine = next(d["id"] for d in documents.values() if d["kind"] == "machine")
    process = next(d["id"] for d in documents.values() if d["kind"] == "process")
    payload = {"name": "Nozzle 0.5", "branch_id": branch["id"],
        "profile_id": machine, "target_model": "Same printer", "configuration": {"copy": True,
        "name": "Nozzle 0.5", "nozzle_diameter": ["0.5"]}, "choices": {process: "copy"},
        "copy_names": {process: "Process 0.5"}}
    status, body = call(url + "/variant-preview", "POST", payload)
    assert status == 200, body
    payload["basis"] = json.loads(body)["basis"]
    status, body = call(url + "/variant-branch", "POST", payload)
    assert status == 200 and json.loads(body)["created"], body
    target = json.loads(body)["branch"]
    docs = json.loads(call(url + "/branches/" + target["id"])[1])["documents"]
    assert {d["name"] for d in docs.values()} == {"Nozzle 0.5", "Process 0.5"}
    assert next(d for d in docs.values() if d["kind"] == "process")["effective"]["compatible_printers"] == ["Nozzle 0.5"]
    assert set(docs).isdisjoint(documents)


def test_whole_restore_keeps_unselected_profile_and_requires_current_branch(editor):
    instance, url = editor
    document, historical = seed(instance)
    other = {**document, "id": "b" * 32, "name": "Unselected"}
    other_revision = history.save_revision(instance, other, [], {})
    document["name"] = "Renamed locally"
    current_revision = history.save_revision(instance, document, [], {})
    state = history.save_state(instance, {document["id"]: current_revision, other["id"]: other_revision}, [], "")
    branch = history.create_branch(instance, "Restore", state, [document["id"], other["id"]])
    payload = {"branch_id": branch["id"], "source_state": historical, "selected": [document["id"]]}
    status, body = call(url + "/restore-state-preview", "POST", payload)
    assert status == 200 and json.loads(body)["changes"][0]["after"]["name"] == "Trial"
    payload["expected_branch_generation"] = json.loads(body)["branch_generation"]
    status, body = call(url + "/restore-state", "POST", payload)
    assert status == 200, body
    restored = json.loads(body)["branch"]
    assert restored["profiles"][other["id"]] == other_revision
    assert history.get_revision(instance, restored["profiles"][document["id"]])["document"]["name"] == "Trial"
    assert call(url + "/restore-state", "POST", payload)[0] == 409


def test_first_draft_save_rejects_branch_advance_after_patch_read(editor, monkeypatch):
    from orcaone import profile_api
    from orcaone.profile_store import replace_ref
    instance, url = editor
    document, state = seed(instance)
    branch = history.create_branch(instance, "Trial", state, [document["id"]])
    later_document = {**document, "effective": {"layer_height": "0.3"}}
    later_revision = history.save_revision(instance, later_document, [branch["profiles"][document["id"]]], {})
    later_state = history.save_state(instance, {document["id"]: later_revision}, [], "concurrent restore")
    def race(inst, body):
        result = {"documents": {document["id"]: document}, "issues": [], "branch_generation": branch["generation"]}
        changed = {key: item for key, item in branch.items() if key != "generation"}
        changed.update(state=later_state, profiles={document["id"]: later_revision})
        replace_ref(instance, branch["id"], branch["generation"], changed)
        return result
    monkeypatch.setattr(profile_api, "_patched", race)
    status, body = call(url + "/drafts/" + branch["id"], "PUT",
                        {"expected_generation": 0, "selected": [document["id"]], "patches": []})
    assert status == 409 and json.loads(body)["error"] == "branch_conflict"
    assert history.get_draft(instance, branch["id"]) is None
    assert history.get_branch(instance, branch["id"])["state"] == later_state

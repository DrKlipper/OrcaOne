import json

from conftest import call, copy_fixture
from orcaone import profile_history as history
from orcaone.profile_normalize import resolve_values
from orcaone.profile_schema import load_catalog


def test_cross_slicer_copy_requires_each_reported_loss(server, fake_home):
    copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    orca = copy_fixture("orca", fake_home / ".config" / "OrcaSlicer")
    # Controlled version fixture for API integration, not a claimed native roundtrip.
    from orcaone.conf import parse_conf, dump_conf
    conf = parse_conf((orca / "OrcaSlicer.conf").read_bytes())
    conf.data["header"] = "OrcaSlicer 2.4.2"
    (orca / "OrcaSlicer.conf").write_bytes(dump_conf(conf))
    rows = json.loads(call(server + "/api/instances")[1])["instances"]
    source = next(i for i in rows if i["version"] == "2.4.0")
    target = next(i for i in rows if i["version"] == "2.4.2")
    catalog = load_catalog("Snapmaker_Orca", "2.4.0")
    resolved = resolve_values(catalog, "process", [{"id": "a" * 32, "values": {"outer_wall_speed": ["100", "200"]}}], {"chain_complete": True})
    doc = {"id": "a" * 32, "name": "Source", "kind": "process", "schema_id": catalog["id"],
           "own": {}, "effective": resolved["values"], "context": resolved["context"], "complete": True,
           "unknown": {}, "origins": resolved["origins"], "inherited": {}, "references": []}
    revision = history.save_revision(source["id"], doc, [], {})
    state = history.save_state(source["id"], {doc["id"]: revision}, [], "")
    branch = history.create_branch(source["id"], "Source", state, [doc["id"]])
    url = server + f"/api/instances/{target['id']}/profile-editor"
    status, body = call(url + "/conversion-preview", "POST", {"source_instance_id": source["id"],
        "source_branch_id": branch["id"], "selected": [doc["id"]], "names": {doc["id"]: "Copied process"}})
    assert status == 200, body
    preview = json.loads(body)
    assert any(loss["code"] == "vector_truncated" for loss in preview["profiles"][doc["id"]]["losses"])
    status, body = call(url + "/conversion-branch", "POST", {"preview_id": preview["id"], "name": "Transferred",
        "confirmed_losses": {doc["id"]: []}})
    assert status == 409, body
    assert history.list_branches(target["id"]) == []
    losses = {pid: [loss["id"] for loss in report["losses"]] for pid, report in preview["profiles"].items()}
    status, body = call(url + "/conversion-branch", "POST", {"preview_id": preview["id"], "name": "Transferred",
        "confirmed_losses": losses})
    assert status == 200, (body, {pid: r["issues"] for pid, r in preview["profiles"].items()})
    transferred = json.loads(body)["branch"]
    assert len(transferred["selected"]) == 1
    copied_revision = history.get_revision(target["id"], next(iter(transferred["profiles"].values())))
    assert copied_revision["parents"] == []
    assert copied_revision["document"]["effective"]["outer_wall_speed"] == "100"
    assert copied_revision["document"]["id"] != doc["id"]

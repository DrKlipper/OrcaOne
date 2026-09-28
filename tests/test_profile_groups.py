"""Explicit local machine grouping; synthetic own profiles only."""

import json

import pytest

from conftest import BUNDLE, add_bundle, copy_fixture
from orcaone import instances, overview, profile_groups, settings


def test_persistence_is_explicit_ordered_isolated_and_idempotent(data_dir):
    settings.change(lambda data: data.update(language="de", printers={"existing": {"host": "fixture"}}))
    names = ["Fourth", "Second", "First", "Third"]
    labels = {"First": "Standard", "Second": "High flow"}
    expected = {"id": "group-1", "names": names, "display_name": "My printer", "labels": labels}
    assert profile_groups.validate_group("instance-a", "group-1", names, "My printer", labels) == expected
    assert "machine_groups" not in settings.load()
    assert profile_groups.save_group("instance-a", "group-1", names, "My printer", labels) == expected
    first = settings._file().read_bytes()
    profile_groups.save_group("instance-a", "group-1", names, "My printer", labels)
    assert settings._file().read_bytes() == first
    assert profile_groups.list_groups("instance-a") == [expected]
    assert profile_groups.list_groups("instance-b") == []
    assert settings.load()["language"] == "de"
    assert settings.load()["printers"] == {"existing": {"host": "fixture"}}
    assert set(settings.load()["machine_groups"]["instance-a"]["group-1"]) == {"names", "display_name", "labels"}


def test_conflicting_members_and_non_metadata_are_rejected_without_write(data_dir):
    profile_groups.save_group("instance", "first", ["A", "B"], "Printer")
    before = settings._file().read_bytes()
    for action in (profile_groups.validate_group, profile_groups.save_group):
        with pytest.raises(profile_groups.ProfileGroupError, match="group_member_conflict"):
            action("instance", "other", ["B", "C"], "Other")
        with pytest.raises(profile_groups.ProfileGroupError, match="invalid_group"):
            action("instance", "other", [{"name": "X", "password": "synthetic-secret"}, "Y"], "Other")
        with pytest.raises(profile_groups.ProfileGroupError, match="invalid_group"):
            action("instance", "other", ["X", "Y"], "Other", {"X": {"password": "synthetic-secret"}})
    assert settings._file().read_bytes() == before
    assert "synthetic-secret" not in settings._file().read_text(encoding="utf-8")


@pytest.fixture
def machines(tmp_path, fake_home):
    folder = copy_fixture("snorca", tmp_path / "slicer")
    names = ["Alpha 0.2 named", "Bravo 0.8 named", "Charlie", "Delta"]
    for index, name in enumerate(names):
        data = {"name": name, "from": "User", "inherits": "Snapmaker U1 (0.4 nozzle)",
                "version": "2.3.3.3", "nozzle_diameter": ["0.5" if index < 2 else "0.6"],
                "printer_variant": "0.4", "print_host": "synthetic-host", "printhost_apikey": "synthetic-secret"}
        (folder / "user" / "default" / "machine" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return instances.load_instance(folder.resolve(), "manual"), names


@pytest.mark.parametrize("count", [2, 4])
def test_group_selected_own_presets_only_and_preserve_variant_links(machines, count):
    instance, names = machines
    baseline = overview.build_instance(instance, [])
    assert len([m for m in baseline["models"] if m.get("own")]) == 5
    selected = list(reversed(names[:count]))
    profile_groups.save_group(instance.id, "chosen", selected, "Workshop printer", {selected[0]: "High flow"}, user_folder=instance.active_user_folder)
    grouped = overview.build_instance(instance, [])
    group = next(m for m in grouped["models"] if m.get("group_id") == "chosen")
    assert group["model"] == "group:chosen" and group["display_name"] == "Workshop printer"
    assert [p["name"] for p in group["printers"]] == selected
    assert group["printers"][0]["label"] == "High flow"
    assert [m for m in grouped["models"] if not m.get("own")] == [m for m in baseline["models"] if not m.get("own")]
    independent = [m["model"] for m in grouped["models"] if m.get("own") and not m.get("group_id")]
    assert set(independent) == {"Mein U1", *names[count:]}
    assert all(p["variant"] == "0.5" and p["nozzle"] == ["0.5"] for p in group["printers"] if p["name"] in names[:2])
    assert grouped["stats"]["per_printer"] == baseline["stats"]["per_printer"]
    assert grouped["filaments"] == baseline["filaments"]
    assert grouped["processes"] == baseline["processes"]
    assert "synthetic-secret" not in settings._file().read_text(encoding="utf-8")
    assert "synthetic-host" not in json.dumps(group)


def test_missing_and_ambiguous_members_are_ignored(machines):
    instance, names = machines
    profile_groups.save_group(instance.id, "chosen", names[:2] + ["Missing"], "Workshop printer", user_folder=instance.active_user_folder)
    # A second own preset with the same name makes membership ambiguous, even if only one loads.
    path = instance.data_dir / "user" / "default" / "machine"
    body = json.loads((path / f"{names[0]}.json").read_text(encoding="utf-8"))
    (path / "duplicate.json").write_text(json.dumps(body), encoding="utf-8")
    result = overview.build_instance(instance, [])
    group = next(m for m in result["models"] if m.get("group_id") == "chosen")
    assert [p["name"] for p in group["printers"]] == [names[1]]


def test_reader_discards_unknown_fields_and_conflicting_or_invalid_groups(data_dir):
    settings.change(lambda data: data.update(machine_groups={"i": {
        "one": {"names": ["A", "B"], "display_name": "One", "password": "synthetic-secret"},
        "two": {"names": ["B", "C"], "display_name": "Two"},
        "broken": {"names": "not a list", "display_name": "Broken"},
    }}))
    assert "synthetic-secret" not in json.dumps(profile_groups.list_groups("i"))
    resolved = profile_groups.resolve_groups("i", ["A", "B", "C"])
    assert [(g["id"], g["names"]) for g in resolved] == [("one", ["A"]), ("two", ["C"])]


def test_group_never_claims_system_or_bundle_presets(tmp_path, fake_home):
    folder = copy_fixture("orca", tmp_path / "slicer")
    add_bundle(folder)
    instance = instances.load_instance(folder.resolve(), "manual")
    profile_groups.save_group(instance.id, "invalid-members", [f"{BUNDLE}/Paket U1", "Snapmaker U1 (0.4 nozzle)"], "Not own", user_folder=instance.active_user_folder)
    result = overview.build_instance(instance, [])
    assert not any(m.get("group_id") for m in result["models"])
    assert next(m for m in result["models"] if m["model"] == f"{BUNDLE}/Paket U1")["bundle"] == "Mein Paket"


def test_groups_are_bound_to_active_account(machines):
    instance, names = machines
    profile_groups.save_group(instance.id, "chosen", names[:2], "Account A", user_folder=instance.active_user_folder)
    assert any(m.get("group_id") == "chosen" for m in overview.build_instance(instance, [])["models"])
    # Identical preset names do not authorize membership for another active account.
    instance.active_user_folder = "other-account"
    assert not any(m.get("group_id") for m in overview.build_instance(instance, [])["models"])
    assert profile_groups.list_groups(instance.id, user_folder="other-account") == []
    profile_groups.save_group(instance.id, "other", names[:2], "Account B", user_folder="other-account")
    assert [g["id"] for g in profile_groups.list_groups(instance.id, user_folder="other-account")] == ["other"]
    with pytest.raises(profile_groups.ProfileGroupError, match="group_member_conflict"):
        profile_groups.save_group(instance.id, "chosen", names[:2], "Hijacked", user_folder="other-account")


def test_legacy_unbound_groups_never_apply_to_bound_accounts(machines):
    instance, names = machines
    profile_groups.save_group(instance.id, "legacy", names[:2], "Unbound")
    assert profile_groups.list_groups(instance.id, user_folder=instance.active_user_folder) == []
    assert not any(m.get("group_id") for m in overview.build_instance(instance, [])["models"])

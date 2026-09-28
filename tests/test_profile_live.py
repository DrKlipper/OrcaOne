from conftest import copy_fixture
from orcaone import profile_live, scanner
from orcaone.model import Instance
from orcaone.profile_observe import identity_for


def test_only_explicitly_tracked_profiles_enter_observation(tmp_path):
    folder = copy_fixture("snorca", tmp_path / "Snapmaker_Orca")
    instance = Instance("a" * 12, "Snapmaker_Orca", folder, "manual", "2.4.0")
    assert profile_live.capture(instance) == {"tracked": False}
    scan = scanner.scan(folder, instance.slicer)
    source = next(p for p in scan.own if not p.problem)
    profile_id = identity_for(instance.id, "default", source.kind, str(source.file), source.name)
    result = profile_live.capture(instance)
    assert result["recorded"]
    from orcaone.profile_history import get_state
    assert set(get_state(instance.id, result["state"])["profiles"]) == {profile_id}


def test_changing_scan_is_not_recorded(tmp_path, monkeypatch):
    folder = copy_fixture("snorca", tmp_path / "Snapmaker_Orca")
    instance = Instance("a" * 12, "Snapmaker_Orca", folder, "manual", "2.4.0")
    source = scanner.scan(folder, instance.slicer).own[0]
    identity_for(instance.id, "default", source.kind, str(source.file), source.name)
    count = iter(["before", "after"])
    monkeypatch.setattr(profile_live, "fingerprint", lambda instance: next(count))
    assert profile_live.capture(instance)["unstable"]

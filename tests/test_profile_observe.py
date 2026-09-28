from orcaone.model import Instance
from orcaone.profile_history import create_branch, get_branch, get_draft, save_draft
from orcaone.profile_observe import identity_for, match_identity, observe


INSTANCE = "a" * 12
PROFILE = "b" * 32


def test_identity_uses_folder_kind_path_not_name(data_dir):
    first = identity_for(INSTANCE, "default", "process", "user/default/process/a.json", "A")
    assert identity_for(INSTANCE, "default", "process", "user/default/process/a.json", "B") == first
    assert identity_for(INSTANCE, "account", "process", "user/default/process/a.json", "A") != first
    assert identity_for(INSTANCE, "default", "process", "user/default/process/b.json", "A") != first


def test_observation_deletion_needs_two_stable_scans_and_resets(data_dir, tmp_path):
    inst = Instance(INSTANCE, "OrcaSlicer", tmp_path, "manual")
    docs = {PROFILE: {"id": PROFILE, "effective": {"speed": "10"}}}
    first = observe(inst, docs, "one", True)
    assert first["recorded"]
    assert not observe(inst, docs, "one", True)["recorded"]
    assert not observe(inst, {}, "missing", True)["recorded"]
    assert not observe(inst, {}, "missing", False)["recorded"]
    assert not observe(inst, {}, "missing", True)["recorded"]
    assert not observe(inst, docs, "one", True)["recorded"]
    assert not observe(inst, {}, "missing", True)["recorded"]
    result = observe(inst, {}, "missing", True)
    assert result["recorded"] and result["removed"] == [PROFILE]


def test_observe_does_not_change_branch_or_draft(data_dir, tmp_path):
    inst = Instance(INSTANCE, "OrcaSlicer", tmp_path, "manual")
    doc = {"id": PROFILE, "effective": {"speed": "10"}}
    first = observe(inst, {PROFILE: doc}, "one", True)
    branch = create_branch(INSTANCE, "Trial", first["state"], [PROFILE])
    draft = save_draft(INSTANCE, branch["id"], 0, {PROFILE: doc})
    observe(inst, {PROFILE: {**doc, "effective": {"speed": "30"}}}, "two", True)
    assert get_branch(INSTANCE, branch["id"]) == branch
    assert get_draft(INSTANCE, branch["id"]) == draft


def test_user_folder_observations_are_independent(data_dir, tmp_path):
    inst = Instance(INSTANCE, "OrcaSlicer", tmp_path, "manual")
    first = observe(inst, {PROFILE: {"id": PROFILE}}, "one", True)
    inst.active_user_folder = "other"
    other = observe(inst, {}, "two", True)
    assert other["removed"] == []
    inst.active_user_folder = "default"
    assert observe(inst, {PROFILE: {"id": PROFILE}}, "one", True)["state"] == first["state"]


def test_explicit_own_rename_keeps_id_and_rejects_other_account(data_dir):
    import pytest
    from orcaone.profile_observe import rename_identity
    from orcaone.profile_store import HistoryError
    profile_id = identity_for(INSTANCE, "default", "process", "old.json", "Old")
    rename_identity(INSTANCE, profile_id, "default", "process", "old.json", "new.json", "New")
    assert identity_for(INSTANCE, "default", "process", "new.json", "New") == profile_id
    with pytest.raises(HistoryError, match="identity_mismatch"):
        rename_identity(INSTANCE, profile_id, "other", "process", "new.json", "third.json", "Third")


def test_verified_publish_binds_exact_identity_without_creating_on_lookup(data_dir):
    from orcaone.profile_observe import bind_identity, identity_at, _IDENTITIES
    from orcaone.profile_store import get_ref
    assert identity_at(INSTANCE, "default", "machine", "user/default/machine/A.json") is None
    assert get_ref(INSTANCE, _IDENTITIES) is None
    bind_identity(INSTANCE, PROFILE, "default", "machine", "user/default/machine/A.json", "A")
    assert identity_at(INSTANCE, "default", "machine", "user/default/machine/A.json") == PROFILE
    assert identity_for(INSTANCE, "default", "machine", "user/default/machine/A.json", "A") == PROFILE
    generation = get_ref(INSTANCE, _IDENTITIES)["generation"]
    bind_identity(INSTANCE, PROFILE, "default", "machine", "user/default/machine/A.json", "A")
    assert get_ref(INSTANCE, _IDENTITIES)["generation"] == generation


def test_publish_binding_never_overwrites_other_identity_or_reassigns_account(data_dir):
    import pytest
    from orcaone.profile_observe import bind_identity, identity_at
    from orcaone.profile_store import HistoryError
    bind_identity(INSTANCE, PROFILE, "default", "machine", "same.json", "A")
    with pytest.raises(HistoryError, match="identity_mismatch"):
        bind_identity(INSTANCE, "c" * 32, "default", "machine", "same.json", "Other")
    with pytest.raises(HistoryError, match="identity_mismatch"):
        bind_identity(INSTANCE, PROFILE, "other", "machine", "same.json", "A")
    with pytest.raises(HistoryError, match="identity_mismatch"):
        bind_identity(INSTANCE, PROFILE, "default", "machine", "new.json", "A")
    assert identity_at(INSTANCE, "default", "machine", "same.json") == PROFILE
    assert identity_at(INSTANCE, "other", "machine", "same.json") is None


def test_publish_binding_cas_preserves_concurrently_assigned_identity(data_dir, monkeypatch):
    import pytest
    from orcaone import profile_observe
    from orcaone.profile_store import HistoryError
    original = profile_observe.replace_ref
    def race(instance_id, ref_id, generation, value):
        original(instance_id, ref_id, generation, {"type": "identities", "index": {"entries": [
            {"id": "c" * 32, "user_folder": "default", "kind": "machine", "path": "A.json", "name": "A"}]}})
        return original(instance_id, ref_id, generation, value)
    monkeypatch.setattr(profile_observe, "replace_ref", race)
    with pytest.raises(HistoryError, match="draft_conflict"):
        profile_observe.bind_identity(INSTANCE, PROFILE, "default", "machine", "A.json", "A")
    assert profile_observe.identity_at(INSTANCE, "default", "machine", "A.json") == "c" * 32

import pytest

from orcaone.profile_history import (create_branch, get_branch, get_draft, get_revision,
                                     get_state, save_draft, save_revision, save_state)
from orcaone.profile_store import HistoryError


INSTANCE = "a" * 12
PROFILE_A = "b" * 32
PROFILE_B = "c" * 32


def test_revision_preserves_unknown_and_incomplete_metadata(data_dir):
    document = {"id": PROFILE_A, "kind": "process", "name": "Quality", "schema_id": "unknown",
                "own": {"layer_height": "0.2"}, "effective": {}, "inherited": {},
                "origins": {}, "context": {"chain_complete": False}, "references": [],
                "unknown": {"future_field": "x"}, "complete": False}
    revision_id = save_revision(INSTANCE, document, [], {"source": "external"})
    revision = get_revision(INSTANCE, revision_id)
    assert revision["document"] == document
    assert revision["parents"] == []
    assert revision["provenance"] == {"source": "external"}


def test_branch_keeps_only_selected_profiles_without_deleting_others(data_dir):
    revision_a = save_revision(INSTANCE, {"id": PROFILE_A, "complete": False}, [], {})
    revision_b = save_revision(INSTANCE, {"id": PROFILE_B, "complete": False}, [], {})
    state_id = save_state(INSTANCE, {PROFILE_A: revision_a, PROFILE_B: revision_b}, [], "Größe ✓")
    branch = create_branch(INSTANCE, "Experiment", state_id, [PROFILE_A])
    assert get_state(INSTANCE, state_id)["note"] == "Größe ✓"
    assert branch["profiles"] == {PROFILE_A: revision_a}
    assert branch["removed"] == []
    assert get_branch(INSTANCE, branch["id"]) == branch


def test_draft_conflict_keeps_first_document(data_dir):
    revision = save_revision(INSTANCE, {"id": PROFILE_A, "complete": False}, [], {})
    state_id = save_state(INSTANCE, {PROFILE_A: revision}, [], "")
    branch = create_branch(INSTANCE, "Trial", state_id, [PROFILE_A])
    first = save_draft(INSTANCE, branch["id"], 0, {PROFILE_A: {"id": PROFILE_A, "own": {"layer_height": "0.2"}}})
    assert first["generation"] == 1
    with pytest.raises(HistoryError, match="draft_conflict"):
        save_draft(INSTANCE, branch["id"], 0, {PROFILE_A: {"id": PROFILE_A, "own": {"layer_height": "0.3"}}})
    assert get_draft(INSTANCE, branch["id"])["documents"] == first["documents"]


def test_state_rejects_missing_or_other_profile_revision(data_dir):
    with pytest.raises(HistoryError, match="object_missing"):
        save_state(INSTANCE, {PROFILE_A: "1" * 64}, [], "")
    revision = save_revision(INSTANCE, {"id": PROFILE_A, "complete": False}, [], {})
    with pytest.raises(HistoryError, match="profile_mismatch"):
        save_state(INSTANCE, {PROFILE_B: revision}, [], "")


def test_revision_parent_must_have_same_profile_identity(data_dir):
    parent = save_revision(INSTANCE, {"id": PROFILE_A, "complete": False}, [], {})
    with pytest.raises(HistoryError, match="profile_mismatch"):
        save_revision(INSTANCE, {"id": PROFILE_B, "complete": False}, [parent], {})


def test_draft_document_identity_matches_selected_profile(data_dir):
    revision = save_revision(INSTANCE, {"id": PROFILE_A, "complete": False}, [], {})
    state_id = save_state(INSTANCE, {PROFILE_A: revision}, [], "")
    branch = create_branch(INSTANCE, "Trial", state_id, [PROFILE_A])
    with pytest.raises(HistoryError, match="profile_mismatch"):
        save_draft(INSTANCE, branch["id"], 0, {PROFILE_A: {"id": PROFILE_B}})


def setup_branch():
    revisions = {pid: save_revision(INSTANCE, {"id": pid, "own": {"speed": "10"}}, [], {})
                 for pid in [PROFILE_A, PROFILE_B]}
    state = save_state(INSTANCE, revisions, [], "initial")
    return create_branch(INSTANCE, "Trial", state, list(revisions))


def test_save_draft_rejects_branch_changed_since_draft_base(data_dir):
    from orcaone.profile_store import replace_ref
    branch = setup_branch()
    draft = save_draft(INSTANCE, branch["id"], 0, {PROFILE_A: {"id": PROFILE_A}})
    value = {key: item for key, item in branch.items() if key != "generation"}
    value["state"] = save_state(INSTANCE, branch["profiles"], [], "other")
    replace_ref(INSTANCE, branch["id"], branch["generation"], value)
    with pytest.raises(HistoryError, match="draft_base_conflict"):
        save_draft(INSTANCE, branch["id"], draft["generation"], draft["documents"])
    assert get_draft(INSTANCE, branch["id"]) == draft


def test_commit_selection_preserves_other_draft_and_advances_consistent_base(data_dir):
    from orcaone.profile_history import commit_draft, list_states
    branch = setup_branch()
    documents = {pid: {"id": pid, "own": {"speed": "20"}} for pid in [PROFILE_A, PROFILE_B]}
    draft = save_draft(INSTANCE, branch["id"], 0, documents)
    result = commit_draft(INSTANCE, branch["id"], [PROFILE_A], 1, 1, "checkpoint")
    updated = result["branch"]
    assert updated["profiles"][PROFILE_B] == branch["profiles"][PROFILE_B]
    revision = get_revision(INSTANCE, updated["profiles"][PROFILE_A])
    assert revision["document"] == documents[PROFILE_A]
    assert revision["parents"] == [branch["profiles"][PROFILE_A]]
    rest = get_draft(INSTANCE, branch["id"])
    assert rest["documents"] == {PROFILE_B: documents[PROFILE_B]}
    assert rest["base_state"] == updated["state"]
    assert rest["generation"] == draft["generation"] + 1
    assert len(list_states(INSTANCE, branch["id"])) == 2
    with pytest.raises(HistoryError, match="draft_conflict"):
        commit_draft(INSTANCE, branch["id"], [PROFILE_B], 1, 1, "stale")


def test_restore_creates_new_selected_revision_and_preserves_other_profiles(data_dir):
    from orcaone.profile_history import commit_draft, restore_state
    branch = setup_branch()
    save_draft(INSTANCE, branch["id"], 0, {PROFILE_A: {"id": PROFILE_A, "own": {"speed": "20"}}})
    committed = commit_draft(INSTANCE, branch["id"], [PROFILE_A], 1, 1, "change")["branch"]
    restored = restore_state(INSTANCE, branch["id"], branch["state"], [PROFILE_A], committed["generation"])
    assert restored["profiles"][PROFILE_B] == branch["profiles"][PROFILE_B]
    rev = get_revision(INSTANCE, restored["profiles"][PROFILE_A])
    assert rev["document"]["own"]["speed"] == "10"
    assert rev["parents"] == [committed["profiles"][PROFILE_A]]
    assert get_draft(INSTANCE, branch["id"])["base_state"] == restored["state"]


def test_restore_requires_explicit_deletion_and_blocks_overlapping_draft(data_dir):
    from orcaone.profile_history import restore_state
    branch = setup_branch()
    absent = save_state(INSTANCE, {}, [], "not selected")
    with pytest.raises(HistoryError, match="historical_profile_missing"):
        restore_state(INSTANCE, branch["id"], absent, [PROFILE_A], 1)
    deleted = save_state(INSTANCE, {}, [PROFILE_A], "explicit deletion")
    draft = save_draft(INSTANCE, branch["id"], 0, {PROFILE_A: {"id": PROFILE_A}})
    with pytest.raises(HistoryError, match="draft_restore_conflict"):
        restore_state(INSTANCE, branch["id"], deleted, [PROFILE_A], 1)
    save_draft(INSTANCE, branch["id"], draft["generation"], {})
    result = restore_state(INSTANCE, branch["id"], deleted, [PROFILE_A], 1)
    assert result["removed"] == [PROFILE_A]
    assert result["profiles"] == {PROFILE_B: branch["profiles"][PROFILE_B]}


def test_commit_rejects_racing_draft_without_advancing_branch(data_dir, monkeypatch):
    from orcaone import profile_history as history
    branch = setup_branch()
    save_draft(INSTANCE, branch["id"], 0, {PROFILE_A: {"id": PROFILE_A}})
    original = history.replace_branch_draft
    def race(instance, ref, branch_generation, draft_generation, next_branch, next_draft):
        original(instance, ref, branch_generation, draft_generation, None,
                 {"type": "draft", "branch_id": ref, "base_state": branch["state"],
                  "base_revisions": branch["profiles"], "documents": {PROFILE_B: {"id": PROFILE_B}}})
        return original(instance, ref, branch_generation, draft_generation, next_branch, next_draft)
    monkeypatch.setattr(history, "replace_branch_draft", race)
    with pytest.raises(HistoryError, match="draft_conflict"):
        history.commit_draft(INSTANCE, branch["id"], [PROFILE_A], 1, 1, "race")
    assert get_branch(INSTANCE, branch["id"]) == branch
    assert get_draft(INSTANCE, branch["id"])["documents"] == {PROFILE_B: {"id": PROFILE_B}}

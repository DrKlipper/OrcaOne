from copy import deepcopy

import pytest

from orcaone import profile_history as history
from orcaone.profile_store import HistoryError
from orcaone.profile_workflows import adopt_history, preview_history
from tests.test_profile_normalize import catalog, option


INSTANCE = "a" * 12
PROFILE = "b" * 32
CATALOGS = {"test": catalog({"speed": option("10"), "height": option("0.2")})}


def setup(source_values=None, target_values=None, source_schema="test", parent=True):
    doc = {"id": PROFILE, "kind": "process", "name": "Quality", "schema_id": "test", "inherits": "Parent",
           "own": {}, "inherited": {"speed": "10", "height": "0.2"},
           "effective": {"speed": "10", "height": "0.2"}, "origins": {}, "complete": True,
           "unknown": {}, "context": {"chain_complete": True}}
    base = history.save_revision(INSTANCE, doc, [], {})
    source = deepcopy(doc)
    source["effective"] = source_values or {"speed": "20", "height": "0.3"}
    source["schema_id"] = source_schema
    source_revision = history.save_revision(INSTANCE, source, [base] if parent else [], {})
    source_state = history.save_state(INSTANCE, {PROFILE: source_revision}, [], "source")
    target = deepcopy(doc)
    target["effective"].update(target_values or {})
    revision = history.save_revision(INSTANCE, target, [base], {})
    state = history.save_state(INSTANCE, {PROFILE: revision}, [], "target")
    return history.create_branch(INSTANCE, "Trial", state, [PROFILE]), source_state, source_revision


def test_partial_adoption_leaves_remaining_change_open_after_commit(data_dir):
    branch, source, source_revision = setup()
    first = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["speed"]}, 0, "merge", CATALOGS)
    assert first["issues"] == []
    assert first["documents"][PROFILE]["effective"] == {"speed": "20", "height": "0.2"}
    committed = history.commit_draft(INSTANCE, branch["id"], [PROFILE], 1, 1, "partial")
    revision = history.get_revision(INSTANCE, committed["branch"]["profiles"][PROFILE])
    assert revision["parents"] == [branch["profiles"][PROFILE]]
    assert revision["provenance"]["adoptions"][0]["source_revision"] == source_revision
    preview = preview_history(INSTANCE, branch["id"], source, [PROFILE])
    assert [row["key"] for row in preview["profiles"][PROFILE]] == ["height"]
    second = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["height"]}, 2, "merge", CATALOGS)
    assert second["documents"][PROFILE]["effective"]["height"] == "0.3"


def test_conflict_preview_does_not_write_and_explicit_source_choice_resolves(data_dir):
    branch, source, _ = setup(target_values={"speed": "15"})
    before = history.get_branch(INSTANCE, branch["id"])
    preview = preview_history(INSTANCE, branch["id"], source, [PROFILE])
    assert preview["conflicts"][0]["key"] == "speed"
    assert history.get_branch(INSTANCE, branch["id"]) == before
    assert history.get_draft(INSTANCE, branch["id"]) is None
    result = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["speed"]}, 0, "merge", CATALOGS)
    assert result["documents"][PROFILE]["effective"]["speed"] == "20"


def test_schema_and_missing_ancestor_block_merge_restore_allows_independent_source(data_dir):
    branch, source, _ = setup(source_schema="other")
    with pytest.raises(HistoryError, match="schema_mismatch"):
        preview_history(INSTANCE, branch["id"], source, [PROFILE])
    branch, source, _ = setup(parent=False)
    with pytest.raises(HistoryError, match="merge_base_missing"):
        preview_history(INSTANCE, branch["id"], source, [PROFILE])
    result = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["speed"]}, 0, "restore", CATALOGS)
    assert result["issues"] == []


def test_missing_source_value_and_invalid_number_leave_draft_untouched(data_dir):
    branch, source, _ = setup(source_values={"speed": "bad"})
    result = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["speed"]}, 0, "merge", CATALOGS)
    assert result["issues"]
    assert history.get_draft(INSTANCE, branch["id"]) is None
    result = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["height"]}, 0, "restore", CATALOGS)
    assert result["issues"][0]["code"] == "source_value_missing"


def test_adopt_keeps_unselected_draft_and_blocks_reference_role(data_dir):
    branch, source, _ = setup()
    document = history.get_revision(INSTANCE, branch["profiles"][PROFILE])["document"]
    document["effective"]["height"] = "0.4"
    history.save_draft(INSTANCE, branch["id"], 0, {PROFILE: document})
    result = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["speed"]}, 1, "merge", CATALOGS)
    assert result["documents"][PROFILE]["effective"] == {"speed": "20", "height": "0.4"}
    cat = deepcopy(CATALOGS)
    cat["test"]["options"]["process"]["height"]["role"] = "reference"
    failed = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["height"]}, 2, "merge", cat)
    assert failed["issues"][0]["code"] == "protected_field"
    assert history.get_draft(INSTANCE, branch["id"])["generation"] == 2


def test_origin_only_difference_is_visible_and_missing_profile_blocks(data_dir):
    branch, source, _ = setup()
    target_id = branch["profiles"][PROFILE]
    document = history.get_revision(INSTANCE, target_id)["document"]
    document["origins"] = {"speed": {"kind": "default", "schema_id": "test", "source": "different"}}
    revision = history.save_revision(INSTANCE, document, [target_id], {})
    origin_state = history.save_state(INSTANCE, {PROFILE: revision}, [], "origins")
    preview = preview_history(INSTANCE, branch["id"], origin_state, [PROFILE])
    row = preview["profiles"][PROFILE][0]
    assert row["before"] == row["after"]
    assert row["before_origin"] != row["after_origin"]
    missing = history.save_state(INSTANCE, {}, [PROFILE], "deleted")
    with pytest.raises(HistoryError, match="history_profile_missing"):
        preview_history(INSTANCE, branch["id"], missing, [PROFILE])


def test_generation_conflict_cannot_replace_first_adoption(data_dir):
    branch, source, _ = setup()
    adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["speed"]}, 0, "merge", CATALOGS)
    before = history.get_draft(INSTANCE, branch["id"])
    with pytest.raises(HistoryError, match="draft_conflict"):
        adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["height"]}, 0, "merge", CATALOGS)
    assert history.get_draft(INSTANCE, branch["id"]) == before


def test_merge_materializes_selected_profile_but_restore_keeps_target_inheritance(data_dir):
    branch, source, _ = setup()
    result = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["speed"]}, 0, "merge", CATALOGS)
    doc = result["documents"][PROFILE]
    assert doc["inherits"] == ""
    assert doc["inherited"] == {} and doc["inherited_origins"] == {}
    assert doc["own"] == doc["effective"] == {"speed": "20", "height": "0.2"}
    assert all(origin["profile_id"] == PROFILE for origin in doc["origins"].values())
    assert not any(ref["key"] == "inherits" for ref in doc.get("references", []))
    other, source, _ = setup()
    restored = adopt_history(INSTANCE, other["id"], source, {PROFILE: ["speed"]}, 0, "restore", CATALOGS)
    restored_doc = restored["documents"][PROFILE]
    assert restored_doc["inherits"] == "Parent"
    assert restored_doc["own"] == {"speed": "20"}


def test_merge_rejects_incomplete_source_before_materializing(data_dir):
    branch, source, source_revision = setup()
    document = history.get_revision(INSTANCE, source_revision)["document"]
    document["complete"] = False
    document["context"]["chain_complete"] = False
    incomplete = history.save_revision(INSTANCE, document, [source_revision], {})
    source = history.save_state(INSTANCE, {PROFILE: incomplete}, [], "incomplete")
    result = adopt_history(INSTANCE, branch["id"], source, {PROFILE: ["speed"]}, 0, "merge", CATALOGS)
    assert result["issues"][0]["code"] == "document_incomplete"
    assert history.get_draft(INSTANCE, branch["id"]) is None

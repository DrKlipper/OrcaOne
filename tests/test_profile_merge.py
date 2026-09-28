"""Profile merges preserve selection, absence and unresolved conflicts."""

from copy import deepcopy

from orcaone.profile_merge import diff_values, merge_parents, merge_values


def test_partial_merge_preserves_remaining_source_change():
    base = {"speed": "10", "height": "0.2"}
    source = {"speed": "20", "height": "0.3"}
    first = merge_values(base, base, source, ["speed"])
    assert first == {"values": {"speed": "20", "height": "0.2"}, "conflicts": []}
    assert merge_parents("target", "source", False) == ["target"]
    second = merge_values(base, first["values"], source, ["height"])
    assert second["values"]["height"] == "0.3"


def test_conflict_keeps_target_until_user_decides():
    got = merge_values({"a": "1"}, {"a": "2"}, {"a": "3"}, ["a"])
    assert got["values"] == {"a": "2"}
    assert got["conflicts"] == [{"key": "a", "base": {"present": True, "value": "1"},
                                 "target": {"present": True, "value": "2"},
                                 "source": {"present": True, "value": "3"}}]


def test_remove_versus_edit_is_a_conflict():
    got = merge_values({"a": "1"}, {}, {"a": "2"}, ["a"])
    assert got["values"] == {}
    assert got["conflicts"][0]["target"] == {"present": False}


def test_unilateral_deletion_differs_from_empty_value():
    assert merge_values({"a": "1"}, {"a": "1"}, {}, ["a"])["values"] == {}
    assert merge_values({"a": "1"}, {"a": "1"}, {"a": ""}, ["a"])["values"] == {"a": ""}
    assert diff_values({}, {"a": []}) == [{"key": "a", "before": {"present": False},
                                           "after": {"present": True, "value": []}}]


def test_vectors_are_not_merged_by_assumed_dimensions():
    got = merge_values({"a": ["1", "2"]}, {"a": ["3", "2"]}, {"a": ["1", "4"]}, ["a"])
    assert got["values"] == {"a": ["3", "2"]}
    assert len(got["conflicts"]) == 1


def test_identical_changes_and_input_independence():
    base, target, source = {"a": ["1"]}, {"a": ["2"]}, {"a": ["2"]}
    saved = deepcopy((base, target, source))
    got = merge_values(base, target, source, ["a", "a"])
    assert got["conflicts"] == []
    got["values"]["a"].append("3")
    assert (base, target, source) == saved
    assert merge_parents("same", "same", True) == ["same"]


def test_diff_is_sorted_and_multiline_is_data_only():
    before = {"z": "G28\nM104 S200", "a": "0"}
    after = {"z": "G28\nM104 S210", "a": "1"}
    got = diff_values(before, after)
    assert [row["key"] for row in got] == ["a", "z"]
    assert got[1]["after"]["value"] == "G28\nM104 S210"

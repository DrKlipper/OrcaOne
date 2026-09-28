from copy import deepcopy

from orcaone.profile_edit import apply_patches, make_document, reference_impacts
from orcaone.scanner import Profile
from tests.test_profile_normalize import catalog, option


def documents():
    return {k: dict(id=k, kind="process", schema_id="test", name=k, own={}, inherited={"speed": ["10", "20"]}, effective={"speed": ["10", "20"]}, origins={}, unknown={"future": "x"}, context={"chain_complete": True}, complete=True) for k in ("a", "b")}


def patch(**changes):
    return dict(profile_id="a", op="set", key="speed", value=["30"], indices=[1], **changes)


def test_selective_patch_preserves_other_document_and_inherited_vector():
    docs = documents()
    before = deepcopy(docs)
    cat = catalog({"speed": option(["10"], "coFloats", "list")})
    result = apply_patches(docs, [patch()], {"test": cat})
    assert result["issues"] == []
    assert result["documents"]["a"]["effective"]["speed"] == ["10", "30"]
    assert result["documents"]["b"] == before["b"]
    assert docs == before


def test_bad_second_patch_is_atomic_and_reset_uses_inheritance():
    docs = documents()
    cat = catalog({"speed": option(["10"], "coFloats", "list")})
    result = apply_patches(docs, [patch(), dict(profile_id="b", op="set", key="speed", value=["bad"], indices=[0])], {"test": cat})
    assert result["issues"]
    assert result["documents"] == docs
    edited = apply_patches(docs, [patch()], {"test": cat})["documents"]
    reset = apply_patches(edited, [dict(profile_id="a", op="reset", key="speed", indices=None)], {"test": cat})
    assert reset["documents"]["a"]["own"] == {}
    assert reset["documents"]["a"]["effective"]["speed"] == ["10", "20"]


def test_protected_fields_and_unknown_cannot_be_patched():
    for role in ("secret", "metadata", "reference"):
        field = option("", "coString")
        field["role"] = role
        assert apply_patches(documents(), [dict(profile_id="a", op="set", key="speed", value="x")], {"test": catalog({"speed": field})})["issues"]


def test_document_strips_secrets_and_missing_chain_blocks():
    class Resolver:
        def chain(self, profile):
            return [], False
    secret = option("", "coString")
    secret["role"] = "secret"
    profile = Profile("Child", "process", "", inherits="Missing", values={"password": "sensitive", "future": "preserve"})
    doc = make_document("a", profile, Resolver(), catalog({"password": secret}))
    assert "sensitive" not in str(doc)
    assert doc["unknown"] == {"future": "preserve"}
    assert not doc["complete"]


def test_own_unknown_is_distinct_from_inherited_unknown():
    parent = Profile("Parent", "process", "Vendor", values={"parent_future": "parent"})
    class Resolver:
        def chain(self, profile):
            return [parent], True
    doc = make_document("a", Profile("Child", "process", "", values={"own_future": "child"}), Resolver(), catalog({}))
    assert doc["own_unknown"] == {"own_future": "child"}
    assert doc["inherited_unknown"] == {"parent_future": "parent"}
    assert doc["unknown"] == {"parent_future": "parent", "own_future": "child"}


def test_unsupported_catalog_never_exposes_known_or_unknown_secret_fields():
    class Resolver:
        def chain(self, profile):
            return [], True
    profile = Profile("Printer", "machine", "", values={
        "printhost_user": "private-user", "printhost_password": "private-password",
        "future_access_token": "private-token", "future": "visible"})
    document = make_document("a", profile, Resolver(), None)
    assert "private" not in str(document)
    assert document["unknown"] == {"future": "visible"}


def test_reference_impacts_never_expands_scope_and_marks_conditions_unknown():
    docs = documents()
    docs["b"]["effective"].update(compatible_printers=["Old"], compatible_printers_condition="printer_model == 'Old'")
    impacts = reference_impacts(docs, {"Old": "New"})
    assert any(i["profile_id"] == "b" and i["code"] == "reference_update_required" for i in impacts)
    assert any(i["code"] == "condition_unknown" for i in impacts)


def test_dimension_change_never_silently_changes_another_parameter():
    fields = {"process_flow_support": option(["standard"], "coStrings", "list"), "speed": option(["10"], "coFloats", "flow")}
    cat = catalog(fields)
    docs = documents()
    docs["a"]["effective"] = {"process_flow_support": ["standard"], "speed": ["10"]}
    docs["a"]["inherited"] = deepcopy(docs["a"]["effective"])
    result = apply_patches(docs, [{"profile_id": "a", "op": "set", "key": "process_flow_support", "value": ["standard", "high_flow"]}], {"test": cat})
    assert result["documents"] == docs
    assert any(i["code"] == "dimension_scope_expansion" for i in result["issues"])


def test_index_reset_keeps_other_owned_index():
    docs = documents()
    docs["a"]["own"]["speed"] = ["30", "40"]
    docs["a"]["effective"]["speed"] = ["30", "40"]
    result = apply_patches(docs, [{"profile_id": "a", "op": "reset", "key": "speed", "indices": [1]}], {"test": catalog({"speed": option(["10"], "coFloats", "list")})})
    assert result["documents"]["a"]["own"]["speed"] == ["30", "20"]


def test_bindings_are_explicit_and_untargeted_indices_remain():
    field = option([], "coStrings", "list")
    field["role"] = "reference"
    docs = documents()
    docs["a"]["effective"]["compatible_printers"] = ["A"]
    cat = catalog({"compatible_printers": field, "speed": option(["10"], "coFloats", "list")})
    added = apply_patches(docs, [{"profile_id": "a", "key": "compatible_printers", "op": "bind_add", "value": ["B"]}], {"test": cat})
    assert added["issues"] == []
    assert added["documents"]["a"]["effective"]["compatible_printers"] == ["A", "B"]


def test_incomplete_option_cannot_be_edited_even_when_document_claims_complete():
    field = option(["10"], "coFloats", "list")
    field["complete"] = False
    result = apply_patches(documents(), [patch()], {"test": catalog({"speed": field})})
    assert any(i["code"] == "option_incomplete" for i in result["issues"])


def test_schema_identity_mismatch_cannot_be_used_for_editing():
    cat = catalog({"speed": option(["10"], "coFloats", "list")})
    cat["id"] = "different"
    result = apply_patches(documents(), [patch()], {"test": cat})
    assert result["issues"]


def test_document_exposes_source_metadata_without_paths():
    class Resolver:
        def chain(self, profile):
            return [], True
    profile = Profile("Child", "process", "Vendor", inherits="Parent", file="private/path")
    doc = make_document("a", profile, Resolver(), None)
    assert (doc["package"], doc["origin_kind"], doc["inherits"]) == ("Vendor", "vendor", "Parent")
    assert "private/path" not in str(doc)


def test_malformed_patches_return_issues_instead_of_crashing():
    for patches in ([None], [{"profile_id": []}], [{"profile_id": "a", "key": []}], [{"profile_id": "a", "key": "speed", "op": []}], None):
        result = apply_patches(documents(), patches, {})
        assert result["issues"]
        assert result["documents"] == documents()

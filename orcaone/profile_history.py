"""Profile revisions, selected states, branches and independent drafts."""

from datetime import datetime, timezone
from uuid import uuid4

from .profile_store import (HistoryError, get_object, get_ref, list_refs, put_object,
                            replace_ref, replace_branch_draft, validate_id)


def _time() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_revision(instance_id: str, document: dict, parents: list[str], provenance: dict) -> str:
    if not isinstance(document, dict) or not isinstance(parents, list) or not isinstance(provenance, dict):
        raise HistoryError("invalid_revision")
    validate_id(document.get("id"), "profile")
    for parent in parents:
        validate_id(parent, "object")
        if get_revision(instance_id, parent)["document"].get("id") != document["id"]:
            raise HistoryError("profile_mismatch")
    return put_object(instance_id, {"type": "revision", "document": document,
                                    "parents": parents, "provenance": provenance, "created": _time()})


def get_revision(instance_id: str, revision_id: str) -> dict:
    value = get_object(instance_id, revision_id)
    if value.get("type") != "revision":
        raise HistoryError("wrong_object_type")
    return value


def save_state(instance_id: str, profiles: dict[str, str], removed: list[str], note: str) -> str:
    if not isinstance(profiles, dict) or not isinstance(removed, list) or not isinstance(note, str):
        raise HistoryError("invalid_state")
    for profile_id, revision_id in profiles.items():
        validate_id(profile_id, "profile")
        validate_id(revision_id, "object")
        if get_revision(instance_id, revision_id)["document"].get("id") != profile_id:
            raise HistoryError("profile_mismatch")
    for profile_id in removed:
        validate_id(profile_id, "profile")
    if set(profiles).intersection(removed) or len(set(removed)) != len(removed):
        raise HistoryError("invalid_state")
    return put_object(instance_id, {"type": "state", "profiles": profiles, "removed": removed,
                                    "note": note, "created": _time()})


def get_state(instance_id: str, state_id: str) -> dict:
    value = get_object(instance_id, state_id)
    if value.get("type") != "state":
        raise HistoryError("wrong_object_type")
    return value


def create_branch(instance_id: str, name: str, state_id: str, selected: list[str]) -> dict:
    if not isinstance(name, str) or not name.strip() or not isinstance(selected, list):
        raise HistoryError("invalid_branch")
    state = get_state(instance_id, state_id)
    for profile_id in selected:
        validate_id(profile_id, "profile")
        if profile_id not in state["profiles"] and profile_id not in state["removed"]:
            raise HistoryError("profile_missing", profile_id=profile_id)
    if len(set(selected)) != len(selected):
        raise HistoryError("invalid_branch")
    branch_id = uuid4().hex
    branch = {"id": branch_id, "name": name, "base_state": state_id, "state": state_id,
              "states": [state_id],
              "selected": selected, "profiles": {key: state["profiles"][key] for key in selected
                                               if key in state["profiles"]},
              "removed": [key for key in selected if key in state["removed"]], "created": _time()}
    return replace_ref(instance_id, branch_id, 0, {"type": "branch", **branch})


def get_branch(instance_id: str, branch_id: str) -> dict:
    validate_id(branch_id, "branch")
    value = get_ref(instance_id, branch_id)
    if value is None:
        raise HistoryError("branch_missing")
    if value.get("type") != "branch":
        raise HistoryError("wrong_ref_type")
    return value


def list_branches(instance_id: str) -> list[dict]:
    return [value for value in list_refs(instance_id) if value.get("type") == "branch"]


def save_draft(instance_id: str, branch_id: str, expected: int, documents: dict,
               expected_branch_generation: int | None = None) -> dict:
    branch = get_branch(instance_id, branch_id)
    if expected_branch_generation is not None and (type(expected_branch_generation) is not int
                                                   or branch["generation"] != expected_branch_generation):
        raise HistoryError("branch_conflict")
    old = get_draft(instance_id, branch_id)
    if old and old["base_state"] != branch["state"]:
        raise HistoryError("draft_base_conflict")
    if not isinstance(documents, dict):
        raise HistoryError("invalid_draft")
    for profile_id, document in documents.items():
        validate_id(profile_id, "profile")
        if profile_id not in branch["selected"] or not isinstance(document, dict):
            raise HistoryError("invalid_draft")
        if document.get("id") != profile_id:
            raise HistoryError("profile_mismatch")
    # The branch ref and its draft ref are separate. A browser's expected generation
    # applies only to the draft and cannot silently advance the branch.
    # Drafts use a dedicated namespace, so branch and draft may share their UUID.
    return replace_branch_draft(instance_id, branch_id, branch["generation"], expected, None,
                             {"type": "draft", "branch_id": branch_id,
                              "base_state": branch["state"], "base_revisions": branch["profiles"],
                              "documents": documents,
                              "adoptions": {key: value for key, value in (old or {}).get("adoptions", {}).items()
                                            if key in documents},
                              "updated": _time()})["draft"]


def get_draft(instance_id: str, branch_id: str) -> dict | None:
    get_branch(instance_id, branch_id)
    from .profile_store import get_draft_ref
    return get_draft_ref(instance_id, branch_id)


def _selection(branch, selected):
    if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected):
        raise HistoryError("invalid_selection")
    if any(profile_id not in branch["selected"] for profile_id in selected):
        raise HistoryError("profile_not_selected")


def _advance(instance_id, branch, draft, profiles, removed, note, expected_branch,
             expected_draft, consumed):
    state_id = save_state(instance_id, profiles, sorted(removed), note)
    next_branch = {key: item for key, item in branch.items() if key != "generation"}
    next_branch.update(state=state_id, profiles=profiles, removed=sorted(removed),
                       states=[*branch.get("states", [branch["state"]]), state_id])
    next_draft = None
    if draft:
        next_draft = {key: item for key, item in draft.items() if key != "generation"}
        next_draft.update(base_state=state_id, base_revisions=profiles,
                          documents={key: item for key, item in draft["documents"].items() if key not in consumed},
                          updated=_time())
        if "adoptions" in next_draft:
            next_draft["adoptions"] = {key: value for key, value in next_draft["adoptions"].items() if key not in consumed}
    result = replace_branch_draft(instance_id, branch["id"], expected_branch, expected_draft,
                                  next_branch, next_draft)
    return {**result, "state": state_id}


def commit_draft(instance_id: str, branch_id: str, selected: list[str], expected_generation: int,
                 expected_branch_generation: int, note: str) -> dict:
    branch, draft = get_branch(instance_id, branch_id), get_draft(instance_id, branch_id)
    _selection(branch, selected)
    if not draft or draft["generation"] != expected_generation:
        raise HistoryError("draft_conflict")
    if branch["generation"] != expected_branch_generation:
        raise HistoryError("branch_conflict")
    if draft["base_state"] != branch["state"]:
        raise HistoryError("draft_base_conflict")
    if any(profile_id not in draft["documents"] for profile_id in selected):
        raise HistoryError("draft_profile_missing")
    profiles, removed = dict(branch["profiles"]), set(branch["removed"])
    for profile_id in selected:
        previous = profiles.get(profile_id)
        provenance = {"source": "draft", "note": note}
        if profile_id in draft.get("adoptions", {}):
            provenance["adoptions"] = draft["adoptions"][profile_id]
        profiles[profile_id] = save_revision(instance_id, draft["documents"][profile_id],
                                             [previous] if previous else [], provenance)
        removed.discard(profile_id)
    return _advance(instance_id, branch, draft, profiles, removed, note,
                    expected_branch_generation, expected_generation, selected)


def restore_state(instance_id: str, branch_id: str, historical_state: str,
                  selected: list[str], expected: int) -> dict:
    branch, draft = get_branch(instance_id, branch_id), get_draft(instance_id, branch_id)
    _selection(branch, selected)
    if branch["generation"] != expected:
        raise HistoryError("branch_conflict")
    if draft and (draft["base_state"] != branch["state"] or set(selected).intersection(draft["documents"])):
        raise HistoryError("draft_restore_conflict")
    historical = get_state(instance_id, historical_state)
    profiles, removed = dict(branch["profiles"]), set(branch["removed"])
    for profile_id in selected:
        if profile_id in historical["profiles"]:
            source = historical["profiles"][profile_id]
            previous = profiles.get(profile_id)
            profiles[profile_id] = save_revision(instance_id, get_revision(instance_id, source)["document"],
                                                 [previous] if previous else [],
                                                 {"source": "restore", "source_revision": source,
                                                  "source_state": historical_state})
            removed.discard(profile_id)
        elif profile_id in historical["removed"]:
            profiles.pop(profile_id, None)
            removed.add(profile_id)
        else:
            raise HistoryError("historical_profile_missing", profile_id=profile_id)
    return _advance(instance_id, branch, draft, profiles, removed, "restore", expected,
                    draft["generation"] if draft else 0, selected)["branch"]


def list_states(instance_id: str, branch_id: str) -> list[dict]:
    branch = get_branch(instance_id, branch_id)
    return [{"id": state_id, **get_state(instance_id, state_id)}
            for state_id in branch.get("states", [branch["state"]])]


from .profile_observe import match_identity, observe

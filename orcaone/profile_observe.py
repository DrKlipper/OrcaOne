"""Independent observations and exact, account-scoped live profile identities."""

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid4, uuid5

from .profile_store import HistoryError, get_ref, replace_ref, validate_id


_IDENTITIES = uuid5(NAMESPACE_URL, "orcaone:profile-identities").hex


def identity_at(instance_id: str, user_folder: str, kind: str, path: str) -> str | None:
    """Read an exact mapping without assigning an identity to an untracked file."""
    ref = get_ref(instance_id, _IDENTITIES)
    matches = [entry for entry in (ref or {}).get("index", {}).get("entries", [])
               if (entry["user_folder"], entry["kind"], entry["path"]) == (user_folder, kind, path)]
    if len(matches) > 1:
        raise HistoryError("identity_ambiguous")
    return matches[0]["id"] if matches else None


def bind_identity(instance_id: str, profile_id: str, user_folder: str, kind: str,
                  path: str, name: str) -> None:
    """Bind a verified publication, rejecting another identity or silent reassignment."""
    validate_id(profile_id, "profile")
    if (kind not in {"machine", "process", "filament"}
            or any(not isinstance(value, str) or not value for value in (user_folder, path, name))):
        raise HistoryError("invalid_identity")
    old = get_ref(instance_id, _IDENTITIES)
    index = deepcopy(old["index"]) if old else {"entries": []}
    target = (user_folder, kind, path)
    entry = {"id": profile_id, "user_folder": user_folder, "kind": kind, "path": path, "name": name}
    relevant = [item for item in index["entries"] if item["id"] == profile_id
                or (item["user_folder"], item["kind"], item["path"]) == target]
    if len(relevant) > 1:
        raise HistoryError("identity_ambiguous")
    if relevant:
        current = relevant[0]
        if current["id"] != profile_id or (current["user_folder"], current["kind"], current["path"]) != target:
            raise HistoryError("identity_mismatch")
        if current == entry:
            return
        current.update(entry)
    else:
        index["entries"].append(entry)
    replace_ref(instance_id, _IDENTITIES, old["generation"] if old else 0, {"type": "identities", "index": index})


def match_identity(index: dict, user_folder: str, kind: str, path: str, name: str) -> dict:
    updated = deepcopy(index)
    entries = updated.setdefault("entries", [])
    matches = [item for item in entries if (item["user_folder"], item["kind"], item["path"])
               == (user_folder, kind, path)]
    if len(matches) > 1:
        raise HistoryError("identity_ambiguous")
    if matches:
        matches[0]["name"] = name
        return {"id": matches[0]["id"], "status": "matched", "index": updated}
    profile_id = uuid4().hex
    entries.append({"id": profile_id, "user_folder": user_folder, "kind": kind,
                    "path": path, "name": name})
    return {"id": profile_id, "status": "new", "index": updated}


def identity_for(instance_id: str, user_folder: str, kind: str, path: str, name: str) -> str:
    old = get_ref(instance_id, _IDENTITIES)
    index = old.get("index", {}) if old else {}
    result = match_identity(index, user_folder, kind, path, name)
    if result["index"] != index:
        replace_ref(instance_id, _IDENTITIES, old["generation"] if old else 0,
                    {"type": "identities", "index": result["index"]})
    return result["id"]


def rename_identity(instance_id: str, profile_id: str, user_folder: str, kind: str,
                    old_path: str, new_path: str, name: str) -> None:
    """Bind a verified OrcaOne rename; callers must confirm the physical rename first."""
    validate_id(profile_id, "profile")
    old = get_ref(instance_id, _IDENTITIES)
    index = deepcopy(old["index"]) if old else {"entries": []}
    matches = [item for item in index["entries"] if (item["id"], item["user_folder"], item["kind"], item["path"])
               == (profile_id, user_folder, kind, old_path)]
    if len(matches) != 1:
        raise HistoryError("identity_mismatch")
    if any(item["id"] != profile_id and (item["user_folder"], item["kind"], item["path"])
           == (user_folder, kind, new_path) for item in index["entries"]):
        raise HistoryError("identity_ambiguous")
    matches[0].update(path=new_path, name=name)
    replace_ref(instance_id, _IDENTITIES, old["generation"], {"type": "identities", "index": index})


def observe(instance, documents: dict, fingerprint: str, stable: bool) -> dict:
    from .profile_history import get_revision, save_revision, save_state

    instance_id = instance.id
    ref_id = uuid5(NAMESPACE_URL, "orcaone:observation:" + instance.active_user_folder).hex
    old = get_ref(instance_id, ref_id)
    generation = old["generation"] if old else 0
    old = old or {"profiles": {}, "removed": [], "state": None, "states": []}
    value = {key: deepcopy(item) for key, item in old.items() if key != "generation"}
    value.update(type="observation", user_folder=instance.active_user_folder)
    result = {"recorded": False, "removed": [], "state": old["state"], "pending": False}
    if not stable:
        if value.pop("pending", None) is not None:
            replace_ref(instance_id, ref_id, generation, value)
        return {**result, "unstable": True}
    if not isinstance(documents, dict) or not isinstance(fingerprint, str):
        raise HistoryError("invalid_observation")
    for profile_id, document in documents.items():
        validate_id(profile_id, "profile")
        if not isinstance(document, dict) or document.get("id") != profile_id:
            raise HistoryError("profile_mismatch")
    missing = sorted(set(old["profiles"]) - set(documents))
    pending = {"fingerprint": fingerprint, "missing": missing}
    if missing and old.get("pending") != pending:
        value["pending"] = pending
        replace_ref(instance_id, ref_id, generation, value)
        return {**result, "pending": True}
    profiles = {}
    for profile_id, document in documents.items():
        previous = old["profiles"].get(profile_id)
        if previous and get_revision(instance_id, previous)["document"] == document:
            profiles[profile_id] = previous
        else:
            profiles[profile_id] = save_revision(instance_id, document, [previous] if previous else [],
                                                 {"source": "slicer_observation"})
    removed = sorted((set(old["removed"]) | set(missing)) - set(profiles))
    changed = profiles != old["profiles"] or removed != old["removed"] or old["state"] is None
    value.pop("pending", None)
    if changed:
        state_id = save_state(instance_id, profiles, removed, "slicer_observation")
        value.update(profiles=profiles, removed=removed, state=state_id,
                     states=[*old.get("states", []), state_id])
    value["fingerprint"] = fingerprint
    if value != {key: item for key, item in old.items() if key != "generation"}:
        replace_ref(instance_id, ref_id, generation, value)
    return {"recorded": changed, "removed": missing if changed else [],
            "state": value["state"], "pending": False}

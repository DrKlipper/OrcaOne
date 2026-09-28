"""Authoritative, selected history previews and explicit adoption into drafts."""

from copy import deepcopy

from . import profile_history as history
from .profile_edit import apply_patches
from .profile_merge import diff_values, merge_values
from .profile_store import HistoryError, replace_branch_draft


def _ancestors(instance_id, revision_id):
    distances, pending = {}, [(revision_id, 0)]
    while pending:
        current, distance = pending.pop(0)
        if current in distances:
            continue
        distances[current] = distance
        pending.extend((parent, distance + 1) for parent in history.get_revision(instance_id, current)["parents"])
    return distances


def _base(instance_id, target_id, source_id):
    target, source = _ancestors(instance_id, target_id), _ancestors(instance_id, source_id)
    common = set(target).intersection(source)
    if not common:
        raise HistoryError("merge_base_missing")
    # A criss-cross DAG can have incomparable merge bases. Do not invent a base.
    nearest = [candidate for candidate in common if not any(
        candidate != other and candidate in _ancestors(instance_id, other) for other in common)]
    if len(nearest) != 1:
        raise HistoryError("merge_base_ambiguous")
    return history.get_revision(instance_id, nearest[0])["document"]


def _load(instance_id, branch_id, source_state, selected, mode):
    if mode not in {"merge", "restore"}:
        raise HistoryError("invalid_history_mode")
    branch = history.get_branch(instance_id, branch_id)
    history._selection(branch, selected)
    draft = history.get_draft(instance_id, branch_id)
    if draft and draft["base_state"] != branch["state"]:
        raise HistoryError("draft_base_conflict")
    source = history.get_state(instance_id, source_state)
    documents = {pid: history.get_revision(instance_id, rev)["document"] for pid, rev in branch["profiles"].items()}
    if draft:
        documents.update(draft["documents"])
    return branch, draft, source, documents


def _preview(instance_id, branch, source, documents, selected, mode):
    profiles, conflicts = {}, []
    for profile_id in selected:
        if profile_id not in source["profiles"] or profile_id not in documents or profile_id not in branch["profiles"]:
            raise HistoryError("history_profile_missing", profile_id=profile_id)
        target = documents[profile_id]
        source_doc = history.get_revision(instance_id, source["profiles"][profile_id])["document"]
        if (not target.get("schema_id") or target.get("schema_id") != source_doc.get("schema_id")
                or target.get("kind") != source_doc.get("kind")):
            raise HistoryError("schema_mismatch", profile_id=profile_id)
        base = _base(instance_id, branch["profiles"][profile_id], source["profiles"][profile_id]) if mode == "merge" else target
        if base.get("schema_id") != target.get("schema_id"):
            raise HistoryError("schema_mismatch", profile_id=profile_id)
        base_values, target_values, source_values = (doc.get("effective", {}) for doc in (base, target, source_doc))
        changed_keys = {row["key"] for row in diff_values(base_values, source_values)}
        changed_keys.update(key for key in set(base.get("origins", {})) | set(source_doc.get("origins", {}))
                            if base.get("origins", {}).get(key) != source_doc.get("origins", {}).get(key))
        value_conflicts = {item["key"]: item for item in merge_values(base_values, target_values, source_values,
                                                                       sorted(changed_keys))["conflicts"]}
        rows = []
        for key in sorted(changed_keys):
            before = {"present": key in target_values}
            after = {"present": key in source_values}
            if before["present"]:
                before["value"] = deepcopy(target_values[key])
            if after["present"]:
                after["value"] = deepcopy(source_values[key])
            before_origin = target.get("origins", {}).get(key)
            after_origin = source_doc.get("origins", {}).get(key)
            if before == after and (before_origin == after_origin or key not in source_doc.get("origins", {})):
                continue
            row = {"key": key, "before": before, "after": after,
                   "before_origin": deepcopy(before_origin), "after_origin": deepcopy(after_origin)}
            if key in value_conflicts:
                row["conflict"] = value_conflicts[key]
                conflicts.append({"profile_id": profile_id, **value_conflicts[key]})
            rows.append(row)
        profiles[profile_id] = rows
    return {"profiles": profiles, "conflicts": conflicts}


def preview_history(instance_id, branch_id, source_state, selected, mode="merge"):
    branch, draft, source, documents = _load(instance_id, branch_id, source_state, selected, mode)
    return _preview(instance_id, branch, source, documents, selected, mode)


def adopt_history(instance_id, branch_id, source_state, fields, expected_generation, mode, catalogs):
    if not isinstance(fields, dict) or not fields or any(not isinstance(keys, list) or not keys
            or any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)) for keys in fields.values()):
        raise HistoryError("invalid_selection")
    branch, draft, source, documents = _load(instance_id, branch_id, source_state, list(fields), mode)
    generation = draft["generation"] if draft else 0
    if type(expected_generation) is not int or generation != expected_generation:
        raise HistoryError("draft_conflict")
    preview = _preview(instance_id, branch, source, documents, list(fields), mode)
    patches, issues = [], []
    for profile_id, keys in fields.items():
        source_document = history.get_revision(instance_id, source["profiles"][profile_id])["document"]
        if mode == "merge" and (not source_document.get("complete")
                                 or not source_document.get("context", {}).get("chain_complete")):
            issues.append({"severity": "error", "code": "document_incomplete", "profile_id": profile_id,
                           "key": None, "indices": None, "params": {}})
            continue
        rows = {row["key"]: row for row in preview["profiles"][profile_id]}
        for key in keys:
            row = rows.get(key)
            code = "history_field_missing" if row is None else "source_value_missing" if not row["after"]["present"] else None
            if code:
                issues.append({"severity": "error", "code": code, "profile_id": profile_id,
                               "key": key, "indices": None, "params": {}})
            else:
                patches.append({"profile_id": profile_id, "op": "set", "key": key,
                                "value": deepcopy(row["after"]["value"]), "indices": None})
    if issues:
        return {"documents": documents, "issues": issues, "generation": generation}
    result = apply_patches(documents, patches, catalogs)
    if result["issues"]:
        return {**result, "generation": generation}
    draft_documents = deepcopy(draft["documents"]) if draft else {}
    adoptions = deepcopy(draft.get("adoptions", {})) if draft else {}
    for profile_id, keys in fields.items():
        document = result["documents"][profile_id]
        if mode == "merge":
            # Selected effective values become independent of both old parents.
            # Unselected profiles and unselected effective field values stay intact.
            document["own"] = {**deepcopy(document.get("unknown", {})), **deepcopy(document["effective"])}
            document["own_unknown"] = deepcopy(document.get("unknown", {}))
            document.update(inherits="", inherited={}, inherited_origins={}, inherited_unknown={})
            document["references"] = [ref for ref in document.get("references", []) if ref["key"] != "inherits"]
            document["origins"] = {key: {"kind": "profile", "profile_id": profile_id,
                                        "schema_id": document["schema_id"]} for key in document["own"]}
        draft_documents[profile_id] = document
        adoptions.setdefault(profile_id, []).append({"mode": mode, "source_state": source_state,
                                                    "source_revision": source["profiles"][profile_id],
                                                    "fields": list(keys)})
    new_draft = {"type": "draft", "branch_id": branch_id, "base_state": branch["state"],
                 "base_revisions": branch["profiles"], "documents": draft_documents,
                 "adoptions": adoptions, "updated": history._time()}
    saved = replace_branch_draft(instance_id, branch_id, branch["generation"], generation, None, new_draft)["draft"]
    return {**result, "generation": saved["generation"]}

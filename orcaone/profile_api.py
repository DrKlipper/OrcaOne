"""Local profile drafts and history; slicer writes remain with the Planner."""

import base64
import json

from fastapi import APIRouter, Body

from . import operations, profile_history as history, profile_schema, scanner
from .profile_store import HistoryError, list_refs, validate_id
from .resolver import Resolver

router = APIRouter(prefix="/api/instances/{instance_id}/profile-editor")
MAX_SCOPE = 200


def _instance(instance_id):
    return operations.find_instance(instance_id)[0]


def _scope(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_SCOPE:
        raise operations.OperationError("invalid_scope", 400)
    for item in value:
        validate_id(item, "profile")
    if len(set(value)) != len(value):
        raise operations.OperationError("invalid_scope", 400)
    return value


def _generation(body):
    value = body.get("expected_generation")
    if type(value) is not int or value < 0:
        raise operations.OperationError("invalid_generation", 400)
    return value


def _documents(instance_id, branch_id):
    branch = history.get_branch(instance_id, branch_id)
    documents = {key: history.get_revision(instance_id, revision)["document"]
                 for key, revision in branch["profiles"].items()}
    draft = history.get_draft(instance_id, branch_id)
    if draft:
        if draft["base_state"] != branch["state"]:
            raise operations.OperationError("draft_base_changed", 409)
        documents.update(draft["documents"])
    return branch, draft, documents


def _read_document(instance, kind, name):
    from .profile_edit import make_document
    if kind not in ("machine", "process", "filament") or not isinstance(name, str):
        raise operations.OperationError("invalid_profile", 400)
    scan = scanner.scan(instance.data_dir, instance.slicer)
    profiles = [p for p in [*scan.of_kind(kind), *scan.own] if p.kind == kind and p.name == name]
    if len(profiles) != 1:
        raise operations.OperationError("profile_not_found", 404)
    profile = profiles[0]
    # The account folder is part of the identity; equal names in different accounts
    # must never inherit one another's local timeline.
    from .profile_observe import identity_for
    from .profile_native import native_document_metadata
    metadata = native_document_metadata(instance, profile)
    identity_path = str(profile.file) if not profile.package or metadata else f"{profile.package}/{kind}/{profile.name}"
    profile_id = identity_for(instance.id, instance.active_user_folder, kind, identity_path, profile.name)
    catalog = profile_schema.load_catalog(instance.slicer, instance.version)
    document = make_document(profile_id, profile, Resolver(scan), catalog)
    document.update(metadata)
    document["context"]["user_folder"] = instance.active_user_folder
    return document


@router.get("/catalog")
def catalog(instance_id: str):
    instance = _instance(instance_id)
    value = profile_schema.load_catalog(instance.slicer, instance.version)
    return {"catalog": value, "supported": bool(value and value.get("complete")),
            "slicer": instance.slicer, "version": instance.version}


@router.get("/document")
def document(instance_id: str, kind: str, name: str):
    return _read_document(_instance(instance_id), kind, name)


@router.post("/branches")
def create_branch(instance_id: str, body: dict = Body(...)):
    instance = _instance(instance_id)
    state_id = body.get("state_id")
    if state_id is None:
        profiles = body.get("profiles")
        if not isinstance(profiles, list) or not 1 <= len(profiles) <= MAX_SCOPE:
            raise operations.OperationError("invalid_scope", 400)
        revisions = {}
        documents = []
        for profile in profiles:
            if not isinstance(profile, dict):
                raise operations.OperationError("invalid_profile", 400)
            documents.append(_read_document(instance, profile.get("kind"), profile.get("name")))
        from .profile_live import capture
        observed = capture(instance)
        if observed.get("unstable") or observed.get("pending") or not observed.get("state"):
            raise operations.OperationError("scan_unstable", 409)
        observed_state = history.get_state(instance_id, observed["state"])
        for doc in documents:
            revision_id = observed_state["profiles"].get(doc["id"])
            if not revision_id or history.get_revision(instance_id, revision_id)["document"] != doc:
                raise operations.OperationError("scan_unstable", 409)
            revisions[doc["id"]] = revision_id
        state_id = history.save_state(instance_id, revisions, [], "")
        selected = list(revisions)
    else:
        selected = _scope(body.get("selected"))
    return history.create_branch(instance_id, body.get("name"), state_id, selected)


@router.get("/branches/{branch_id}")
def read_branch(instance_id: str, branch_id: str):
    _instance(instance_id)
    branch, draft, documents = _documents(instance_id, branch_id)
    names = {key: doc["name"] for key, doc in documents.items()}
    missing = set(branch["selected"]) - set(names)
    for state_id in reversed(branch.get("states", [branch["state"]])):
        if not missing:
            break
        state = history.get_state(instance_id, state_id)
        for profile_id in list(missing):
            if profile_id in state["profiles"]:
                names[profile_id] = history.get_revision(instance_id, state["profiles"][profile_id])["document"]["name"]
                missing.remove(profile_id)
    return {"branch": branch, "draft_generation": draft["generation"] if draft else 0,
            "documents": documents, "profile_names": names}


def _patched(instance, body):
    from .profile_edit import apply_patches
    branch, draft, documents = _documents(instance.id, body.get("branch_id"))
    patches = body.get("patches")
    if not isinstance(patches, list) or len(patches) > 2000:
        raise operations.OperationError("invalid_patches", 400)
    catalog = profile_schema.load_catalog(instance.slicer, instance.version)
    catalogs = {catalog["id"]: catalog} if catalog else {}
    return {**apply_patches(documents, patches, catalogs), "branch_generation": branch["generation"]}


@router.post("/patch-preview")
def patch_preview(instance_id: str, body: dict = Body(...)):
    return _patched(_instance(instance_id), body)


@router.put("/drafts/{branch_id}")
def save_draft(instance_id: str, branch_id: str, body: dict = Body(...)):
    instance = _instance(instance_id)
    expected = _generation(body)
    result = _patched(instance, {**body, "branch_id": branch_id})
    if any(issue.get("severity") == "error" for issue in result["issues"]):
        return {"saved": False, **result}
    selected = _scope(body["selected"]) if "selected" in body else []
    touched = set(selected) | {patch["profile_id"] for patch in body.get("patches", [])}
    if not touched.issubset(result["documents"]):
        raise operations.OperationError("invalid_scope", 400)
    old = history.get_draft(instance_id, branch_id)
    staged = dict(old["documents"]) if old else {}
    staged.update({key: result["documents"][key] for key in touched})
    draft = history.save_draft(instance_id, branch_id, expected, staged,
                               expected_branch_generation=result["branch_generation"])
    return {"saved": True, "generation": draft["generation"], **result}


@router.post("/diff")
def diff(instance_id: str, body: dict = Body(...)):
    from .profile_merge import diff_values
    _instance(instance_id)
    before = history.get_state(instance_id, body.get("before"))
    after = history.get_state(instance_id, body.get("after"))
    result = {}
    for profile_id in _scope(body.get("selected")):
        if profile_id not in before["profiles"] and profile_id not in after["profiles"]:
            raise operations.OperationError("profile_not_found", 404)
        values = []
        for state in (before, after):
            revision = state["profiles"].get(profile_id)
            values.append(history.get_revision(instance_id, revision)["document"].get("effective", {})
                          if revision else {})
        result[profile_id] = diff_values(*values)
    return {"profiles": result}


@router.get("/history")
def timeline(instance_id: str, cursor: str = "", limit: int = 50, branch_id: str = ""):
    instance = _instance(instance_id)
    if not 1 <= limit <= MAX_SCOPE:
        raise operations.OperationError("invalid_limit", 400)
    try:
        offset = json.loads(base64.b64decode(cursor, validate=True)) if cursor else 0
        if type(offset) is not int or offset < 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise operations.OperationError("invalid_cursor", 400) from None
    from .profile_live import capture
    observation = capture(instance)
    observations = []
    for ref in list_refs(instance_id):
        if ref.get("type") == "observation" and ref.get("user_folder") == instance.active_user_folder:
            observations = [{"id": state_id, **history.get_state(instance_id, state_id)}
                            for state_id in ref.get("states", [])]
    branches = sorted(history.list_branches(instance_id), key=lambda b: (b["created"], b["id"]))
    states = history.list_states(instance_id, branch_id) if branch_id else []
    next_offset = offset + limit
    return {"branches": branches[offset:next_offset], "states": states[offset:next_offset],
            "observations": observations[offset:next_offset], "observation": observation,
            "cursor": base64.b64encode(json.dumps(next_offset).encode()).decode()
            if next_offset < max(len(branches), len(states), len(observations)) else None}


@router.post("/states")
def checkpoint(instance_id: str, body: dict = Body(...)):
    _instance(instance_id)
    expected_branch = body.get("expected_branch_generation")
    if type(expected_branch) is not int or expected_branch < 1:
        raise operations.OperationError("invalid_generation", 400)
    note = body.get("note", "")
    if not isinstance(note, str) or len(note) > 500:
        raise operations.OperationError("invalid_note", 400)
    return history.commit_draft(instance_id, body.get("branch_id"), _scope(body.get("selected")),
                                _generation(body), expected_branch, note)


@router.post("/merge-preview")
def merge_preview(instance_id: str, body: dict = Body(...)):
    from .profile_workflows import preview_history
    _instance(instance_id)
    return preview_history(instance_id, body.get("branch_id"), body.get("source_state"),
                           _scope(body.get("selected")), "merge")


@router.post("/restore-preview")
def restore_preview(instance_id: str, body: dict = Body(...)):
    from .profile_workflows import preview_history
    _instance(instance_id)
    return preview_history(instance_id, body.get("branch_id"), body.get("source_state"),
                           _scope(body.get("selected")), "restore")


@router.post("/history-draft")
def history_draft(instance_id: str, body: dict = Body(...)):
    from .profile_workflows import adopt_history
    instance = _instance(instance_id)
    fields = body.get("fields")
    if not isinstance(fields, dict):
        raise operations.OperationError("invalid_scope", 400)
    _scope(list(fields))
    if any(not isinstance(keys, list) or len(keys) > 2000 or
           any(not isinstance(key, str) for key in keys) for keys in fields.values()):
        raise operations.OperationError("invalid_fields", 400)
    catalog = profile_schema.load_catalog(instance.slicer, instance.version)
    return adopt_history(instance_id, body.get("branch_id"), body.get("source_state"), fields,
                         _generation(body), body.get("mode"), {catalog["id"]: catalog} if catalog else {})


@router.post("/restore-state-preview")
def restore_state_preview(instance_id: str, body: dict = Body(...)):
    _instance(instance_id)
    branch = history.get_branch(instance_id, body.get("branch_id"))
    state = history.get_state(instance_id, body.get("source_state"))
    selected = _scope(body.get("selected"))
    if not set(selected).issubset(branch["selected"]):
        raise operations.OperationError("invalid_scope", 400)
    changes = []
    for profile_id in selected:
        old_id, new_id = branch["profiles"].get(profile_id), state["profiles"].get(profile_id)
        if not new_id and profile_id not in state["removed"]:
            raise operations.OperationError("historical_profile_missing", 404)
        old = history.get_revision(instance_id, old_id)["document"] if old_id else None
        new = history.get_revision(instance_id, new_id)["document"] if new_id else None
        changes.append({"profile_id": profile_id, "name": (new or old or {}).get("name", profile_id),
                        "action": "remove" if new is None else "restore", "before": old, "after": new})
    return {"changes": changes, "branch_generation": branch["generation"]}


@router.post("/restore-state")
def restore_state(instance_id: str, body: dict = Body(...)):
    _instance(instance_id)
    expected = body.get("expected_branch_generation")
    if type(expected) is not int or expected < 1:
        raise operations.OperationError("invalid_generation", 400)
    return {"branch": history.restore_state(instance_id, body.get("branch_id"), body.get("source_state"),
                                             _scope(body.get("selected")), expected)}


@router.post("/publish-preview")
def publish_preview(instance_id: str, body: dict = Body(...)):
    from .profile_jobs import report
    report("check")
    from .profile_publish import prepare_changes, current_target
    from .profile_edit import make_document
    from .profile_merge import diff_values
    instance, processes = operations.find_instance(instance_id)
    selected = _scope(body.get("selected"))
    branch = history.get_branch(instance_id, body.get("branch_id"))
    if body.get("state_id") != branch["state"] or not set(selected).issubset(branch["selected"]):
        raise operations.OperationError("plan_outdated", 409)
    draft = history.get_draft(instance_id, branch["id"])
    if draft and set(selected).intersection(draft["documents"]):
        raise operations.OperationError("draft_not_committed", 409)
    changes = prepare_changes(instance, {"state_id": branch["state"], "selected": selected}, current_target(instance))
    plan = operations.make_plan(instance, processes, changes)
    scan = scanner.scan(instance.data_dir, instance.slicer)
    resolver = Resolver(scan)
    catalog = profile_schema.load_catalog(instance.slicer, instance.version)
    diffs = []
    report("diff", 0, len(selected))
    for profile_index, profile_id in enumerate(selected):
        target = history.get_revision(instance_id, branch["profiles"][profile_id])["document"]
        live = next((p for p in scan.own if p.kind == target["kind"] and p.name == target.get("rename_from", target["name"])), None)
        before = make_document(profile_id, live, resolver, catalog) if live else {}
        options = (catalog or {}).get("options", {}).get(target["kind"], {})
        def values(document):
            return {key: value for key, value in document.get("effective", {}).items()
                    if options.get(key, {}).get("role") not in {"metadata", "secret"}}
        diffs.append({"profile_id": profile_id, "name": target["name"], "fields": diff_values(values(before), values(target)),
                      "rename": {"before": target.get("rename_from", target["name"]), "after": target["name"]},
                      "inherits": {"before": before.get("inherits", ""), "after": target.get("inherits", "")}})
        report("diff", profile_index + 1, len(selected))
    return {**plan, "profile_diffs": diffs}


@router.post("/publish-preview-job")
def publish_preview_job(instance_id: str, body: dict = Body(...)):
    from . import profile_jobs
    return profile_jobs.start(instance_id, "preview", body, lambda: publish_preview(instance_id, body))


@router.post("/apply-job")
def apply_job(instance_id: str, body: dict = Body(...)):
    from . import profile_jobs
    return profile_jobs.start(instance_id, "apply", body, lambda: operations.apply(instance_id, body.get("plan_id")))


@router.get("/jobs/{job_id}")
def profile_job(instance_id: str, job_id: str):
    from . import profile_jobs
    return profile_jobs.get(instance_id, job_id)


def _variant(instance_id, body):
    from .profile_variants import variant_changes
    from .profile_normalize import resolve_values
    instance = _instance(instance_id)
    branch, draft, documents = _documents(instance_id, body.get("branch_id"))
    source = documents.get(body.get("profile_id"))
    if source is None:
        raise operations.OperationError("profile_not_found", 404)
    configuration = body.get("configuration")
    choices = body.get("choices", {})
    if not isinstance(configuration, dict) or not isinstance(choices, dict):
        raise operations.OperationError("invalid_variant", 400)
    if not configuration.get("copy") and configuration.get("name", source["name"]) != source["name"]:
        raise operations.OperationError("rename_requires_copy", 409)
    if not set(choices).issubset(documents):
        raise operations.OperationError("invalid_scope", 400)
    result = variant_changes(source, body.get("target_model"), configuration, choices)
    result["basis"] = {"branch_generation": branch["generation"], "draft_generation": draft["generation"] if draft else 0}
    if "basis" in body and body["basis"] != result["basis"]:
        raise operations.OperationError("draft_conflict", 409)
    if result["issues"]:
        return branch, result
    catalog = profile_schema.load_catalog(instance.slicer, instance.version)
    doc = result["document"]
    if operations.name_problem(doc["name"]):
        result["issues"].append({"severity": "error", "code": "invalid_name"})
    if configuration.get("copy"):
        doc["source_revision"] = branch["profiles"].get(source["id"])
    normalized = resolve_values(catalog or {}, "machine", [{"id": doc["id"], "values": doc["effective"]}],
                                {"chain_complete": True})
    if normalized["values"] != doc["effective"] or not normalized["complete"]:
        result["issues"].append({"severity": "error", "code": "dimension_scope_expansion"})
    output = {doc["id"]: doc}
    for profile_id, choice in choices.items():
        if choice == "leave":
            continue
        from copy import deepcopy
        related = deepcopy(documents[profile_id])
        if related["kind"] not in ("process", "filament"):
            result["issues"].append({"severity": "error", "code": "invalid_reference"})
            continue
        if choice == "copy":
            from uuid import uuid4
            names_by_id = body.get("copy_names", {})
            name = names_by_id.get(profile_id) if isinstance(names_by_id, dict) else None
            if not isinstance(name, str) or operations.name_problem(name):
                result["issues"].append({"severity": "error", "code": "copy_name_required", "profile_id": profile_id})
                continue
            related.update(id=uuid4().hex, name=name, copied_from=profile_id,
                           source_revision=branch["profiles"].get(profile_id), inherits="", inherited={})
            related["own"] = deepcopy(related["effective"])
            related["own"]["compatible_printers"] = [doc["name"]]
            related["effective"]["compatible_printers"] = [doc["name"]]
        names = related["effective"].get("compatible_printers", [])
        # Empty is unrestricted and stays unrestricted. Explicit bindings gain only
        # the chosen variant; existing printer bindings remain in place.
        if names and doc["name"] not in names:
            related["own"]["compatible_printers"] = [*names, doc["name"]]
            related["effective"]["compatible_printers"] = [*names, doc["name"]]
        output[related["id"]] = related
    result["documents"] = output
    for document in output.values():
        options = (catalog or {}).get("options", {}).get(document["kind"], {})
        document["references"] = [{"key": key, "value": value} for key, value in document["effective"].items()
                                  if options.get(key, {}).get("role") == "reference"]
        if document.get("inherits"):
            document["references"].append({"key": "inherits", "value": document["inherits"]})
        for key, value in document["own"].items():
            document["origins"][key] = {"kind": "profile", "profile_id": document["id"], "schema_id": document["schema_id"]}
    return branch, result


@router.post("/variant-preview")
def variant_preview(instance_id: str, body: dict = Body(...)):
    return _variant(instance_id, body)[1]


@router.post("/variant-branch")
def variant_branch(instance_id: str, body: dict = Body(...)):
    _instance(instance_id)
    if not isinstance(body.get("basis"), dict):
        raise operations.OperationError("preview_required", 400)
    branch, result = _variant(instance_id, body)
    if result["issues"]:
        return {"created": False, **result}
    revisions = {}
    for profile_id, document in result["documents"].items():
        parent = branch["profiles"].get(profile_id)
        revisions[profile_id] = history.save_revision(instance_id, document, [parent] if parent else [],
                                                       {"source": "variant", "source_state": branch["state"]})
    state = history.save_state(instance_id, revisions, [], "variant")
    created = history.create_branch(instance_id, body.get("name"), state, list(revisions))
    return {"created": True, "branch": created, "issues": []}


@router.post("/copy-branch")
def copy_branch(instance_id: str, body: dict = Body(...)):
    from copy import deepcopy
    from uuid import uuid4
    _instance(instance_id)
    branch, draft, documents = _documents(instance_id, body.get("branch_id"))
    source = documents.get(body.get("profile_id"))
    name = body.get("name")
    if source is None:
        raise operations.OperationError("profile_not_found", 404)
    if not source.get("complete"):
        raise operations.OperationError("profile_incomplete", 409)
    if not isinstance(name, str) or operations.name_problem(name):
        raise operations.OperationError("invalid_name", 400)
    document = deepcopy(source)
    document.update(id=uuid4().hex, name=name, inherits="", inherited={}, inherited_origins={},
                    copied_from=source["id"], source_revision=branch["profiles"].get(source["id"]))
    document["own"] = deepcopy(document["effective"])
    document["references"] = [ref for ref in document["references"] if ref["key"] != "inherits"]
    document["origins"] = {key: {"kind": "profile", "profile_id": document["id"], "schema_id": document["schema_id"]}
                           for key in document["effective"]}
    revision = history.save_revision(instance_id, document, [], {"source": "copy", "source_state": branch["state"]})
    state = history.save_state(instance_id, {document["id"]: revision}, [], "copy")
    return {"branch": history.create_branch(instance_id, body.get("branch_name", name), state, [document["id"]]), "issues": []}


@router.post("/suggestions")
def suggestions(instance_id: str, body: dict = Body(...)):
    from .profile_variants import suggest_nozzle_changes
    instance = _instance(instance_id)
    _, _, documents = _documents(instance_id, body.get("branch_id"))
    source, target = documents.get(body.get("profile_id")), documents.get(body.get("target_profile_id"))
    if source is None or target is None:
        raise operations.OperationError("profile_not_found", 404)
    catalog = profile_schema.load_catalog(instance.slicer, instance.version)
    return {"suggestions": suggest_nozzle_changes(source, target, catalog or {})}


@router.post("/conversion-preview")
def conversion_preview(instance_id: str, body: dict = Body(...)):
    from copy import deepcopy
    import hashlib
    from .profile_normalize import resolve_values
    from .profile_publish import current_target
    from .profile_store import put_object
    from .profile_transfer import conversion_report
    target = _instance(instance_id)
    source_instance = _instance(body.get("source_instance_id"))
    catalog = profile_schema.load_catalog(target.slicer, target.version)
    if not catalog or not catalog.get("complete"):
        raise operations.OperationError("schema_unavailable", 409)
    _, _, documents = _documents(source_instance.id, body.get("source_branch_id"))
    selected = _scope(body.get("selected"))
    names = body.get("names")
    if not isinstance(names, dict) or not set(selected).issubset(documents):
        raise operations.OperationError("invalid_scope", 400)
    reports = {}
    for profile_id in selected:
        name = names.get(profile_id)
        if not isinstance(name, str) or operations.name_problem(name):
            raise operations.OperationError("invalid_name", 400)
        report = conversion_report(documents[profile_id], catalog)
        document = report["document"]
        original = deepcopy(document["effective"])
        normalized = resolve_values(catalog, document["kind"], [{"id": document["id"], "values": original}],
                                    {"chain_complete": True})
        for key, value in original.items():
            if normalized["values"].get(key) != value:
                loss = {"key": key, "code": "normalization_changed", "before": value,
                        "after": normalized["values"].get(key)}
                loss["id"] = hashlib.sha256(json.dumps(loss, sort_keys=True).encode()).hexdigest()[:24]
                report["losses"].append(loss)
        report["issues"].extend(normalized["issues"])
        document.update(name=name, origin_kind="user", own=deepcopy(normalized["values"]),
                        effective=normalized["values"], origins=normalized["origins"],
                        inherited_origins={}, complete=False,
                        context={**normalized["context"], "user_folder": target.active_user_folder})
        report["ready"] = False
        reports[profile_id] = report
    value = {"type": "conversion", "profiles": reports, "expected": current_target(target),
             "source_instance_id": source_instance.id}
    report_id = put_object(instance_id, value)
    return {"id": report_id, "profiles": reports}


@router.post("/composer-preview")
def composer_preview(instance_id: str, body: dict = Body(...)):
    from .profile_composer import prepare_preview
    return prepare_preview(_instance(instance_id), body)


@router.post("/composer-branch")
def composer_branch(instance_id: str, body: dict = Body(...)):
    from .profile_composer import create_branch
    branch = create_branch(_instance(instance_id), body.get("preview_id"), body.get("name"))
    return {"created": True, "branch": branch, "issues": []}


@router.post("/composer-repair-plan")
def composer_repair_plan(instance_id: str, body: dict = Body(...)):
    from .profile_composer import prepare_repair_plan
    instance, processes = operations.find_instance(instance_id)
    return prepare_repair_plan(instance, processes, body.get("preview_id"))


@router.post("/composer-refresh")
def composer_refresh(instance_id: str, body: dict = Body(...)):
    from .profile_composer import refresh_branch
    return {"branch": refresh_branch(_instance(instance_id), body.get("branch_id"))}


@router.post("/printer-merge-preview")
def printer_merge_preview(instance_id: str, body: dict = Body(...)):
    from .profile_printer_merge import prepare_preview
    return prepare_preview(_instance(instance_id), body)


@router.post("/printer-merge-branch")
def printer_merge_branch(instance_id: str, body: dict = Body(...)):
    from .profile_printer_merge import create_merge_branch
    branch = create_merge_branch(_instance(instance_id), body.get("preview_id"), body.get("name"))
    return {"created": True, "branch": branch, "issues": []}


@router.post("/conversion-branch")
def conversion_branch(instance_id: str, body: dict = Body(...)):
    from .profile_publish import check_target, current_target
    from .profile_store import get_object
    from .profile_transfer import confirm_conversion
    instance = _instance(instance_id)
    preview = get_object(instance_id, body.get("preview_id"))
    if preview.get("type") != "conversion":
        raise operations.OperationError("invalid_preview", 400)
    check_target(preview["expected"], current_target(instance))
    confirmed = body.get("confirmed_losses")
    if not isinstance(confirmed, dict):
        raise operations.OperationError("invalid_confirmation", 400)
    documents = []
    for profile_id, report in preview["profiles"].items():
        selected = confirmed.get(profile_id, [])
        if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
            raise operations.OperationError("invalid_confirmation", 400)
        accepted = confirm_conversion(report, selected)
        if not accepted["ready"]:
            raise operations.OperationError("conversion_unconfirmed", 409)
        documents.append(accepted["document"])
    revisions = {doc["id"]: history.save_revision(instance_id, doc, [], doc["provenance"]) for doc in documents}
    state = history.save_state(instance_id, revisions, [], "cross_slicer_copy")
    branch = history.create_branch(instance_id, body.get("name"), state, list(revisions))
    return {"branch": branch}

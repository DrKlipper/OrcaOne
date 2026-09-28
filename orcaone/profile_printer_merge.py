"""Explicit printer/model merge previews; no Slicer files are written here."""

from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from . import operations, profile_history as history, scanner
from .profile_edit import make_document
from .profile_normalize import resolve_values
from .profile_observe import identity_for
from .profile_schema import load_catalog, validate_value
from .profile_store import get_object, put_object
from .resolver import Resolver


MAX_SCOPE = 200


def _error(code, **params):
    raise operations.OperationError(code, 409, **params)


def _text(value, code):
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        _error(code)
    return value.strip()


def _materialize(document):
    result = deepcopy(document)
    result.update(own=deepcopy(result["effective"]), inherits="", inherited={}, inherited_origins={},
                  own_unknown=deepcopy(result.get("unknown", {})), inherited_unknown={})
    result["references"] = [ref for ref in result.get("references", []) if ref["key"] != "inherits"]
    result["origins"] = {key: {"kind": "profile", "profile_id": result["id"], "schema_id": result["schema_id"]}
                         for key in result["effective"]}
    return result


def build_merge(documents: list[dict], catalog: dict, configuration: dict,
                process_documents: dict | None = None, taken_process_names=()) -> dict:
    """Pure merge construction from already authenticated, resolved documents."""
    if not 2 <= len(documents) <= MAX_SCOPE or len({doc["id"] for doc in documents}) != len(documents):
        _error("invalid_scope")
    if not catalog or not catalog.get("complete"):
        _error("schema_unavailable")
    name = _text(configuration.get("group_name"), "invalid_group_name")
    model = _text(configuration.get("target_model"), "invalid_model")
    variants = configuration.get("variants")
    if (not isinstance(variants, list) or len(variants) != len(documents)
            or any(not isinstance(v, dict) or not isinstance(v.get("name"), str) for v in variants)):
        _error("invalid_variants")
    variants_by_name = {v["name"]: v for v in variants}
    if len(variants_by_name) != len(variants) or set(variants_by_name) != {doc["name"] for doc in documents}:
        _error("invalid_variants")
    labels = [_text(v.get("label"), "invalid_variant_label") for v in variants]
    if len({label.casefold() for label in labels}) != len(labels):
        _error("variant_label_duplicate")
    group = {"id": uuid4().hex, "display_name": name, "target_model": model,
             "names": [doc["name"] for doc in documents], "profile_ids": [doc["id"] for doc in documents],
             "labels": {v["name"]: label for v, label in zip(variants, labels)},
             "user_folder": documents[0].get("context", {}).get("user_folder")}
    output = {}
    for source in documents:
        if source.get("kind") != "machine" or source.get("origin_kind") not in {"user", "own"}:
            _error("printer_merge_own_only", name=source.get("name"))
        if (not source.get("complete") or source.get("schema_id") != catalog["id"]
                or not source.get("context", {}).get("chain_complete")
                or source.get("context", {}).get("user_folder") != group["user_folder"]):
            _error("profile_incomplete", name=source["name"])
        variant = variants_by_name[source["name"]]
        values = deepcopy(source["effective"])
        diameters = variant.get("nozzle_diameter", values.get("nozzle_diameter"))
        if (not isinstance(diameters, list) or not diameters
                or validate_value(catalog["options"]["machine"]["nozzle_diameter"], diameters)
                or any(Decimal(value) <= 0 for value in diameters)):
            _error("invalid_nozzle", name=source["name"])
        if len(diameters) != len(values.get("nozzle_diameter", [])):
            _error("dimension_scope_expansion", name=source["name"])
        values.update(printer_model=model, nozzle_diameter=deepcopy(diameters))
        normalized = resolve_values(catalog, "machine", [{"id": source["id"], "values": values}], source["context"])
        if not normalized["complete"] or normalized["values"] != values:
            _error("dimension_scope_expansion", name=source["name"])
        document = _materialize({**source, "effective": values})
        document["variant_label"] = group["labels"][source["name"]]
        document["model_group"] = group["id"]
        output[document["id"]] = document
    choices = configuration.get("process_choices", [])
    if not isinstance(choices, list) or len(choices) > MAX_SCOPE:
        _error("invalid_process_choices")
    used, taken = set(), {n.casefold() for n in taken_process_names}
    process_documents = process_documents or {}
    for choice in choices:
        if (not isinstance(choice, dict) or not isinstance(choice.get("name"), str)
                or choice.get("action") not in {"leave", "share", "copy"} or choice["name"] in used):
            _error("invalid_process_choices")
        used.add(choice["name"])
        if choice["action"] == "leave":
            continue
        source = process_documents.get(choice["name"])
        if not source or not source.get("complete") or source.get("schema_id") != catalog["id"]:
            _error("profile_incomplete", name=choice["name"])
        targets = choice.get("targets")
        if (not isinstance(targets, list) or not targets or any(not isinstance(t, str) for t in targets)
                or len(set(targets)) != len(targets) or not set(targets).issubset(group["names"])):
            _error("invalid_process_targets", name=choice["name"])
        if source["effective"].get("compatible_printers_condition"):
            _error("condition_unknown", name=choice["name"])
        document = deepcopy(source)
        if choice["action"] == "copy":
            copy_name = _text(choice.get("copy_name"), "copy_name_required")
            if operations.name_problem(copy_name) or copy_name.casefold() in taken:
                _error("name_taken", name=copy_name)
            taken.add(copy_name.casefold())
            document.update(id=uuid4().hex, name=copy_name, copied_from=source["id"], origin_kind="user", package="")
            document["effective"]["compatible_printers"] = list(targets)
            document = _materialize(document)
        else:
            if source.get("origin_kind") not in {"user", "own"}:
                _error("process_copy_required", name=source["name"])
            current = source["effective"].get("compatible_printers", [])
            if not isinstance(current, list):
                _error("profile_incomplete", name=source["name"])
            # An empty list is unrestricted; never narrow its existing reach.
            if current:
                current = [*current, *(target for target in targets if target not in current)]
                document["own"]["compatible_printers"] = deepcopy(current)
                document["effective"]["compatible_printers"] = current
        document["references"] = [ref for ref in document.get("references", []) if ref["key"] != "compatible_printers"]
        document["references"].append({"key": "compatible_printers", "value": deepcopy(document["effective"]["compatible_printers"])})
        output[document["id"]] = document
    if len(output) > MAX_SCOPE:
        _error("invalid_scope")
    group["required_profile_ids"] = list(output)
    for document in output.values():
        document["printer_merge_group"] = deepcopy(group)
    return {"group": group, "documents": output, "issues": []}


def prepare_preview(instance, configuration: dict) -> dict:
    from .profile_publish import check_target, current_target
    expected = current_target(instance)
    profiles = configuration.get("profiles")
    if (not isinstance(profiles, list) or not 2 <= len(profiles) <= MAX_SCOPE
            or any(not isinstance(p, dict) or p.get("kind", "machine") != "machine" or not isinstance(p.get("name"), str) for p in profiles)
            or len({p["name"] for p in profiles}) != len(profiles)):
        _error("invalid_scope")
    scan = scanner.scan(instance.data_dir, instance.slicer)
    resolver = Resolver(scan)
    catalog = load_catalog(instance.slicer, instance.version)
    all_profiles = [*scan.profiles.values(), *scan.own]
    def read(kind, name):
        matches = [p for p in all_profiles if p.kind == kind and p.name == name]
        if len(matches) != 1:
            _error("profile_not_found", name=name)
        profile = matches[0]
        if profile.bundle:
            _error("bundle_profile", name=name)
        path = profile.file if not profile.package else f"{profile.package}/{kind}/{profile.name}"
        pid = identity_for(instance.id, scan.active_folder, kind, path, name)
        doc = make_document(pid, profile, resolver, catalog)
        doc["context"]["user_folder"] = scan.active_folder
        return doc
    documents = [read("machine", p["name"]) for p in profiles]
    choices = configuration.get("process_choices", [])
    if not isinstance(choices, list) or any(not isinstance(c, dict) for c in choices):
        _error("invalid_process_choices")
    processes = {c["name"]: read("process", c["name"]) for c in choices
                 if isinstance(c.get("name"), str) and c.get("action") in {"share", "copy"}}
    result = build_merge(documents, catalog, configuration, processes,
                         [p.name for p in all_profiles if p.kind == "process"])
    candidates = []
    for profile in all_profiles:
        if profile.kind == "process" and profile.selectable and not profile.bundle:
            candidates.append({"name": profile.name, "origin_kind": profile.origin_kind,
                               "compatible_printers": deepcopy(resolver.value(profile, "compatible_printers") or []),
                               "condition": resolver.value(profile, "compatible_printers_condition") or "",
                               "complete": resolver.chain(profile)[1] and not profile.problem})
    from .profile_groups import ProfileGroupError, validate_group
    group = result["group"]
    try:
        validate_group(instance.id, group["id"], group["names"], group["display_name"], labels=group["labels"], user_folder=group["user_folder"])
    except ProfileGroupError as exc:
        _error(exc.code)
    check_target(expected, current_target(instance))
    preview = {"type": "printer_merge_preview", "expected": expected, **result,
               "sources": {doc["id"]: doc for doc in [*documents, *processes.values()]}}
    preview_id = put_object(instance.id, preview)
    return {"preview_id": preview_id, **result, "process_candidates": candidates}


def create_merge_branch(instance, preview_id, name=None):
    from .profile_publish import check_target, current_target
    preview = get_object(instance.id, preview_id)
    if preview.get("type") != "printer_merge_preview":
        _error("invalid_preview")
    check_target(preview["expected"], current_target(instance))
    sources = {pid: history.save_revision(instance.id, doc, [], {"source": "printer_merge_basis"})
               for pid, doc in preview["sources"].items()}
    revisions = {}
    for pid, original in preview["documents"].items():
        doc = deepcopy(original)
        doc["printer_merge_group"]["preview_id"] = preview_id
        if doc.get("copied_from") in sources:
            doc["source_revision"] = sources[doc["copied_from"]]
        revisions[pid] = history.save_revision(instance.id, doc, [sources[pid]] if pid in sources else [],
                                               {"source": "printer_merge", "preview_id": preview_id})
    check_target(preview["expected"], current_target(instance))
    state = history.save_state(instance.id, revisions, [], "printer_merge")
    return history.create_branch(instance.id, name or preview["group"]["display_name"], state, list(revisions))

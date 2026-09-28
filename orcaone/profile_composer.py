"""Server-built profile compositions and explicit, typed rename closure."""

from copy import deepcopy
from uuid import uuid4

from . import operations, profile_history as history, scanner
from .profile_edit import make_document
from .profile_normalize import resolve_values
from .profile_observe import identity_for
from .profile_printer_merge import _error, _materialize, _text
from .profile_schema import load_catalog, validate_value
from .profile_store import get_object, put_object
from .profile_variants import variant_changes
from .profile_native import native_document_metadata, supported as native_supported, _variant
from .resolver import Resolver


REFERENCE_KINDS = {"compatible_printers": "machine", "compatible_prints": "process",
                   "default_print_profile": "process", "default_filament_profile": "filament",
                   "upward_compatible_machine": "machine"}


def _set_reference(document, key, value):
    if key == "inherits":
        document["inherits"] = value
    else:
        document["own"][key] = deepcopy(value)
        document["effective"][key] = deepcopy(value)
    document["references"] = [r for r in document.get("references", []) if r["key"] != key]
    document["references"].append({"key": key, "value": deepcopy(value)})


def prepare_preview(instance, configuration):
    from .profile_publish import check_target, current_target
    expected = current_target(instance)
    variants, assignments = configuration.get("variants"), configuration.get("assignments", [])
    if (not isinstance(variants, list) or not 1 <= len(variants) <= 200
            or not isinstance(assignments, list) or len(assignments) > 200
            or any(not isinstance(v, dict) for v in [*variants, *assignments])):
        _error("invalid_scope")
    group_name = _text(configuration.get("group_name"), "invalid_group_name")
    model = _text(configuration.get("target_model"), "invalid_model")
    catalog = load_catalog(instance.slicer, instance.version)
    if not catalog or not catalog.get("complete"):
        _error("schema_unavailable")
    native = native_supported(instance)
    if native:
        model = group_name
    scan = scanner.scan(instance.data_dir, instance.slicer)
    resolver = Resolver(scan)
    profiles = [*scan.profiles.values(), *scan.own]
    sources, output, renames, impacts, keys, repairs = {}, {}, {}, [], {}, {}
    taken = {(p.kind, p.name.casefold()) for p in profiles}

    def read(kind, name):
        matches = [p for p in profiles if p.kind == kind and p.name == name]
        if len(matches) != 1 or matches[0].bundle:
            _error("profile_not_found", name=name)
        profile = matches[0]
        metadata = native_document_metadata(instance, profile)
        path = profile.file if not profile.package or metadata else f"{profile.package}/{kind}/{name}"
        pid = identity_for(instance.id, scan.active_folder, kind, path, name)
        if pid not in sources:
            doc = make_document(pid, profile, resolver, catalog)
            doc.update(metadata)
            doc["context"]["user_folder"] = scan.active_folder
            sources[pid] = doc
        return deepcopy(sources[pid])

    def ready(doc):
        if not doc.get("complete") or not doc.get("context", {}).get("chain_complete"):
            options = catalog["options"][doc["kind"]]
            values = deepcopy(doc["effective"])
            converted = []
            issues = []
            for issue in doc.get("issues", []):
                key = issue.get("key")
                option = options.get(key, {})
                value = values.get(key)
                issues.append({**issue, "value": value, "expected": option.get("type"),
                               "origin": doc.get("origins", {}).get(key, {}).get("profile_id")})
                if (issue["code"] == "invalid_type" and option.get("type") == "coEnums"
                        and isinstance(value, str) and not validate_value(option, [value])):
                    values[key] = [value]
                    converted.append(key)
            normalized = resolve_values(catalog, doc["kind"], [{"id": doc["id"], "values": values}], doc["context"])
            repairable = bool(converted) and normalized["complete"]
            if configuration.get("repair_compatibility") is not True or not repairable:
                _error("profile_incomplete", name=doc["name"], issues=issues, repairable=repairable,
                       schema_id=catalog["id"])
            for key, value in normalized["values"].items():
                if value != doc["effective"].get(key):
                    impacts.append({"profile_id": doc["id"], "name": doc["name"], "key": key,
                                    "before": doc["effective"].get(key), "after": value,
                                    "reason": "compatibility_conversion"})
                    doc["own"][key] = deepcopy(value)
            doc.update(effective=normalized["values"], context=normalized["context"],
                       complete=True, issues=normalized["issues"])
            repairs[doc["id"]] = deepcopy(doc)

    def identity(source, name, copy):
        name = _text(name, "invalid_name")
        if operations.name_problem(name):
            _error("invalid_name", name=name)
        if (copy or name != source["name"]) and (source["kind"], name.casefold()) in taken:
            _error("name_taken", name=name)
        if not copy and source.get("origin_kind") not in {"own", "user"}:
            _error("process_copy_required", name=source["name"])
        taken.add((source["kind"], name.casefold()))
        doc = deepcopy(source)
        doc["name"] = name
        if copy:
            doc.update(id=uuid4().hex, copied_from=source["id"], origin_kind="user", package="")
            doc = _materialize(doc)
        elif name != source["name"]:
            doc["rename_from"] = source["name"]
            renames[(source["kind"], source["name"])] = name
            impacts.append({"profile_id": doc["id"], "name": name, "key": "name",
                            "before": source["name"], "after": name})
        return doc

    moved, used = [], set()
    for variant in variants:
        key = variant.get("key")
        if not isinstance(key, str) or not key or key in keys or variant.get("mode") not in {"copy", "move"}:
            _error("invalid_variants")
        source = read("machine", variant.get("source_name"))
        ready(source)
        if variant["mode"] == "move":
            if source.get("native_package"):
                _error("native_source_move_unsupported", name=source["name"])
            if source["id"] in used:
                _error("invalid_variants")
            used.add(source["id"])
            moved.append(source["name"])
        doc = identity(source, variant.get("name"), variant["mode"] == "copy")
        result = variant_changes(doc, model, {"nozzle_diameter": variant.get("nozzle_diameter")}, {})
        if result["issues"]:
            _error(result["issues"][0]["code"])
        doc = _materialize(result["document"])
        if native:
            nozzle_variant = _variant(doc["effective"])
            doc["own"]["printer_variant"] = nozzle_variant
            doc["effective"]["printer_variant"] = nozzle_variant
        if len(doc["effective"]["nozzle_diameter"]) != len(source["effective"].get("nozzle_diameter", [])):
            _error("dimension_scope_expansion")
        normalized = resolve_values(catalog, "machine", [{"id": doc["id"], "values": doc["effective"]}], doc["context"])
        if not normalized["complete"] or normalized["values"] != doc["effective"]:
            _error("dimension_scope_expansion")
        keys[key] = doc["name"]
        output[doc["id"]] = doc
    for assignment in assignments:
        kind, action = assignment.get("kind"), assignment.get("action")
        if kind not in {"process", "filament"} or action not in {"share", "copy", "move", "rename"}:
            _error("invalid_process_choices")
        source = read(kind, assignment.get("source_name"))
        ready(source)
        if action != "copy" and source["id"] in used:
            _error("invalid_process_choices")
        if action != "copy":
            used.add(source["id"])
        targets = assignment.get("targets", [])
        if (not isinstance(targets, list) or any(not isinstance(t, str) or t not in keys for t in targets)
                or len(set(targets)) != len(targets) or (not targets and action != "rename")):
            _error("invalid_process_targets")
        if any(v for k, v in source["effective"].items() if k.endswith("_condition")):
            _error("condition_unknown", name=source["name"])
        name = assignment.get("name", source["name"])
        doc = identity(source, name, action == "copy")
        current = doc["effective"].get("compatible_printers", [])
        if not isinstance(current, list):
            _error("profile_incomplete")
        names = [keys[t] for t in targets]
        if action == "copy":
            current = names
        elif action == "move":
            removed = assignment.get("from")
            if (not isinstance(removed, list) or not removed or not current
                    or any(not isinstance(n, str) or n not in current for n in removed)):
                _error("invalid_process_targets")
            current = [n for n in current if n not in removed]
            current.extend(n for n in names if n not in current)
        elif current:
            current = [*current, *(n for n in names if n not in current)]
        _set_reference(doc, "compatible_printers", current)
        output[doc["id"]] = doc

    if renames:
        candidates = {doc["id"]: doc for doc in (read(p.kind, p.name) for p in scan.own)}
        candidates.update(output)
        for doc in candidates.values():
            fields = {**doc["effective"], "inherits": doc.get("inherits", "")}
            changed = False
            for key, value in fields.items():
                condition_kind = {"compatible_printers_condition": "machine",
                                  "compatible_prints_condition": "process"}.get(key)
                if value and condition_kind and any(kind == condition_kind for kind, _ in renames):
                    _error("condition_unknown", name=doc["name"])
                target_kind = doc["kind"] if key == "inherits" else REFERENCE_KINDS.get(key)
                if not target_kind:
                    continue
                def replace(name):
                    return renames.get((target_kind, name), name) if isinstance(name, str) else name
                updated = [replace(n) for n in value] if isinstance(value, list) else replace(value)
                if isinstance(updated, list) and key in {"compatible_printers", "compatible_prints", "upward_compatible_machine"}:
                    updated = list(dict.fromkeys(updated))
                if updated != value:
                    ready(doc)
                    _set_reference(doc, key, updated)
                    impacts.append({"profile_id": doc["id"], "name": doc["name"], "key": key,
                                    "before": value, "after": updated})
                    changed = True
            if changed:
                output[doc["id"]] = doc
    # Preserve a child's resolved settings when a selected parent changes its
    # configuration. Make the loss of inheritance an explicit preview impact.
    changed_parents = set()
    for pid, doc in output.items():
        if pid not in sources:
            continue
        basis = deepcopy(sources[pid]["effective"])
        for key, target_kind in REFERENCE_KINDS.items():
            if key not in basis:
                continue
            value = basis[key]
            def renamed(name):
                return renames.get((target_kind, name), name) if isinstance(name, str) else name
            basis[key] = [renamed(n) for n in value] if isinstance(value, list) else renamed(value)
        if doc["effective"] != basis:
            changed_parents.add((doc["kind"], sources[pid]["name"]))
    for profile in scan.own:
        if not profile.inherits or (profile.kind, profile.inherits) not in changed_parents:
            continue
        source = read(profile.kind, profile.name)
        doc = output.get(source["id"], source)
        if not doc.get("inherits"):
            continue
        ready(doc)
        impacts.append({"profile_id": doc["id"], "name": doc["name"], "key": "inherits",
                        "before": doc["inherits"], "after": "", "reason": "preserve_child_configuration"})
        output[doc["id"]] = _materialize(doc)
    if len(output) > 200:
        _error("invalid_scope")
    machine_docs = [d for d in output.values() if d["name"] in keys.values() and d["kind"] == "machine"]
    if native:
        nozzle_names = {}
        for doc in machine_docs:
            nozzle_names.setdefault(doc["effective"]["printer_variant"], []).append(doc["name"])
        conflicts = [name for names in nozzle_names.values() if len(names) > 1 for name in names]
        if conflicts:
            _error("native_nozzle_conflict", names=conflicts)
    group = {"id": uuid4().hex, "display_name": group_name, "target_model": model,
             "names": list(keys.values()), "profile_ids": [d["id"] for d in machine_docs],
             "labels": {d["name"]: d["name"] for d in machine_docs}, "moved_names": moved,
             "user_folder": scan.active_folder, "required_profile_ids": list(output)}
    if native:
        group["native_model"] = True
    from .profile_groups import ProfileGroupError, validate_group
    try:
        validate_group(instance.id, group["id"], group["names"], group_name, labels=group["labels"],
                       user_folder=scan.active_folder, moved_names=moved)
    except ProfileGroupError as exc:
        _error(exc.code)
    for doc in output.values():
        doc["printer_merge_group"] = deepcopy(group)
    result = {"documents": output, "group": group, "issues": [], "impacts": impacts,
              "repairs": [{"name": doc["name"], "kind": doc["kind"]} for doc in repairs.values()]}
    check_target(expected, current_target(instance))
    preview_id = put_object(instance.id, {"type": "composer_preview", "expected": expected,
                                          "sources": sources, "configuration": deepcopy(configuration),
                                          "repair_documents": repairs, **result})
    return {"preview_id": preview_id, **result}


def prepare_repair_plan(instance, processes, preview_id):
    from .profile_publish import check_target, current_target, prepare_changes
    preview = get_object(instance.id, preview_id)
    if preview.get("type") != "composer_preview" or not preview.get("repair_documents"):
        _error("invalid_preview")
    check_target(preview["expected"], current_target(instance))
    revisions = {}
    for pid, document in preview["repair_documents"].items():
        source = preview["sources"][pid]
        if source.get("origin_kind") not in {"own", "user"}:
            _error("repair_vendor_profile", name=source["name"])
        # Start from the original: never include composition names or bindings.
        doc = deepcopy(source)
        doc.update(complete=True, issues=[], context=deepcopy(document["context"]))
        for impact in preview["impacts"]:
            if impact.get("reason") == "compatibility_conversion" and impact["profile_id"] == pid:
                doc["own"][impact["key"]] = deepcopy(impact["after"])
                doc["effective"][impact["key"]] = deepcopy(impact["after"])
        basis = history.save_revision(instance.id, source, [], {"source": "compatibility_basis"})
        revisions[pid] = history.save_revision(instance.id, doc, [basis], {"source": "compatibility_repair"})
    state = history.save_state(instance.id, revisions, [], "compatibility_repair")
    check_target(preview["expected"], current_target(instance))
    return operations.make_plan(instance, processes, prepare_changes(instance,
        {"state_id": state, "selected": list(revisions)}, preview["expected"]))


def create_branch(instance, preview_id, name=None):
    from .profile_publish import check_target, current_target
    preview = get_object(instance.id, preview_id)
    if preview.get("type") != "composer_preview":
        _error("invalid_preview")
    check_target(preview["expected"], current_target(instance))
    sources = {pid: history.save_revision(instance.id, doc, [], {"source": "composer_basis"})
               for pid, doc in preview["sources"].items()}
    revisions = {}
    for pid, original in preview["documents"].items():
        doc = deepcopy(original)
        doc["workbench"] = {"preview_id": preview_id, "required_profile_ids": list(preview["documents"])}
        doc["printer_merge_group"]["preview_id"] = preview_id
        if doc.get("copied_from"):
            doc["source_revision"] = sources[doc["copied_from"]]
        revisions[pid] = history.save_revision(instance.id, doc, [sources[pid]] if pid in sources else [],
                                               {"source": "composer", "preview_id": preview_id})
    check_target(preview["expected"], current_target(instance))
    state = history.save_state(instance.id, revisions, [], "composer")
    return history.create_branch(instance.id, name or preview["group"]["display_name"], state, list(revisions))


def refresh_branch(instance, branch_id):
    branch = history.get_branch(instance.id, branch_id)
    if history.get_draft(instance.id, branch_id):
        _error("composer_modified")
    documents = [history.get_revision(instance.id, revision)["document"] for revision in branch["profiles"].values()]
    preview_ids = {doc.get("workbench", {}).get("preview_id") for doc in documents}
    if len(preview_ids) != 1 or None in preview_ids:
        _error("composer_modified")
    preview = get_object(instance.id, preview_ids.pop())
    if not preview.get("configuration") or set(branch["profiles"]) != set(preview["documents"]):
        _error("composer_modified")
    for original in documents:
        doc = deepcopy(original)
        doc.pop("workbench", None)
        doc.pop("source_revision", None)
        doc.get("printer_merge_group", {}).pop("preview_id", None)
        if doc != preview["documents"][doc["id"]]:
            _error("composer_modified")
    updated = prepare_preview(instance, preview["configuration"])
    return create_branch(instance, updated["preview_id"], branch["name"])

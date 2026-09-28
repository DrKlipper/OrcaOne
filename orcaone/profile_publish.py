"""Fixed profile revisions published exclusively through the existing Planner."""

from copy import deepcopy
import hashlib
import json
import re
from pathlib import PurePosixPath
from uuid import uuid4

from . import backup, guard, operations, profile_history, scanner
from .profile_schema import load_catalog, validate_value
from .profile_normalize import resolve_values
from .profile_edit import make_document
from .profile_observe import identity_at, bind_identity, rename_identity
from .profile_store import HistoryError, _root, _safe, _write, _writer, validate_id
from .resolver import Resolver


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def current_target(instance) -> dict:
    catalog = load_catalog(instance.slicer, instance.version)
    scan = scanner.scan(instance.data_dir, instance.slicer)
    resources = {}
    system = instance.data_dir / "system"
    if system.exists():
        for path in system.rglob("*"):
            if path.is_symlink() or not path.resolve().is_relative_to(system.resolve()):
                raise operations.OperationError("unsafe_resources")
            if path.is_file():
                resources[path.relative_to(system).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"folder": scan.active_folder, "schema_id": catalog.get("id") if catalog else None,
            "fingerprint": _digest(operations._tree_snapshot(instance)),
            "data_dir": str(instance.data_dir.resolve()), "version": instance.version,
            "resources": _digest(resources)}


def check_target(expected: dict, current: dict) -> None:
    if not isinstance(expected, dict) or any(expected.get(key) != current.get(key) for key in ("folder", "schema_id", "fingerprint", "data_dir", "version", "resources")):
        raise operations.OperationError("plan_outdated")


def prepare_changes(instance, selection: dict, expected: dict) -> list[dict]:
    """Resolve an immutable state once; never accept profile documents from a client."""
    current = current_target(instance)
    check_target(expected, current)
    if current["schema_id"] is None:
        raise operations.OperationError("schema_unavailable")
    if not isinstance(selection, dict) or not isinstance(selection.get("selected"), list) or not selection["selected"]:
        raise operations.OperationError("invalid_selection", 400)
    state = profile_history.get_state(instance.id, selection.get("state_id"))
    selected = selection["selected"]
    if any(not isinstance(pid, str) or pid not in state["profiles"] for pid in selected) or len(set(selected)) != len(selected):
        raise operations.OperationError("invalid_selection", 400)
    return [{"op": "profile_publish", "revisions": {pid: state["profiles"][pid] for pid in selected},
             "expected": deepcopy(current), "state_id": selection["state_id"]}]


def _secret(key, option=None):
    return (option or {}).get("role") == "secret" or key in operations._SECRET_KEYS or bool(re.search(r"api.?key|password|token|secret|access_code", key, re.I))


def _live_connection(resolver, profile, options):
    chain, complete = resolver.chain(profile)
    if not complete:
        raise operations.Blocked("connection_source_mismatch")
    values = {}
    for source in [*reversed(chain), profile]:
        values.update({key: deepcopy(value) for key, value in source.values.items()
                       if _secret(key, options.get(key)) or options.get(key, {}).get("role") == "metadata"})
    return values


def _validate_groups(instance, groups):
    from .profile_groups import ProfileGroupError, list_groups, validate_group
    from .profile_store import get_object
    try:
        for group in groups:
            validate_group(instance.id, group["id"], group["names"], group["display_name"], labels=group.get("labels"), user_folder=group["user_folder"], moved_names=group.get("moved_names"))
            if group.get("preview_id"):
                preview = get_object(instance.id, group["preview_id"])
                if (preview.get("type") not in {"printer_merge_preview", "composer_preview"}
                        or preview.get("group") != {key: value for key, value in group.items() if key != "preview_id"}):
                    raise operations.OperationError("printer_group_invalid")
                registered = any(item["id"] == group["id"] for item in list_groups(instance.id, user_folder=group["user_folder"]))
                if not registered:
                    check_target(preview["expected"], current_target(instance))
    except (ProfileGroupError, HistoryError) as exc:
        raise operations.OperationError(exc.code) from None


def _selected_groups(documents, folder):
    selected = {doc["id"]: doc for doc in documents}
    groups = {}
    for document in documents:
        group = document.get("printer_merge_group")
        if group is None:
            continue
        if (not isinstance(group, dict) or not isinstance(group.get("id"), str)
                or not isinstance(group.get("required_profile_ids"), list)
                or any(not isinstance(pid, str) for pid in group["required_profile_ids"])
                or not isinstance(group.get("profile_ids"), list)
                or any(not isinstance(pid, str) for pid in group["profile_ids"])
                or not isinstance(group.get("names"), list) or len(group["names"]) != len(group["profile_ids"])
                or not isinstance(group.get("target_model"), str) or group.get("user_folder") != folder):
            raise operations.Blocked("printer_group_invalid")
        if not set(group["required_profile_ids"]).issubset(selected):
            raise operations.Blocked("printer_group_incomplete")
        if not set(group["profile_ids"]).issubset(group["required_profile_ids"]):
            raise operations.Blocked("printer_group_invalid")
        if any(selected[pid].get("printer_merge_group") != group for pid in group["required_profile_ids"]):
            raise operations.Blocked("printer_group_invalid")
        for pid, name in zip(group["profile_ids"], group["names"]):
            member = selected[pid]
            if member["kind"] != "machine" or member["name"] != name or member["effective"].get("printer_model") != group["target_model"]:
                raise operations.Blocked("printer_group_invalid")
        if group["id"] in groups and groups[group["id"]] != group:
            raise operations.Blocked("printer_group_invalid")
        groups[group["id"]] = deepcopy(group)
    return list(groups.values())


def _workbench_scope(planner, documents):
    from .profile_store import get_object
    selected = {doc["id"]: doc for doc in documents}
    for doc in documents:
        scope = doc.get("workbench")
        if scope is None:
            continue
        if (not isinstance(scope, dict) or not isinstance(scope.get("required_profile_ids"), list)
                or not set(scope["required_profile_ids"]).issubset(selected)):
            raise operations.Blocked("printer_group_incomplete")
        if any(selected[pid].get("workbench") != scope for pid in scope["required_profile_ids"]):
            raise operations.Blocked("printer_group_invalid")
        try:
            preview = get_object(planner.instance.id, scope.get("preview_id"))
            # A successful publication can be replayed; before the first write
            # its source snapshot must still be exactly the preview's snapshot.
            published = False
            for path in (_root(planner.instance.id) / "receipts").glob("*.json"):
                receipt = json.loads(path.read_text(encoding="utf-8"))
                if receipt.get("state") == "verified" and scope["preview_id"] in receipt.get("workbench_previews", []):
                    published = True
                    break
            if not published:
                check_target(preview["expected"], current_target(planner.instance))
        except (HistoryError, operations.OperationError, KeyError) as exc:
            raise operations.Blocked(getattr(exc, "code", "printer_group_invalid")) from None


def _prepare_renames(planner, documents):
    selected = {(doc["kind"], doc.get("rename_from", doc["name"])) for doc in documents}
    typed = {"compatible_printers": "machine", "upward_compatible_machine": "machine",
             "compatible_prints": "process", "default_print_profile": "process",
             "default_filament_profile": "filament"}
    renames = {}
    for doc in documents:
        old, new, kind = doc.get("rename_from"), doc["name"], doc["kind"]
        if not old or old == new:
            continue
        own = next((o for o in planner.live(kind) if o.name == old), None)
        native = None
        if own is None:
            target = next((o for o in planner.live(kind) if o.name == new), None)
            if target and identity_at(planner.instance.id, planner.scan.active_folder, kind, target.rel) == doc["id"]:
                continue
            if doc.get("native_package") or doc.get("printer_merge_group", {}).get("native_model"):
                from .profile_native_paths import owned_files
                paths = owned_files(planner.instance.data_dir)
                native = next((p for p in planner.scan.profiles.values() if p.kind == kind and p.name in {old, new}
                               and p.file in paths and identity_at(planner.instance.id, planner.scan.active_folder, kind, p.file) == doc["id"]), None)
                if native and native.name == new:
                    continue
            if native is None:
                raise operations.Blocked("connection_source_mismatch")
        if own and identity_at(planner.instance.id, planner.scan.active_folder, kind, own.rel) != doc["id"]:
            raise operations.Blocked("connection_source_mismatch")
        planner.check_new_name(kind, new, exclude=own)
        # Case-only renames alias both receipt paths on Windows. Reject rather
        # than constructing an ambiguous rollback manifest.
        if old.casefold() == new.casefold():
            raise operations.Blocked("name_taken", name=new)
        for source in planner.scan.own:
            references = source.kind == kind and source.inherits == old
            references |= any(target_kind == kind and (old in value if isinstance(value, list) else value == old)
                              for key, target_kind in typed.items() for value in [source.values.get(key)])
            if references and (source.kind, source.name) not in selected:
                raise operations.Blocked("references_outside_selection", names=[source.name])
        renames[(kind, old)] = new
        if own:
            own.name = new
            own.rel = (PurePosixPath(own.rel).parent / (new + ".json")).as_posix()
        for _, entry in planner.preset_entries():
            for key, value in list(entry.items()):
                matches = ((kind == "machine" and key == "machine")
                           or (kind == "process" and key in {"process", "print"})
                           or (kind == "filament" and (operations._FILAMENT_SLOT.fullmatch(key) or key == "filaments")))
                if matches:
                    entry[key] = [new if item == old else item for item in value] if isinstance(value, list) else new if value == old else value
    return renames


def plan_publish(planner, change):
    """Populate Planner's own-profile models; no file writes occur here."""
    from .profile_jobs import report
    expected, revisions = change.get("expected"), change.get("revisions")
    try:
        check_target(expected, current_target(planner.instance))
    except operations.OperationError as exc:
        raise operations.Blocked(exc.code) from None
    catalog = load_catalog(planner.instance.slicer, planner.instance.version)
    if not catalog or not catalog.get("complete"):
        raise operations.Blocked("schema_unavailable")
    if not isinstance(revisions, dict) or not revisions:
        raise operations.Blocked("invalid_selection")
    documents = []
    try:
        for pid, rid in revisions.items():
            validate_id(pid, "profile")
            document = profile_history.get_revision(planner.instance.id, rid)["document"]
            if (document.get("id") != pid or document.get("schema_id") != catalog["id"]
                    or not document.get("complete") or not document.get("context", {}).get("chain_complete")):
                raise operations.Blocked("document_incomplete")
            if document.get("origin_kind") in {"user", "own"} and document["context"].get("user_folder") != planner.scan.active_folder:
                raise operations.Blocked("source_folder_mismatch")
            documents.append(document)
    except HistoryError as exc:
        raise operations.Blocked(exc.code) from None
    _workbench_scope(planner, documents)
    renames = _prepare_renames(planner, documents)
    groups = _selected_groups(documents, planner.scan.active_folder)
    from .profile_native import supported as native_supported
    if native_supported(planner.instance) and any(not group.get("native_model") for group in groups):
        raise operations.Blocked("native_preview_required")
    native_ids = {pid for group in groups if group.get("native_model") for pid in group["profile_ids"]}
    native_ids.update(doc["id"] for doc in documents if doc.get("native_package"))
    try:
        _validate_groups(planner.instance, groups)
    except operations.OperationError as exc:
        raise operations.Blocked(exc.code) from None
    selected = {(doc.get("kind"), doc.get("name")) for doc in documents}
    if len(selected) != len(documents):
        raise operations.Blocked("invalid_selection")
    report("plan", 0, len(documents))
    for document_index, document in enumerate(documents):
        report("plan", document_index, len(documents))
        kind, name = document.get("kind"), document.get("name")
        if kind not in scanner.KINDS or operations.name_problem(name):
            raise operations.Blocked("profile_invalid")
        options = catalog["options"][kind]
        effective = document.get("effective")
        if not isinstance(effective, dict):
            raise operations.Blocked("document_incomplete")
        for key, option in options.items():
            if option.get("role") in {"metadata", "secret"}:
                continue
            if key not in effective or not option.get("complete") or validate_value(option, effective[key]):
                raise operations.Blocked("profile_invalid", key=key)
        normalized = resolve_values(catalog, kind, [{"id": document["id"], "values": effective}], document["context"])
        if not normalized["complete"] or any(normalized["values"].get(key) != value for key, value in effective.items()
                                             if key in options and options[key].get("role") not in {"secret", "metadata"}):
            raise operations.Blocked("profile_dimension_invalid")
        reference_kinds = {"compatible_printers": "machine", "compatible_prints": "process",
                           "default_print_profile": "process", "default_filament_profile": "filament",
                           "upward_compatible_machine": "machine"}
        for key, value in effective.items():
            if key.endswith("_condition") and value:
                raise operations.Blocked("condition_unknown", key=key)
            if key not in reference_kinds:
                continue
            target_kind = reference_kinds[key]
            names = value if isinstance(value, list) else [value]
            for reference in names:
                if not reference:
                    continue
                if (target_kind, reference) in renames:
                    raise operations.Blocked("references_outside_selection", names=[document["name"]])
                exists = reference in planner.res.collection[target_kind] or any(o.name == reference and o.loaded for o in planner.live(target_kind))
                if not exists and (target_kind, reference) not in selected:
                    raise operations.Blocked("reference_missing", key=key, name=reference)
        # A changed parent would otherwise silently alter unselected descendants.
        children = [p.name for p in planner.scan.own if p.kind == kind and p.inherits == name and (p.kind, p.name) not in selected]
        if children:
            raise operations.Blocked("references_outside_selection", names=children)
        if document["id"] in native_ids:
            continue
        existing = next((o for o in planner.live(kind) if o.name == name), None)
        if existing is not None:
            try:
                live_id = identity_at(planner.instance.id, planner.scan.active_folder, kind, existing.orig_rel or existing.rel)
            except HistoryError as exc:
                raise operations.Blocked(exc.code) from None
            if live_id != document["id"]:
                raise operations.Blocked("name_taken", name=name)
        if existing is None:
            planner.check_new_name(kind, name)
        elif existing.data is None or any(p.kind == kind and p.name == name for p in planner.scan.profiles.values()):
            raise operations.Blocked("not_own_profile", name=name)
        parent_name = document.get("inherits", "")
        parent = None
        if not isinstance(parent_name, str) or not isinstance(document.get("own"), dict):
            raise operations.Blocked("document_incomplete")
        if parent_name:
            if existing:
                old_parent = existing.data.get("inherits", "")
                if renames.get((kind, old_parent), old_parent) != parent_name:
                    raise operations.Blocked("parent_basis_changed")
                parent = existing.parent
                live_document = make_document(document["id"], existing.profile, planner.res, catalog)
                inherited_values = live_document["inherited"]
                inherited_unknown = live_document["inherited_unknown"]
                chain_complete = live_document["context"]["chain_complete"]
            else:
                parent = planner.res.collection[kind].get(parent_name)
                if parent is None:
                    parent = next((o.profile for o in planner.live(kind) if o.name == parent_name and o.loaded), None)
                live_document = make_document("parent-basis", parent, planner.res, catalog) if parent else None
                inherited_values = live_document["effective"] if live_document else None
                inherited_unknown = live_document["unknown"] if live_document else None
                chain_complete = live_document is not None and live_document["context"]["chain_complete"]
            if (not parent or not chain_complete or document.get("inherited") != inherited_values
                    or document.get("inherited_unknown", {}) != inherited_unknown):
                raise operations.Blocked("parent_basis_changed")
            # Selection alone does not authorize changed inherited fields in a
            # child. Its pinned effective revision must remain the result.
            ancestors, _ = planner.res.chain(parent)
            for ancestor in [parent, *ancestors]:
                selected_parent = next((doc for doc in documents if doc["kind"] == kind and doc.get("rename_from", doc["name"]) == ancestor.name), None)
                if selected_parent is not None:
                    live_parent = make_document("parent-basis", ancestor, planner.res, catalog)
                    for key, target_kind in reference_kinds.items():
                        value = live_parent["effective"].get(key)
                        if isinstance(value, list):
                            live_parent["effective"][key] = list(dict.fromkeys(renames.get((target_kind, item), item) for item in value))
                        elif isinstance(value, str):
                            live_parent["effective"][key] = renames.get((target_kind, value), value)
                    if (selected_parent["effective"] != live_parent["effective"]
                            or selected_parent.get("unknown", {}) != live_parent["unknown"]):
                        raise operations.Blocked("parent_basis_changed")
        materialized = not parent_name and document.get("inherited") == {}
        source_unknown = document.get("unknown", {}) if materialized else document.get("own_unknown", {})
        if existing:
            source_unknown = {**source_unknown, **{key: value for key, value in existing.data.items() if key not in options}}
        values = {key: deepcopy(value) for key, value in source_unknown.items()
                  if key not in scanner.META_KEYS and key not in operations.SETTINGS_ID.values() and not _secret(key)}
        values.update({key: deepcopy(value) for key, value in document["own"].items()
                       if key in options and options[key].get("role") not in {"metadata", "secret"} and not _secret(key, options[key])})
        if existing:
            # Secrets are sourced only from today's destination, never revision history.
            if materialized:
                values.update(_live_connection(planner.res, existing.profile, options))
            values.update({key: deepcopy(value) for key, value in existing.data.items()
                           if _secret(key, options.get(key)) or options.get(key, {}).get("role") == "metadata"})
            values.update({key: deepcopy(value) for key, value in existing.data.items()
                           if key in scanner.META_KEYS and key != "inherits" and not (materialized and key == "is_custom_defined")})
            values.update(name=name, inherits=parent_name,
                          version=planner.version if materialized else existing.data.get("version", planner.version))
            values["from"] = "User"
            values[operations.SETTINGS_ID[kind]] = [name] if kind == "filament" else name
            existing.data, existing.parent, existing.touched = values, parent, values != existing.orig_data
            if existing.info and materialized:
                existing.info = {**existing.info, "base_id": ""}
        else:
            if (kind == "machine" and document.get("copied_from")
                    and document.get("provenance", {}).get("operation") != "cross_slicer_copy"):
                try:
                    source_document = profile_history.get_revision(planner.instance.id, document.get("source_revision"))["document"]
                except HistoryError as exc:
                    raise operations.Blocked("connection_source_missing") from exc
                if (source_document.get("id") != document["copied_from"] or source_document.get("kind") != kind
                        or source_document.get("schema_id") != catalog["id"]):
                    raise operations.Blocked("connection_source_mismatch")
                if source_document.get("origin_kind") in {"user", "own"}:
                    if source_document.get("context", {}).get("user_folder") != planner.scan.active_folder:
                        raise operations.Blocked("source_folder_mismatch")
                    source_own = next((o for o in planner.live(kind) if o.profile and o.profile.name == source_document.get("name")), None)
                    if source_own is None:
                        raise operations.Blocked("connection_source_missing")
                    if identity_at(planner.instance.id, planner.scan.active_folder, kind, source_own.orig_rel or source_own.rel) != document["copied_from"]:
                        raise operations.Blocked("connection_source_mismatch")
                    values.update(_live_connection(planner.res, source_own.profile, options))
                    values.update({key: deepcopy(value) for key, value in source_own.data.items()
                                   if _secret(key, options.get(key)) or options.get(key, {}).get("role") == "metadata"})
            if kind == "filament":
                values["filament_id"] = "P" + hashlib.md5(name.encode()).hexdigest()[:7]
            planner.new_own(kind, name, values, parent, parent.setting_id if parent else "")
        shared = [p.name for p in planner.scan.own if p.name != name and name in (p.values.get("compatible_printers") or [])]
        if shared:
            planner.warnings.append({"code": "shared_profile", "name": name, "profiles": shared})
        report("plan", document_index + 1, len(documents))
    from .profile_native import build as build_native, resource_hash_after
    native = build_native(planner, groups, [doc for doc in documents if doc["id"] in native_ids], catalog) if native_ids else {"steps": [], "ops": [], "bindings": []}
    planner.publish = {"expected": deepcopy(expected), "revisions": deepcopy(revisions), "state_id": change.get("state_id"),
                       "native_steps": native["steps"], "native_ops": native["ops"],
                       "resources_after": resource_hash_after(planner.instance, native["steps"]) if native_ids else expected["resources"],
                       "machine_renames": {old: new for (kind, old), new in renames.items() if kind == "machine"},
                       "workbench_previews": sorted({doc["workbench"]["preview_id"] for doc in documents if doc.get("workbench")}),
                       "profiles": sorted(selected),
                       "groups": groups,
                       "bindings": [{"profile_id": doc["id"], "user_folder": planner.scan.active_folder,
                                     "kind": doc["kind"], "name": doc["name"],
                                     "path": next(o.rel for o in planner.live(doc["kind"]) if o.name == doc["name"]),
                                     "old_path": next(o.orig_rel for o in planner.live(doc["kind"]) if o.name == doc["name"])}
                                    for doc in documents if doc["id"] not in native_ids] + native["bindings"],
                       "nested_keys": [key for fields in catalog["options"].values() for key, option in fields.items()
                                       if option["type"] == "coPointsGroups"]}


def _receipt_path(instance_id, receipt_id):
    validate_id(receipt_id, "profile")
    return _safe(_root(instance_id) / "receipts" / f"{receipt_id}.json")


def write_receipt(instance_id: str, receipt: dict) -> str:
    receipt = deepcopy(receipt)
    receipt_id = receipt.setdefault("id", uuid4().hex)
    if receipt.get("state") not in {"prepared", "writing", "verified", "rolled_back", "needs_review"}:
        raise HistoryError("invalid_receipt")
    with _writer(instance_id):
        _write(_receipt_path(instance_id, receipt_id), (json.dumps(receipt, sort_keys=True, ensure_ascii=False) + "\n").encode())
    return receipt_id


def _file_hash(instance, rel):
    if operations.outside_backup(instance.data_dir, rel, f"{instance.slicer}.conf"):
        raise operations.OperationError("path_outside_backup")
    path = instance.data_dir / rel
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _loaded(instance, expected):
    scan = scanner.scan(instance.data_dir, instance.slicer)
    if scan.conf_file is None:
        return False
    resolver = Resolver(scan)
    from .profile_native_paths import owned_files
    owned = owned_files(instance.data_dir)
    candidates = [*scan.own, *(p for p in scan.profiles.values() if p.file in owned)]
    for kind, name in expected:
        profile = next((p for p in candidates if p.kind == kind and p.name == name and not p.bundle), None)
        if profile is None or not resolver.loaded(profile) or not resolver.chain(profile)[1]:
            return False
    return True


def _bind_published(instance, receipt):
    for binding in receipt.get("bindings", []):
        binding = dict(binding)
        old_path = binding.pop("old_path", None)
        if old_path and old_path != binding["path"] and identity_at(instance.id, binding["user_folder"], binding["kind"], binding["path"]) != binding["profile_id"]:
            rename_identity(instance.id, binding["profile_id"], binding["user_folder"], binding["kind"], old_path, binding["path"], binding["name"])
        else:
            bind_identity(instance.id, **binding)


def _register_published_groups(instance, receipt):
    from .profile_groups import save_group, rename_members
    for group in receipt.get("groups", []):
        save_group(instance.id, group["id"], group["names"], group["display_name"], labels=group.get("labels"), user_folder=group["user_folder"], moved_names=group.get("moved_names"))
    if receipt.get("machine_renames"):
        rename_members(instance.id, receipt["machine_renames"], receipt["expected"]["folder"])


def recover_receipt(instance, receipt_id: str) -> dict:
    """Inspect a crash receipt; recovery never overwrites destination files."""
    receipt = json.loads(_receipt_path(instance.id, receipt_id).read_text(encoding="utf-8"))
    try:
        current = current_target(instance)
        if any(current.get(key) != receipt["expected"].get(key) for key in ("folder", "schema_id", "data_dir", "version")) or current["resources"] not in {receipt["expected"]["resources"], receipt.get("resources_after", receipt["expected"]["resources"])}:
            raise operations.OperationError("plan_outdated")
        hashes = {rel: _file_hash(instance, rel) for rel in receipt["after"]}
        if hashes == receipt["after"] and _loaded(instance, receipt["expect_loaded"]):
            _bind_published(instance, receipt)
            receipt["state"] = "verified"
        elif hashes == receipt["before"]:
            receipt["state"] = "rolled_back"
        else:
            receipt["state"] = "needs_review"
    except Exception:
        receipt["state"] = "needs_review"
    write_receipt(instance.id, receipt)
    if receipt["state"] == "verified":
        try:
            _register_published_groups(instance, receipt)
            if receipt.pop("group_registration_pending", None):
                write_receipt(instance.id, receipt)
        except Exception:
            receipt["state"] = "needs_review"
            receipt["group_registration_pending"] = True
            write_receipt(instance.id, receipt)
    return receipt


def _rollback(instance, receipt, backup_name):
    if operations.run_block(instance, guard.find_processes()):
        return False
    try:
        files, _ = backup.restorable(instance, backup_name)
    except backup.BackupError:
        return False
    clean = True
    from .profile_native_paths import vendor_of
    entries = list(reversed(list(receipt["after"].items())))
    manifests = {rel for rel, _ in entries if vendor_of(rel) and rel == f"system/{vendor_of(rel)}.json"}
    entries = [item for item in entries if item[0] not in manifests] + [item for item in entries if item[0] in manifests]
    for rel, written_hash in entries:
        try:
            actual = _file_hash(instance, rel)
            if actual == receipt["before"][rel]:
                continue
            intermediate = receipt.get("rename_intermediate", {})
            if (actual != written_hash and (rel not in intermediate or actual != intermediate[rel])) or rel not in receipt.get("written", []):
                clean = False
                continue
            if operations.run_block(instance, guard.find_processes()):
                return False
            if rel in files:
                operations.write_atomic(instance.data_dir / rel, files[rel])
            else:
                (instance.data_dir / rel).unlink(missing_ok=True)
        except (OSError, operations.OperationError):
            clean = False
    from .profile_native_paths import managed_path
    for rel in receipt["after"]:
        if managed_path(rel) and receipt["before"].get(rel) is None:
            parent = (instance.data_dir / rel).parent
            while parent != instance.data_dir / "system" and parent.is_relative_to(instance.data_dir / "system"):
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
    try:
        return clean and all(_file_hash(instance, rel) == before for rel, before in receipt["before"].items())
    except (OSError, operations.OperationError):
        return False


def execute_publish(instance, plan):
    """Receipt lifecycle around the existing writer, with conditional rollback."""
    from .profile_jobs import report
    report("check")
    check_target(plan.publish["expected"], current_target(instance))
    _validate_groups(instance, plan.publish.get("groups", []))
    try:
        report("backup")
        made = backup.create(instance, plan.reason, plan.reason_params)
    except backup.BackupError as exc:
        raise operations.OperationError(exc.code, 500) from None
    block = operations.run_block(instance, guard.find_processes())
    if block:
        raise operations.OperationError(block, backup=made)
    check_target(plan.publish["expected"], current_target(instance))
    if any(step.action not in ({"write", "rename", "delete"} if plan.publish.get("native_steps") else {"write", "rename"}) for step in plan.steps):
        raise operations.OperationError("publish_invalid_steps")
    paths = list(dict.fromkeys(path for step in plan.steps for path in (step.path, step.to) if path))
    after = {path: None for path in paths}
    for step in plan.steps:
        after[step.to or step.path] = hashlib.sha256(step.content).hexdigest() if step.content is not None else None
    receipt = {"id": uuid4().hex, "state": "prepared", "backup": made["name"],
               "expected": plan.publish["expected"], "revisions": plan.publish["revisions"],
               "before": {path: _file_hash(instance, path) for path in paths},
               "after": after,
               "rename_intermediate": {step.to: _file_hash(instance, step.path) for step in plan.steps if step.action == "rename"},
               "expect_loaded": plan.expect_loaded, "written": [], "bindings": plan.publish["bindings"],
               "groups": plan.publish.get("groups", []),
               "resources_after": plan.publish.get("resources_after", plan.publish["expected"]["resources"]),
               "machine_renames": plan.publish.get("machine_renames", {}),
               "workbench_previews": plan.publish.get("workbench_previews", [])}
    try:
        write_receipt(instance.id, receipt)
        receipt["state"] = "writing"
        write_receipt(instance.id, receipt)
    except (OSError, HistoryError):
        raise operations.OperationError("receipt_write_failed", 500, backup=made) from None
    operations._plans.pop(plan.id, None)
    try:
        check_target(plan.publish["expected"], current_target(instance))
        report("write", 0, len(plan.steps))
        for step_index, step in enumerate(plan.steps):
            if operations.run_block(instance, guard.find_processes()):
                raise operations.OperationError("slicer_running")
            receipt["written"].extend(path for path in (step.path, step.to) if path)
            operations._execute(instance.data_dir, [step])
            report("write", step_index + 1, len(plan.steps))
        report("verify")
        current = current_target(instance)
        if any(current.get(key) != plan.publish["expected"].get(key) for key in ("folder", "schema_id", "data_dir", "version")) or current["resources"] != plan.publish.get("resources_after", plan.publish["expected"]["resources"]):
            raise operations.OperationError("plan_outdated")
        if (not operations._verify(instance.data_dir, plan.steps)
                or operations.run_block(instance, guard.find_processes())
                or not _loaded(instance, plan.expect_loaded)):
            raise operations.OperationError("publish_verification_failed")
        _bind_published(instance, receipt)
        receipt["state"] = "verified"
        write_receipt(instance.id, receipt)
    except Exception as exc:
        report("rollback")
        rolled_back = _rollback(instance, receipt, made["name"])
        receipt["state"] = "rolled_back" if rolled_back else "needs_review"
        try:
            write_receipt(instance.id, receipt)
        except (OSError, HistoryError):
            pass  # The durable writing receipt still enables recovery after restart.
        raise operations.OperationError("publish_failed", 500, backup=made, receipt_id=receipt["id"],
                                        receipt_state=receipt["state"], rolled_back=rolled_back) from exc
    # The file transaction has committed durably. Registry failure must not
    # roll back already registered group members or claim a complete UI update.
    try:
        _register_published_groups(instance, receipt)
    except Exception as exc:
        receipt["state"] = "needs_review"
        receipt["group_registration_pending"] = True
        write_receipt(instance.id, receipt)
        raise operations.OperationError("group_registration_failed", 500, backup=made, receipt_id=receipt["id"],
                                        receipt_state="needs_review", rolled_back=False) from exc
    return {"ok": True, "backup": made, "applied": len(plan.steps), "warnings": plan.public["warnings"],
            "receipt_id": receipt["id"], "receipt_state": "verified"}

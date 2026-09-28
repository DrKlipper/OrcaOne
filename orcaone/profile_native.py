"""OrcaOne-owned native Orca printer models, never arbitrary vendor edits."""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from . import operations, scanner
from .profile_observe import identity_at


def supported(instance):
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:$|[.-])", instance.version or "")
    return instance.slicer == "OrcaSlicer" and match is not None and tuple(map(int, match.groups())) >= (2, 4, 2)


def _encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=4) + "\n").encode("utf-8")


def native_document_metadata(instance, profile):
    from .profile_native_paths import managed_path, owned_files
    if profile.kind != "machine" or not managed_path(profile.file):
        return {}
    return {"native_package": profile.package} if profile.file in owned_files(instance.data_dir) else {}


def _variant(values):
    sizes = values.get("nozzle_diameter")
    if not isinstance(sizes, list) or not sizes:
        raise operations.Blocked("profile_dimension_invalid")
    try:
        if any(not isinstance(v, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", v) or Decimal(v) <= 0 for v in sizes):
            raise InvalidOperation
        return "+".join(format(Decimal(v).normalize(), "f") for v in sizes)
    except InvalidOperation:
        raise operations.Blocked("profile_dimension_invalid") from None


def build(planner, groups, documents, catalog):
    """Prepare package writes and activation after ordinary document validation."""
    from .profile_native_paths import validate_existing, owned_files
    from .profile_publish import _live_connection, _secret
    from . import profile_history
    if not supported(planner.instance):
        raise operations.Blocked("native_model_unsupported")
    packages = {}
    doc_packages = {}
    for group in groups:
        if group.get("native_model"):
            vendor = "OrcaOne_" + group["id"]
            packages[vendor] = {"group": group, "documents": []}
            for pid in group["profile_ids"]:
                doc_packages[pid] = vendor
    for doc in documents:
        vendor = doc_packages.get(doc["id"], doc.get("native_package"))
        if vendor:
            if not re.fullmatch(r"OrcaOne_[0-9a-f]{32}", vendor):
                raise operations.Blocked("native_package_invalid")
            packages.setdefault(vendor, {"group": None, "documents": []})["documents"].append(doc)
    steps, ops, bindings = [], [], []
    for vendor, package in packages.items():
        try:
            validate_existing(planner.instance.data_dir, vendor)
        except (ValueError, OSError):
            raise operations.Blocked("native_package_collision") from None
        manifest_path = f"system/{vendor}.json"
        path = planner.instance.data_dir / manifest_path
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        group = package["group"]
        if old:
            if old.get("orcaone_user_folder") != planner.scan.active_folder:
                raise operations.Blocked("source_folder_mismatch")
            manifest = deepcopy(old)
            model_name = manifest["machine_model_list"][0]["name"]
            if group and group["display_name"] != model_name:
                raise operations.Blocked("native_package_collision")
        else:
            if not group:
                raise operations.Blocked("native_package_invalid")
            model_name = group["display_name"]
            if any(p.values.get("printer_model") == model_name for p in planner.scan.profiles.values()):
                raise operations.Blocked("name_taken", name=model_name)
            manifest = {"name": "OrcaOne", "version": "02.04.02.00",
                        "orcaone": {"kind": "native_model", "format": 1, "group_id": group["id"]},
                        "orcaone_user_folder": planner.scan.active_folder,
                        "machine_model_list": [{"name": model_name, "sub_path": "machine/model.json"}],
                        "machine_list": [], "process_list": [], "filament_list": []}
        entries = {entry["profile_id"]: entry for entry in manifest["machine_list"]}
        values_by_id = {}
        for pid, entry in entries.items():
            values_by_id[pid] = json.loads((planner.instance.data_dir / "system" / vendor / entry["sub_path"]).read_text(encoding="utf-8"))
        for doc in package["documents"]:
            pid, name = doc["id"], doc["name"]
            if doc["effective"].get("printer_model") != model_name:
                raise operations.Blocked("native_model_mismatch")
            previous = entries.get(pid)
            if previous and identity_at(planner.instance.id, planner.scan.active_folder, "machine", f"system/{vendor}/{previous['sub_path']}") != pid:
                raise operations.Blocked("connection_source_mismatch")
            colliding = [p for p in planner.scan.profiles.values() if p.kind == "machine" and p.name == name
                         and not (p.package == vendor and previous and p.file == f"system/{vendor}/{previous['sub_path']}")]
            if colliding:
                raise operations.Blocked("name_taken", name=name)
            options = catalog["options"]["machine"]
            values = {key: deepcopy(value) for key, value in doc.get("unknown", {}).items()
                      if key not in scanner.META_KEYS and not _secret(key)}
            values.update({key: deepcopy(value) for key, value in doc["effective"].items()
                           if key in options and options[key].get("role") not in {"metadata", "secret"} and not _secret(key, options[key])})
            old_path = None
            if previous:
                profile = next(p for p in planner.scan.profiles.values() if p.file == f"system/{vendor}/{previous['sub_path']}")
                values.update(_live_connection(planner.res, profile, options))
            else:
                source_doc = doc
                if doc.get("copied_from"):
                    source_doc = profile_history.get_revision(planner.instance.id, doc.get("source_revision"))["document"]
                    if source_doc["id"] != doc["copied_from"]:
                        raise operations.Blocked("connection_source_mismatch")
                source_name = source_doc.get("rename_from", source_doc["name"])
                source = next((o for o in planner.own if o.kind == "machine" and o.profile and o.profile.name == source_name and not o.deleted), None)
                if source is not None:
                    if identity_at(planner.instance.id, planner.scan.active_folder, "machine", source.orig_rel) != source_doc["id"]:
                        raise operations.Blocked("connection_source_mismatch")
                    values.update(_live_connection(planner.res, source.profile, options))
                    if not doc.get("copied_from"):
                        source.deleted = True
                        old_path = source.orig_rel
                elif source_doc.get("origin_kind") in {"user", "own"}:
                    raise operations.Blocked("connection_source_missing")
                elif source_doc.get("native_package"):
                    if not doc.get("copied_from"):
                        raise operations.Blocked("native_source_move_unsupported")
                    source = next((p for p in planner.scan.profiles.values() if p.package == source_doc["native_package"]
                                   and p.name == source_name and p.file in owned_files(planner.instance.data_dir)), None)
                    if source is None or identity_at(planner.instance.id, planner.scan.active_folder, "machine", source.file) != source_doc["id"]:
                        raise operations.Blocked("connection_source_mismatch")
                    values.update(_live_connection(planner.res, source, options))
            variant = _variant(values)
            values.update(type="machine", name=name, version=planner.version, instantiation="true",
                          printer_model=model_name, printer_variant=variant, printer_settings_id=name)
            for key in ("inherits", "from", "is_custom_defined", "setting_id"):
                values.pop(key, None)
            entry = {"name": name, "sub_path": f"machine/{pid}.json", "profile_id": pid}
            entries[pid] = entry
            values_by_id[pid] = values
            bindings.append({"profile_id": pid, "user_folder": planner.scan.active_folder, "kind": "machine",
                             "name": name, "path": f"system/{vendor}/{entry['sub_path']}", "old_path": old_path})
        variants = {}
        for value in values_by_id.values():
            variant = _variant(value)
            if variant in variants:
                raise operations.Blocked("native_nozzle_conflict", names=[variants[variant], value["name"]], variant=variant)
            variants[variant] = value["name"]
        manifest["machine_list"] = list(entries.values())
        model = {"type": "machine_model", "name": model_name, "model_id": vendor,
                 "nozzle_diameter": ";".join(variants), "machine_tech": "FFF", "family": "OrcaOne",
                 "bed_model": "", "bed_texture": "", "hotend_model": "", "default_materials": ""}
        contents = {manifest_path: _encode(manifest), f"system/{vendor}/machine/model.json": _encode(model)}
        contents.update({f"system/{vendor}/{entry['sub_path']}": _encode(values_by_id[pid]) for pid, entry in entries.items()})
        for rel, content in contents.items():
            current = planner.instance.data_dir / rel
            if current.exists() and current.read_bytes() == content:
                continue
            profile_name = next((entry["name"] for entry in entries.values() if rel == f"system/{vendor}/{entry['sub_path']}"), None)
            steps.append(operations.Step("write", rel, content, check="profile" if profile_name else None, name=profile_name,
                                         nested_keys=tuple(k for k, option in catalog["options"]["machine"].items() if option["type"] == "coPointsGroups")))
            ops.append(operations._op("modify" if current.exists() else "create", rel, "native_profile", name=profile_name or model_name))
        enabled = {"vendor": vendor, "model": model_name, "nozzle_diameter": ";".join(variants)}
        planner.conf["models"] = [item for item in planner.conf.get("models", []) if item.get("vendor") != vendor] + [enabled]
    return {"steps": steps, "ops": ops, "bindings": bindings}


def resource_hash_after(instance, steps):
    """Expected complete system tree, including unrelated resources unchanged."""
    resources = {}
    system = instance.data_dir / "system"
    for path in system.rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(system.resolve()):
            raise operations.Blocked("unsafe_resources")
        if path.is_file():
            resources[path.relative_to(system).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    for step in steps:
        resources[step.path.removeprefix("system/")] = hashlib.sha256(step.content).hexdigest()
    return hashlib.sha256(json.dumps(resources, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

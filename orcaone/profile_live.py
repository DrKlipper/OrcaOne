"""Observe only profiles explicitly opened for local editing."""

import hashlib
import json

from . import operations, scanner
from .profile_edit import make_document
from .profile_observe import _IDENTITIES, observe
from .profile_schema import load_catalog
from .profile_store import get_ref
from .resolver import Resolver


def fingerprint(instance):
    files = operations._tree_snapshot(instance)
    system = instance.data_dir / "system"
    if system.exists():
        for path in system.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(system.resolve()):
                files["system/" + path.relative_to(system).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def capture(instance):
    index = get_ref(instance.id, _IDENTITIES)
    entries = [item for item in (index or {}).get("index", {}).get("entries", [])
               if item["user_folder"] == instance.active_user_folder]
    if not entries:
        return {"tracked": False}
    before = fingerprint(instance)
    scan = scanner.scan(instance.data_dir, instance.slicer)
    resolver = Resolver(scan)
    catalog = load_catalog(instance.slicer, instance.version)
    selected = {(entry["kind"], entry["path"]): entry["id"] for entry in entries}
    documents = {}
    from .profile_native import native_document_metadata
    for profile in [*scan.profiles.values(), *scan.own]:
        metadata = native_document_metadata(instance, profile)
        path = str(profile.file) if not profile.package or metadata else f"{profile.package}/{profile.kind}/{profile.name}"
        profile_id = selected.get((profile.kind, path))
        if profile_id:
            documents[profile_id] = make_document(profile_id, profile, resolver, catalog)
            documents[profile_id].update(metadata)
            documents[profile_id]["context"]["user_folder"] = instance.active_user_folder
    after = fingerprint(instance)
    stable = (before == after and scan.active_folder == instance.active_user_folder and
              not any(p.problem for p in scan.own) and not any(p.error for p in scan.packages))
    return observe(instance, documents, after, stable)

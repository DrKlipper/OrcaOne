"""The page "Änderungen": what changed in an installation since the user last marked it seen,
e.g. after an update, a login or a cloud sync (PLAN 1.4). A snapshot per installation in
data/snapshots/<id>.json keeps the state of then as flat items. OrcaOne compares profiles rather
than files: OrcaSlicer 2.5 keeps all system profiles in a few .opc files, and a name says more
than a file. What OrcaOne writes itself counts as seen (accept(), from operations.apply). Writes
only into OrcaOne's own folder.

Items, key -> value:
    slicer                  "header" of the .conf, e.g. "Snapmaker Orca 2.4.0"
    folder                  the user folder the slicer reads: logged in or not (FINDINGS 4.2)
    package/<name>          version of a vendor package in system/
    printer/<model>         {"vendor", "nozzles"} of an entry in "models"
    visible                 "list" with a "filaments" list, else "all" (FINDINGS 4.3)
    visible/<name>          a name in that list
    system/<kind>/<name>    [package, hash of the resolved values] of a selectable system profile
    own/<kind>/<name>       the whole file of an own profile, credentials only as a hash; None
                            if the slicer cannot read it
"""

import hashlib
import json
import re
import threading
from datetime import datetime

from . import scanner, settings
from .model import Instance
from .resolver import Resolver

# Values of own printer profiles that are credentials: the dialog "Physical Printer" saves them
# there (printhost_apikey, printhost_password, FINDINGS "Wo die Slicer die Adresse ablegen").
SECRET = re.compile(r"apikey|password|token|secret|access_code", re.IGNORECASE)
_MISSING = object()
_lock = threading.Lock()


class SnapshotError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("ascii")).hexdigest()[:16]


def _hidden(data: dict) -> dict:
    return {k: "***" + _hash(v)[:8] if SECRET.search(k) and v not in ("", None, []) else v for k, v in data.items()}


def items(scan: scanner.Scan, res: Resolver) -> dict:
    conf = scan.conf
    found = {"slicer": conf.get("header") if isinstance(conf.get("header"), str) else "", "folder": scan.active_folder}
    for package in scan.packages:
        found[f"package/{package.name}"] = package.version
    models = conf.get("models")
    for entry in models if isinstance(models, list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("model"), str):
            found[f"printer/{entry['model']}"] = {"vendor": entry.get("vendor", ""), "nozzles": entry.get("nozzle_diameter", "")}
    names = [n for n in conf.get("filaments") or [] if isinstance(n, str)] if isinstance(conf.get("filaments"), list) else []
    found["visible"] = "list" if names else "all"
    found.update((f"visible/{name}", True) for name in names)
    for p in scan.profiles.values():
        if p.selectable:
            values = {}
            for q in res.layers(p):
                for key, value in q.values.items():
                    values.setdefault(key, value)
            found[f"system/{p.kind}/{p.name}"] = [p.package, _hash(values)]
    for p in scan.own:
        data = scanner._read_json(scan.data_dir / p.file)
        found[f"own/{p.kind}/{p.name}"] = _hidden(data) if isinstance(data, dict) else None
    return found


def current(instance: Instance) -> dict:
    scan = scanner.scan(instance.data_dir, instance.slicer)
    if scan.conf_file is None:
        # The slicer deletes the .conf for a moment while saving it (FINDINGS 4.3); compared
        # then, every printer would look gone.
        raise SnapshotError("conf_unreadable")
    return items(scan, Resolver(scan))


def _file(instance_id: str):
    return settings.DATA_DIR / "snapshots" / f"{instance_id}.json"


def load(instance_id: str) -> dict | None:
    try:
        data = json.loads(_file(instance_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("items"), dict) else None


def _write(instance_id: str, snapshot: dict) -> dict:
    file = _file(instance_id)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(file.name + ".tmp")
    # ASCII: names from file systems may hold surrogates (non-UTF-8 file names).
    tmp.write_text(json.dumps(snapshot, sort_keys=True), encoding="ascii")
    settings.replace(tmp, file)
    return snapshot


def _save(instance_id: str, found: dict, first: bool = False) -> dict:
    """first: taken by OrcaOne the first time it saw the installation, not by the user."""
    return _write(instance_id, {"taken": datetime.now().isoformat(timespec="seconds"), "items": found, "first": first})


def _pairs(old: dict, new: dict, prefix: str):
    """(rest of the key, old value, new value) of every item under prefix that differs; _MISSING
    where the item is not there."""
    for key in sorted({k for k in (*old, *new) if k.startswith(prefix)}):
        a, b = old.get(key, _MISSING), new.get(key, _MISSING)
        if a != b:
            yield key[len(prefix):], a, b


def _state(a, b) -> str:
    return "added" if a is _MISSING else "removed" if b is _MISSING else "changed"


def _why(old: dict, new: dict, keys: list) -> str | None:
    """Changes the slicers make to own profiles by themselves (FINDINGS 4.4)."""
    names = {k["key"] for k in keys}
    if names == {"version"}:
        return "version"
    if "inherits" in names:
        return "parent"
    if "compatible_printers" in names and not old.get("compatible_printers"):
        return "printers"
    return None


def compare(old: dict, new: dict) -> dict:
    """What differs, grouped as the page shows it; codes, no texts. count: the lines it lists."""
    out = {key: {"old": old.get(key), "new": new.get(key)} if old.get(key) != new.get(key) else None
           for key in ("slicer", "folder")}
    vendors = {v["vendor"] for k, v in new.items() if k.startswith("printer/")}
    out["packages"] = [{"name": name, "old": None if a is _MISSING else a, "new": None if b is _MISSING else b,
                        # The slicer deletes a vendor none of whose printers is selected (FINDINGS 4.2).
                        "why": "unused" if b is _MISSING and name not in vendors else None}
                       for name, a, b in _pairs(old, new, "package/")]
    out["printers"] = [{"model": model, "vendor": (b if a is _MISSING else a)["vendor"],
                        "old": None if a is _MISSING else a["nozzles"], "new": None if b is _MISSING else b["nozzles"]}
                       for model, a, b in _pairs(old, new, "printer/")]
    names = list(_pairs(old, new, "visible/"))
    visible = {"old": old.get("visible"), "new": new.get("visible"),
               "added": [n for n, a, _ in names if a is _MISSING], "removed": [n for n, _, b in names if b is _MISSING]}
    out["visible"] = visible if visible["added"] or visible["removed"] or visible["old"] != visible["new"] else None

    groups = {}
    for key, a, b in _pairs(old, new, "system/"):
        kind, name = key.split("/", 1)
        package = (a if b is _MISSING else b)[0]
        groups.setdefault((kind, package), {"added": [], "changed": [], "removed": []})[_state(a, b)].append(name)
    order = {kind: i for i, kind in enumerate(("filament", "process", "machine"))}
    out["system"] = [{"kind": kind, "package": package, **lists}
                     for (kind, package), lists in sorted(groups.items(), key=lambda g: (order.get(g[0][0], 9), g[0][1]))]

    out["own"] = []
    for key, a, b in _pairs(old, new, "own/"):
        kind, name = key.split("/", 1)
        entry = {"kind": kind, "name": name, "change": _state(a, b), "keys": [], "why": None}
        if isinstance(a, dict) and isinstance(b, dict):
            entry["keys"] = [{"key": k, "old": a.get(k), "new": b.get(k)} for k in sorted({*a, *b}) if a.get(k) != b.get(k)]
            entry["why"] = _why(a, b, entry["keys"])
            # A secret only as "***": the hash in the snapshot would let a device in the LAN try
            # passwords offline.
            entry["keys"] = [{**e, **{s: "***" for s in ("old", "new") if SECRET.search(e["key"]) and e[s] not in ("", None, [])}}
                             for e in entry["keys"]]
        elif entry["change"] == "changed":
            entry["why"] = "unreadable" if b is None else None
        out["own"].append(entry)

    out["count"] = (sum(out[k] is not None for k in ("slicer", "folder")) + len(out["packages"]) + len(out["printers"])
                    + (len(visible["added"]) + len(visible["removed"]) or int(out["visible"] is not None))
                    + sum(len(g[s]) for g in out["system"] for s in ("added", "changed", "removed")) + len(out["own"]))
    return out


def news(instance: Instance) -> dict:
    """The page: what differs from the snapshot. Takes the first one for an installation that
    has none yet. first: nobody has marked it seen yet, the page says it just started."""
    found = current(instance)
    with _lock:
        stored = load(instance.id) or _save(instance.id, found, first=True)
    return {**compare(stored["items"], found), "since": stored["taken"], "first": bool(stored.get("first"))}


def seen(instance: Instance) -> dict:
    """"Als gesehen markieren": the state of now becomes the snapshot."""
    found = current(instance)
    with _lock:
        stored = _save(instance.id, found)
    return {**compare(found, found), "since": stored["taken"], "first": False}


def count(instance: Instance, scan: scanner.Scan, res: Resolver) -> int:
    """For the menu, with the scan of GET /api/data. The first time OrcaOne sees an
    installation, its state becomes the snapshot."""
    if scan.conf_file is None:
        return 0
    found = items(scan, res)
    with _lock:
        stored = load(instance.id)
        if stored is None:
            try:
                _save(instance.id, found, first=True)
            except OSError:
                pass  # tried again with the next scan
            return 0
    return compare(stored["items"], found)["count"]


def accept(instance: Instance, before: dict, after: dict) -> None:
    """What OrcaOne wrote itself counts as seen: each item that differs between before and after
    its write goes into the snapshot as it is now. Changes from elsewhere not yet marked seen
    stay visible."""
    with _lock:
        stored = load(instance.id)
        if stored is None:
            return
        found = stored["items"]
        for key in set(before) | set(after):
            if before.get(key, _MISSING) != after.get(key, _MISSING):
                if key in after:
                    found[key] = after[key]
                else:
                    found.pop(key, None)
        _write(instance.id, stored)

"""Everything the pages show, per installation, read live: GET /api/data.

The structure is the one the draft E2 read from data.js (prototypes/ui-overview/make_data.py,
last in commit deee0f2), without example profiles and example backups. Texts are codes, their
German wording lives in orcaone/static/texts.js. Strictly read only.
"""

import colorsys
import logging
import re
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import backup, camera, covers, guard, instances, profile_groups, scanner, snapshot
from .model import SLICERS, Instance
from .resolver import CORE_VALUES, EDITABLE_FIELDS, STATUS_OF_PROBLEM, VALUE_KEYS, Resolver, first, strings
from .scanner import LIBRARY, KINDS

HEX_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}")
# A printer that came in with a 3MF project is named "<name>(<file>.3mf)" (FINDINGS 4.9).
PROJECT_NAME = re.compile(r"\(.*\.3mf\)$", re.IGNORECASE)
_FILAMENT_SLOT = re.compile(r"filament_\d\d")
# Credential fields in the .conf (FINDINGS 4.3), only counted, never shown.
DEVICE_FIELDS = ("api_key", "user", "password", "ca", "cert", "key", "clientId")

log = logging.getLogger(__name__)


def home_path(path: Path) -> str:
    try:
        return "~/" + path.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(path)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _items(value) -> list:
    return list(value.values()) if isinstance(value, dict) else value if isinstance(value, list) else []


def credential_counts(conf: dict) -> dict:
    """How many credentials of each kind the .conf holds. Values never leave this function."""
    counts = {}
    for device in _items(conf.get("devices")):
        for key in DEVICE_FIELDS:
            if isinstance(device, dict) and device.get(key):
                counts[key] = counts.get(key, 0) + 1
    codes = sum(1 for m in _items(conf.get("local_machines")) if isinstance(m, dict) and m.get("access_code"))
    codes += sum(1 for code in _items(conf.get("access_code")) if code)
    if codes:
        counts["access_code"] = codes
    return counts


def _lively(hexes: list) -> str | None:
    """First colour that is neither near white, black nor grey, so the spools differ at a glance."""
    for h in hexes:
        try:
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        except (ValueError, IndexError):
            continue
        _, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
        if saturation > 0.35 and 0.2 < lightness < 0.85:
            return h
    return hexes[0] if hexes else None


def _colours(res: Resolver, p, chain) -> tuple:
    """(colour for the spool, known colours). default_filament_colour wins, then the vendor
    colour file of the first profile in the chain that has an entry there."""
    known = []
    for q in [p] + chain:
        known = res.scan.colours.get((q.package, q.alias), [])
        if known:
            break
    value = first(res.value(p, "default_filament_colour"))
    match = HEX_COLOUR.match(value.strip()) if isinstance(value, str) else None
    if match:
        return match.group(0).upper(), known
    return _lively([c["hex"] for c in known]), known


def _info(p) -> dict | None:
    """What the .info says about syncing, without the account and cloud ids."""
    if not p.info:
        return None
    updated = p.info.get("updated_time", "")
    # Seconds since 1970; int() refuses more than 4300 digits, JavaScript is exact up to 15.
    valid = updated.isascii() and updated.isdigit() and len(updated) <= 15
    return {"sync_info": p.info.get("sync_info", ""), "updated_time": int(updated) if valid else None}


def _problem(res: Resolver, p, complete: bool) -> str | None:
    """Why the slicer does not show p: a code of STATUS_OF_PROBLEM."""
    if not p.package:
        return res.state(p).problem
    # A system profile with a broken chain takes its whole package down (FINDINGS 4.5).
    return None if complete else "parent_missing"


def _filament_record(res: Resolver, p, in_list: bool) -> dict:
    chain, complete = res.chain(p)
    colour, colours = _colours(res, p, chain)
    record = {
        "name": p.name, "alias": p.alias, "origin_kind": p.origin_kind, "package": p.package or None,
        "inherits": p.inherits or None,
        "material": first(res.value(p, "filament_type")),
        "vendor": first(res.value(p, "filament_vendor")),
        "chain": [c.name for c in chain], "chain_complete": complete,
        "compatible_printers": res.compatible_printers(p) if complete else strings(p.values.get("compatible_printers")),
        "in_list": in_list, "values": {key: res.value_entry(p, key, chain, complete) for key in VALUE_KEYS},
        "printers": {}, "colour": colour,
    }
    if colours:
        record["colours"] = colours
    if p.bundle:
        record["bundle"] = res.scan.bundles.get(p.bundle, "")
    if "high_flow" in strings(res.value(p, "filament_flow_support")):
        # Snapmaker Orca: own values for the high-flow hotend (FINDINGS 4.4).
        record["high_flow"] = True
    if not p.package:
        state = res.state(p)
        record["file"] = p.file
        record["info"] = _info(p)
        if state.via not in (None, "exact"):
            record["parent_via"] = state.via
    problem = _problem(res, p, complete)
    if problem:
        record["status"] = STATUS_OF_PROBLEM[problem]
        record["problem"] = problem
    return record


def _own_printer_models(res: Resolver) -> list:
    """Own printers the slicer loads, one model each: base model, variant and vendor package
    come from the template chain (FINDINGS 4.4)."""
    out = []
    for p in sorted(res.own_profiles("machine"), key=lambda p: p.name.lower()):
        chain, complete = res.chain(p)
        if not res.loaded(p) or not complete:
            continue
        base = next((c for c in chain if c.package), None)
        nozzle = strings(res.value(p, "nozzle_diameter"))
        out.append({"printer": p, "model": first(res.value(p, "printer_model")) or "",
                    "variant": "+".join(dict.fromkeys(nozzle)) or first(res.value(p, "printer_variant")) or "",
                    "nozzle": nozzle,
                    "package": base.package if base else ""})
    return out


def _ota_enabled(conf: dict) -> bool:
    return _dict(conf.get("app")).get("enable_ota") in (True, "true", "1")


def _drops_unused_package(scan, package: str) -> bool:
    """Whether the slicer deletes this vendor package at its next start once no model of it is
    left in "models" (FINDINGS 4.2, PresetUpdater::check_installed_vendor_profiles). Each slicer
    keeps its own package: Snapmaker in Snapmaker Orca, Custom in OrcaSlicer. OrcaSlicer main
    (.opc) only touches installed vendors with app.enable_ota."""
    if package == LIBRARY:
        return False
    if scan.snorca:
        return package != "Snapmaker"
    if scan.storage == "opc" and not _ota_enabled(scan.conf):
        return False
    return package != "Custom"


def _only_on(res: Resolver, printer_names: set) -> list:
    """Own filaments and processes usable on these printers only: offered for deleting along."""
    out = []
    for q in res.own_profiles():
        # Bundle profiles stay: OrcaOne never deletes them.
        if q.kind == "machine" or q.bundle:
            continue
        chain, complete = res.chain(q)
        printers = res.compatible_printers(q) if complete else strings(q.values.get("compatible_printers"))
        if not printers or not set(printers) <= printer_names:
            continue
        item = {"name": q.name, "kind": q.kind}
        if not complete and res.state(q).problem != "parent_unreadable":
            item["orphaned"] = True
        if res.snorca and q.kind == "filament" and res.is_helper(q):
            item["helper"] = True
        out.append(item)
    return sorted(out, key=lambda i: (i["kind"], i["name"].lower()))


# ---------------------------------------------------------------- page "Prozesse"

# The slicer's default for the values the page shows first, where no profile of the chain sets
# them: PrintConfigDef, the same in Snapmaker Orca 2.4.0 and OrcaSlicer main (PrintConfig.cpp,
# e.g. brim_type at line 1350 and 1857). Strings as the slicer writes them to JSON.
PROCESS_DEFAULTS = {
    "layer_height": "0.2", "initial_layer_print_height": "0.2", "seam_position": "aligned",
    "ironing_type": "no ironing", "wall_loops": "2", "top_shell_layers": "4", "bottom_shell_layers": "3",
    "sparse_infill_density": "20%", "sparse_infill_pattern": "crosshatch", "outer_wall_speed": "60",
    "inner_wall_speed": "60", "sparse_infill_speed": "100", "top_surface_speed": "100",
    "initial_layer_speed": "30", "travel_speed": "120", "default_acceleration": "500", "enable_support": "0",
    "support_type": "normal(auto)", "support_threshold_angle": "30", "support_on_build_plate_only": "0",
    "brim_type": "auto_brim", "brim_width": "0", "skirt_loops": "1", "raft_layers": "0",
}


def _process_record(res: Resolver, p) -> dict:
    """A process as a tile: its layer height, and the name up to "@", which names the kind."""
    record = {"name": p.name, "alias": p.alias, "origin_kind": p.origin_kind, "package": p.package or None,
              "layer_height": first(res.value(p, "layer_height")) or PROCESS_DEFAULTS["layer_height"]}
    if not p.package:
        parent = res.parent(p)
        record["template"] = parent.name if parent else None
    if p.bundle:
        record["bundle"] = res.scan.bundles.get(p.bundle, "")
    if "high_flow" in strings(res.value(p, "process_flow_support")):
        record["high_flow"] = True
    return record


def _link(p) -> dict:
    return {"name": p.name, "origin_kind": p.origin_kind, "package": p.package or None, "file": p.file,
            "abstract": not p.selectable, "inherits": p.inherits or None}


def profile_details(instance: Instance, kind: str, name: str) -> dict | None:
    """One profile as the slicer resolves it, read on demand for the side panel of the page
    "Prozesse" and for the page "Details": its chain of templates with their files, and every
    value with the profile that sets it. A process also gets the slicer's default for the values
    the page shows first. None if there is no such profile."""
    scan = scanner.scan(instance.data_dir, instance.slicer)
    res = Resolver(scan)
    found = [p for p in scan.of_kind(kind) if p.name == name and p.selectable]
    found += [p for p in res.own_profiles(kind) if p.name == name]
    if not found:
        return None
    p = found[0]
    chain, complete = res.chain(p)
    values = {}
    for q in [p] + chain:
        for key, value in q.values.items():
            # "…_settings_id" repeats the name.
            if key not in values and key not in scanner.META_KEYS and not key.endswith("_settings_id"):
                # A printer's API key or password (printhost_apikey, printhost_password) stays hidden:
                # any device in the LAN may open this page (the user's wish of 25.09.2026).
                shown = "***" if snapshot.SECRET.search(key) and value not in ("", None, []) else value
                values[key] = {"value": shown, "source": q.name, "own": q is p}
    if kind == "process":
        for key, value in PROCESS_DEFAULTS.items():
            values.setdefault(key, {"value": value, "source": None, "own": False, "default": True})
    out = {**_link(p), "kind": kind, "inherits": p.inherits or None, "renamed_from": p.renamed_from,
           "chain": [_link(q) for q in chain], "chain_complete": complete, "values": dict(sorted(values.items()))}
    if not p.package:
        state = res.state(p)
        out["info"] = _info(p)
        out["problem"] = state.problem if state else None
        out["parent_via"] = state.via if state else None
    if p.bundle:
        out["bundle"] = scan.bundles.get(p.bundle, "")
    return out


# ---------------------------------------------------------------- page "Drucker"

def _printers_page(res: Resolver, system_models: list, system_printers: list, selected: str, cover) -> dict:
    scan = res.scan
    own_printers = sorted(res.own_profiles("machine"), key=lambda p: p.name.lower())
    loadable = {p.name for p in own_printers if res.loaded(p) and res.chain(p)[1]}
    known = {p.name for p in system_printers} | loadable

    system = []
    for m in system_models:
        names = {v["name"] for v in m["printers"]}
        based = [p.name for p in own_printers if (res.parent(p) and res.parent(p).name) in names]
        system.append({
            "model": m["model"], "origin": m["origin"], "cover": m["cover"],
            "printers": [{"name": v["name"], "variant": v["variant"], "default": v["selected"],
                          "visible_filaments": v["counts"]["visible"], "processes": v["process_count"]}
                         for v in m["printers"]],
            "own_printers": based, "only_here": _only_on(res, names),
            # Whether it is the last model of its package is up to the page: it can change there.
            "drops_package": _drops_unused_package(scan, m["origin"]),
        })

    own = []
    for p in own_printers:
        chain, complete = res.chain(p)
        base = next((c for c in chain if c.package), None) if complete else None
        model = first(res.value(p, "printer_model")) if complete else None
        entry = {
            "name": p.name, "based_on": p.inherits or None, "based_on_found": complete and bool(p.inherits),
            "package": base.package if base else None,
            "model": model, "variant": first(res.value(p, "printer_variant")) if complete else None,
            "cover": cover(base.package if base else None, model), "visible": p.name in loadable, "default": p.name == selected,
            "origin": "bundle" if p.bundle else "project" if PROJECT_NAME.search(p.name) else "own",
            "file": p.file, "info": _info(p), "only_here": _only_on(res, {p.name}),
            # "Hostname, IP or URL" of the dialog "Physical Printer": the slicer saves it into an
            # own printer (PhysicalPrinterDialog::OnOK, save_preset).
            "print_host": (first(res.value(p, "print_host")) or None) if complete else None,
        }
        if p.bundle:
            entry["bundle"] = scan.bundles.get(p.bundle, "")
        problem = _problem(res, p, complete)
        if problem:
            entry["status"] = STATUS_OF_PROBLEM[problem]
            entry["problem"] = problem
        own.append(entry)

    # A printer Snapmaker Orca connected to (found by mDNS) stays in the .conf under "devices" with
    # its address, next to credentials that never leave this function. Its preset names the printer
    # model the address belongs to (FINDINGS, "Windows am echten Rechner").
    by_name = {p.name: p for p in system_printers}
    devices = []
    for d in _items(scan.conf.get("devices")):
        if not isinstance(d, dict) or not isinstance(d.get("ip"), str) or not d["ip"]:
            continue
        preset = by_name.get(d["preset_name"]) if isinstance(d.get("preset_name"), str) else None
        model = (first(res.value(preset, "printer_model")) if preset else None) or d.get("model_name")
        if isinstance(model, str) and model:
            devices.append({"model": model, "host": d["ip"]})

    # orca_presets keeps the last choice per printer and is never cleaned up (FINDINGS 4.3, 4.9).
    presets = [e for e in _items(scan.conf.get("orca_presets")) if isinstance(e, dict)]
    dead = []
    for e in presets:
        machine = e.get("machine", "")
        # A non-string stops the slicer from loading the .conf (FINDINGS 4.3), not OrcaOne.
        if not isinstance(machine, str) or machine in known:
            continue
        if machine == "Default Printer":
            reason = "default_printer"   # placeholder from the first start, before the wizard
        elif PROJECT_NAME.search(machine):
            reason = "project"
        elif res.missing_parent == "parent_unreadable":
            continue   # it may sit in a package OrcaOne cannot read (FINDINGS, .opc rules)
        else:
            reason = "missing"
        dead.append({"machine": machine, "process": e.get("process", ""),
                     "filaments": [e[k] for k in sorted(e) if k == "filament" or _FILAMENT_SLOT.fullmatch(k)],
                     "reason": reason})

    default = {"name": selected, "exists": selected in known, "own": selected in loadable}
    for m in system_models:
        for v in m["printers"]:
            if v["name"] == selected:
                default.update(model=m["model"], variant=v["variant"], cover=m["cover"])
    return {"default_printer": default, "system": system, "own": own, "devices": devices,
            "remembered": len(presets), "dead_entries": dead}


# ---------------------------------------------------------------- page "Installationen"

def _system_refresh(scan) -> dict:
    # OrcaSlicer main refreshes installed vendors only with app.enable_ota (FINDINGS 4.2).
    if not scan.snorca and scan.storage == "opc" and not _ota_enabled(scan.conf):
        return {"value": False, "code": "missing_only"}
    return {"value": True, "code": "every_start"}


def _own_file_count(scan, kind: str) -> int:
    user = scan.data_dir / "user"
    try:
        folders = [d for d in user.iterdir() if d.is_dir() and d.name != "Temp"] if user.is_dir() else []
    except OSError:
        return 0
    return sum(len(list((d / kind).glob("*.json"))) + len(list((d / kind / "base").glob("*.json"))) for d in folders)


def _slicer_page(instance: Instance, res: Resolver, measured: tuple, running: bool) -> dict:
    scan = res.scan
    conf = scan.conf
    credentials = credential_counts(conf)
    set_up = {}
    for entry in _items(conf.get("models")):
        if isinstance(entry, dict) and isinstance(entry.get("vendor"), str) and isinstance(entry.get("model"), str):
            set_up.setdefault(entry["vendor"], []).append(entry["model"])

    packages = []
    for pk in scan.packages:
        size = files = 0
        for rel in (pk.file, pk.folder):
            if rel and (scan.data_dir / rel).exists():
                s, f = scanner.measure(scan.data_dir / rel)
                size, files = size + s, files + f
        library = pk.name == LIBRARY
        note = "library" if library else "installed_for" if set_up.get(pk.name) else "not_set_up"
        entry = {"name": pk.name, "role": "library" if library else "vendor", "format": pk.format,
                 "file": pk.file, "folder": pk.folder, "version": pk.version,
                 "version_display": scanner.display_version(pk.version), "size": size, "files": files,
                 "models": pk.models, "printers_set_up": set_up.get(pk.name, []), "counts": pk.counts,
                 "note": note, "manifest_empty": pk.manifest_empty}
        if pk.extra_files:
            entry["extra_files"] = [f"{pk.folder}/{name}" for name in pk.extra_files]
        if pk.error:
            entry["error"] = pk.error
        packages.append(entry)

    counts = {}
    for kind in KINDS:
        system = scan.of_kind(kind)
        counts[kind] = {"system": len(system), "system_selectable": sum(1 for p in system if p.selectable),
                        "own": _own_file_count(scan, kind)}

    ignored = {p.file: res.state(p).problem for p in res.own_profiles() if res.state(p).problem}
    tree = scanner.tree(scan, ignored, bool(credentials))
    conf_file = scan.conf_file
    indent = conf_file.indent if conf_file else None
    preset_folder = _dict(conf.get("app")).get("preset_folder", "")
    raw, zipped, backup_files = measured
    return {
        "slicer": SLICERS[instance.slicer]["name"], "header": conf.get("header", ""),
        "version": instance.version or "", "path": home_path(instance.data_dir), "source": instance.source,
        "running": running, "logged_in": instance.logged_in,
        "preset_folder": preset_folder if isinstance(preset_folder, str) else "",
        "user_folder": f"user/{scan.active_folder}",
        "conf": {"file": f"{instance.slicer}.conf", "size": scan.conf_size,
                 "indent": None if indent is None else "tab" if indent == "\t" else "spaces",
                 "indent_width": len(indent) if indent and indent != "\t" else None,
                 "checksum": bool(conf_file and conf_file.checksum),
                 "sections": len(conf), "credentials": credentials},
        "system_format": scan.storage,
        "system_refresh": _system_refresh(scan),
        "packages": packages,
        "profile_counts": counts,
        "tree": tree,
        "outside": scanner.outside(instance.slicer),
        "totals": {"size": sum(e["size"] for e in tree), "files": sum(e["files"] for e in tree),
                   "backup_size": raw, "backup_zip_size": zipped, "backup_files": backup_files},
    }


def _backups_page(instance: Instance, measured: tuple) -> dict:
    """The backups OrcaOne made (orcaone/backup.py), newest first, as GET /api/instances/{id}/backups
    lists them. "now" is what a backup of this data directory would be today (hard rule 4,
    zipped in memory)."""
    raw, zipped, files = measured
    made = backup.list_backups(instance.id)
    return {
        "location": home_path(backup.backup_dir(instance.id)),
        "backups": made, "count": len(made), "total_size": sum(b["size"] for b in made),
        "now": {"size": raw, "zip_size": zipped, "files": files},
        "excluded": scanner.BACKUP_EXCLUDED,
    }


# ---------------------------------------------------------------- one installation

def hidden_filaments(res: Resolver, names) -> list:
    """Of these system filament names, the ones "filaments" hides. For the library filaments
    OrcaOne unlocked (way A): the wizard and a few dialogs rewrite the list (FINDINGS 4.6, 4.7)."""
    listed = set(res.filament_list())
    filaments = res.scan.of_kind("filament")
    return sorted(n for n in names if not any(p.name == n and res.in_list(p, listed) for p in filaments))


def _warnings(res: Resolver, records: dict, without_printer: list, same_alias: list, real_printers: set,
              lost_unlocks: list) -> list:
    scan = res.scan
    warnings = []
    if lost_unlocks:
        warnings.append({"code": "unlock_lost", "level": "warning", "count": len(lost_unlocks), "names": lost_unlocks})
    for pk in scan.packages:
        if pk.error:
            warnings.append({"code": "package_unreadable", "level": "error", "count": 1, "names": [pk.name],
                             "problem": pk.error, "file": pk.file})
    broken = {}
    for p in scan.profiles.values():
        if p.selectable and not res.chain(p)[1]:
            broken.setdefault(p.package, []).append(p.name)
    for package, names in sorted(broken.items()):
        # The slicer drops the whole package when a parent is missing (FINDINGS 4.5).
        warnings.append({"code": "package_incomplete", "level": "error", "count": len(names),
                         "names": sorted(names), "package": package})
    if without_printer:
        warnings.append({"code": "visible_without_printer", "level": "info", "count": len(without_printer),
                         "names": [w["name"] for w in without_printer]})
    for p in res.own_profiles():
        state = res.state(p)
        if state.problem:
            status = STATUS_OF_PROBLEM[state.problem]
            warnings.append({"code": status, "level": "error" if status == "orphaned" else "warning", "count": 1,
                             "names": [p.name], "kind": p.kind, "problem": state.problem,
                             "inherits": p.inherits or None, "file": p.file})
        elif state.via == "generic":
            # The slicer found a parent only by the Generic fallback and writes it into inherits.
            warnings.append({"code": "fallback_parent", "level": "info", "count": 1, "names": [p.name],
                             "kind": p.kind, "inherits": p.inherits, "parent": state.parent.name})
        if p.json_name and not state.problem:
            # The other slicer takes the other name (FINDINGS 4.4).
            warnings.append({"code": "name_mismatch", "level": "info", "count": 1, "names": [p.name],
                             "kind": p.kind, "json_name": p.json_name, "file": p.file})
    for printer_name, names in same_alias:
        warnings.append({"code": "same_alias", "level": "warning", "count": len(names), "names": names,
                         "printer": printer_name})
    if scan.snorca:
        unlockable = {r["name"] for r in records.values()
                      if any(e.get("unlockable") for name, e in r["printers"].items() if name in real_printers)}
        if unlockable:
            warnings.append({"code": "library_hidden", "level": "info", "count": len(unlockable),
                             "names": sorted(unlockable)})
    return warnings


# What the scan for GET /api/data does right now, for the boot screen (GET /api/progress, the user's
# wish of 24.09.2026): its steps in order, each with a code, a few numbers and whether it is done.
# Only the last scan counts; two at the same time mix, which only the boot screen would show.
STEPS_PER_INSTANCE = 4   # profiles, resolve, folders, news
_progress = {"steps": [], "total": 0}
_progress_lock = threading.Lock()


def _begin(code: str | None, **detail) -> None:
    """The step running so far is done, the next starts; None ends the scan."""
    with _progress_lock:
        if _progress["steps"]:
            _progress["steps"][-1]["done"] = True
        if code:
            _progress["steps"].append({"code": code, **detail, "done": False})


def _note(**numbers) -> None:
    """Numbers for the step running now, e.g. how many profiles it read."""
    with _progress_lock:
        if _progress["steps"]:
            _progress["steps"][-1].update(numbers)


def _fail(label: str) -> None:
    """The installation could not be read: its running step failed, else a step says so."""
    with _progress_lock:
        steps = _progress["steps"]
        if not steps or steps[-1]["done"] or steps[-1].get("instance") != label:
            steps.append({"code": "failed", "instance": label})
        steps[-1].update(done=True, failed=True)


def progress() -> dict:
    with _progress_lock:
        return {"steps": [dict(s) for s in _progress["steps"]], "total": _progress["total"]}


def _label(instance: Instance) -> str:
    return f"{SLICERS[instance.slicer]['name']} {instance.version or ''}".strip()


def build_instance(instance: Instance, processes: list, manual: bool = False) -> dict:
    label = _label(instance)
    _begin("profiles", instance=label)
    scan = scanner.scan(instance.data_dir, instance.slicer)
    _note(system=len(scan.profiles), own=len(scan.own))
    _begin("resolve", instance=label)
    res = Resolver(scan)
    snorca = scan.snorca
    conf = scan.conf

    models = res.installed_printers()
    # Each model's picture from the slicer's program folder (covers.py), else OrcaOne's own drawing.
    cover = covers.finder(processes)
    system_printers = [p for m in models for _, p in m["printers"]]
    own_models = _own_printer_models(res)
    all_printers = system_printers + [o["printer"] for o in own_models]

    filament_list = res.filament_list()
    list_names = set(filament_list)
    system_filaments = [p for p in scan.of_kind("filament") if p.selectable]
    excluded = res.library_exclusions()
    selected = _dict(conf.get("presets")).get("machine", "")
    selected = selected if isinstance(selected, str) else ""

    # Own filaments hidden with instantiation "false" come along: the page shows them switched off.
    candidates = sorted(system_filaments + res.own_profiles("filament"),
                        key=lambda p: (p.origin_kind != "user", p.name.lower()))
    records = {}
    for p in candidates:
        record = _filament_record(res, p, res.in_list(p, list_names) if p.package else True)
        hidden = not p.package and not p.selectable
        if hidden:
            record["hidden"] = True
        if snorca and res.is_helper(p):
            record["helper"] = True
        if record.get("status"):
            records[p.name] = record
            continue
        for printer in all_printers:
            fit = res.fits(printer, p)
            if not fit:
                continue
            by = res.displaced_by(excluded, p, printer)
            if by:
                entry = {"status": "displaced", "displaced_by": by}
            elif hidden:
                entry = {"status": "hidden"}
            elif record["in_list"]:
                entry = {"status": "visible"}
            else:
                entry = {"status": "hidden"}
                if snorca and p.origin_kind == "library":
                    # Only the list hides it; OrcaOne can unlock it (FINDINGS 4.7).
                    entry["unlockable"] = True
            if fit == "conditional":
                entry["conditional"] = True
            record["printers"][printer.name] = entry
        if record["printers"] or (list_names and record["in_list"]):
            records[p.name] = record

    processes_all = [p for p in scan.of_kind("process") if p.selectable] + \
                    [p for p in res.own_profiles("process") if res.loaded(p)]
    # The process last chosen per printer: the slicer keeps the current one in "presets", the
    # others in "orca_presets" (FINDINGS 4.3).
    presets = _dict(conf.get("presets"))
    chosen = {e["machine"]: e for e in _items(conf.get("orca_presets")) if isinstance(e, dict) and isinstance(e.get("machine"), str)}
    remembered = {machine: e.get("process") for machine, e in chosen.items()}
    same_alias = []

    def heads_of(printer):
        """The filament per head the slicer remembers for a printer, with its colour: "filament",
        "filament_01" … and "filament_colors" of its orca_presets entry (FINDINGS 4.3), for the page
        "Übersicht" (what is set in the slicer). The material from the profile, if OrcaOne knows it."""
        e = chosen.get(printer.name) or {}
        names = [e.get("filament")]
        while isinstance(e.get(f"filament_{len(names):02d}"), str):
            names.append(e[f"filament_{len(names):02d}"])
        colours = [c.strip() for c in str(e.get("filament_colors") or "").split(",")]
        heads = []
        for k, name in enumerate(names):
            if not isinstance(name, str) or not name:
                break
            colour = colours[k] if k < len(colours) and re.fullmatch(r"#[0-9A-Fa-f]{6}", colours[k]) else None
            heads.append({"name": name, "colour": colour, "material": (records.get(name) or {}).get("material")})
        return heads

    def variant_entry(variant, printer):
        counts = {"visible": 0, "hidden": 0, "displaced": 0}
        rows = []
        for r in records.values():
            entry = r["printers"].get(printer.name)
            if entry:
                counts[entry["status"]] += 1
                rows.append(r)
        proc_names = sorted(p.name for p in processes_all if res.fits(printer, p))
        if snorca:
            # Snapmaker Orca's sidebar shows only one system filament per alias (FINDINGS 4.6).
            seen = {}
            for r in rows:
                if r["printers"][printer.name]["status"] == "visible" and r["origin_kind"] != "user":
                    seen.setdefault(r["alias"], []).append(r["name"])
            same_alias.extend((printer.name, names) for names in seen.values() if len(names) > 1)
        last = presets.get("process") if printer.name == selected else None
        if not isinstance(last, str) or last not in proc_names:
            last = remembered.get(printer.name)
        return {"name": printer.name, "variant": variant, "selected": printer.name == selected,
                "counts": counts, "process_count": len(proc_names), "processes": proc_names,
                "process": last if isinstance(last, str) and last in proc_names else None, "heads": heads_of(printer)}

    system_models = [{"model": m["model"], "origin": m["package"],
                      "printers": [variant_entry(variant, printer) for variant, printer in m["printers"]],
                      "cover": cover(m["package"], m["model"])} for m in models]
    # Own printers after the system models, so a model keeps its index (and its address).
    own_cards = [
        {"model": o["printer"].name, "origin": o["package"], "own": True, "based_on": o["model"],
         "printers": [{**variant_entry(o["variant"], o["printer"]), "nozzle": o["nozzle"]}],
         "cover": cover(o["package"], o["model"]),
         **({"bundle": scan.bundles.get(o["printer"].bundle, "")} if o["printer"].bundle else {})}
        for o in own_models]
    own_counts = Counter(p.name for p in scan.own if p.kind == "machine")
    groups = profile_groups.resolve_groups(instance.id,
                                            [o["printer"].name for o in own_models if o["printer"].origin_kind == "user"],
                                            [name for name, count in own_counts.items() if count > 1],
                                            user_folder=instance.active_user_folder)
    by_name = {card["printers"][0]["name"]: card for card in own_cards}
    membership = {name: group for group in groups for name in group["names"]}
    out_models = list(system_models)
    seen_groups = set()
    for card in own_cards:
        name = card["printers"][0]["name"]
        group = membership.get(name)
        if group is None:
            out_models.append(card)
        elif group["id"] not in seen_groups:
            seen_groups.add(group["id"])
            members = [by_name[member] for member in group["names"]]
            bases = {member["based_on"] for member in members}
            out_models.append({"model": "group:" + group["id"], "group_id": group["id"],
                               "display_name": group["display_name"], "own": True,
                               "origin": members[0]["origin"], "cover": members[0]["cover"],
                               "based_on": next(iter(bases)) if len(bases) == 1 else "",
                               "printers": [{**member["printers"][0],
                                             **({"label": group["labels"][member["printers"][0]["name"]]}
                                                if member["printers"][0]["name"] in group.get("labels", {}) else {})}
                                            for member in members]})

    without_printer = []
    for name in filament_list:
        matches = [p for p in system_filaments if p.name == name or name in p.renamed_from]
        if any(records.get(p.name, {}).get("printers") for p in matches):
            continue
        without_printer.append({"name": name, "exists": bool(matches)})

    lost = hidden_filaments(res, instances.load_unlocks(instance.id)) if snorca else []
    warnings = _warnings(res, records, without_printer, same_alias, {p.name for p in all_printers}, lost)
    running, reason = _run_state(instance, processes)
    _note(printers=len(all_printers), filaments=len(records))
    _begin("folders", instance=label)
    measured = scanner.backup_measure(instance.data_dir)
    slicer_page = _slicer_page(instance, res, measured, running)
    _note(size=measured[0])
    _begin("news", instance=label)
    news = snapshot.count(instance, scan, res)
    _note(count=news)
    return {
        "id": instance.id, "slicer": SLICERS[instance.slicer]["name"], "app_key": instance.slicer,
        "kind": "snorca" if snorca else "orca",
        "header": conf.get("header", ""), "version": instance.version or "",
        "path": home_path(instance.data_dir), "storage": scan.storage, "source": instance.source, "manual": manual,
        # The path as orcaone/instances.py stores it: "Entfernen" sends it back for a manual one.
        "data_dir": str(instance.data_dir),
        "running": running,
        # Why OrcaOne only shows: "lock", "process" or "process_unmapped" (orcaone/guard.py).
        "running_reason": reason,
        "problems": list(instance.problems),
        "logged_in": instance.logged_in,
        "selected_printer": selected,
        "conf_saved": scan.conf_saved,
        "filament_list": {"mode": "list" if filament_list else "all", "count": len(filament_list)},
        "models": out_models,
        "filaments": list(records.values()),
        "processes": [_process_record(res, p) for p in processes_all],
        "without_printer": without_printer,
        "warnings": warnings,
        # Changes since the user last marked the installation seen, for the menu (page "Änderungen").
        "news": news,
        "stats": {
            "models": len(out_models), "printers": len(all_printers),
            "system_filaments_selectable": len(system_filaments),
            "filaments_shown": len(records),
            "warnings": len(warnings),
            "per_printer": {v["name"]: {**v["counts"], "processes": v["process_count"]}
                            for m in out_models for v in m["printers"]},
        },
        "slicer_page": slicer_page,
        "printers_page": _printers_page(res, system_models, system_printers, selected, cover),
        "backups_page": _backups_page(instance, measured),
    }


def _run_state(instance: Instance, processes: list) -> tuple:
    state = guard.run_state(instance, processes)
    if not state.running:
        return False, None
    return True, {"code": state.reason, "pids": state.pids, "lock": state.lock}


def build_all() -> dict:
    """All installations OrcaOne finds, including those added by hand, read fresh. One that
    cannot be read (a file edited by hand, a bug in OrcaOne) goes to "failed", the others stay."""
    with _progress_lock:
        _progress.update(steps=[], total=0)
    _begin("processes")
    processes = guard.find_processes()
    _note(running=sorted({SLICERS[p.slicer]["name"] for p in processes}))
    _begin("discover")
    found = instances.discover([p.data_dir for p in processes if p.data_dir])
    _note(count=len(found))
    with _progress_lock:
        _progress["total"] = 2 + STEPS_PER_INSTANCE * len(found)
    manual = set(instances.manual_paths())
    built, failed = [], []
    for i in found:
        try:
            item = build_instance(i, processes, str(i.data_dir) in manual)
            # Only profiles explicitly opened in the editor have local identities.
            # A history-store failure must not hide the slicer's normal overview.
            try:
                from .profile_live import capture
                item["profile_history"] = capture(i)
            except Exception:
                log.exception("Reading local profile history failed")
                item["profile_history"] = {"error": "history_unavailable"}
            built.append(item)
        except Exception:
            log.exception("Reading %s failed", i.data_dir)
            _fail(_label(i))
            failed.append({"id": i.id, "slicer": SLICERS[i.slicer]["name"], "path": home_path(i.data_dir),
                           "data_dir": str(i.data_dir), "manual": str(i.data_dir) in manual, "code": "scan_failed"})
    _begin(None)
    # The addresses the slicers have, for the printer part. One typed in on the page "Drucker" goes
    # first (camera.printers), then the one of the dialog "Physical Printer", then the one of a
    # printer Snapmaker Orca connected to; the first installation first. Each address is a printer
    # of its own, a second of the same model named after its printer profile.
    typed = [{"model": p["model"], "host": p["print_host"], "slicer": b["slicer"], "name": p["name"]}
             for b in built for p in b["printers_page"]["own"] if p.get("model") and p.get("print_host")]
    connected = [{"model": d["model"], "host": d["host"], "slicer": b["slicer"], "name": None}
                 for b in built for d in b["printers_page"]["devices"]]
    camera.remember_slicer_hosts(typed + connected)
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "core_values": [{"key": key} for key in CORE_VALUES],
        "editable_fields": [{"key": k, "group": group, "type": kind, "default": default, "min": low, "max": high}
                            for k, group, kind, default, low, high in EDITABLE_FIELDS],
        "instances": built,
        "failed": failed,
    }

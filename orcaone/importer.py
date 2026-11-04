"""Page "Import/Export": profiles from a file into an installation, and own profiles out as a ZIP.

The import reads what the Orca family writes (docs/IMPORT-QUELLEN.md): a profile JSON, a ZIP of
profiles (the slicers' export dialog, OrcaOne's export, vendor packs), the bundles .orca_filament,
.orca_printer and .orca_bundle, OrcaOne's backups (a data directory as ZIP), 3MF projects and the
slicer's own copies of user/ in the data directory (user_backup-v<version>, read_backup). No
slicer shows beforehand what a file holds; here read() lists it, analyse() tells per profile
what an import would do in the chosen installation, and the planner writes the chosen ones
(operations.op_profile_import) like every change: plan, backup, write, scan. Archives are read in
memory with limits, never unpacked to disk.

How a profile lands (convert): as the child of its parent if the installation has that one,
else as a root profile with every value, the way the page "Übertragen" copies (transfer.py).
Parents from the same file go into it. A 3MF holds complete profiles, so these land even without
their parent. A filament can instead be hung onto a printer here (attach): the child of a
filament of that printer, with only the material's values from the file.

The page "3MF bereinigen" gets a 3MF back without its project's printer (clean_3mf).
"""

import hashlib
import io
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import snapshot, transfer
from .resolver import Resolver, as_list, first
from .scanner import META_KEYS, alias_of

KINDS = ("filament", "process", "machine")
SETTINGS_ID = {"filament": "filament_settings_id", "process": "print_settings_id", "machine": "printer_settings_id"}
# The slicers know the kind of a file only by its settings id (FINDINGS 4.8); "type" and the
# folder help where it is missing.
_TYPES = {"filament": "filament", "process": "process", "print": "process", "machine": "machine", "printer": "machine"}
# Own profiles a 3MF project embeds, as complete JSON (bbs_3mf.cpp, FINDINGS 4.8).
_EMBEDDED = re.compile(r"Metadata/(machine|filament|process)_settings_\d+\.config", re.IGNORECASE)
_PROJECT = "Metadata/project_settings.config"
_MODEL = "3d/3dmodel.model"
# What makes a slicer set up the printer, process and filaments of a project when it opens the 3MF,
# even temporarily: the project's settings and the profiles it embeds; with them go the G-code and
# slice info of plates sliced for that printer (bbs_3mf.cpp, FINDINGS 4.8).
_PRINTER_BOUND = re.compile(r"Metadata/(?:project_settings\.config|slice_info\.config|[^/]+\.gcode(?:\.md5)?"
                            r"|(?:print_setting|process_settings|filament_settings|machine_settings)_[^/]+)", re.IGNORECASE)
_APPLICATION = re.compile(r'<metadata name="Application">([^<]*)</metadata>')
# A data directory or one of OrcaOne's backups: the own profiles of every user folder.
_USER_FILE = re.compile(r"user/[^/]+/(machine|process|filament)/(?:base/)?[^/]+\.json")
# The slicer's own copy of user/, made once per program version at its first start
# (PresetBundle::backup_user_folder, FINDINGS 4.2): after an update, lost profiles are often there.
_SLICER_BACKUP = re.compile(r"user_backup-v[^/\\]+")
_BACKUP_FILE = re.compile(r"[^/]+/(machine|process|filament)/(?:base/)?[^/]+\.json")
# Files beside the profiles: bundle descriptions, vendor manifests, metadata of archives.
_NOT_PROFILES = {"bundle_structure.json", "bundle_metadata.json", "orcaone-backup.json", "orfix-backup.json"}
# A printer's connection and its credentials; the slicers' export drops them too (FINDINGS 4.8).
_CONNECTION = re.compile(r"print_?host")
# Scripts the slicer runs on this computer after slicing (post_process; BackgroundSlicingProcess of
# both slicers): never from a file, whoever sent it, the page or a device in the LAN.
_RUNS_HERE = {"post_process"}
# A filament's colour in a project, "#RRGGBB" and in some versions with alpha.
_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?")
# Values the page shows per profile, besides name and printers.
CORE = {"filament": ("filament_vendor", "filament_type", "nozzle_temperature", "filament_flow_ratio", "filament_max_volumetric_speed"),
        "process": ("layer_height", "wall_loops", "sparse_infill_density"),
        "machine": ("printer_model", "nozzle_diameter")}
# Values of the material, not of the printer (ORCAONE_SPEC, "An Zielprofil hängen"): a filament
# hung onto a printer here takes these from the file, all else from a filament of that printer.
MATERIAL_KEYS = (
    "filament_vendor", "filament_type", "default_filament_colour", "filament_density", "filament_cost", "filament_diameter",
    "filament_flow_ratio", "filament_max_volumetric_speed", "nozzle_temperature", "nozzle_temperature_initial_layer",
    "nozzle_temperature_range_low", "nozzle_temperature_range_high", "hot_plate_temp", "hot_plate_temp_initial_layer",
    "cool_plate_temp", "cool_plate_temp_initial_layer", "eng_plate_temp", "eng_plate_temp_initial_layer",
    "textured_plate_temp", "textured_plate_temp_initial_layer", "supertack_plate_temp", "supertack_plate_temp_initial_layer",
    "textured_cool_plate_temp", "textured_cool_plate_temp_initial_layer", "chamber_temperature", "temperature_vitrification",
    "fan_min_speed", "fan_max_speed", "fan_cooling_layer_time", "slow_down_layer_time", "slow_down_min_speed",
    "overhang_fan_speed", "overhang_fan_threshold", "close_fan_the_first_x_layers", "full_fan_speed_layer",
    "reduce_fan_stop_start_freq", "filament_shrink", "filament_shrinkage_compensation_z", "filament_soluble",
    "filament_is_support", "required_nozzle_HRC",
)
MAX_FILE = 300 * 1024 * 1024   # the whole upload: a 3MF carries its meshes
MAX_ENTRY = 8 * 1024 * 1024    # one profile or config in an archive
MAX_ENTRIES = 50000


class ImportFailed(Exception):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


@dataclass
class Found:
    kind: str
    name: str
    data: dict           # the profile as the file has it, meta keys included
    where: str           # its place in the file, for the page
    full: bool = False   # every value, not only the differences to its parent (3MF)


# ---------------------------------------------------------------- reading

def _json(raw: bytes):
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _kind(data: dict, where: str) -> str | None:
    for kind, key in SETTINGS_ID.items():
        if key in data:
            return kind
    if isinstance(data.get("type"), str) and data["type"] in _TYPES:
        return _TYPES[data["type"]]
    return next((_TYPES[p] for p in reversed(PurePosixPath(where).parts[:-1]) if p in _TYPES), None)


def _name(data: dict, kind: str, where: str) -> str:
    if isinstance(data.get("name"), str) and data["name"].strip():
        return data["name"]
    sid = data.get(SETTINGS_ID[kind])
    sid = sid[0] if isinstance(sid, list) and sid else sid
    return sid if isinstance(sid, str) and sid.strip() else PurePosixPath(where).stem


def _add(out: dict, data, where: str, full: bool = False) -> None:
    if data is None:
        out["skipped"].append({"where": where, "code": "not_readable"})
        return
    if "filament_list" in data or "machine_model_list" in data:
        return  # the manifest of a vendor pack, no profile
    kind = _kind(data, where)
    if kind is None:
        out["skipped"].append({"where": where, "code": "not_a_profile"})
        return
    name = _name(data, kind, where)
    data = {**data, "name": name}
    if any(f.kind == kind and f.name == name for f in out["profiles"]):
        out["skipped"].append({"where": where, "code": "twice", "name": name})
        return
    out["profiles"].append(Found(kind, name, data, where, full))


def _hidden(data: dict) -> dict:
    """A profile for the page: a printer's API key or password masked, any device in the LAN may
    see it (the user's wish of 25.09.2026). The import drops them anyway (_CONNECTION)."""
    return {k: "***" if snapshot.SECRET.search(k) and v not in ("", None, []) else v for k, v in data.items()}


def _entry(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes | None:
    """An entry up to MAX_ENTRY bytes, None if it is bigger: its header may lie about the size."""
    with archive.open(info) as f:
        data = f.read(MAX_ENTRY + 1)
    return data if len(data) <= MAX_ENTRY else None


def read(raw: bytes, filename: str) -> dict:
    """What a file holds: {"format", "profiles": [Found], "skipped": [{"where", "code"}]}.
    Raises ImportFailed."""
    if len(raw) > MAX_FILE:
        raise ImportFailed("file_too_big")
    out = {"format": "json", "profiles": [], "skipped": []}
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        data = _json(raw)
        if data is None:
            raise ImportFailed("file_unknown")
        _add(out, data, filename)
        return out
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = [e for e in archive.infolist() if not e.is_dir() and not e.filename.startswith("__MACOSX/")]
            if len(entries) > MAX_ENTRIES:
                raise ImportFailed("file_too_big")
            names = {e.filename for e in entries}
            if _PROJECT in names or any(_EMBEDDED.fullmatch(n) or n.lower() == _MODEL for n in names):
                out["format"] = "3mf"
                _read_3mf(archive, entries, out, PurePosixPath(filename).stem)
                return out
            data_dir = any(_USER_FILE.fullmatch(n) for n in names)
            out["format"] = "backup" if data_dir else "bundle" if "bundle_structure.json" in names else "zip"
            for e in entries:
                path = PurePosixPath(e.filename)
                if data_dir and not _USER_FILE.fullmatch(e.filename) or path.suffix.lower() != ".json" \
                        or path.name in _NOT_PROFILES:
                    continue
                raw_entry = _entry(archive, e)
                if raw_entry is None:
                    out["skipped"].append({"where": e.filename, "code": "too_big"})
                    continue
                _add(out, _json(raw_entry), e.filename)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, NotImplementedError, RuntimeError) as exc:
        raise ImportFailed("file_unknown", detail=str(exc)) from None
    return out


def _backup_files(folder: Path):
    """(relative posix path, Path) of the profiles in a copy of user/. No symlinks and nothing
    that resolves outside the copy: a junction on Windows is no symlink to is_symlink()."""
    base = folder.resolve()
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not (Path(root) / d).is_symlink())
        for name in sorted(names):
            path = Path(root) / name
            rel = path.relative_to(folder).as_posix()
            if _BACKUP_FILE.fullmatch(rel) and not path.is_symlink() and path.resolve().is_relative_to(base):
                yield rel, path


def slicer_backups(data_dir: Path) -> list:
    """The slicer's copies of user/ in a data directory, newest first:
    [{"name", "modified" (seconds since 1970), "profiles" (profile files in it)}]."""
    out = []
    for folder in data_dir.iterdir() if data_dir.is_dir() else []:
        if _SLICER_BACKUP.fullmatch(folder.name) and folder.is_dir() and not folder.is_symlink():
            out.append({"name": folder.name, "modified": folder.stat().st_mtime,
                        "profiles": sum(1 for _ in _backup_files(folder))})
    return sorted(out, key=lambda b: (-b["modified"], b["name"]))


def read_backup(data_dir: Path, name: str) -> dict:
    """What one of the slicer's copies of user/ holds, as read() says it of a file.
    Raises ImportFailed."""
    folder = data_dir / name
    if not _SLICER_BACKUP.fullmatch(name) or folder.is_symlink() or not folder.is_dir():
        raise ImportFailed("folder_unknown")
    out = {"format": "slicer_backup", "profiles": [], "skipped": []}
    for count, (rel, path) in enumerate(_backup_files(folder)):
        if count >= MAX_ENTRIES:
            raise ImportFailed("file_too_big")
        where = f"{name}/{rel}"
        try:
            with path.open("rb") as f:
                raw = f.read(MAX_ENTRY + 1)
        except OSError:
            out["skipped"].append({"where": where, "code": "not_readable"})
            continue
        if len(raw) > MAX_ENTRY:
            out["skipped"].append({"where": where, "code": "too_big"})
            continue
        _add(out, _json(raw), where)
    return out


def _of_slot(value, slot: int, count: int):
    """A filament's part of a project value (slot from 0): the project keeps one value per
    filament, or one per filament and hotend variant (Snapmaker Orca)."""
    if isinstance(value, list) and count and len(value) % count == 0:
        size = len(value) // count
        return value[slot * size:(slot + 1) * size]
    return value


def _read_3mf(archive: zipfile.ZipFile, entries: list, out: dict, stem: str) -> None:
    """The own profiles a project embeds, complete, and the changes it made to others without
    saving them: those are in project_settings.config only, as the keys that differ from the
    profile it used (different_settings_to_system; order process, filament 1…n, printer)."""
    for e in sorted((e for e in entries if _EMBEDDED.fullmatch(e.filename)), key=lambda e: e.filename):
        raw = _entry(archive, e)
        _add(out, _json(raw) if raw is not None else None, e.filename, full=True)
    model = next((e for e in entries if e.filename.lower() == _MODEL), None)
    found = None
    if model is not None:
        # The model holds the meshes, often more than MAX_ENTRY; its metadata come first.
        with archive.open(model) as f:
            found = _APPLICATION.search(f.read(65536).decode("utf-8", "replace"))
    info = next((e for e in entries if e.filename == _PROJECT), None)
    project = _json(_entry(archive, info) or b"") if info is not None else None
    if project is None:
        return
    filaments = [f for f in as_list(project.get("filament_settings_id")) if isinstance(f, str)]
    slots = [("process", project.get("print_settings_id"))] + [("filament", f) for f in filaments] \
        + [("machine", project.get("printer_settings_id"))]
    # What the project uses, for the page: system profiles stand in a 3MF by their name only, with
    # the values the project prints with; the page finds what fits here by the nozzle.
    uses = {}
    for i, (kind, name) in enumerate(slots):
        if not isinstance(name, str) or not name:
            continue
        use = uses.setdefault((kind, name), {"kind": kind, "name": name, "values": {}})
        for key in CORE[kind]:
            value = first(_of_slot(project.get(key), i - 1, len(filaments)) if kind == "filament" else project.get(key))
            if isinstance(value, (str, int, float)) and value != "":
                use["values"].setdefault(key, value)
        if kind == "filament":
            colour = first(_of_slot(project.get("filament_colour"), i - 1, len(filaments)))
            if isinstance(colour, str) and _COLOUR.fullmatch(colour.strip()):
                use.setdefault("colours", []).append(colour.strip().upper())
    nozzle = first(project.get("nozzle_diameter"))
    out["project"] = {"application": found.group(1).replace("-", " ") if found else "",
                      "nozzle": nozzle if isinstance(nozzle, str) else "", "uses": list(uses.values())}
    parents, changed = as_list(project.get("inherits_group")), as_list(project.get("different_settings_to_system"))
    if len(changed) != len(slots):
        return
    embedded = {(f.kind, f.name) for f in out["profiles"]}
    for i, ((kind, name), keys) in enumerate(zip(slots, changed)):
        if not isinstance(name, str) or not name or not isinstance(keys, str) or (kind, name) in embedded:
            continue
        parent = parents[i] if i < len(parents) and isinstance(parents[i], str) and parents[i] else name
        values = {}
        for key in dict.fromkeys(k for k in keys.split(";") if k):
            if key in META_KEYS or key.endswith("_settings_id") or key not in project:
                continue
            values[key] = _of_slot(project[key], i - 1, len(filaments)) if kind == "filament" else project[key]
        if values:
            new_name = f"{name.removesuffix(' @System').removesuffix(' @base')} ({stem})"
            out["profiles"].append(Found(kind, new_name, {"name": new_name, "inherits": parent, **values},
                                         f"{_PROJECT} · {kind} {i}"))


def clean_3mf(raw: bytes) -> bytes:
    """Page "3MF bereinigen": the 3MF without what binds it to the printer it was made for
    (_PRINTER_BOUND), so the slicer opens it with the printer, process and filaments chosen there.
    Model, plates, painting and pictures stay as they are. Raises ImportFailed."""
    if len(raw) > MAX_FILE:
        raise ImportFailed("file_too_big")
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(buffer, "w") as target:
            entries = [e for e in source.infolist() if not e.is_dir()]
            if len(entries) > MAX_ENTRIES:
                raise ImportFailed("file_too_big")
            if not any(e.filename.lower() == _MODEL for e in entries):
                raise ImportFailed("file_unknown")
            if not any(_PRINTER_BOUND.fullmatch(e.filename) for e in entries):
                raise ImportFailed("nothing_to_clean")
            for e in entries:
                if _PRINTER_BOUND.fullmatch(e.filename):
                    continue
                info = zipfile.ZipInfo(e.filename, e.date_time)
                info.compress_type = zipfile.ZIP_STORED if e.compress_type == zipfile.ZIP_STORED else zipfile.ZIP_DEFLATED
                info.external_attr = e.external_attr
                # Streamed: a model can have hundreds of megabytes.
                with source.open(e) as src, target.open(info, "w", force_zip64=e.file_size >= zipfile.ZIP64_LIMIT) as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, NotImplementedError, RuntimeError) as exc:
        raise ImportFailed("file_unknown", detail=str(exc)) from None
    return buffer.getvalue()


# ---------------------------------------------------------------- one profile in the target

def _chain_values(res: Resolver, p) -> dict:
    values = {}
    for q in res.layers(p):
        for key, value in q.values.items():
            values.setdefault(key, value)
    return values


def _selectable(res: Resolver, kind: str, name: str):
    """The profile of that name a new own one can inherit from, as Planner.template allows."""
    system = res.collection[kind].get(name)
    if system is not None:
        return system if res.chain(system)[1] else None
    return next((p for p in res.own_profiles(kind) if p.name == name and not p.bundle and res.loaded(p)), None)


def _resolved(res: Resolver, kind: str, profile: dict, parents: list, full: bool) -> tuple:
    """(values, parent here or None): the profile's values over those of its parents from the same
    file (nearest first). A template (@base, fdm_*) cannot be a parent (FINDINGS 4.4): its values
    go in. Raises ImportFailed if the parent is missing and the profile holds only differences."""
    chain = [profile] + parents
    values = {}
    for q in reversed(chain):
        values.update({k: v for k, v in q.items() if k not in META_KEYS})
    wanted = chain[-1].get("inherits") if isinstance(chain[-1].get("inherits"), str) else ""
    target_parent = _selectable(res, kind, wanted) if wanted else None
    if wanted and target_parent is None:
        template = next((p for p in res.scan.profiles.values() if p.kind == kind and p.name == wanted), None)
        if template is not None and res.chain(template)[1]:
            values = {**_chain_values(res, template), **values}
        elif not full:
            raise ImportFailed("parent_missing", parent=wanted)
    return values, target_parent


def convert(res: Resolver, app: str, kind: str, profile: dict, parents: list, full: bool) -> transfer.Copy:
    """How profile lands in the installation of res: its values in the form the slicer app reads,
    and the parent there, None for a root profile. parents: its parents from the same file,
    nearest first. Raises ImportFailed."""
    if kind not in KINDS:
        raise ImportFailed("unknown_kind")
    values, target_parent = _resolved(res, kind, profile, parents, full)
    if kind == "machine":
        values = {k: v for k, v in values.items() if not _CONNECTION.match(k)}
    here = [k for k in _RUNS_HERE if k in values]
    values = {k: v for k, v in values.items() if k not in _RUNS_HERE}
    printers_wanted = [n for n in as_list(values.get("compatible_printers")) if isinstance(n, str)] if kind != "machine" else []
    have = transfer.target_printers(res)
    printers = [n for n in printers_wanted if n in have]
    if printers_wanted and not printers:
        raise ImportFailed("no_target_printer", printers=printers_wanted)
    data, dropped, cut = transfer.adapt({k: v for k, v in values.items() if k not in transfer.OWN_KEYS},
                                        transfer.OPTIONS[app], kind, same_app=True)
    dropped = sorted(set(dropped) | set(here))   # said in the plan like any key the slicer lacks
    if kind != "machine" and (target_parent is None or printers_wanted):
        data["compatible_printers"] = printers
    if kind != "machine" and target_parent is None:
        condition = values.get("compatible_printers_condition")
        data["compatible_printers_condition"] = condition if isinstance(condition, str) else ""
    name = profile.get("name") if isinstance(profile.get("name"), str) and profile["name"].strip() else ""
    if not name:
        raise ImportFailed("unknown_kind")
    return transfer.Copy(name=name, data=data, parent=target_parent,
                         base_id=target_parent.setting_id if target_parent is not None else "",
                         dropped=dropped, cut=cut, printers_left=[n for n in printers_wanted if n not in have])


def _printer_here(res: Resolver, name: str):
    found = res.collection["machine"].get(name)
    return found or next((p for p in res.own_profiles("machine") if p.name == name and res.loaded(p)), None)


def _base_for(res: Resolver, printer, material: str):
    """The system filament of that material a filament for printer hangs onto: one made for this
    printer (with a printer list, not the library), "Generic …" first."""
    fits = [p for p in res.collection["filament"].values() if first(res.value(p, "filament_type")) == material
            and res.compatible_printers(p) and res.fits(printer, p) == "yes"]
    return min(fits, key=lambda p: (not p.alias.startswith("Generic"), p.name), default=None)


def attach(res: Resolver, app: str, profile: dict, parents: list, printer_name: str) -> transfer.Copy:
    """A filament of the file hung onto printer_name here (ORCAONE_SPEC, "An Zielprofil hängen"): the
    child of a system filament of that printer and material, with the file's material values
    (MATERIAL_KEYS) where they differ from it. Also for a filament whose own parent is missing: what
    the file holds is taken, the page names it. Named like the slicer's "Filament erstellen" names
    its filaments, "<name up to @> @<printer>". Raises ImportFailed."""
    printer = _printer_here(res, printer_name)
    if printer is None:
        raise ImportFailed("unknown_printer", printer=printer_name)
    values, parent = _resolved(res, "filament", profile, parents, True)
    if parent is not None:
        values = {**_chain_values(res, parent), **values}
    material = first(values.get("filament_type"))
    base = _base_for(res, printer, material) if isinstance(material, str) else None
    if base is None:
        raise ImportFailed("no_base", printer=printer_name, material=material if isinstance(material, str) else "")
    inherited = _chain_values(res, base)
    taken = {k: values[k] for k in MATERIAL_KEYS if k in values and as_list(values[k]) != as_list(inherited.get(k))}
    data, dropped, cut = transfer.adapt(taken, transfer.OPTIONS[app], "filament", same_app=True)
    data["compatible_printers"] = [printer_name]
    name = profile.get("name") if isinstance(profile.get("name"), str) and profile["name"].strip() else "Filament"
    return transfer.Copy(name=f"{alias_of(name)} @{printer_name}", data=data, parent=base, base_id=base.setting_id,
                         dropped=dropped, cut=cut)


def _comparable(values: dict, app: str, kind: str) -> dict:
    """Only what an import would write, on both sides: keys the target does not know and those
    OrcaOne never copies (transfer.OWN_KEYS) do not make two profiles differ."""
    data = transfer.adapt({k: v for k, v in values.items() if k not in transfer.OWN_KEYS}, transfer.OPTIONS[app], kind, True)[0]
    return {k: as_list(v) for k, v in data.items()}


def _name_state(res: Resolver, app: str, kind: str, copy: transfer.Copy) -> str:
    if any(p.kind == kind and p.name == copy.name for p in res.scan.profiles.values()):
        return "system_name"
    own = next((p for p in res.own_profiles(kind) if p.name == copy.name and not p.bundle), None)
    if own is None:
        return "new"
    mine = {**(_chain_values(res, copy.parent) if copy.parent is not None else {}), **copy.data}
    # Hidden (instantiation "false") still counts: the slicer loads it, it only does not show it.
    state = res.state(own)
    same = bool(state and state.loaded) and _comparable(mine, app, kind) == _comparable(_chain_values(res, own), app, kind)
    return "same" if same else "name_taken"


def analyse(source: dict, res: Resolver, app: str) -> list:
    """Per profile of the file what an import would do in the installation of res, for the page.
    profile, parents and full go back in the change "profile_import"."""
    by_name = {(f.kind, f.name): f for f in source["profiles"]}
    # Invisible bases of a vendor pack (instantiation "false", "@base"): they go into the profiles
    # built on them; alone they would become a visible profile.
    templates = {(f.kind, f.data["inherits"]) for f in source["profiles"] if isinstance(f.data.get("inherits"), str)}
    out = []
    for f in source["profiles"]:
        parents, seen, current = [], {(f.kind, f.name)}, f
        while isinstance(current.data.get("inherits"), str) and (f.kind, current.data["inherits"]) in by_name:
            current = by_name[(f.kind, current.data["inherits"])]
            if (current.kind, current.name) in seen:
                break
            seen.add((current.kind, current.name))
            parents.append(current)
        entry = {"kind": f.kind, "name": f.name, "where": f.where, "full": f.full,
                 "profile": _hidden(f.data), "parents": [_hidden(p.data) for p in parents], "from_file": [p.name for p in parents]}
        if (f.kind, f.name) in templates and f.data.get("instantiation") == "false":
            out.append({**entry, "status": "template", "params": {}})
            continue
        if str(f.data.get("from", "")).lower() == "system" and any(p.kind == f.kind and p.name == f.name for p in res.scan.profiles.values()):
            # A system profile the slicer's export wrote out in full (a printer bundle holds its
            # printer so): the installation has it; a copy would only double it.
            out.append({**entry, "status": "system_here", "params": {}})
            continue
        try:
            copy = convert(res, app, f.kind, f.data, entry["parents"], f.full)
        except ImportFailed as exc:
            entry.update(status=exc.code, params=exc.params)
            out.append(entry)
            continue
        entry.update(_outcome(res, app, f.kind, copy))
        out.append(entry)
    return out


def _outcome(res: Resolver, app: str, kind: str, copy: transfer.Copy) -> dict:
    """What the page shows of a profile as it would land: status, the name it gets, parent,
    printers and the main values."""
    resolved = {**(_chain_values(res, copy.parent) if copy.parent is not None else {}), **copy.data}
    return {"status": _name_state(res, app, kind, copy), "target": copy.name,
            "parent": copy.parent.name if copy.parent is not None else None,
            "printers": [n for n in as_list(resolved.get("compatible_printers")) if isinstance(n, str)],
            "dropped": copy.dropped, "printers_left": copy.printers_left,
            "values": {k: as_list(resolved[k])[0] for k in CORE[kind] if as_list(resolved.get(k))}}


def attach_here(res: Resolver, app: str, p, printer_name: str) -> transfer.Copy:
    """attach() for a filament of the installation itself: the page "Filamente" makes one for a
    nozzle it lacks ("Für andere Düse"), with its material values on that nozzle's filament."""
    return attach(res, app, {**_chain_values(res, p), "name": p.name}, [], printer_name)


def analyse_attach(res: Resolver, app: str, profile: dict, parents: list, printer: str) -> dict:
    """What analyse() says of a filament when it is hung onto printer instead (attach), plus the
    keys it takes from the file."""
    try:
        copy = attach(res, app, profile, parents, printer)
    except ImportFailed as exc:
        return {"status": exc.code, "params": exc.params}
    return {**_outcome(res, app, "filament", copy), "taken": sorted(k for k in copy.data if k != "compatible_printers")}


def uses(source: dict, res: Resolver) -> list:
    """The profiles a 3MF project uses, and whether the installation of res has them."""
    project = source.get("project") or {}
    have = {(p.kind, p.name) for p in res.scan.profiles.values()} | {(p.kind, p.name) for p in res.own_profiles()}
    return [{**u, "here": (u["kind"], u["name"]) in have} for u in project.get("uses", [])]


def filament_id(name: str) -> str:
    """For an own root filament, as op_profile_copy gives it: Snapmaker Orca's filament dialogs find
    one by its id (FINDINGS, "Übertragung")."""
    return "P" + hashlib.md5(name.encode("utf-8")).hexdigest()[:7]


# ---------------------------------------------------------------- export

def export(res: Resolver, wanted: list, flat: bool) -> bytes:
    """Own profiles as a ZIP the slicers import ("Import Configs") and OrcaOne reads again:
    as the files are, with their parent, or flat, every value and no parent, for another slicer or
    a computer without that parent. Parents come before their children, as the slicers' import
    needs (FINDINGS 4.8); a printer goes without its connection. wanted: [(kind, name)].
    Raises ImportFailed."""
    own = {(p.kind, p.name): p for p in res.own_profiles() if not p.bundle}
    chosen = []
    for kind, name in wanted:
        p = own.get((kind, name))
        if p is None:
            raise ImportFailed("unknown_profile", name=name)
        chosen.append(p)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(chosen, key=lambda p: p.load_pass):
            data = _json((res.scan.data_dir / p.file).read_bytes())
            if data is None:
                raise ImportFailed("profile_invalid", name=p.name)
            if flat:
                chain, complete = res.chain(p)
                if not complete:
                    raise ImportFailed("profile_invalid", name=p.name)
                # Not the cloud's id: it belongs to this profile in this account (FINDINGS 4.8).
                meta = {k: v for k, v in data.items() if k in META_KEYS and k != "setting_id"}
                data = {**_chain_values(res, p), **meta, "inherits": "", "name": p.name, "from": "User",
                        SETTINGS_ID[p.kind]: [p.name] if p.kind == "filament" else p.name}
                if p.kind == "filament":
                    data["filament_id"] = filament_id(p.name)
            if p.kind == "machine":
                data = {k: v for k, v in data.items() if not _CONNECTION.match(k)}
            folder = f"{p.kind}/base" if flat or not data.get("inherits") else p.kind
            archive.writestr(f"{folder}/{p.name}.json", json.dumps(data, indent=4, ensure_ascii=False, sort_keys=True) + "\n")
    return buffer.getvalue()

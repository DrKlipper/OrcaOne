"""Plan and apply changes to a data directory (hard rules 2 to 7).

Every change goes in two steps. plan() works out every file operation and the diff of the
.conf, with credentials masked, and keeps the plan in memory together with a fingerprint of the
.conf and all of user/ taken before planning. apply() writes it after the user confirmed, only if
nothing is blocked and none of those files changed since, another plan applied meanwhile
included: run check -> backup -> run check -> write (atomic, parsed again; on a failure the
touched files go back to the backup) -> run check -> scan again.

- The .conf is read, changed key by key and written back whole in the format found (orcaone/conf.py).
- Own profiles are written the way Preset::save does (FINDINGS 4.4): sorted keys, indented like
  the slicer, version, name, from "User", inherits, filament_settings_id, only the differences to
  the parent; a .info next to it. The file name is the profile name, OrcaSlicer reads the file name.
- Unknown keys stay, files that do not change are never written again (hard rule 7).
"""

import copy
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import backup, guard, importer, instances, overview, scanner, snapshot, transfer
from .conf import ConfFile, dump_conf, loads, parse_conf
from .model import Instance
from .resolver import DEFAULT_NAMES, EDITABLE_DEFAULTS, Resolver, as_list
from .scanner import LIBRARY, META_KEYS, SEMVER, read_info

SETTINGS_ID = {"filament": "filament_settings_id", "process": "print_settings_id", "machine": "printer_settings_id"}
# Characters Windows forbids in file names, and its reserved device names (CON.json is no file).
_FORBIDDEN = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)}
_FILAMENT_SLOT = re.compile(r"filament(_\d\d)?")
_INDENT = re.compile(rb"\{\r?\n([ \t]+)\S")
# Credential fields in the .conf (FINDINGS 4.3): masked in every diff.
_SECRET_KEYS = set(overview.DEVICE_FIELDS) | {"access_code"}
_INFO_KEYS = ("sync_info", "user_id", "setting_id", "base_id", "updated_time")
_KEEP_PLANS = 20
# Longest profile name in characters: file names stay below the 255 bytes of most file systems,
# paths short enough for Windows. The page "Filamente" has the same limit (filament-editor.js).
MAX_NAME = 120

_plans: dict = {}
_lock = threading.Lock()
log = logging.getLogger(__name__)


class OperationError(Exception):
    """An error code for the API, with optional parameters."""

    def __init__(self, code: str, status: int = 409, **params):
        super().__init__(code)
        self.code, self.status, self.params = code, status, params


class Blocked(Exception):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


class InvalidChange(Exception):
    """A change the API cannot read at all: unknown op, missing or mistyped field."""

    def __init__(self, index: int | None = None, field_name: str | None = None):
        super().__init__(field_name or "")
        self.index, self.field = index, field_name


@dataclass
class Step:
    action: str                  # write, rename, delete, mkdir, rmdir
    path: str                    # relative to the data directory, "/" as separator
    content: bytes | None = None  # write and rename: the new content
    to: str | None = None        # rename: the new path
    check: str | None = None     # "profile" or "conf": parse again after writing
    name: str | None = None      # profile name for check "profile"
    nested_keys: tuple = ()      # catalog-approved coPointsGroups JSON arrays


@dataclass
class Plan:
    id: str
    instance_id: str
    steps: list
    snapshot: dict               # the .conf and all of user/ when planning began (_tree_snapshot)
    public: dict
    blocked: str | None
    reason: str
    reason_params: dict
    restore: bool = False        # a restore: a broken .conf does not stop it, the unlock list is pruned
    expect_loaded: list = field(default_factory=list)  # (kind, name) the scan afterwards must load
    unlock_add: set = field(default_factory=set)
    unlock_remove: set = field(default_factory=set)
    publish: dict | None = None


# ---------------------------------------------------------------- small helpers

def find_instance(instance_id: str) -> tuple[Instance, list]:
    """The installation with this id (as in /api/data), read fresh, and the slicer processes."""
    processes = guard.find_processes()
    for instance in instances.discover([p.data_dir for p in processes if p.data_dir]):
        if instance.id == instance_id:
            return instance, processes
    raise OperationError("instance_not_found", 404)


def run_block(instance: Instance, processes: list) -> str | None:
    state = guard.run_state(instance, processes)
    if not state.running:
        return None
    # A slicer process without a known data directory may be working on this one (orcaone/guard.py).
    return "slicer_maybe_running" if state.reason == "process_unmapped" else "slicer_running"


def environment_block(instance: Instance, processes: list, restore: bool = False) -> str | None:
    # A restore writes the whole .conf back, so a broken one does not stop it: it is the way to
    # repair it. Starting the slicer instead would reset every setting (FINDINGS 4.3).
    if "conf_unreadable" in instance.problems and not restore:
        return "conf_unreadable"
    return run_block(instance, processes)


def outside_backup(data_dir: Path, rel: str, conf_name: str) -> bool:
    """True if a step on rel would reach past what the backup holds (hard rules 2 and 4): a
    symlink on the way (backup.walk leaves them out, so nothing there could be restored), "..",
    or a place that is neither the .conf nor in user/. A preset_folder like ".." ends up here."""
    from .profile_native_paths import vendor_of, directory_vendor, validate_existing, safe_path
    vendor = vendor_of(rel) or directory_vendor(rel)
    if vendor:
        try:
            validate_existing(data_dir, vendor)
            return not safe_path(data_dir, rel)
        except ValueError:
            return True
    parts = PurePosixPath(rel).parts
    if ".." in parts or rel != conf_name and parts[:1] != ("user",):
        return True
    path = data_dir
    for part in parts:
        path = path / part
        if path.is_symlink():
            return True
    # Junctions on Windows are no symlinks to is_symlink(), resolve() follows them all the same.
    real, base = (data_dir / rel).resolve(), data_dir.resolve()
    return real != base / conf_name if rel == conf_name else not real.is_relative_to(base / "user")


def profile_version(slicer_version: str | None) -> str:
    """A valid Semver for "version" of a new profile, from the slicer version ("2.5.0-dev" -> "2.5.0").
    Without it the slicer skips the file (FINDINGS 4.4)."""
    match = re.match(r"\d+(\.\d+){1,3}", slicer_version or "")
    return match.group(0) if match else "1.0.0"


def name_problem(name) -> str | None:
    """None if name can be a profile name and thus a file name on Linux and Windows."""
    if not isinstance(name, str) or not name or name != name.strip() or name.endswith("."):
        return "name_invalid"
    if any(c in _FORBIDDEN for c in name) or name.split(".")[0].strip().upper() in _RESERVED:
        return "name_invalid"
    # path_from_name adds ".json" only if the name does not end with it (Preset.cpp).
    if name.lower().endswith((".json", ".info")):
        return "name_invalid"
    try:
        raw = name.encode("utf-8")
    except UnicodeEncodeError:
        return "name_invalid"
    return "name_too_long" if len(name) > MAX_NAME or len(raw) + len(".json") > 255 else None


def check_profile(raw: bytes, name: str, nested_keys: tuple = ()) -> bool:
    """What the slicer needs to load the file instead of deleting or skipping it (FINDINGS 4.4):
    JSON, metadata as strings, values as strings or lists of strings, a valid version."""
    try:
        data = loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False
    if not isinstance(data, dict) or data.get("name") != name:
        return False
    for key, value in data.items():
        if key in META_KEYS:
            if not isinstance(value, str):
                return False
        elif not (isinstance(value, str) or isinstance(value, list) and all(isinstance(v, str) for v in value)
                  or key in nested_keys and isinstance(value, list)
                  and all(isinstance(group, list) and all(isinstance(v, str) for v in group) for group in value)):
            return False
    return bool(SEMVER.fullmatch(data.get("version", "")))


def _strings_dict(value) -> bool:
    return isinstance(value, dict) and all(isinstance(v, str) for v in value.values())


def check_conf(data: dict) -> bool:
    """Types of the sections the slicer reads with get<std::string>(): another type stops it
    loading the rest of the file, in orca_presets it does not even start (FINDINGS 4.3)."""
    models = data.get("models")
    if models is not None and not (isinstance(models, list) and all(_strings_dict(m) for m in models)):
        return False
    filaments = data.get("filaments")
    if filaments is not None and not (isinstance(filaments, list) and all(isinstance(n, str) for n in filaments)):
        return False
    presets = data.get("presets")
    if presets is not None:
        if not isinstance(presets, dict):
            return False
        for key, value in presets.items():
            ok = value is None or isinstance(value, list) and all(isinstance(n, str) for n in value) \
                if key == "filaments" else isinstance(value, str)
            if not ok:
                return False
    entries = data.get("orca_presets")
    return entries is None or isinstance(entries, list) and all(_strings_dict(e) for e in entries)


def _fingerprint(path: Path):
    try:
        st = path.lstat()
        if path.is_dir():
            return "dir"
        return [st.st_mtime_ns, st.st_size, hashlib.sha256(path.read_bytes()).hexdigest()]
    except OSError:
        return None


def _style(raw: bytes | None, default: tuple) -> tuple:
    """(indent, CRLF) of an existing file, else the one of the .conf: both slicers write profiles
    like their .conf, Snapmaker Orca with 4 spaces, OrcaSlicer >= 2.4 with a tab (FINDINGS 4.3)."""
    if raw is None:
        return default
    match = _INDENT.match(raw.removeprefix(b"\xef\xbb\xbf"))
    return (match.group(1).decode("ascii") if match else default[0]), b"\r\n" in raw


def dump_profile(data: dict, style: tuple) -> bytes:
    # nlohmann::json with sorted keys and raw UTF-8, std::endl at the end (ConfigBase::save_to_json).
    text = json.dumps(data, indent=style[0], ensure_ascii=False, sort_keys=True) + "\n"
    return (text.replace("\n", "\r\n") if style[1] else text).encode("utf-8")


def dump_info(info: dict, crlf: bool) -> bytes:
    # Preset::save_info: "key = value" per line, in this order.
    keys = list(_INFO_KEYS) + [k for k in info if k not in _INFO_KEYS]
    text = "".join(f"{k} = {info.get(k, '')}\n" for k in keys)
    return (text.replace("\n", "\r\n") if crlf else text).encode("utf-8")


def _mask(value, secret_all: bool = False, key: str | None = None):
    if isinstance(value, dict):
        return {k: _mask(v, secret_all, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v, secret_all, key) for v in value]
    if (secret_all or key in _SECRET_KEYS) and value not in ("", None):
        return "***"
    return value


def _masked(path: str, value):
    top = path.split(".", 1)[0].split("[", 1)[0]
    if top == "access_code":
        return _mask(value, secret_all=True)
    return _mask(value, key=path.rsplit(".", 1)[-1]) if top in ("devices", "local_machines") else value


def conf_diff(before: dict, after: dict, prefix: str = "") -> list:
    """Changed keys of the .conf as {"path", "before", "after"}, credentials masked. Entries of
    orca_presets are compared per printer ("orca_presets[<machine>].filament")."""
    out = []
    for key in sorted(set(before) | set(after)):
        path = f"{prefix}{key}"
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if isinstance(old, dict) and isinstance(new, dict):
            out += conf_diff(old, new, f"{path}.")
        elif key == "orca_presets" and not prefix and _by_machine(old) is not None and _by_machine(new) is not None:
            olds, news = _by_machine(old), _by_machine(new)
            for machine in sorted(set(olds) | set(news)):
                a, b = olds.get(machine), news.get(machine)
                if a is not None and b is not None:
                    out += conf_diff(a, b, f"{path}[{machine}].")
                elif a != b:
                    out.append({"path": f"{path}[{machine}]", "before": a, "after": b})
        else:
            out.append({"path": path, "before": _masked(path, old), "after": _masked(path, new)})
    return out


def _by_machine(entries):
    if not isinstance(entries, list) or not all(isinstance(e, dict) and isinstance(e.get("machine"), str) for e in entries):
        return None
    out = {e["machine"]: e for e in entries}
    return out if len(out) == len(entries) else None


# ---------------------------------------------------------------- reading a change

def _field(change: dict, key: str, index: int, kind, required: bool = True):
    if key not in change:
        if required:
            raise InvalidChange(index, key)
        return None
    value = change[key]
    if value is None and not required:
        return None
    if kind == "strings":
        ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
    else:
        ok = isinstance(value, kind)
    if not ok:
        raise InvalidChange(index, key)
    return value


def _values(change: dict, index: int) -> dict:
    values = _field(change, "values", index, dict, required=False) or {}
    for k, v in values.items():
        if k in META_KEYS or k in SETTINGS_ID.values():
            raise InvalidChange(index, "values")
        if not (isinstance(v, str) or isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise InvalidChange(index, "values")
    return values


def _same(a, b) -> bool:
    return b is not None and as_list(a) == as_list(b)


def _shape(value, inherited, kind: str):
    """A value in the form the slicer saves it: a list for vector options. Their definitions are
    not known here, so the inherited value tells; filament options are nearly all vectors. A
    single value for a two-value option (Snapmaker Orca's high flow, FINDINGS 4.4) replaces the
    first one only."""
    if isinstance(value, list):
        return value
    if isinstance(inherited, list):
        return [value] + inherited[1:]
    if isinstance(inherited, str):
        return value
    return [value] if kind == "filament" else value


# ---------------------------------------------------------------- planning

@dataclass
class Own:
    """An own profile file of the active user folder as the plan changes it."""
    name: str
    kind: str
    rel: str                   # path of the .json now
    orig_rel: str | None       # path on disk, None for a new profile
    data: dict | None          # parsed JSON as the plan changes it, None if it does not parse
    orig_data: dict | None     # parsed JSON on disk
    raw: bytes | None
    info: dict | None
    info_raw: bytes | None
    profile: object = None     # scanner.Profile, None for a new profile
    parent: object = None      # the profile it inherits from, as the slicer resolves it
    loaded: bool = False       # the slicer loads it (or will, for a new one)
    deleted: bool = False
    touched: bool = False      # changed: the .info gets a new updated_time

    @property
    def info_rel(self) -> str:
        return self.rel[:-len(".json")] + ".info"


class Planner:
    def __init__(self, instance: Instance):
        self.instance = instance
        self.scan = scanner.scan(instance.data_dir, instance.slicer)
        if self.scan.conf_file is None:
            raise Blocked("conf_unreadable")
        self.res = Resolver(self.scan)
        self.conf = copy.deepcopy(self.scan.conf)
        cf = self.scan.conf_file
        self.style = (cf.indent, cf.crlf)
        self.version = profile_version(instance.version)
        self.folder = f"user/{self.scan.active_folder}"
        # Bundle profiles belong to OrcaSlicer: never changed, but their printers can be chosen.
        self.own = [self._load(p) for p in self.scan.own if not p.bundle]
        self.bundle_printers = [p for p in self.scan.own if p.bundle and p.kind == "machine"
                                and self.res.loaded(p) and self.res.chain(p)[1]]
        self.warnings = []
        self.unlock_add, self.unlock_remove = set(), set()
        self.gone = set()  # printers the slicer no longer lists after the changes so far
        self._excluded = None
        self._sources = {}  # installations profiles are copied from: id -> (instance, resolver)
        self.publish = None

    def _load(self, p) -> Own:
        path = self.instance.data_dir / p.file
        try:
            raw = path.read_bytes()
        except OSError:
            raw = None
        try:
            data = loads(raw.decode("utf-8-sig")) if raw is not None else None
        except (UnicodeDecodeError, ValueError):
            data = None
        info_path = path.with_suffix(".info")
        info_raw = info_path.read_bytes() if info_path.is_file() else None
        state = self.res.state(p)
        data = data if isinstance(data, dict) else None
        return Own(name=p.name, kind=p.kind, rel=p.file, orig_rel=p.file, data=data, orig_data=data, raw=raw,
                   info=read_info(info_path) if info_raw is not None else None, info_raw=info_raw,
                   profile=p, parent=state.parent if state else None,
                   loaded=bool(state and state.problem is None and p.selectable))

    # ------------------------------------------------------------ lookups

    def live(self, kind: str | None = None) -> list:
        return [o for o in self.own if not o.deleted and (kind is None or o.kind == kind)]

    def not_own(self, name: str, kinds) -> Blocked:
        """Why name is no own profile OrcaOne may change: it sits in a bundle, is a system profile
        or does not exist."""
        if any(p.bundle and p.kind in kinds and p.name == name for p in self.scan.own):
            return Blocked("bundle_profile", name=name)
        if any(p.kind in kinds and p.name == name for p in self.scan.profiles.values()):
            return Blocked("not_own_profile", name=name)
        return Blocked("unknown_profile", name=name)

    def find_own(self, kind: str, name: str, need_data: bool = True) -> Own:
        found = [o for o in self.live(kind) if o.name == name]
        if not found:
            raise self.not_own(name, (kind,))
        # Of two files with one name the slicer loads the first; that is the one meant.
        own = next((o for o in found if o.loaded), found[0])
        if need_data and own.data is None:
            # A file that does not parse cannot be changed, only deleted.
            raise Blocked("profile_invalid", name=name)
        return own

    def check_new_name(self, kind: str, name: str, exclude: Own | None = None) -> None:
        problem = name_problem(name)
        if problem:
            raise Blocked(problem, name=name)
        if name == DEFAULT_NAMES[kind] or any(p.kind == kind and p.name == name for p in self.scan.profiles.values()):
            raise Blocked("name_taken", name=name)
        # Case-insensitive: on Windows and macOS "mein pla.json" is the file "Mein PLA.json".
        taken = {o.name.casefold() for o in self.live(kind) if o is not exclude}
        taken |= {PurePosixPath(r).stem.casefold() for o in self.own if o.kind == kind and o is not exclude
                  for r in (o.rel, o.orig_rel) if r}
        skip = {exclude.orig_rel, exclude.orig_rel[:-len(".json")] + ".info"} if exclude and exclude.orig_rel else set()
        for folder in (f"{self.folder}/{kind}", f"{self.folder}/{kind}/base"):
            path = self.instance.data_dir / folder
            if path.is_dir():
                taken |= {f.stem.casefold() for f in path.iterdir()
                          if f.suffix in (".json", ".info") and f"{folder}/{f.name}" not in skip}
        if name.casefold() in taken:
            raise Blocked("name_taken", name=name)

    def template(self, kind: str, name: str):
        """(parent, own values to start from, base_id) for a new profile based on name, the way
        save_current_preset copies it: a system profile or an own root profile becomes the parent,
        a copy of an own child keeps that child's parent and values."""
        system = self.res.collection[kind].get(name)
        if system is not None:
            if not self.res.chain(system)[1]:
                raise Blocked("parent_not_selectable", name=name)
            return system, {}, system.setting_id
        if any(p.kind == kind and p.name == name for p in self.scan.profiles.values()):
            # Abstract profiles (@base, fdm_*) are no profiles to the slicer (FINDINGS 4.4).
            raise Blocked("parent_not_selectable", name=name)
        own = self.find_own(kind, name)
        if not own.loaded or own.profile is None:
            raise Blocked("parent_not_selectable", name=name)
        info = own.info or {}
        if own.data.get("inherits"):
            start = {k: v for k, v in own.data.items() if k not in META_KEYS and k != SETTINGS_ID[kind]}
            return own.parent, start, info.get("base_id", "")
        return own.profile, {}, info.get("setting_id", "")

    def inherited(self, parent, key: str):
        if parent is None:
            return None
        value = self.res.value(parent, key)
        return EDITABLE_DEFAULTS.get(key) if value is None else value

    def set_values(self, data: dict, values: dict, parent, kind: str) -> None:
        """Only differences to the parent are saved (Preset::save); a value equal to the inherited
        one is removed. Root profiles (no parent) keep every value."""
        for key, value in values.items():
            inherited = self.inherited(parent, key)
            shaped = _shape(value, inherited if parent is not None else data.get(key), kind)
            if parent is not None and _same(shaped, inherited):
                data.pop(key, None)
            else:
                data[key] = shaped

    def printers(self, names: list) -> list:
        known = {p.name for p in self.res.collection["machine"].values()}
        known |= {o.name for o in self.live("machine") if o.loaded}
        known |= {p.name for p in self.bundle_printers}
        for name in names:
            if name not in known:
                raise Blocked("unknown_profile", name=name)
        return list(dict.fromkeys(names))

    def visible_printers(self) -> list:
        """Names of the printers the slicer lists after the changes so far: installed system
        printers, then own ones."""
        out = [p.name for m in self.res.installed_printers() for _, p in m["printers"]]
        out += sorted(o.name for o in self.live("machine") if o.loaded)
        out += sorted(p.name for p in self.bundle_printers)
        return [n for n in out if n not in self.gone]

    def filament_names(self):
        """The list in "filaments", or None if everything is visible (missing, [] or null)."""
        value = self.conf.get("filaments")
        return value if isinstance(value, list) and value else None

    def printer_profile(self, name: str):
        found = self.res.collection["machine"].get(name)
        if found is not None:
            return found
        own = next((o for o in self.live("machine") if o.name == name and o.loaded), None)
        if own:
            return own.profile
        return next((p for p in self.bundle_printers if p.name == name), None)

    def replacement(self, machine: str, gone: set) -> str | None:
        """A filament the slicer shows for this printer, to replace a deleted one in orca_presets."""
        printer = self.printer_profile(machine)
        if printer is None:
            return None
        if self._excluded is None:
            self._excluded = self.res.library_exclusions()
        listed = set(self.filament_names() or [])
        for p in sorted(self.res.collection["filament"].values(), key=lambda p: p.name):
            if p.name not in gone and self.res.chain(p)[1] and self.res.fits(printer, p) \
                    and not self.res.displaced_by(self._excluded, p, printer) and self.res.in_list(p, listed):
                return p.name
        for o in sorted(self.live("filament"), key=lambda o: o.name):
            if o.name not in gone and o.loaded and o.profile is not None and self.res.fits(printer, o.profile):
                return o.name
        return None

    def has_listed(self, printer, listed: set) -> bool:
        """Whether a system filament in the "filaments" list fits the printer (an empty list:
        all of them, FINDINGS 4.6)."""
        if self._excluded is None:
            self._excluded = self.res.library_exclusions()
        return any(self.res.in_list(p, listed) and self.res.chain(p)[1] and self.res.fits(printer, p)
                   and not self.res.displaced_by(self._excluded, p, printer)
                   for p in self.res.collection["filament"].values())

    def warn_default_materials(self) -> None:
        """At its start the slicer switches the default_materials of a printer model on again
        for each of its printers without a listed filament that fits (load_installed_filaments,
        FINDINGS 4.6). None of the Snapmaker models in Snapmaker Orca has any."""
        before, after = set(self.res.filament_list()), set(self.filament_names() or [])
        if after == before:
            return
        for m in self.res.installed_printers():
            names = [n for n in self.scan.default_materials.get((m["package"], m["model"]), [])
                     if n in self.res.collection["filament"] and n not in after]
            printers = [p.name for _, p in m["printers"] if names and p.name not in self.gone
                        and self.has_listed(p, before) and not self.has_listed(p, after)]
            if printers:
                self.warnings.append({"code": "default_materials_back", "printers": printers, "names": names})

    def preset_entries(self) -> list:
        """(machine, dict) of every remembered choice: orca_presets per printer and presets."""
        out = []
        entries = self.conf.get("orca_presets")
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict):
                out.append((e.get("machine"), e))
        presets = self.conf.get("presets")
        if isinstance(presets, dict):
            out.append((presets.get("machine"), presets))
        return out

    def rename_references(self, old: str, new: str) -> None:
        for _, entry in self.preset_entries():
            for key, value in entry.items():
                if _FILAMENT_SLOT.fullmatch(key) and value == old:
                    entry[key] = new
                elif key == "filaments" and isinstance(value, list):
                    entry[key] = [new if v == old else v for v in value]

    def drop_references(self, gone: set) -> None:
        """Point remembered filament slots away from deleted filaments. presets.filaments is a
        list of slots as well (AppConfig::load)."""
        for machine, entry in self.preset_entries():
            slots = [(entry, key) for key in sorted(entry) if _FILAMENT_SLOT.fullmatch(key)]
            if isinstance(entry.get("filaments"), list):
                slots += [(entry["filaments"], n) for n in range(len(entry["filaments"]))]
            for holder, key in slots:
                if holder[key] not in gone:
                    continue
                target = self.replacement(machine, gone) if isinstance(machine, str) else None
                if target is None:
                    self.warnings.append({"code": "preset_reference_left", "machine": machine,
                                          "slot": key if isinstance(key, str) else f"filaments[{key}]",
                                          "name": holder[key]})
                else:
                    holder[key] = target

    def replace_default(self, gone: set) -> None:
        self.gone |= gone
        presets = self.conf.get("presets")
        if not isinstance(presets, dict) or presets.get("machine") not in gone:
            return
        # A default this plan picked before goes as well: one warning, from the first default on.
        picked = [w for w in self.warnings if w["code"] == "default_printer_changed"]
        before = picked[0]["before"] if picked else presets["machine"]
        self.warnings = [w for w in self.warnings if w not in picked]
        rest = self.visible_printers()
        if rest:
            self.warnings.append({"code": "default_printer_changed", "before": before, "after": rest[0]})
            presets["machine"] = rest[0]
        else:
            presets["machine"] = before
            self.warnings.append({"code": "default_printer_removed", "name": before})

    def children(self, doomed: list) -> list:
        names = {(o.kind, o.name) for o in doomed}
        return sorted(o.name for o in self.live() if o not in doomed and o.data
                      and (o.kind, o.data.get("inherits")) in names)

    def sync_warning(self, names: list) -> None:
        # A profile synced to the cloud comes back after deleting it locally (FINDINGS, section 7).
        app = self.conf.get("app") if isinstance(self.conf.get("app"), dict) else {}
        if self.instance.logged_in and app.get("sync_user_preset") in (True, "true", "1"):
            self.warnings.append({"code": "cloud_sync", "names": names})

    def new_own(self, kind: str, name: str, data: dict, parent, base_id: str) -> Own:
        full = {**data, "name": name, "from": "User", "version": self.version, SETTINGS_ID[kind]:
                [name] if kind == "filament" else name}
        # A root profile says so with an empty "inherits", as the slicer saves one (Preset::save).
        full["inherits"] = parent.name if parent is not None else ""
        folder = f"{self.folder}/{kind}" + ("" if parent is not None else "/base")
        own = Own(name=name, kind=kind, rel=f"{folder}/{name}.json", orig_rel=None, data=full, orig_data=None, raw=None,
                  info={"sync_info": "", "user_id": "", "setting_id": "", "base_id": base_id or ""},
                  info_raw=None, parent=parent, loaded=True, touched=True)
        self.own.append(own)
        return own

    # ------------------------------------------------------------ the changes

    def apply(self, change, index: int) -> None:
        if not isinstance(change, dict) or not isinstance(change.get("op"), str):
            raise InvalidChange(index, "op")
        handler = getattr(self, f"op_{change['op']}", None)
        if handler is None:
            raise InvalidChange(index, "op")
        handler(change, index)

    def op_filament_visible(self, c: dict, i: int) -> None:
        name = _field(c, "name", i, str)
        visible = _field(c, "visible", i, bool)
        targets = [p for p in self.scan.of_kind("filament") if p.name == name]
        listed = self.filament_names()
        if visible:
            p = next((p for p in targets if p.selectable), None)
            if p is None:
                raise Blocked("unknown_profile", name=name)
            if listed is None or self.res.in_list(p, set(listed)):
                self.warnings.append({"code": "already_visible", "name": name})
                return
            self.conf["filaments"] = sorted(set(listed) | {name})
            if self.scan.snorca and p.package == LIBRARY:
                # Way A (FINDINGS 4.7): the wizard may drop it again, overview.py reports that.
                self.unlock_add.add(name)
                self.unlock_remove.discard(name)
                self.warnings.append({"code": "unlock_fragile", "name": name})
            return
        names = {name} | {old for p in targets for old in p.renamed_from}
        if listed is None:
            if not targets:
                raise Blocked("unknown_profile", name=name)
            # Everything is visible: the list starts with every selectable system filament.
            new = sorted({p.name for p in self.scan.of_kind("filament") if p.selectable} - names)
            self.warnings.append({"code": "list_created", "count": len(new)})
        elif not names & set(listed):
            if not targets:
                raise Blocked("unknown_profile", name=name)
            self.warnings.append({"code": "already_hidden", "name": name})
            return
        else:
            new = [n for n in listed if n not in names]
        if not new:
            # An empty list means "everything visible" to the slicer (FINDINGS 4.6).
            raise Blocked("filaments_would_be_empty", name=name)
        self.conf["filaments"] = new
        self.unlock_remove.add(name)
        self.unlock_add.discard(name)

    def op_filament_bind(self, c: dict, i: int) -> None:
        base = _field(c, "base", i, str)
        name = _field(c, "name", i, str)
        printers = _field(c, "printers", i, "strings")
        parent = self.res.collection["filament"].get(base)
        if parent is None or not self.res.chain(parent)[1]:
            known = any(p.kind == "filament" and p.name == base for p in self.scan.profiles.values())
            raise Blocked("parent_not_selectable" if known else "unknown_profile", name=base)
        self.check_new_name("filament", name)
        # Way B (FINDINGS 4.7): nothing but the binding, everything else comes from the parent.
        data = {"compatible_printers": self.printers(printers)} if printers else {}
        self.new_own("filament", name, data, parent, parent.setting_id)

    def op_filament_create(self, c: dict, i: int) -> None:
        base = _field(c, "base", i, str)
        name = _field(c, "name", i, str)
        values = _values(c, i)
        printers = _field(c, "printers", i, "strings", required=False)
        parent, data, base_id = self.template("filament", base)
        self.check_new_name("filament", name)
        self.set_values(data, values, parent, "filament")
        if printers is not None:
            data["compatible_printers"] = self.printers(printers)
        self.new_own("filament", name, data, parent, base_id)

    def op_filament_attach(self, c: dict, i: int) -> None:
        """A filament for a nozzle it lacks (page "Filamente", "Für andere Düse"): a new own one
        hung onto a filament of that printer with the source's material values (importer.attach)."""
        source = _field(c, "source", i, str)
        printer = _field(c, "printer", i, str)
        p = self.res.collection["filament"].get(source)
        if p is None:
            own = next((o for o in self.live("filament") if o.name == source and o.loaded), None)
            p = own.profile if own else None
        if p is None:
            raise Blocked("unknown_profile", name=source)
        try:
            copy = importer.attach_here(self.res, self.instance.slicer, p, printer)
        except importer.ImportFailed as exc:
            raise Blocked(exc.code, **exc.params) from None
        data = {}
        self.set_values(data, copy.data, copy.parent, "filament")
        name = self.free_name("filament", copy.name)
        self.new_own("filament", name, data, copy.parent, copy.base_id)
        self.warnings.append({"code": "filament_attached", "name": name, "source": source, "printer": printer, "parent": copy.parent.name})

    def op_filament_update(self, c: dict, i: int) -> None:
        name = _field(c, "name", i, str)
        values = _values(c, i)
        reset = _field(c, "reset", i, "strings", required=False) or []
        # Off at every nozzle: an empty printer list would mean "every printer" (FINDINGS 4.6), so
        # the profile is hidden instead. Both slicers load it and keep it out of their lists
        # (instantiation "false", Preset.cpp load_presets); its printer list stays for later.
        hidden = _field(c, "hidden", i, bool, required=False)
        if any(k in META_KEYS or k in SETTINGS_ID.values() for k in reset):
            raise InvalidChange(i, "reset")
        own = self.find_own("filament", name)
        data = dict(own.data)
        for key in reset:
            data.pop(key, None)
        if hidden is True and data.get("instantiation") != "false":
            data["instantiation"] = "false"
            self.warnings.append({"code": "filament_hidden", "name": name})
        elif hidden is False and "instantiation" in data:
            data.pop("instantiation")
            self.warnings.append({"code": "filament_shown", "name": name})
        self.set_values(data, values, own.parent if data.get("inherits") else None, "filament")
        if data == own.data:
            self.warnings.append({"code": "nothing_changed", "name": name})
            return
        # File name and "name" always match when OrcaOne writes (FINDINGS 4.4).
        own.data, own.touched = dict(data, name=own.name), True

    def op_filament_rename(self, c: dict, i: int) -> None:
        name = _field(c, "name", i, str)
        new_name = _field(c, "new_name", i, str)
        own = self.find_own("filament", name)
        if new_name == own.name:
            self.warnings.append({"code": "nothing_changed", "name": name})
            return
        self.check_new_name("filament", new_name, exclude=own)
        data = dict(own.data, name=new_name)
        settings_id = data.get("filament_settings_id")
        data["filament_settings_id"] = new_name if isinstance(settings_id, str) else [new_name]
        own.data, own.touched, own.name = data, True, new_name
        own.rel = f"{PurePosixPath(own.rel).parent.as_posix()}/{new_name}.json"
        for child in self.live("filament"):
            if child is not own and child.data and child.data.get("inherits") == name:
                child.data, child.touched = dict(child.data, inherits=new_name), True
        self.rename_references(name, new_name)

    def op_filament_delete(self, c: dict, i: int) -> None:
        name = _field(c, "name", i, str)
        own = self.find_own("filament", name, need_data=False)
        children = self.children([own])
        if children:
            # The slicer refuses as well (delete_current_preset): they would lose their parent.
            raise Blocked("has_children", name=name, children=children)
        own.deleted = True
        self.drop_references({name})
        self.sync_warning([name])

    def source(self, instance_id: str):
        """Another installation to copy from, read once per plan. Its slicer may run: it is only read."""
        if instance_id == self.instance.id:
            raise Blocked("same_installation")
        if instance_id not in self._sources:
            try:
                instance = find_instance(instance_id)[0]
            except OperationError:
                raise Blocked("source_not_found") from None
            self._sources[instance_id] = (instance, Resolver(scanner.scan(instance.data_dir, instance.slicer)))
        return self._sources[instance_id]

    def free_name(self, kind: str, name: str) -> str:
        """name, or with " (2)", " (3)" … before its "@" part if a profile has it already."""
        stem, at, rest = name.partition(" @")
        for n in range(1, 100):
            candidate = name if n == 1 else f"{stem} ({n}){at}{rest}"
            try:
                self.check_new_name(kind, candidate)
                return candidate
            except Blocked as exc:
                if exc.code != "name_taken":
                    raise
        raise Blocked("name_taken", name=name)

    def op_profile_copy(self, c: dict, i: int) -> None:
        """A profile of another installation as a new own one here (orcaone/transfer.py)."""
        source_id = _field(c, "from", i, str)
        kind = _field(c, "kind", i, str)
        name = _field(c, "name", i, str)
        if kind not in transfer.KINDS:
            raise InvalidChange(i, "kind")
        source, res = self.source(source_id)
        try:
            copy = transfer.convert(res, source.slicer, self.res, self.instance.slicer, kind, name)
        except transfer.TransferError as exc:
            raise Blocked(exc.code, **exc.params) from None
        new_name = self.free_name(kind, copy.name)
        if kind == "filament" and copy.parent is None:
            # Snapmaker Orca's own filament dialogs find an own root filament by its id: one of its
            # own, never that of a system profile (FINDINGS, "Übertragung"). Unique per name.
            copy.data["filament_id"] = "P" + hashlib.md5(new_name.encode("utf-8")).hexdigest()[:7]
        self.new_own(kind, new_name, copy.data, copy.parent, copy.base_id)
        source_name = overview.SLICERS[source.slicer]["name"]
        self.warnings.append({"code": "transfer_from", "name": new_name, "source": name, "slicer": source_name})
        if copy.dropped:
            self.warnings.append({"code": "transfer_dropped", "name": new_name, "keys": copy.dropped})
        if copy.cut:
            self.warnings.append({"code": "transfer_first_value", "name": new_name, "keys": copy.cut})
        if copy.printers_left:
            self.warnings.append({"code": "transfer_printers_left", "name": new_name, "printers": copy.printers_left})

    def op_profile_publish(self, c: dict, i: int) -> None:
        from .profile_publish import plan_publish
        plan_publish(self, c)

    def op_profile_import(self, c: dict, i: int) -> None:
        """A profile from a file (orcaone/importer.py) as a new own one, or in place of the own
        one of that name. profile, parents and full as importer.analyse gave them to the page;
        converted again here, for the installation as it is now. printer: a filament hung onto that
        printer instead (importer.attach); name: the name the user gave it on the page."""
        kind = _field(c, "kind", i, str)
        profile = _field(c, "profile", i, dict)
        parents = _field(c, "parents", i, list, required=False) or []
        full = _field(c, "full", i, bool, required=False) or False
        replace = _field(c, "replace", i, bool, required=False) or False
        source = _field(c, "source", i, str, required=False) or ""
        printer = _field(c, "printer", i, str, required=False) or ""
        rename = _field(c, "name", i, str, required=False) or ""
        if kind not in importer.KINDS:
            raise InvalidChange(i, "kind")
        if not all(isinstance(p, dict) for p in parents):
            raise InvalidChange(i, "parents")
        if printer and kind != "filament":
            raise InvalidChange(i, "printer")
        try:
            copy = (importer.attach(self.res, self.instance.slicer, profile, parents, printer) if printer
                    else importer.convert(self.res, self.instance.slicer, kind, profile, parents, full))
        except importer.ImportFailed as exc:
            raise Blocked(exc.code, **exc.params) from None
        if rename:
            # free_name and find_own below check it like every new name (check_new_name).
            copy.name = rename
        data = {}
        self.set_values(data, copy.data, copy.parent, kind)
        if replace:
            own = self.find_own(kind, copy.name)
            name = own.name
            own.data = {**data, "name": name, "from": "User", "version": self.version,
                        SETTINGS_ID[kind]: [name] if kind == "filament" else name,
                        "inherits": copy.parent.name if copy.parent is not None else ""}
            if kind == "filament" and copy.parent is None:
                own.data["filament_id"] = importer.filament_id(name)
            own.parent, own.touched = copy.parent, True
            own.info = {"sync_info": "", "user_id": "", "setting_id": "", **(own.info or {}), "base_id": copy.base_id or ""}
        else:
            name = self.free_name(kind, copy.name)
            if kind == "filament" and copy.parent is None:
                data["filament_id"] = importer.filament_id(name)
            self.new_own(kind, name, data, copy.parent, copy.base_id)
        self.warnings.append({"code": "import_from", "name": name, "source": source, "replaced": replace})
        if printer:
            self.warnings.append({"code": "import_attached", "name": name, "printer": printer, "parent": copy.parent.name})
        if copy.dropped:
            self.warnings.append({"code": "transfer_dropped", "name": name, "keys": copy.dropped})
        if copy.printers_left:
            self.warnings.append({"code": "transfer_printers_left", "name": name, "printers": copy.printers_left})

    def op_default_printer(self, c: dict, i: int) -> None:
        printer = _field(c, "printer", i, str)
        if printer not in self.visible_printers():
            raise Blocked("unknown_profile", name=printer)
        presets = self.conf.get("presets")
        if not isinstance(presets, dict):
            presets = self.conf["presets"] = {}
        # The page picks the next default itself when the default printer goes: that choice
        # replaces the one replace_default made earlier in this plan, and its warning.
        picked = [w for w in self.warnings if w["code"] == "default_printer_changed"]
        self.warnings = [w for w in self.warnings if w not in picked]
        if presets.get("machine") == printer:
            if not picked:
                self.warnings.append({"code": "nothing_changed", "name": printer})
            return
        presets["machine"] = printer

    def op_printer_delete(self, c: dict, i: int) -> None:
        name = _field(c, "name", i, str)
        along = _field(c, "with", i, "strings", required=False) or []
        own = self.find_own("machine", name, need_data=False)
        doomed = [own]
        for other in along:
            found = [o for o in self.live() if o.name == other and o.kind in ("filament", "process")]
            if not found:
                raise self.not_own(other, ("filament", "process"))
            doomed += [o for o in found if o not in doomed]
        children = self.children(doomed)
        if children:
            raise Blocked("has_children", name=name, children=children)
        for o in doomed:
            o.deleted = True
        # Its remembered choice goes with it; the slicer never cleans it up (FINDINGS 4.9).
        entries = self.conf.get("orca_presets")
        if isinstance(entries, list):
            self.conf["orca_presets"] = [e for e in entries if not (isinstance(e, dict) and e.get("machine") == name)]
        self.drop_references({o.name for o in doomed if o.kind == "filament"})
        self.replace_default({name})
        self.sync_warning(sorted(o.name for o in doomed))

    def op_printer_model_off(self, c: dict, i: int) -> None:
        vendor = _field(c, "vendor", i, str)
        model = _field(c, "model", i, str)
        models = self.conf.get("models") if isinstance(self.conf.get("models"), list) else []
        keep = [e for e in models if not (isinstance(e, dict) and e.get("vendor") == vendor and e.get("model") == model)]
        if len(keep) == len(models):
            raise Blocked("unknown_profile", name=model)
        # Only whole models: Snapmaker Orca switches every variant of a model on again (FINDINGS 4.6).
        self.conf["models"] = keep
        printers = {p.name for m in self.res.installed_printers() if m["package"] == vendor and m["model"] == model
                    for _, p in m["printers"]}
        if not any(isinstance(e, dict) and e.get("vendor") == vendor for e in keep) \
                and overview._drops_unused_package(self.scan, vendor):
            # The slicer deletes the vendor package at its next start (FINDINGS 4.2).
            self.warnings.append({"code": "package_removed", "package": vendor})
        self.replace_default(printers)
        if not keep:
            self.warnings.append({"code": "no_printer_left"})

    def op_cleanup_presets(self, c: dict, i: int) -> None:
        machines = set(_field(c, "machines", i, "strings"))
        entries = self.conf.get("orca_presets") if isinstance(self.conf.get("orca_presets"), list) else []
        missing = sorted(machines - {e.get("machine") for e in entries if isinstance(e, dict)})
        if missing:
            raise Blocked("unknown_profile", name=missing[0])
        self.conf["orca_presets"] = [e for e in entries if not (isinstance(e, dict) and e.get("machine") in machines)]

    # ------------------------------------------------------------ result

    def finish(self) -> tuple[list, list, list]:
        """(steps, public ops, loaded (kind, name) expected afterwards)."""
        self.warn_default_materials()
        writes, deletes, ops, expect = [], [], [], []
        now = str(int(time.time()))
        nested_keys = tuple(self.publish.get("nested_keys", ())) if self.publish else ()
        for o in self.own:
            if o.deleted:
                if o.orig_rel:
                    deletes.append(Step("delete", o.orig_rel))
                    ops.append(_op("delete", o.orig_rel, "own_profile", name=o.name, kind=o.kind))
                    if o.info_raw is not None:
                        info_rel = o.orig_rel[:-len(".json")] + ".info"
                        deletes.append(Step("delete", info_rel))
                        ops.append(_op("delete", info_rel, "profile_info", name=o.name))
                continue
            if not o.touched:
                continue
            style = _style(o.raw, self.style)
            content = dump_profile(o.data, style)
            if content == o.raw:
                continue
            if not check_profile(content, o.name, nested_keys):
                raise Blocked("profile_invalid", name=o.name)
            info = dict(o.info or {"sync_info": "", "user_id": "", "setting_id": "", "base_id": ""})
            info["updated_time"] = now
            info_content = dump_info(info, style[1])
            keys = _changed_keys(o.orig_data or {}, o.data)
            if o.orig_rel is None:
                writes += [Step("write", o.rel, content, check="profile", name=o.name, nested_keys=nested_keys), Step("write", o.info_rel, info_content)]
                ops.append(_op("create", o.rel, "own_profile", name=o.name, kind=o.kind,
                               inherits=o.data.get("inherits"), keys=keys))
                ops.append(_op("create", o.info_rel, "profile_info", name=o.name))
            elif o.rel != o.orig_rel:
                old_info = o.orig_rel[:-len(".json")] + ".info"
                writes.append(Step("rename", o.orig_rel, content, to=o.rel, check="profile", name=o.name, nested_keys=nested_keys))
                ops.append(_op("rename", o.orig_rel, "own_profile", name=o.profile.name, kind=o.kind, to=o.rel,
                               new_name=o.name))
                if o.info_raw is not None:
                    writes.append(Step("rename", old_info, info_content, to=o.info_rel))
                    ops.append(_op("rename", old_info, "profile_info", name=o.profile.name, to=o.info_rel))
                else:
                    writes.append(Step("write", o.info_rel, info_content))
                    ops.append(_op("create", o.info_rel, "profile_info", name=o.name))
            else:
                writes += [Step("write", o.rel, content, check="profile", name=o.name, nested_keys=nested_keys), Step("write", o.info_rel, info_content)]
                ops.append(_op("modify", o.rel, "own_profile", name=o.name, kind=o.kind, keys=keys))
                ops.append(_op("modify" if o.info_raw is not None else "create", o.info_rel, "profile_info", name=o.name))
            expect.append((o.kind, o.name))
        steps = (self.publish or {}).get("native_steps", []) + writes + deletes
        ops = (self.publish or {}).get("native_ops", []) + ops
        if self.conf != self.scan.conf:
            if not check_conf(self.conf):
                raise Blocked("conf_unreadable")
            cf = self.scan.conf_file
            content = dump_conf(ConfFile(self.conf, cf.indent, cf.checksum, cf.crlf))
            rel = f"{self.instance.slicer}.conf"
            steps.append(Step("write", rel, content, check="conf"))
            ops.append(_op("modify", rel, "conf", keys=[d["path"] for d in conf_diff(self.scan.conf, self.conf)]))
        conf_name = f"{self.instance.slicer}.conf"
        for rel in (r for s in steps for r in (s.path, s.to) if r):
            if outside_backup(self.instance.data_dir, rel, conf_name):
                raise Blocked("path_outside_backup", path=rel)
        return steps, ops, expect


def _changed_keys(before: dict, after: dict) -> list:
    """Changed settings, without the keys every profile carries."""
    return sorted(k for k in set(before) | set(after) if k not in META_KEYS and k not in SETTINGS_ID.values()
                  and (k not in before or k not in after or before[k] != after[k]))


def _op(action: str, path: str, what: str, **params) -> dict:
    return {"action": action, "path": path, "what": what, "params": {k: v for k, v in params.items() if v is not None}}


# ---------------------------------------------------------------- plans

def _restorable_now(instance: Instance) -> tuple[dict, set]:
    """({relative path: Path} of the .conf and every file in user/ a restore may touch, folders in user/)."""
    data_dir = instance.data_dir
    files, dirs = {}, set()
    from .profile_native_paths import owned_files
    managed = owned_files(data_dir)
    for rel in managed:
        files[rel] = data_dir / rel
        if rel.count("/") > 1:
            dirs.update((str(PurePosixPath(rel).parent), str(PurePosixPath(rel).parent.parent)))
    conf = data_dir / f"{instance.slicer}.conf"
    if conf.is_file():
        files[conf.name] = conf
    for rel, is_dir in backup.walk(data_dir):
        if rel != "user" and not rel.startswith("user/"):
            continue
        if is_dir:
            dirs.add(rel)
        else:
            files[rel] = data_dir / rel
    return files, dirs


def _tree_snapshot(instance: Instance) -> dict:
    files, dirs = _restorable_now(instance)
    snap = {rel: _fingerprint(path) for rel, path in files.items()}
    snap.update({f"{rel}/": "dir" for rel in dirs})
    return snap


def _store(plan: Plan) -> None:
    with _lock:
        _plans[plan.id] = plan
        while len(_plans) > _KEEP_PLANS:
            _plans.pop(next(iter(_plans)))


def make_plan(instance: Instance, processes: list, changes: list) -> dict:
    """Work out what changes would do. Raises InvalidChange for a change the API cannot read."""
    if any(isinstance(c, dict) and c.get("op") == "profile_publish" for c in changes) and len(changes) != 1:
        raise InvalidChange(None, "changes")
    # Before reading anything: whatever changes in user/ or the .conf from here on, another plan
    # applied meanwhile included, makes this plan outdated. A plan built on a profile another
    # one deletes would otherwise leave an orphan behind.
    snapshot = _tree_snapshot(instance)
    blocked, blocked_params = environment_block(instance, processes), {}
    steps, ops, expect, warnings, conf_before, conf_after = [], [], [], [], {}, {}
    unlock_add, unlock_remove = set(), set()
    try:
        planner = Planner(instance)
    except Blocked as exc:
        planner, blocked = None, blocked or exc.code
    if planner is not None:
        for index, change in enumerate(changes):
            try:
                planner.apply(change, index)
            except Blocked as exc:
                if blocked is None:
                    blocked, blocked_params = exc.code, {"change": index, **exc.params}
                break
        try:
            steps, ops, expect = planner.finish()
        except Blocked as exc:
            blocked = blocked or exc.code
            blocked_params = blocked_params or exc.params
        warnings = planner.warnings
        conf_before, conf_after = planner.scan.conf, planner.conf
        unlock_add, unlock_remove = planner.unlock_add, planner.unlock_remove
        if planner.publish is not None:
            expect = planner.publish["profiles"]
    plan = Plan(id=secrets.token_hex(8), instance_id=instance.id, steps=steps, snapshot=snapshot, public={},
                blocked=blocked, reason="before_change",
                reason_params={"ops": [c.get("op") for c in changes if isinstance(c, dict)]},
                expect_loaded=expect, unlock_add=unlock_add, unlock_remove=unlock_remove,
                publish=planner.publish if planner is not None else None)
    if not steps and not blocked:
        warnings = warnings + [{"code": "nothing_to_do"}]
    plan.public = {"id": plan.id, "ops": ops, "conf_diff": conf_diff(conf_before, conf_after), "warnings": warnings,
                   "blocked": blocked}
    if blocked_params:
        plan.public["blocked_params"] = blocked_params
    _store(plan)
    return plan.public


def _file_kind(rel: str, conf_name: str) -> tuple[str, dict]:
    if rel == conf_name:
        return "conf", {}
    path = PurePosixPath(rel)
    parts = path.parts
    kind = parts[2] if len(parts) > 3 else None
    if kind in SETTINGS_ID and path.suffix in (".json", ".info"):
        return ("own_profile" if path.suffix == ".json" else "profile_info"), {"name": path.stem, "kind": kind}
    return "file", {}


def restore_plan(instance: Instance, processes: list, name: str) -> dict:
    """What restoring a backup would change: the .conf and user/** (hard rule 2), files in user/
    the backup does not have are removed. Raises backup.BackupError."""
    files, dirs = backup.restorable(instance, name)
    snapshot = _tree_snapshot(instance)
    blocked, blocked_params = environment_block(instance, processes, restore=True), {}
    conf_name = f"{instance.slicer}.conf"
    now_files, now_dirs = _restorable_now(instance)
    mkdirs = [Step("mkdir", rel) for rel in sorted(dirs - now_dirs)]
    writes, deletes, ops = [], [], []
    for rel in sorted(files, key=lambda r: (r == conf_name, r)):
        path = now_files.get(rel)
        if path is not None and path.read_bytes() == files[rel]:
            continue
        writes.append(Step("write", rel, files[rel]))
        what, params = _file_kind(rel, conf_name)
        ops.append(_op("create" if path is None else "modify", rel, what, **params))
    for rel in sorted(set(now_files) - set(files)):
        if rel == conf_name:
            continue  # a backup without .conf leaves the current one alone
        deletes.append(Step("delete", rel))
        what, params = _file_kind(rel, conf_name)
        ops.append(_op("delete", rel, what, **params))
    # Deepest first, and only if empty then: OrcaOne never removes what it does not know.
    rmdirs = [Step("rmdir", rel) for rel in sorted(now_dirs - dirs, key=lambda r: -r.count("/"))]
    conf_before, conf_after = {}, {}
    try:
        conf_before = parse_conf(now_files[conf_name].read_bytes()).data if conf_name in now_files else {}
    except (OSError, ValueError):
        conf_before = {}
    if conf_name in files:
        try:
            conf_after = parse_conf(files[conf_name]).data
        except ValueError:
            # The .conf in the backup is broken: restoring it would not help.
            blocked = blocked or "backup_unreadable"
    else:
        conf_after = conf_before
    # Deletes first: on Windows and macOS "mein pla.json" and "Mein PLA.json" are one file.
    steps = mkdirs + deletes + writes + rmdirs
    outside = next((s.path for s in steps if outside_backup(instance.data_dir, s.path, conf_name)), None)
    if outside and not blocked:
        blocked, blocked_params = "path_outside_backup", {"path": outside}
    plan = Plan(id=secrets.token_hex(8), instance_id=instance.id, steps=steps, snapshot=snapshot, public={},
                blocked=blocked, reason="before_restore", reason_params={"backup": name}, restore=True)
    warnings = [] if ops or blocked else [{"code": "nothing_to_do"}]
    plan.public = {"id": plan.id, "ops": ops, "conf_diff": conf_diff(conf_before, conf_after), "warnings": warnings,
                   "blocked": blocked}
    if blocked_params:
        plan.public["blocked_params"] = blocked_params
    _store(plan)
    return plan.public


# ---------------------------------------------------------------- writing

def write_atomic(path: Path, content: bytes) -> None:
    """Temporary file next to it, then os.replace: the slicer sees the old or the new file,
    never half of one. The new file takes over the permissions of the old one (FINDINGS 4.3)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # A short name: ".<long profile name>.json.tmp" could pass the 255 bytes of a file name.
    tmp = path.with_name(f".orcaone-{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        if path.exists():
            try:
                os.chmod(tmp, path.stat().st_mode & 0o7777)
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _execute(data_dir: Path, steps: list) -> None:
    for step in steps:
        path = data_dir / step.path
        if step.action == "write":
            write_atomic(path, step.content)
        elif step.action == "rename":
            # Rename first, then write: a change of case only is one file on Windows and macOS.
            target = data_dir / step.to
            os.replace(path, target)
            write_atomic(target, step.content)
        elif step.action == "delete":
            path.unlink(missing_ok=True)
        elif step.action == "mkdir":
            path.mkdir(parents=True, exist_ok=True)
        elif step.action == "rmdir":
            try:
                path.rmdir()
            except OSError:
                pass  # not empty: something OrcaOne did not back up stays


def _verify(data_dir: Path, steps: list) -> bool:
    """Read everything written back: same bytes, and still loadable by the slicer."""
    for step in steps:
        if step.action not in ("write", "rename"):
            continue
        try:
            raw = (data_dir / (step.to or step.path)).read_bytes()
        except OSError:
            return False
        if raw != step.content:
            return False
        if step.check == "profile" and not check_profile(raw, step.name, step.nested_keys):
            return False
        if step.check == "conf":
            try:
                if not check_conf(parse_conf(raw).data):
                    return False
            except ValueError:
                return False
    return True


def _roll_back(instance: Instance, steps: list, backup_name: str) -> bool:
    """After a failed write: every path the steps touch goes back to how the backup made just
    before has it, last step first. True if all of that worked."""
    try:
        files, dirs = backup.restorable(instance, backup_name)
    except backup.BackupError:
        return False
    ok = True
    for step in reversed(steps):
        # A rename: the new path goes, the old one comes back.
        for rel in (r for r in (step.to, step.path) if r):
            path = instance.data_dir / rel
            try:
                if rel in files:
                    if not path.is_file() or path.read_bytes() != files[rel]:
                        write_atomic(path, files[rel])
                elif rel in dirs:
                    path.mkdir(parents=True, exist_ok=True)
                elif step.action in ("mkdir", "rmdir"):
                    if path.is_dir():
                        path.rmdir()
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                ok = False
    from .profile_native_paths import vendor_of, safe_path
    vendors = {vendor_of(rel) for step in steps for rel in (step.path, step.to) if rel and vendor_of(rel)}
    for vendor in vendors:
        for rel in (f"system/{vendor}/machine", f"system/{vendor}"):
            if rel in dirs or not safe_path(instance.data_dir, rel):
                continue
            path = instance.data_dir / rel
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    ok = False
    return ok


def apply(instance_id: str, plan_id) -> dict:
    """Write a plan. Raises OperationError."""
    from .profile_jobs import report
    report("check")
    with _lock:
        plan = _plans.get(plan_id) if isinstance(plan_id, str) else None
        if plan is None or plan.instance_id != instance_id:
            raise OperationError("plan_not_found", 404)
        instance, processes = find_instance(instance_id)
        if plan.blocked:
            raise OperationError(plan.blocked)
        block = environment_block(instance, processes, restore=plan.restore)
        if block:
            raise OperationError(block)
        if _tree_snapshot(instance) != plan.snapshot:
            raise OperationError("plan_outdated")
        if any(outside_backup(instance.data_dir, rel, f"{instance.slicer}.conf")
               for step in plan.steps for rel in (step.path, step.to) if rel):
            raise OperationError("path_outside_backup")
        if plan.publish is not None:
            from .profile_publish import execute_publish
            return execute_publish(instance, plan)
        if not plan.steps:
            _plans.pop(plan.id, None)
            return {"ok": True, "backup": None, "applied": 0, "warnings": []}
        try:
            made = backup.create(instance, plan.reason, plan.reason_params)
        except backup.BackupError as exc:
            raise OperationError(exc.code, 500) from None
        # The backup takes a moment; the slicer may have started meanwhile.
        block = run_block(instance, guard.find_processes())
        if block:
            raise OperationError(block, backup=made)
        _plans.pop(plan.id, None)
        try:
            before = snapshot.current(instance)
        except snapshot.SnapshotError:
            before = None
        try:
            _execute(instance.data_dir, plan.steps)
            written = _verify(instance.data_dir, plan.steps)
        except OSError:
            written = False
        if not written:
            # A full disk, say: no half change stays behind.
            rolled_back = _roll_back(instance, plan.steps, made["name"])
            raise OperationError("write_failed", 500, backup=made, rolled_back=rolled_back)
        warnings = []
        if run_block(instance, guard.find_processes()):
            # It started while OrcaOne wrote: it may have read half of the change. The backup helps.
            warnings.append({"code": "slicer_started", "backup": made["name"]})
        # Scan again (hard rule 5): whatever OrcaOne wrote must load in the slicer.
        scan = scanner.scan(instance.data_dir, instance.slicer)
        if scan.conf_file is None:
            warnings.append({"code": "conf_unreadable"})
        res = Resolver(scan)
        if before is not None and scan.conf_file is not None:
            # The page "Änderungen" shows what others changed, not what OrcaOne just wrote.
            try:
                snapshot.accept(instance, before, snapshot.items(scan, res))
            except OSError:
                log.exception("Snapshot of %s not updated", instance.data_dir)
        for kind, name in plan.expect_loaded:
            p = next((q for q in scan.own if q.kind == kind and q.name == name and not q.bundle), None)
            problem = "missing" if p is None else res.state(p).problem
            if problem:
                warnings.append({"code": "not_loaded", "name": name, "kind": kind, "problem": problem})
        unlocks = set(instances.load_unlocks(instance.id))
        new = (unlocks | plan.unlock_add) - plan.unlock_remove
        if plan.restore:
            # After a restore only what the restored list still shows counts as unlocked.
            new -= set(overview.hidden_filaments(res, new))
        if new != unlocks:
            try:
                instances.save_unlocks(instance.id, sorted(new))
            except OSError:
                warnings.append({"code": "unlocks_not_saved"})
        return {"ok": True, "backup": made, "applied": len(plan.steps), "warnings": warnings}

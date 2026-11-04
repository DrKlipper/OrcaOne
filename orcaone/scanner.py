"""Read what a slicer data directory holds. Strictly read only.

- System profiles come from the manifest system/<Vendor>.json (FINDINGS 4.2). The library of
  Snapmaker Orca has an empty manifest and is read straight from its folder (FINDINGS 4.7).
  OrcaSlicer 2.5 ships system/<Vendor>.opc instead (orcaone/opc.py).
- Own profiles are read from the active user folder only, as the slicer does:
  <kind>/base/ first, then <kind>/*.json; OrcaSlicer main also loads the bundles in
  _local/<id>/ and _subscribed/<id>/ before them (FINDINGS 4.2, Preset.cpp load_presets).
  Whether a profile really loads depends on its parent and is decided in orcaone/resolver.py.
- The folder tree lists every entry with size, category and a note code; the texts for the
  codes live in orcaone/static/texts.js.
"""

import io
import os
import re
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import opc
from .conf import ConfFile, loads, read_conf

LIBRARY = "OrcaFilamentLibrary"
SNORCA = "Snapmaker_Orca"
KINDS = ("machine", "process", "filament")
# Other spellings of the folder type in the "type" key (Preset::get_type_from_string).
TYPE_NAMES = {"machine": {"machine", "printer"}, "process": {"process", "print"}, "filament": {"filament"}}

# Meta keys of a profile JSON; everything else is a setting (FINDINGS 4.4). The slicer reads them
# into a map of strings (ConfigBase::load_from_json), another type makes it reject the file —
# except "include" (OrcaSlicer 2.5): a list of names, layered under the own values.
META_KEYS = {"version", "name", "type", "from", "inherits", "include", "instantiation", "setting_id",
             "filament_id", "description", "renamed_from", "url", "is_custom_defined"}
# Semver as the slicer accepts it: 2 to 4 numeric parts, leading zeros allowed (FINDINGS 4.4).
# A pre-release or build suffix ("2.5.0-dev") is accepted as well, semver.c knows them.
SEMVER = re.compile(r"\d+(\.\d+){1,3}(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")
_BUNDLE_DIRS = ("_local", "_subscribed")


@dataclass
class Profile:
    name: str
    kind: str                  # machine, process, filament
    package: str               # vendor package, LIBRARY, or "" for own profiles
    inherits: str = ""
    instantiation: str = "true"
    renamed_from: list = field(default_factory=list)  # explicit or implicit, FINDINGS 4.4
    includes: list = field(default_factory=list)  # OrcaSlicer 2.5: bases layered under the own values
    values: dict = field(default_factory=dict)        # own settings only: key -> str or list
    setting_id: str = ""       # system profiles: the id an own child keeps as base_id in its .info
    file: str | None = None    # path relative to the data directory; the cache file for an .opc package
    # Own profiles only:
    load_pass: int = 0         # the slicer loads folder by folder; a parent must come earlier
    problem: str | None = None  # invalid_json, bad_version, wrong_type: the slicer skips it
    json_name: str | None = None  # "name" in the file, if it differs from the name used
    bundle: str | None = None  # "_local/<id>" for bundle profiles of OrcaSlicer main
    custom_defined: bool = False  # is_custom_defined = "1": Snapmaker Orca loads it without parent
    info: dict | None = None   # <Name>.info: sync_info, user_id, setting_id, base_id, updated_time

    @property
    def selectable(self) -> bool:
        return self.instantiation != "false"

    @property
    def alias(self) -> str:
        return alias_of(self.name)

    @property
    def origin_kind(self) -> str:
        # A bundle belongs to OrcaSlicer: OrcaOne shows it, but never changes it.
        if self.bundle:
            return "bundle"
        if not self.package:
            return "user"
        return "library" if self.package == LIBRARY else "vendor"


@dataclass
class Package:
    name: str
    format: str                # json or opc
    file: str                  # system/<Vendor>.json or system/<Vendor>.opc
    folder: str | None = None  # system/<Vendor> for JSON packages
    version: str = ""
    models: int = 0
    manifest_empty: bool = False
    counts: dict = field(default_factory=lambda: {kind: 0 for kind in KINDS})
    extra_files: list = field(default_factory=list)  # relative to folder, not in the manifest
    error: str | None = None   # opc_unsupported_version, opc_corrupt, …: profiles not read


@dataclass
class Scan:
    data_dir: Path
    app_key: str
    conf: dict
    conf_file: ConfFile | None
    conf_size: int
    active_folder: str
    # When the .conf was last written, local time: the slicer writes it soon after every change
    # (GUI_App, on idle when dirty), so this is how current its choices are ("Übersicht").
    conf_saved: str | None = None
    packages: list = field(default_factory=list)
    profiles: dict = field(default_factory=dict)  # (package, kind, name) -> system Profile
    own: list = field(default_factory=list)       # own profiles in load order
    bundles: dict = field(default_factory=dict)   # "_local/<id>" -> name of the bundle, for the page
    colours: dict = field(default_factory=dict)   # (package, alias) -> [{"hex", "name"}]
    # (package, printer model) -> default_materials: the slicer switches them on again for a
    # printer without any filament in "filaments" that fits it (FINDINGS 4.6).
    default_materials: dict = field(default_factory=dict)

    @property
    def snorca(self) -> bool:
        return self.app_key == SNORCA

    @property
    def storage(self) -> str:
        return "opc" if any(p.format == "opc" for p in self.packages) else "json"

    def of_kind(self, kind: str) -> list:
        return [p for p in self.profiles.values() if p.kind == kind]


def alias_of(name: str) -> str:
    # Text before the first "@", right-trimmed (PresetBundle::load_vendor_configs_from_json).
    pos = name.find("@")
    alias = name[:pos].rstrip() if pos >= 0 else ""
    return alias or name


def split_list(text) -> list[str]:
    # "a;b" or with quotes, as written by escape_strings_cstyle; good enough for names and variants.
    if not isinstance(text, str):
        return []
    return [part.strip().strip('"') for part in text.split(";") if part.strip()]


def implicit_renamed_from(name: str, renamed_from: list) -> list:
    # Without an explicit renamed_from, the name with the first "@" removed counts as an old
    # name ("Generic PLA @System" -> "Generic PLA System"), FINDINGS 4.4.
    if renamed_from or "@" not in name:
        return list(renamed_from)
    pos = name.find("@")
    return [name[:pos] + name[pos + 1:]]


def includes_of(data: dict) -> list[str]:
    """The "include" key of a profile (OrcaSlicer 2.5, load_vendor_preset): names of base profiles
    whose values are layered under the profile's own, in the order given. One bare name or a list —
    in a vendor JSON the list is a real array, in the slicer's meta map its text."""
    raw = data.get("include")
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            raw = loads(raw)
        except ValueError:
            raw = ""
    if isinstance(raw, list):
        return [v for v in raw if isinstance(v, str)]
    return [raw.strip()] if isinstance(raw, str) and raw.strip() else []


def profile_from_json(data: dict, kind: str, package: str, name: str | None = None) -> Profile:
    renamed = data.get("renamed_from", [])
    if isinstance(renamed, str):
        renamed = split_list(renamed)
    elif not isinstance(renamed, list):
        renamed = []
    name = name if name is not None else str(data.get("name", ""))
    inherits = data.get("inherits", "")
    instantiation = data.get("instantiation", "true")
    setting_id = data.get("setting_id", "")
    return Profile(
        name=name, kind=kind, package=package,
        inherits=inherits if isinstance(inherits, str) else "",
        instantiation=instantiation if isinstance(instantiation, str) else "true",
        renamed_from=implicit_renamed_from(name, [r for r in renamed if isinstance(r, str)]),
        includes=includes_of(data),
        values={k: v for k, v in data.items() if k not in META_KEYS},
        setting_id=setting_id if isinstance(setting_id, str) else "",
    )


def _read_json(path: Path):
    """The parsed file, or None if the slicer could not read it either. nlohmann::json skips a
    UTF-8 BOM, as it comes from older Notepad versions, but rejects NaN (orcaone/conf.py)."""
    try:
        return loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _list(value) -> list:
    return value if isinstance(value, list) else []


def display_version(version: str) -> str:
    # "02.03.03.03" -> "2.3.3.3"; the .opc stamp "2.4.0.15" stays as it is.
    return ".".join(str(int(part)) if part.isdigit() else part for part in version.split("."))


def _version_key(version: str) -> tuple:
    return tuple(int(part) if part.isdigit() else 0 for part in version.split("."))


# ---------------------------------------------------------------- system/

def _sub_paths(manifest: dict, list_key: str) -> list:
    return [item["sub_path"] for item in _list(manifest.get(list_key))
            if isinstance(item, dict) and isinstance(item.get("sub_path"), str) and item["sub_path"]]


def _load_json_package(scan: Scan, manifest_path: Path, manifest: dict) -> None:
    name = manifest_path.stem
    folder = manifest_path.parent / name
    package = Package(name=name, format="json", file=f"system/{manifest_path.name}", folder=f"system/{name}",
                      version=str(manifest.get("version", "")), models=len(_list(manifest.get("machine_model_list"))))
    scan.packages.append(package)
    listed = set()
    if scan.snorca and name == LIBRARY and not _sub_paths(manifest, "filament_list"):
        # Only Snapmaker Orca, only the library and only its filaments: with an empty filament_list
        # it loads filament/**/*.json straight from disk (PresetBundle.cpp load_vendor_configs_from_json,
        # FINDINGS 4.7).
        package.manifest_empty = True
        for path in sorted((folder / "filament").rglob("*.json")):
            data = _read_json(path)
            if not isinstance(data, dict) or "name" not in data:
                continue
            listed.add(path.relative_to(folder).as_posix())
            profile = profile_from_json(data, "filament", name)
            profile.file = f"system/{name}/{path.relative_to(folder).as_posix()}"
            scan.profiles[(name, "filament", profile.name)] = profile
            package.counts["filament"] += 1
    for list_key, kind in (("machine_list", "machine"), ("process_list", "process"), ("filament_list", "filament")):
        for sub_path in _sub_paths(manifest, list_key):
            listed.add(sub_path)
            data = _read_json(folder / sub_path)
            if not isinstance(data, dict):
                continue
            profile = profile_from_json(data, kind, name)
            profile.file = f"system/{name}/{sub_path}"
            scan.profiles[(name, kind, profile.name)] = profile
            package.counts[kind] += 1
    listed |= set(_sub_paths(manifest, "machine_model_list"))
    for item in _list(manifest.get("machine_model_list")):
        # The model id is the name in the manifest (VendorProfile::from_json).
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("sub_path"), str) \
                and item["sub_path"]:
            data = _read_json(folder / item["sub_path"])
            materials = split_list(data.get("default_materials")) if isinstance(data, dict) else []
            if materials:
                scan.default_materials[(name, item["name"])] = materials
    # Files the manifest does not list are no system profiles (FINDINGS 4.2).
    if folder.is_dir():
        package.extra_files = sorted(rel for rel in (f.relative_to(folder).as_posix() for f in folder.rglob("*")
                                                     if f.is_file()) if rel not in listed)


def _load_opc_package(scan: Scan, path: Path, cache: opc.VendorCache) -> None:
    package = Package(name=cache.vendor_name, format="opc", file=f"system/{path.name}", version=cache.vendor_version,
                      models=sum(len(v.models) for v in cache.vendors.values()))
    scan.packages.append(package)
    for vendor in cache.vendors.values():
        for model in vendor.models:
            if model.default_materials:
                scan.default_materials[(cache.vendor_name, model.id)] = list(model.default_materials)
    for kind in KINDS:
        for entry in getattr(cache, kind):
            profile = Profile(
                name=entry.name, kind=kind, package=cache.vendor_name, inherits=entry.inherits,
                instantiation=entry.instantiation or "true",
                renamed_from=implicit_renamed_from(entry.name, entry.renamed_from),
                includes=list(entry.includes),
                values={k: opc.to_json_value(o) for k, o in entry.config.items()},
                setting_id=entry.setting_id, file=package.file,
            )
            scan.profiles[(cache.vendor_name, kind, entry.name)] = profile
            package.counts[kind] += 1


def load_system(scan: Scan) -> None:
    """All vendor packages. With <Vendor>.json and <Vendor>.opc side by side, OrcaSlicer takes the
    cache if its stamp is at least as new as the manifest (cache_covers, FINDINGS .opc rules);
    a cache in an unknown format falls back to the JSON, or stays as a package with an error."""
    system = scan.data_dir / "system"
    if not system.is_dir():
        return
    manifests = {p.stem: p for p in sorted(system.glob("*.json")) if p.is_file()}
    caches = {p.stem: p for p in sorted(system.glob("*.opc")) if p.is_file()}
    for stem in sorted(set(manifests) | set(caches)):
        manifest = _read_json(manifests[stem]) if stem in manifests else None
        if not isinstance(manifest, dict):
            manifest = None
        cache, error = None, None
        if stem in caches:
            try:
                cache = opc.read_opc(caches[stem])
            except opc.OpcError as exc:
                error = exc.code
        if cache and (manifest is None or _version_key(cache.vendor_version) >= _version_key(str(manifest.get("version", "")))):
            _load_opc_package(scan, caches[stem], cache)
        elif manifest is not None:
            _load_json_package(scan, manifests[stem], manifest)
        elif error:
            scan.packages.append(Package(name=stem, format="opc", file=f"system/{caches[stem].name}", error=error))
        elif stem in manifests:
            scan.packages.append(Package(name=stem, format="json", file=f"system/{manifests[stem].name}",
                                         folder=f"system/{stem}", error="manifest_unreadable"))


def load_colours(scan: Scan) -> None:
    """system/<Vendor>/filament/filaments_colours.json, only Snapmaker Orca ships it
    (FilamentColorLibrary.cpp). Keyed by alias: one entry ("Snapmaker ABS @U1") stands for
    all nozzle profiles."""
    for path in sorted((scan.data_dir / "system").glob("*/filament/filaments_colours.json")):
        package = path.parent.parent.name
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        for entry in _list(data.get("filaments")):
            if not isinstance(entry, dict) or not isinstance(entry.get("filament_name"), str):
                continue
            items = []
            for c in _list(entry.get("filament_color")):
                hexes = _list(c.get("filament_color")) if isinstance(c, dict) else []
                if hexes and isinstance(hexes[0], str) and c.get("enabled", True):
                    names = c.get("color_name")
                    name = names.get("en", "") if isinstance(names, dict) else ""
                    items.append({"hex": hexes[0], "name": name if isinstance(name, str) else ""})
            if entry.get("enabled", True) and items:
                scan.colours.setdefault((package, alias_of(entry["filament_name"])), items)


# ---------------------------------------------------------------- user/

def read_info(path: Path) -> dict | None:
    """<Name>.info as "key = value" lines (Preset::load_info reads it as INI, FINDINGS 4.4)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    info = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            info[key.strip()] = value.strip()
    return info


def _own_profile(scan: Scan, path: Path, kind: str, load_pass: int, bundle: str | None) -> Profile:
    profile = _own_profile_json(scan, path, kind, load_pass, bundle)
    # Bundle profiles have no .info (FINDINGS 4.2).
    profile.info = read_info(path.with_suffix(".info"))
    return profile


def _own_profile_json(scan: Scan, path: Path, kind: str, load_pass: int, bundle: str | None) -> Profile:
    rel = path.relative_to(scan.data_dir).as_posix()
    stem = path.stem
    data = _read_json(path)
    # A file that does not parse, or non-string metadata, makes the slicer delete .json and
    # .info at its next start (FINDINGS 4.4). "include" is a list, it is exempt from strings-only.
    if not isinstance(data, dict) or any(k in data and k != "include" and not isinstance(data[k], str)
                                         for k in META_KEYS):
        return Profile(name=stem, kind=kind, package="", file=rel, load_pass=load_pass, problem="invalid_json", bundle=bundle)
    json_name = data.get("name", "")
    # Snapmaker Orca takes the "name" field, OrcaSlicer >= 2.4 the file name (FINDINGS 4.4).
    # A bundle with an empty id adds no prefix (get_preset_canonical_name in Preset.cpp).
    if scan.snorca and json_name:
        name = json_name
    else:
        name = f"{bundle}/{stem}" if bundle and not bundle.endswith("/") else stem
    profile = profile_from_json(data, kind, "", name)
    profile.file, profile.load_pass, profile.bundle = rel, load_pass, bundle
    profile.custom_defined = data.get("is_custom_defined") == "1"
    if json_name and json_name != stem:
        # The other slicer would call this profile differently.
        profile.json_name = json_name
    if scan.snorca and "type" in data and data["type"] not in TYPE_NAMES[kind]:
        profile.problem = "wrong_type"
    elif not SEMVER.fullmatch(data.get("version", "")):
        profile.problem = "bad_version"
    return profile


def _load_kind_folder(scan: Scan, folder: Path, kind: str, next_pass: int, bundle: str | None) -> int:
    """<kind>/base/ (and base/base/ …) first, then <kind>/*.json. Returns the next pass number."""
    if (folder / "base").is_dir():
        next_pass = _load_kind_folder(scan, folder / "base", kind, next_pass, bundle)
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            if path.is_file():
                scan.own.append(_own_profile(scan, path, kind, next_pass, bundle))
    return next_pass + 1


# Keys BundleMetadata::load_from_json reads with get<>(), which throws on another type.
_BUNDLE_KEYS = {"id": str, "name": str, "version": str, "description": str, "author": str,
                "imported_time": (int, float), "updated_time": (int, float),
                "print_presets": list, "filament_presets": list, "printer_presets": list}


def _bundle_id(meta) -> str | None:
    """The id of an OrcaSlicer main bundle, "" without one, or None if the slicer skips the bundle
    because its bundle_metadata.json does not load (PresetBundle.cpp load_user_presets)."""
    if not isinstance(meta, dict) or any(k in meta and not isinstance(meta[k], t) for k, t in _BUNDLE_KEYS.items()):
        return None
    return meta.get("id", "")


def load_own(scan: Scan) -> None:
    folder = scan.data_dir / "user" / scan.active_folder
    next_pass = 0
    for bundle_dir in _BUNDLE_DIRS:
        base = folder / bundle_dir
        if scan.snorca or not base.is_dir():
            continue
        for bundle in sorted(d for d in base.iterdir() if (d / "bundle_metadata.json").is_file()):
            meta = _read_json(bundle / "bundle_metadata.json")
            bundle_id = _bundle_id(meta)
            if bundle_id is None:
                continue
            scan.bundles[f"{bundle_dir}/{bundle_id}"] = meta.get("name") or bundle_id or bundle.name
            # Order as in PresetBundle::load_user_presets: process, filament, machine.
            for kind in ("process", "filament", "machine"):
                next_pass = _load_kind_folder(scan, bundle / kind, kind, next_pass, f"{bundle_dir}/{bundle_id}")
    for kind in ("process", "filament", "machine"):
        next_pass = _load_kind_folder(scan, folder / kind, kind, next_pass, None)


def scan(data_dir: Path, app_key: str) -> Scan:
    conf_path = data_dir / f"{app_key}.conf"
    try:
        conf_file = read_conf(conf_path)
        stat = conf_path.stat()
        conf, size = conf_file.data, stat.st_size
        saved = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")
    except (OSError, ValueError):
        conf_file, conf, size, saved = None, {}, 0, None
    app = conf.get("app") if isinstance(conf.get("app"), dict) else {}
    preset_folder = app.get("preset_folder")
    active = preset_folder if isinstance(preset_folder, str) and preset_folder else "default"
    result = Scan(data_dir=data_dir, app_key=app_key, conf=conf, conf_file=conf_file, conf_size=size,
                  active_folder=active, conf_saved=saved)
    load_system(result)
    load_colours(result)
    load_own(result)
    return result


# ---------------------------------------------------------------- folder tree

# Top-level entries of a data directory: category and note code (FINDINGS 4.2).
TOP_LEVEL = {
    "system": ("system", "system"),
    "user": ("managed", "user"),
    "log": ("temp", "log"),
    "cache": ("temp", "cache"),
    "web": ("unmanaged", "web"),
    "hms": ("unmanaged", "hms"),
    "ota": ("unmanaged", "ota"),
    "log_upload_spool": ("temp", "log_upload_spool"),
    "printers": ("unmanaged", "printers"),
    "plugins": ("unmanaged", "plugins"),
    "orca_plugins": ("unmanaged", "plugins"),
    "python": ("unmanaged", "python"),
    "simplyprint_oauth.json": ("sensitive", "simplyprint"),
    "3dprinteros_api_cred.json": ("sensitive", "3dprinteros"),
    "orca_refresh_token.sec": ("sensitive", "refresh_token"),
}
OTHER = ("unmanaged", "slicer_owned")
# Order of the top level on the page "Installationen", as in its size bar: what OrcaOne writes to first.
CATEGORY_ORDER = ["managed", "system", "unmanaged", "temp", "sensitive"]
# Hard rule 4: everything goes into the backup except these.
BACKUP_SKIP_TOP = {"log", "cache", "web", "hms", "ota"}
BACKUP_EXCLUDED = ["log/", "cache/", "web/", "hms/", "ota/", "user/Temp/", "user/*/temp/", "user_backup-v*/"]
# Folders of the built-in web view (WebKitGTK on Linux) outside the data directory, named
# after the program (FINDINGS 4.2): path below home, category, note code.
OUTSIDE = {
    "Snapmaker_Orca": [(".local/share/snapmaker-orca", "sensitive", "webview_data_snorca"),
                       (".cache/snapmaker-orca", "temp", "webview_cache")],
    "OrcaSlicer": [(".local/share/orca-slicer", "unmanaged", "webview_data"),
                   (".cache/orca-slicer", "temp", "webview_cache")],
}


def measure(path: Path) -> tuple[int, int]:
    """(bytes, files) of a file or a whole folder. Symlinks are not followed."""
    if path.is_symlink() or not path.is_dir():
        try:
            return path.lstat().st_size, 1
        except OSError:
            return 0, 0
    size = files = 0
    for root, _, names in os.walk(path):
        for name in names:
            try:
                size += (Path(root) / name).lstat().st_size
                files += 1
            except OSError:
                continue
    return size, files


def in_backup(rel: PurePosixPath) -> bool:
    parts = PurePosixPath(rel).parts
    if not parts:
        return True
    if parts[0] in BACKUP_SKIP_TOP or parts[0].startswith("user_backup-v"):
        return False
    if parts[0] == "user" and len(parts) >= 2 and parts[1] == "Temp":
        return False
    return not (parts[0] == "user" and len(parts) >= 3 and parts[2] == "temp")


# The last measurement per data directory with the files it saw (path, size, mtime): zipping takes
# seconds, listing the files a tenth of that, so GET /api/data zips again only when a file changed.
_measured: dict[str, tuple[tuple, tuple[int, int, int]]] = {}


def backup_measure(data_dir: Path) -> tuple[int, int, int]:
    """(bytes, ZIP bytes, files) of what a backup would hold today. Zipped in memory only."""
    found = []
    for root, dirs, names in os.walk(data_dir):
        rel_root = PurePosixPath(Path(root).relative_to(data_dir).as_posix())
        dirs[:] = [d for d in dirs if in_backup(rel_root / d)]
        for name in names:
            file, rel = Path(root) / name, rel_root / name
            if file.is_symlink() or not in_backup(rel):
                continue
            try:
                st = file.stat()
            except OSError:
                continue
            # A name that is not valid UTF-8 (Linux, from a Latin-1 ZIP) cannot go into a ZIP
            # as it is; for measuring, a replacement character does.
            found.append((file, os.fsencode(rel.as_posix()).decode("utf-8", "replace"), st.st_size, st.st_mtime_ns))
    stamp = tuple((arcname, size, mtime) for _, arcname, size, mtime in found)
    known = _measured.get(str(data_dir))
    if known and known[0] == stamp:
        return known[1]
    raw = files = 0
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file, arcname, _, _ in found:
            try:
                zf.write(file, arcname)
                raw += file.stat().st_size
            except OSError:
                continue
            files += 1
    result = (raw, len(buffer.getvalue()), files)
    _measured[str(data_dir)] = (stamp, result)
    return result


def _children(folder: Path) -> list[Path]:
    try:
        return sorted(folder.iterdir(), key=lambda c: c.name.lower())
    except OSError:
        return []


def _node(path: Path, rel: PurePosixPath, category: str, note: str, children=None, **extra) -> dict:
    size, files = measure(path)
    out = {"name": path.name, "path": rel.as_posix(), "type": "dir" if path.is_dir() else "file",
           "size": size, "files": files, "category": category, "note": note, "backup": in_backup(rel)}
    out.update(extra)
    if children is not None:
        out["children"] = children
    return out


def _top_level_info(name: str, app_key: str) -> tuple:
    if name == f"{app_key}.conf":
        return "managed", "conf"
    if name == f"{app_key}.conf.bak":
        return "managed", "conf_bak"
    if name.startswith(f"{app_key}.conf."):
        return "temp", "conf_tmp"
    if name.startswith("user_backup-v"):
        return "unmanaged", "user_backup"
    if name.startswith(".") and name.endswith("_machine_id"):
        return "sensitive", "machine_id"
    return TOP_LEVEL.get(name, OTHER)


def _extra_file_note(path: Path) -> str:
    """Files in a vendor folder that the manifest does not list (FINDINGS 4.2)."""
    if path.name == "filaments_colours.json":
        return "colour_table"
    data = _read_json(path)
    if isinstance(data, dict) and "name" in data and path.parent.name in KINDS:
        return "unlisted_profile"
    return "vendor_extra"


def _system_tree(scan: Scan) -> list:
    system = scan.data_dir / "system"
    by_file = {pk.file: pk for pk in scan.packages}
    by_folder = {pk.folder: pk for pk in scan.packages if pk.folder}
    out = []
    for child in _children(system):
        rel = PurePosixPath("system", child.name)
        pk = by_file.get(rel.as_posix()) or by_folder.get(rel.as_posix())
        info = {"package": pk.name, "version": display_version(pk.version)} if pk else {}
        if pk and pk.error:
            info["error"] = pk.error
        if pk and child.is_file():
            out.append(_node(child, rel, "system", "package_opc" if pk.format == "opc" else "package_manifest", **info))
        elif pk:
            subs = [_node(sub, rel / sub.name, "system", f"package_{sub.name}" if sub.name in KINDS else OTHER[1])
                    for sub in _children(child) if sub.is_dir()]
            extra = [{"path": f"{rel.as_posix()}/{name}", "note": _extra_file_note(child / name)}
                     for name in pk.extra_files]
            if extra:
                info["extra_files"] = extra
            out.append(_node(child, rel, "system", "package_folder", subs, manifest_empty=pk.manifest_empty, **info))
        elif child.suffix in (".new", ".old"):
            out.append(_node(child, rel, "temp", "update_leftover"))
        else:
            out.append(_node(child, rel, *OTHER))
    return out


def _profile_nodes(folder: Path, rel: PurePosixPath, ignored: dict) -> list:
    """One row per profile, <Name>.json and <Name>.info together (FINDINGS 4.2); other files alone."""
    files = [f for f in _children(folder) if f.is_file()]
    pairs = {f.stem for f in files if f.suffix == ".json"} & {f.stem for f in files if f.suffix == ".info"}
    out = []
    for f in files:
        frel = rel / f.name
        extra = {"ignored": ignored[frel.as_posix()]} if frel.as_posix() in ignored else {}
        if f.stem not in pairs:
            out.append(_node(f, frel, "managed", "own_profile" if f.suffix == ".json" else "profile_info", **extra))
        elif f.suffix == ".json":
            size = measure(f)[0] + measure(f.with_suffix(".info"))[0]
            out.append({"name": f.stem, "path": frel.as_posix(), "type": "profile", "size": size, "files": 2,
                        "category": "managed", "note": "own_profile", "backup": in_backup(frel), **extra})
    return out


def _kind_node(folder: Path, rel: PurePosixPath, note: str, ignored: dict) -> dict:
    files = _profile_nodes(folder, rel, ignored)
    if (folder / "base").is_dir():
        files.insert(0, _kind_node(folder / "base", rel / "base", "user_base", ignored))
    return _node(folder, rel, "managed", note, files)


def _user_tree(scan: Scan, ignored: dict) -> list:
    user = scan.data_dir / "user"
    out = []
    for child in _children(user):
        rel = PurePosixPath("user", child.name)
        if child.is_file():
            out.append(_node(child, rel, *(("unmanaged", "hints") if child.name == "hints.cereal" else OTHER)))
            continue
        if child.name == "Temp":
            out.append(_node(child, rel, "temp", "export_temp"))
            continue
        kinds = []
        for sub in _children(child):
            srel = rel / sub.name
            if sub.name == "temp":
                kinds.append(_node(sub, srel, "temp", "import_leftover"))
            elif sub.name in KINDS and sub.is_dir():
                kinds.append(_kind_node(sub, srel, f"user_{sub.name}", ignored))
            elif sub.name in _BUNDLE_DIRS and sub.is_dir():
                kinds.append(_node(sub, srel, "managed", "bundles"))
            else:
                kinds.append(_node(sub, srel, *OTHER))
        note = "account_default" if child.name == "default" else "account_user"
        out.append(_node(child, rel, "managed", note, kinds, active=child.name == scan.active_folder))
    return out


def tree(scan: Scan, ignored: dict, has_credentials: bool) -> list:
    """Folder tree of the data directory. ignored: file path -> reason code for own profiles
    the slicer does not load; has_credentials marks the .conf."""
    out = []
    for child in _children(scan.data_dir):
        rel = PurePosixPath(child.name)
        category, note = _top_level_info(child.name, scan.app_key)
        if child.name == "system" and child.is_dir():
            out.append(_node(child, rel, category, note, _system_tree(scan)))
        elif child.name == "user" and child.is_dir():
            out.append(_node(child, rel, category, note, _user_tree(scan, ignored)))
        elif note == "conf" and has_credentials:
            out.append(_node(child, rel, category, note, secret=True))
        elif note == "user_backup":
            out.append(_node(child, rel, category, note, version=child.name[len("user_backup-v"):]))
        else:
            out.append(_node(child, rel, category, note))
    out.sort(key=lambda e: (CATEGORY_ORDER.index(e["category"]), e["type"] != "dir", e["name"].lower()))
    return out


def outside(app_key: str) -> list:
    """Folders of the built-in web view outside the data directory (Linux only)."""
    if not sys.platform.startswith("linux"):
        return []
    out = []
    for rel, category, note in OUTSIDE.get(app_key, []):
        path = Path.home() / rel
        if path.is_dir():
            size, files = measure(path)
            out.append({"path": "~/" + rel, "size": size, "files": files, "category": category,
                        "note": note, "backup": False})
    return out

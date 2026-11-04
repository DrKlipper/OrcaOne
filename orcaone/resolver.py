"""Inheritance, visibility and compatibility of profiles, as the slicers compute them.

- System profiles find their parent in their own package, filaments also in the library
  (FINDINGS 4.5). Own profiles resolve like PresetCollection::find_preset2: exact name, then
  renamed_from, then the "Generic" fallback to the library, and only against profiles the
  slicer has loaded before them: selectable system profiles and own profiles of an earlier
  folder (<kind>/base/ before <kind>/, Preset.cpp load_presets).
- "filaments" in the .conf has three states: missing, [] and null all mean "everything visible"
  (FINDINGS 4.3, 4.6).
- Compatibility follows is_compatible_with_printer (FINDINGS 4.6): library exclusion, then the
  condition if the list is empty, then the list, and for own printers their direct parent.
- The library exclusion differs between Snapmaker Orca and OrcaSlicer main
  (update_library_profile_excluded_from in both Preset.cpp).
- OrcaSlicer 2.5 layers a preset's `include` bases under its own values, between the parent
  chain and them, the last listed first (load_vendor_preset): layers() gives lookup, value and
  value_entry this order.
"""

import re
from dataclasses import dataclass

from .scanner import KINDS, LIBRARY, Profile, Scan, split_list

# Keys a helper profile may carry besides the meta keys: the printer binding and the id the
# slicer always writes when saving (FINDINGS 4.7, way B).
BINDING_KEYS = {"compatible_printers", "compatible_printers_condition", "filament_settings_id"}
# The default preset of each collection; an own profile cannot take its name.
DEFAULT_NAMES = {"machine": "Default Printer", "process": "Default Setting", "filament": "Default Filament"}
# find_preset2: "… Generic <material> …" falls back to "Generic <material> @System" (Preset.cpp).
# std::regex (ECMAScript) knows only ASCII word characters, hence re.ASCII.
_GENERIC = re.compile(r"^(?:.*?\b(?:\w+_)?)(Generic)\b\s+([^@]+?)\s*(?:@.*)?$", re.ASCII)

# Core values shown per filament.
CORE_VALUES = ["nozzle_temperature", "hot_plate_temp", "filament_flow_ratio",
               "filament_max_volumetric_speed", "filament_density", "filament_cost"]
# Values a user may change per filament: key, group, type, slicer default, min, max.
# Defaults and limits from PrintConfigDef (src/libslic3r/PrintConfig.cpp), identical in
# SnOrca 2.4.0 and Orca main. The default applies when no profile in the chain sets the key.
# The colour is default_filament_colour: the filament tab shows that one, filament_colour is
# the colour of a slot in the project (Tab.cpp, TabFilament::build).
EDITABLE_FIELDS = [
    ("filament_vendor", "general", "text", "(Undefined)", None, None),
    ("default_filament_colour", "general", "colour", "", None, None),
    ("nozzle_temperature", "temperatures", "int", "200", 0, 1500),
    ("nozzle_temperature_initial_layer", "temperatures", "int", "200", 0, 1500),
    ("hot_plate_temp", "temperatures", "int", "45", 0, 300),
    ("hot_plate_temp_initial_layer", "temperatures", "int", "45", None, 300),
    ("filament_flow_ratio", "flow", "float", "1", 0, 2),
    ("filament_max_volumetric_speed", "flow", "float", "2", 0, None),
    ("filament_density", "material", "float", "0", 0, None),
    ("filament_diameter", "material", "float", "1.75", 0, None),
    ("filament_cost", "material", "float", "0", 0, None),
    ("fan_min_speed", "cooling", "float", "20", 0, 100),
    ("fan_max_speed", "cooling", "float", "100", 0, 100),
]
EDITABLE_DEFAULTS = {f[0]: f[3] for f in EDITABLE_FIELDS}
VALUE_KEYS = CORE_VALUES + [f[0] for f in EDITABLE_FIELDS if f[0] not in CORE_VALUES]


@dataclass
class OwnState:
    """How the slicer loads an own profile."""
    parent: Profile | None  # None for a root profile or a missing parent
    via: str | None         # exact, renamed, generic; None without parent
    problem: str | None     # why the slicer does not load it, see STATUS_OF_PROBLEM

    @property
    def loaded(self) -> bool:
        return self.problem is None


# Own profiles the slicer does not load: "orphaned" if the parent is missing, "ignored" otherwise.
# "unresolved": the parent may sit in a package OrcaOne cannot read, so whether the slicer loads the
# profile is unknown; OrcaOne must not offer it for cleaning up (FINDINGS, .opc rules).
STATUS_OF_PROBLEM = {"parent_missing": "orphaned", "parent_abstract": "orphaned",
                     "parent_unreadable": "unresolved",
                     "invalid_json": "ignored", "bad_version": "ignored", "wrong_type": "ignored",
                     "name_taken": "ignored"}


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def strings(value) -> list:
    """as_list without entries that are no text: a file edited by hand may hold anything."""
    return [v for v in as_list(value) if isinstance(v, str)]


def first(value):
    values = as_list(value)
    return values[0] if values else None


class Resolver:
    def __init__(self, scan: Scan):
        self.scan = scan
        self.snorca = scan.snorca
        self._chains = {}
        self._layers = {}
        by_name = sorted(scan.profiles.values(), key=lambda p: p.name)
        # What the slicer's preset collections hold after loading the vendors: selectable
        # system profiles only (FINDINGS 4.5). renamed_from maps old names, first one wins
        # (update_map_system_profile_renamed inserts into a std::map).
        self.collection = {kind: {} for kind in KINDS}
        self.renamed = {kind: {} for kind in KINDS}
        for p in by_name:
            if p.selectable:
                self.collection[p.kind].setdefault(p.name, p)
                for old in p.renamed_from:
                    self.renamed[p.kind].setdefault(old, p.name)
        self.own_state = {}
        self.missing_parent = "parent_unreadable" if any(pk.error for pk in scan.packages) else "parent_missing"
        self._load_own()

    # ------------------------------------------------------------ loading own profiles

    def _find_preset2(self, kind: str, name: str, loaded: dict, auto_match: bool = True):
        found = loaded.get(name)
        if found:
            return found, "exact"
        target = self.renamed[kind].get(name)
        if target and target in loaded:
            return loaded[target], "renamed"
        if auto_match and "Generic" in name:
            alternative = _GENERIC.sub(r"Generic \2 @System", name)
            found, _ = self._find_preset2(kind, alternative, loaded, False)
            if found:
                return found, "generic"
        return None, None

    def _load_own(self) -> None:
        loaded = {kind: dict(self.collection[kind]) for kind in KINDS}
        current_pass, added = None, []
        for p in self.scan.own:
            if p.load_pass != current_pass:
                # Profiles of one folder only see what was loaded before that folder.
                for q in added:
                    loaded[q.kind].setdefault(q.name, q)
                current_pass, added = p.load_pass, []
            parent, via = self._find_preset2(p.kind, p.inherits, loaded[p.kind]) if p.inherits else (None, None)
            problem = p.problem
            if problem is None and (p.name in loaded[p.kind] or p.name == DEFAULT_NAMES[p.kind]):
                problem = "name_taken"
            if problem is None and p.inherits and parent is None and not (self.snorca and p.custom_defined):
                # Snapmaker Orca still loads it with defaults if it is marked is_custom_defined.
                abstract = any(q.kind == p.kind and q.name == p.inherits and not q.selectable
                               for q in self.scan.profiles.values())
                problem = "parent_abstract" if abstract else self.missing_parent
            self.own_state[id(p)] = OwnState(parent, via, problem)
            if problem is None:
                added.append(p)

    def own_profiles(self, kind: str | None = None) -> list:
        return [p for p in self.scan.own if kind is None or p.kind == kind]

    def state(self, p: Profile) -> OwnState | None:
        return self.own_state.get(id(p))

    def loaded(self, p: Profile) -> bool:
        """Whether the slicer shows the profile at all."""
        if p.package:
            return p.selectable
        state = self.state(p)
        return bool(state and state.loaded and p.selectable)

    # ------------------------------------------------------------ chains and values

    def parent(self, p: Profile) -> Profile | None:
        if not p.package:
            state = self.state(p)
            return state.parent if state else None
        if not p.inherits:
            return None
        for package in (p.package, LIBRARY) if p.kind == "filament" else (p.package,):
            found = self.scan.profiles.get((package, p.kind, p.inherits))
            if found:
                return found
        return None

    def chain(self, p: Profile) -> tuple[list, bool]:
        """Parents from the direct one to the root; complete is False if a parent is missing
        or the chain runs in a circle."""
        key = id(p)
        if key not in self._chains:
            chain, seen, current, complete = [], {(p.package, p.name)}, p, True
            while True:
                parent = self.parent(current)
                if parent is None:
                    # A missing parent breaks the chain, unless the slicer loads the profile as
                    # a root anyway (is_custom_defined in Snapmaker Orca).
                    if current.inherits and not (not current.package and self.state(current)
                                                 and self.state(current).problem is None):
                        complete = False
                    break
                if (parent.package, parent.name) in seen:
                    complete = False
                    break
                chain.append(parent)
                seen.add((parent.package, parent.name))
                current = parent
            self._chains[key] = (chain, complete)
        return self._chains[key]

    def layers(self, p: Profile) -> list:
        """p and everything its values stand on, highest priority first: p itself, then its
        includes (the last one listed wins, load_vendor_preset), each with what it stands on,
        then the parent chain the same way. Includes stay within the profile's package; one not
        found there is skipped, as the slicer logs it and loads without it. Approximation: an
        included base contributes its resolved values, the slicer takes its diff against the
        default — a value it shares with the default would not shadow a lower layer there."""
        key = id(p)
        if key not in self._layers:
            out, seen = [], {key}

            def visit(q: Profile) -> None:
                out.append(q)
                for name in reversed(q.includes):
                    inc = self.scan.profiles.get((q.package, q.kind, name))
                    if inc is not None and id(inc) not in seen:
                        seen.add(id(inc))
                        visit(inc)
                parent = self.parent(q)
                if parent is not None and id(parent) not in seen:
                    seen.add(id(parent))
                    visit(parent)

            visit(p)
            self._layers[key] = out
        return self._layers[key]

    def lookup(self, p: Profile, key: str):
        """(value, source profile) of key: the first profile in p and its chain that sets it."""
        for q in self.layers(p):
            if key in q.values:
                return q.values[key], q
        return None, None

    def value(self, p: Profile, key: str):
        return self.lookup(p, key)[0]

    def value_entry(self, p: Profile, key: str, chain=None, complete=None) -> dict:
        """Effective value of key, whether p sets it itself, and where it comes from.

        A value an own profile sets itself also carries "inherited", the value its template
        gives: the filament editor shows it as placeholder and goes back to it."""
        if chain is None:
            chain, complete = self.chain(p)
        layers = self.layers(p)
        source = next((q for q in layers if key in q.values), None)
        if source is None:
            if not complete or key not in EDITABLE_DEFAULTS:
                # A broken chain is not loaded by the slicer at all, so there is no effective value.
                return {"value": None, "own": False, "source": None}
            # No profile sets it: the slicer takes the PrintConfigDef default (FINDINGS 4.5).
            return {"value": EDITABLE_DEFAULTS[key], "own": False, "source": None, "default": True}
        items = as_list(source.values[key])
        entry = {"value": items[0] if items else None, "own": source is p, "source": source.name}
        if len(items) > 1:
            # Snapmaker Orca keeps a second value for the high-flow hotend (FINDINGS 4.4).
            entry["high_flow"] = items[1]
        if source is p and p.origin_kind == "user" and complete:
            below = next((q for q in layers[1:] if key in q.values), None)
            if below is None and chain and key not in EDITABLE_DEFAULTS:
                inherited = {"value": None, "source": None}
            elif below is None:
                # A root profile has no template, only the slicer default.
                inherited = {"value": EDITABLE_DEFAULTS.get(key), "source": None, "default": True}
            else:
                bitems = as_list(below.values[key])
                inherited = {"value": bitems[0] if bitems else None, "source": below.name}
                if len(bitems) > 1:
                    inherited["high_flow"] = bitems[1]
            entry["inherited"] = inherited
        return entry

    # ------------------------------------------------------------ compatibility

    def compatible_printers(self, p: Profile) -> list:
        printers = strings(self.value(p, "compatible_printers"))
        if not printers and not self.snorca and not p.package and p.kind == "filament" and not p.inherits:
            # OrcaSlicer main binds an own root filament with an empty list to the text after
            # "@" of its file name, and saves that (FINDINGS 4.4).
            stem = p.file.rsplit("/", 1)[-1][:-len(".json")] if p.file else p.name
            at = stem.find("@")
            if 0 <= at < len(stem) - 1:
                return [stem[at + 1:]]
        return printers

    def condition(self, p: Profile) -> str:
        value = first(self.value(p, "compatible_printers_condition"))
        return value.strip() if isinstance(value, str) else ""

    def fits(self, printer: Profile, p: Profile) -> str | None:
        """"yes", "conditional" or None. The condition is not evaluated: it decides alone if the
        list is empty, and a parser error counts as compatible (FINDINGS 4.6)."""
        printers = self.compatible_printers(p)
        if not printers and self.condition(p):
            return "conditional"
        if not printers or printer.name in printers or (not printer.package and printer.inherits in printers):
            return "yes"
        return None

    def library_exclusions(self) -> dict:
        """library profile name -> {printer name: [names of the profiles that displace it]}.

        Library filaments with an empty printer list are keyed by alias (a later name
        overwrites an earlier one, like the slicer's std::map); every other system filament
        with the same alias and an explicit printer list excludes those printers. Snapmaker
        Orca only counts other packages, OrcaSlicer main also the library itself."""
        filaments = sorted(self.collection["filament"].values(), key=lambda p: p.name)
        by_alias = {}
        for p in filaments:
            if p.package == LIBRARY and not self.compatible_printers(p):
                by_alias[p.alias] = p.name
        excluded = {}
        for p in filaments:
            if self.snorca and p.package == LIBRARY:
                continue
            printers = self.compatible_printers(p)
            target = by_alias.get(p.alias)
            if not printers or not target or target == p.name:
                continue
            for printer in printers:
                excluded.setdefault(target, {}).setdefault(printer, []).append(p.name)
        return excluded

    def displaced_by(self, excluded: dict, p: Profile, printer: Profile) -> list:
        by = excluded.get(p.name, {}).get(printer.name)
        if not by and not self.snorca:
            # OrcaSlicer main also matches the printer's parent (is_compatible_with_printer).
            by = excluded.get(p.name, {}).get(printer.inherits)
        return by or []

    # ------------------------------------------------------------ visibility

    def filament_list(self) -> list:
        value = self.scan.conf.get("filaments")
        return [n for n in value if isinstance(n, str)] if isinstance(value, list) else []

    def in_list(self, p: Profile, names: set) -> bool:
        """Visibility of a system filament: no list means everything visible, otherwise the
        name or one of its old names must be in it (FINDINGS 4.6)."""
        return not names or p.name in names or any(n in names for n in p.renamed_from)

    def installed_printers(self) -> list:
        """Selectable system printers whose model and variant are switched on in "models",
        grouped by model in the order of the .conf."""
        out = []
        models = self.scan.conf.get("models")
        for entry in models if isinstance(models, list) else []:
            if not isinstance(entry, dict):
                continue
            package, model = entry.get("vendor", ""), entry.get("model", "")
            if not isinstance(package, str) or not isinstance(model, str):
                continue
            variants = split_list(entry.get("nozzle_diameter", ""))
            printers = []
            for p in self.collection["machine"].values():
                if p.package != package:
                    continue
                variant = first(self.value(p, "printer_variant"))
                if first(self.value(p, "printer_model")) == model and variant in variants:
                    printers.append((variants.index(variant), variant, p))
            printers.sort(key=lambda t: t[0])
            out.append({"model": model, "package": package, "printers": [(v, p) for _, v, p in printers]})
        return out

    def is_helper(self, p: Profile) -> bool:
        """Own profile without own settings on top of a library profile: the helper that
        unlocks the library in Snapmaker Orca (FINDINGS 4.7, way B)."""
        if p.package or p.kind != "filament" or set(p.values) - BINDING_KEYS:
            return False
        parent = self.parent(p)
        return parent is not None and parent.origin_kind == "library"


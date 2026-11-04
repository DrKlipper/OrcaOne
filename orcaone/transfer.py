"""A profile of one installation as a new own profile of another one (page "Übertragen").

The rules follow FINDINGS, "Übertragung OrcaSlicer → SnOrca":
- Between two different slicers the copy is a root profile: every value of the source's chain,
  no template. The target may lack the templates, or have other values under their names, and a
  copy must not change when the target's templates change. Between two installations of the same
  slicer an own profile stays the child of its template, if the target has it.
- Every value the target can take (orcaone/options.json): a key it knows for this kind, as a string
  or a list as the target defines it, since a value it cannot read makes it delete the profile;
  and an old name it translates while loading (handle_legacy, e.g. wall_infill_order to
  wall_sequence), as it is. A key it does not know or ignores as obsolete goes, the plan names it.
  A choice it does not know stays: the target translates it or takes its default, both without
  harm. "nil" (the printer's value) only where the target allows it.
- Some keys hold two values in one list: standard and high-flow hotend in Snapmaker Orca
  (["265", "280"]), extruder variants in OrcaSlicer 2.5. The other slicer has no place for the
  second one, so between different slicers such a key keeps its first value, the plan names it;
  Snapmaker Orca then takes that value for both hotends.
- The printers: those of the source's list the target has, by name. An empty list stays empty,
  i.e. every printer. If none of them is there, the copy is refused.
- The name: an own profile keeps its name. A system profile gets its source in brackets, without
  "@System" or "@base": "Elegoo PLA (Orca)". An own file with the name of a system profile stays
  unloaded once the target ships that profile, and the brackets show where it came from.
  OrcaSlicer binds an own root filament with an empty printer list to the text after "@"
  (FINDINGS 4.4), so there such a name has no "@".
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .resolver import Resolver, as_list
from .scanner import META_KEYS

OPTIONS = json.loads((Path(__file__).parent / "options.json").read_text(encoding="utf-8"))
KINDS = ("filament", "process")
# Written by the planner, or not copied: the list of processes a filament fits names processes
# of the source, and FINDINGS 4.6 found no slicer using it.
OWN_KEYS = META_KEYS | {"filament_settings_id", "print_settings_id", "printer_settings_id",
                        "compatible_printers", "compatible_prints", "compatible_prints_condition"}
SHORT = {"Snapmaker_Orca": "SnOrca", "OrcaSlicer": "Orca"}


@dataclass
class Copy:
    name: str                 # proposed name in the target; the planner makes it unique
    data: dict                # values without name, from, version and settings id
    parent: object = None     # template in the target (a child), None for a root profile
    base_id: str = ""
    dropped: list = field(default_factory=list)       # keys the target cannot take
    cut: list = field(default_factory=list)           # lists cut to their first value
    printers_left: list = field(default_factory=list)  # printers of the source the target lacks


class TransferError(Exception):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def target_printers(res: Resolver) -> set:
    return set(res.collection["machine"]) | {p.name for p in res.own_profiles("machine") if res.loaded(p)}


def adapt(values: dict, target: dict, kind: str, same_app: bool) -> tuple:
    """values as the target reads them; the keys that had to go, and those cut to one value.
    target: the entry of the target slicer in orcaone/options.json."""
    specs, legacy = target["options"][kind], set(target["legacy"])
    out, dropped, cut = {}, [], []
    for key, value in values.items():
        spec = specs.get(key)
        items = [v for v in as_list(value) if isinstance(v, str)]
        if spec is None and key not in legacy or not items:
            dropped.append(key)
            continue
        if not same_app and len(items) > 1:
            # Only worth a word if the second value differed from the first.
            if len(set(items)) > 1:
                cut.append(key)
            items = items[:1]
        if spec is None:
            out[key] = items if isinstance(value, list) else items[0]
        elif "nil" in items and not spec["nullable"]:
            dropped.append(key)
        else:
            out[key] = items if spec["type"].endswith("s") else items[0]
    return out, sorted(dropped), sorted(cut)


def convert(source_res: Resolver, source_app: str, target_res: Resolver, target_app: str, kind: str, name: str) -> Copy:
    """The copy of the source profile name for the target. Raises TransferError."""
    found = [p for p in source_res.scan.of_kind(kind) if p.name == name and p.selectable]
    found += [p for p in source_res.own_profiles(kind) if p.name == name and source_res.loaded(p)]
    if not found:
        raise TransferError("unknown_profile", name=name)
    p = found[0]
    chain, complete = source_res.chain(p)
    if not complete:
        raise TransferError("profile_invalid", name=name)
    same_app = source_app == target_app
    own = not p.package

    # Printers of the target by the source's names.
    wanted = source_res.compatible_printers(p)
    have = target_printers(target_res)
    printers = [n for n in wanted if n in have]
    if wanted and not printers:
        raise TransferError("no_target_printer", name=name)

    # A child of the same template where that is safe, else a root profile with every value.
    # With includes (OrcaSlicer 2.5) the child form would lose their layers: flatten then.
    parent = source_res.parent(p) if own else None
    target_parent = target_res.collection[kind].get(parent.name) if same_app and parent is not None else None
    if target_parent is not None and target_res.chain(target_parent)[1] and not p.includes:
        values = dict(p.values)
    else:
        target_parent, values = None, {}
        for q in reversed(source_res.layers(p)):
            values.update(q.values)
    data, dropped, cut = adapt({k: v for k, v in values.items() if k not in OWN_KEYS},
                               OPTIONS[target_app], kind, same_app)
    # A root profile names its printers; a child only if the source child did.
    if target_parent is None or "compatible_printers" in p.values:
        data["compatible_printers"] = printers
    if target_parent is None:
        condition = source_res.value(p, "compatible_printers_condition")
        data["compatible_printers_condition"] = condition if isinstance(condition, str) else ""

    # The name, see above.
    new_name = p.name
    if not own:
        stem = p.name[:-len(" @System")] if p.name.endswith(" @System") else \
            p.name[:-len(" @base")] if p.name.endswith(" @base") else p.name
        new_name = f"{stem} ({SHORT[source_app]})"
    if target_app == "OrcaSlicer" and kind == "filament" and target_parent is None and not printers and "@" in new_name:
        stem, _, rest = new_name.partition("@")
        new_name = f"{stem.strip()} ({rest.strip()})"

    return Copy(name=new_name, data=data, parent=target_parent,
                base_id=target_parent.setting_id if target_parent is not None else "",
                dropped=dropped, cut=cut, printers_left=[n for n in wanted if n not in have])

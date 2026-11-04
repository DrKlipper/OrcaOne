import json
from pathlib import Path

import pytest

from conftest import FIXTURES, copy_fixture
from orcaone import scanner
from orcaone.resolver import Resolver
from orcaone.scanner import LIBRARY, Profile, Scan
from test_opc import build_cache_v2
from test_scanner import write_profile

U1_02, U1_04 = "Snapmaker U1 (0.2 nozzle)", "Snapmaker U1 (0.4 nozzle)"


@pytest.fixture(scope="module")
def snorca():
    return Resolver(scanner.scan(FIXTURES / "snorca", "Snapmaker_Orca"))


def names(profiles):
    return [p.name for p in profiles]


def own(res, name):
    return next(p for p in res.scan.own if p.name == name)


def test_chains_of_the_acceptance_checklist(snorca):
    """FINDINGS, "Abnahme-Checkliste Resolver" 1, 6 and 8."""
    sunlu = snorca.scan.profiles[(LIBRARY, "filament", "SUNLU PLA+ @System")]
    chain, complete = snorca.chain(sunlu)
    assert complete and names(chain) == ["SUNLU PLA+ @base", "fdm_filament_pla", "fdm_filament_common"]
    assert snorca.value_entry(sunlu, "nozzle_temperature") == {"value": "220", "own": False, "source": "fdm_filament_pla"}
    assert snorca.value_entry(sunlu, "filament_cost")["source"] == "SUNLU PLA+ @base"
    # Keys no profile sets come from PrintConfigDef, marked as such.
    assert snorca.value_entry(sunlu, "default_filament_colour") == {"value": "", "own": False, "source": None, "default": True}

    aliz = snorca.scan.profiles[(LIBRARY, "filament", "AliZ PETG-CF @System")]
    assert names(snorca.chain(aliz)[0]) == ["AliZ PETG-CF @base", "AliZ PETG @base", "fdm_filament_pet", "fdm_filament_common"]
    assert snorca.value(aliz, "nozzle_temperature") == ["275"]

    printer = snorca.scan.profiles[("Snapmaker", "machine", U1_04)]
    assert names(snorca.chain(printer)[0]) == ["fdm_U1", "fdm_toolchanger", "fdm_klipper"]
    assert snorca.value(printer, "printable_height") == "270.05"
    assert snorca.lookup(printer, "gcode_flavor") == ("klipper", snorca.scan.profiles[("Snapmaker", "machine", "fdm_U1")])


def test_high_flow_value(snorca):
    abs04 = snorca.scan.profiles[("Snapmaker", "filament", "Snapmaker ABS @U1 0.4 nozzle")]
    entry = snorca.value_entry(abs04, "nozzle_temperature")
    assert (entry["value"], entry["high_flow"]) == ("265", "280")


def test_own_profiles_of_the_fixture(snorca):
    mein_pla, altes_petg, mein_u1 = own(snorca, "Mein PLA"), own(snorca, "Altes PETG"), own(snorca, "Mein U1")
    state = snorca.state(mein_pla)
    assert (state.parent.name, state.via, state.problem) == ("Snapmaker PLA Basic @U1", "exact", None)
    assert snorca.value_entry(mein_pla, "nozzle_temperature") == {
        "value": "215", "own": True, "source": "Mein PLA",
        "inherited": {"value": "220", "source": "Snapmaker PLA Basic @U1"}}
    assert snorca.state(altes_petg).problem == "parent_missing" and snorca.chain(altes_petg) == ([], False)
    assert snorca.loaded(mein_u1) and snorca.parent(mein_u1).name == U1_04


def test_library_exclusion_in_snorca(snorca):
    excluded = snorca.library_exclusions()
    # Snapmaker brings "Generic PLA" for the U1, so the library profile goes (FINDINGS 4.6).
    assert excluded == {"Generic PLA @System": {U1_04: ["Generic PLA"], U1_02: ["Generic PLA @U1 0.2 nozzle"]}}


def test_installed_printers(snorca):
    [model] = snorca.installed_printers()
    assert (model["model"], model["package"]) == ("Snapmaker U1", "Snapmaker")
    assert [(v, p.name) for v, p in model["printers"]] == [
        ("0.2", U1_02), ("0.4", U1_04), ("0.6", "Snapmaker U1 (0.6 nozzle)"), ("0.8", "Snapmaker U1 (0.8 nozzle)")]


def test_find_preset2_and_load_order(tmp_path):
    data = copy_fixture("snorca", tmp_path / "snorca")
    filament = data / "user" / "default" / "filament"

    def profile(name, folder=filament, **values):
        write_profile(folder, name, {"name": name, "version": "2.3.3.3", "from": "User", **values})

    profile("Umbenannt", inherits="My Generic PLA")        # renamed_from of Generic PLA @System
    profile("Ersatz", inherits="Generic PLA @Irgendwo")    # Generic fallback
    profile("Wurzel", folder=filament / "base")
    profile("Kind", inherits="Wurzel")                     # base/ was loaded before
    profile("Enkel", inherits="Kind")                      # same folder: not loaded yet
    profile("Abstrakt", inherits="fdm_filament_pla")
    profile("Snapmaker PLA Basic @U1", inherits="Snapmaker PLA Basic @U1 base")
    profile("Eigene Wurzel", inherits="Gibt es nicht", is_custom_defined="1")

    res = Resolver(scanner.scan(data, "Snapmaker_Orca"))
    got = {p.name: (res.state(p).parent.name if res.state(p).parent else None, res.state(p).via, res.state(p).problem)
           for p in res.scan.own}
    assert got["Umbenannt"] == ("Generic PLA @System", "renamed", None)
    assert got["Ersatz"] == ("Generic PLA @System", "generic", None)
    assert got["Wurzel"] == (None, None, None)
    assert got["Kind"] == ("Wurzel", "exact", None)
    assert got["Enkel"] == (None, None, "parent_missing")
    assert got["Abstrakt"] == (None, None, "parent_abstract")
    assert got["Snapmaker PLA Basic @U1"][2] == "name_taken"
    # Snapmaker Orca loads a profile marked is_custom_defined without its parent.
    assert got["Eigene Wurzel"] == (None, None, None)
    assert res.chain(own(res, "Eigene Wurzel")) == ([], True)
    assert names(res.chain(own(res, "Kind"))[0]) == ["Wurzel"]


def test_orca_binds_an_own_root_filament_to_the_name_after_the_at(tmp_path):
    data = copy_fixture("orca", tmp_path / "orca")
    base = data / "user" / "default" / "filament" / "base"
    write_profile(base, f"Mein PLA @{U1_04}", {"name": "egal", "version": "2.5.0.0", "compatible_printers": []})
    res = Resolver(scanner.scan(data, "OrcaSlicer"))
    [p] = res.scan.own
    assert res.compatible_printers(p) == [U1_04]


def test_orca_excludes_via_the_parent_of_an_own_printer(tmp_path):
    data = copy_fixture("orca", tmp_path / "orca")
    write_profile(data / "user" / "default" / "machine", "Mein U1",
                  {"name": "Mein U1", "version": "2.5.0.0", "inherits": U1_04, "printer_settings_id": "Mein U1"})
    res = Resolver(scanner.scan(data, "OrcaSlicer"))
    excluded = res.library_exclusions()
    [mine] = res.scan.own
    system = res.scan.profiles[("Snapmaker", "machine", U1_04)]
    library = [p for p in res.collection["filament"].values() if p.package == LIBRARY]
    by_system = {p.name for p in library if res.displaced_by(excluded, p, system)}
    by_own = {p.name for p in library if res.displaced_by(excluded, p, mine)}
    assert len(by_system) == 23 and by_own == by_system
    # In Orca main Snapmaker brings no Generic PLA for the U1 (FINDINGS 4.6).
    assert "Generic PLA @System" not in by_system


def resolver_with(*profiles, snorca=True):
    scan = Scan(data_dir=Path("."), app_key="Snapmaker_Orca" if snorca else "OrcaSlicer", conf={}, conf_file=None,
                conf_size=0, active_folder="default")
    for p in profiles:
        if p.package:
            scan.profiles[(p.package, p.kind, p.name)] = p
        else:
            scan.own.append(p)
    return Resolver(scan)


def test_compatibility_rules():
    printer = Profile("P", "machine", "V")
    other = Profile("Q", "machine", "V")
    mine = Profile("Mein P", "machine", "", inherits="P")
    any_printer = Profile("F1", "filament", "V", values={"compatible_printers": []})
    listed = Profile("F2", "filament", "V", values={"compatible_printers": ["P"]})
    conditional = Profile("F3", "filament", "V", values={"compatible_printers": [],
                                                           "compatible_printers_condition": "nozzle_diameter[0]==0.4"})
    # With a list the condition does not count (FINDINGS 4.6).
    both = Profile("F4", "filament", "V", values={"compatible_printers": ["Q"], "compatible_printers_condition": "x"})
    res = resolver_with(printer, other, mine, any_printer, listed, conditional, both)
    assert [res.fits(printer, f) for f in (any_printer, listed, conditional, both)] == ["yes", "yes", "conditional", None]
    assert res.fits(other, listed) is None
    # An own printer takes what its direct parent takes.
    assert res.fits(mine, listed) == "yes"


def test_filaments_list_has_three_states(tmp_path):
    for value in ("missing", None, []):
        data = copy_fixture("snorca", tmp_path / f"snorca-{value}")
        conf_path = data / "Snapmaker_Orca.conf"
        conf = json.loads(conf_path.read_text(encoding="utf-8"))
        if value == "missing":
            del conf["filaments"]
        else:
            conf["filaments"] = value
        conf_path.write_text(json.dumps(conf, indent=4) + "\n", encoding="utf-8")
        res = Resolver(scanner.scan(data, "Snapmaker_Orca"))
        sunlu = res.scan.profiles[(LIBRARY, "filament", "SUNLU PLA+ @System")]
        assert res.filament_list() == [] and res.in_list(sunlu, set()), value
    res = Resolver(scanner.scan(FIXTURES / "snorca", "Snapmaker_Orca"))
    names_in_list = set(res.filament_list())
    assert not res.in_list(res.scan.profiles[(LIBRARY, "filament", "SUNLU PLA+ @System")], names_in_list)
    assert res.in_list(res.scan.profiles[("Snapmaker", "filament", "Snapmaker PLA Basic @U1")], names_in_list)


def _opc_installation(tmp_path, filament):
    """An OrcaSlicer 2.5 installation: system profiles only in a cache of CACHE_VERSION 2."""
    data_dir = tmp_path / "OrcaSlicer"
    (data_dir / "system").mkdir(parents=True)
    (data_dir / "system" / "TestMaker.opc").write_bytes(build_cache_v2(filament=filament))
    return Resolver(scanner.scan(data_dir, "OrcaSlicer"))


def test_includes_layer_under_the_own_values(tmp_path):
    """OrcaSlicer 2.5 (load_vendor_preset): own values > includes, later first > earlier > parent."""
    res = _opc_installation(tmp_path, [
        ("Elternprofil", {"x": "vom Eltern", "farbe": "grau"}, "", [], "true"),
        ("Erste", {"x": "erste", "y": "erste"}, "", [], "false"),
        ("Zweite", {"y": "zweite"}, "", [], "false"),
        ("Kind", {"eigen": "kind"}, "Elternprofil", ["Erste", "Zweite"], "true"),
    ])
    p = res.collection["filament"]["Kind"]
    assert p.includes == ["Erste", "Zweite"]
    assert res.value(p, "eigen") == "kind"       # the profile's own value
    assert res.value(p, "y") == "zweite"         # the later include wins over the earlier
    assert res.value(p, "x") == "erste"          # an include wins over the parent
    assert res.value(p, "farbe") == "grau"       # the parent fills what no include sets


def test_a_missing_include_is_skipped(tmp_path):
    """The slicer logs a missing include and loads without it (load_vendor_preset)."""
    res = _opc_installation(tmp_path, [("Kind", {"a": "1"}, "", ["Gibt es nicht"], "true")])
    p = res.collection["filament"]["Kind"]
    assert res.value(p, "a") == "1" and res.chain(p)[1]

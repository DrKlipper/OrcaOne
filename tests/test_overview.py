import json
from datetime import datetime
from pathlib import Path

import pytest

from conftest import BUNDLE, FIXTURES, add_bundle, copy_fixture
from orcaone import camera, instances, overview, settings
from orcaone.conf import dump_conf, read_conf
from orcaone.guard import SlicerProcess
from test_opc import patched

U1_02, U1_04 = "Snapmaker U1 (0.2 nozzle)", "Snapmaker U1 (0.4 nozzle)"


def build(path, processes=()):
    instance = instances.load_instance(path.resolve(), "manual")
    return overview.build_instance(instance, list(processes), manual=True)


@pytest.fixture
def snorca(fake_home):
    # fake_home keeps the web view folders out of the real home.
    return build(FIXTURES / "snorca")


@pytest.fixture
def orca(fake_home):
    return build(FIXTURES / "orca")


def by_name(data):
    return {f["name"]: f for f in data["filaments"]}


def on(data, printer, status="visible", kind=None):
    return {f["name"] for f in data["filaments"] if f["printers"].get(printer, {}).get("status") == status
            and (kind is None or (f["origin_kind"] == "user") == (kind == "user"))}


def test_snorca_what_the_slicer_shows(snorca):
    """docs/STAND.md, reported on 22.09.: U1 0.4 shows ABS and PLA from Snapmaker."""
    assert on(snorca, U1_04, kind="system") == {"Snapmaker ABS @U1 0.4 nozzle", "Snapmaker PLA Basic @U1"}
    assert on(snorca, U1_04, kind="user") == {"Mein PLA"}
    assert on(snorca, U1_02) == {"Snapmaker ABS @U1 0.2 nozzle"}
    assert snorca["stats"]["per_printer"][U1_04] == {"visible": 3, "hidden": 5, "displaced": 1, "processes": 2}


def test_snorca_library(snorca):
    filaments = by_name(snorca)
    # SUNLU is hidden only by the list, nothing displaces it (FINDINGS 4.6, 4.7).
    for name in ("SUNLU PLA+ @System", "SUNLU PLA Marble @System"):
        assert {e["status"] for e in filaments[name]["printers"].values()} == {"hidden"}
        assert all(e["unlockable"] for e in filaments[name]["printers"].values())
    generic = filaments["Generic PLA @System"]["printers"]
    assert generic[U1_04] == {"status": "displaced", "displaced_by": ["Generic PLA"]}
    assert generic[U1_02] == {"status": "displaced", "displaced_by": ["Generic PLA @U1 0.2 nozzle"]}
    sunlu = filaments["SUNLU PLA+ @System"]
    assert (sunlu["chain"], sunlu["chain_complete"], sunlu["origin_kind"], sunlu["package"]) == (
        ["SUNLU PLA+ @base", "fdm_filament_pla", "fdm_filament_common"], True, "library", "OrcaFilamentLibrary")
    assert sunlu["values"]["filament_cost"] == {"value": "18.99", "own": False, "source": "SUNLU PLA+ @base"}
    hidden = next(w for w in snorca["warnings"] if w["code"] == "library_hidden")
    assert "SUNLU PLA+ @System" in hidden["names"]


def test_snorca_own_profiles(snorca):
    filaments = by_name(snorca)
    mine = filaments["Mein PLA"]
    assert (mine["origin_kind"], mine["file"], mine["in_list"]) == ("user", "user/default/filament/Mein PLA.json", True)
    assert mine["values"]["nozzle_temperature"]["inherited"] == {"value": "220", "source": "Snapmaker PLA Basic @U1"}
    # Account and cloud ids of the .info stay in the backend.
    assert mine["info"] == {"sync_info": "", "updated_time": 1758520000}
    orphan = filaments["Altes PETG"]
    assert (orphan["status"], orphan["problem"], orphan["inherits"], orphan["printers"]) == (
        "orphaned", "parent_missing", "Snapmaker PETG @U1 alt", {})
    warning = next(w for w in snorca["warnings"] if w["code"] == "orphaned")
    assert (warning["names"], warning["problem"], warning["level"]) == (["Altes PETG"], "parent_missing", "error")
    assert snorca["slicer_page"]["tree"][0]["name"] == "user"


def test_snorca_own_printer(snorca):
    own_model = snorca["models"][-1]
    assert (own_model["model"], own_model["own"], own_model["based_on"], own_model["origin"]) == (
        "Mein U1", True, "Snapmaker U1", "Snapmaker")
    # An own printer takes the filaments of its direct parent (FINDINGS 4.6).
    assert on(snorca, "Mein U1") == on(snorca, U1_04)
    page = snorca["printers_page"]
    [mine] = page["own"]
    assert (mine["visible"], mine["based_on_found"], mine["package"], mine["origin"], mine["cover"]) == (
        True, True, "Snapmaker", "own", "assets/printer-snapmaker-u1.svg")
    [card] = page["system"]
    assert card["own_printers"] == ["Mein U1"] and card["drops_package"] is False
    assert page["default_printer"] == {"name": U1_04, "exists": True, "own": False, "model": "Snapmaker U1",
                                       "variant": "0.4", "cover": "assets/printer-snapmaker-u1.svg"}


def test_snorca_dead_orca_presets_entry(snorca):
    """docs/STAND.md: the entry "Default Printer" was not found before."""
    page = snorca["printers_page"]
    assert page["remembered"] == 3
    assert page["dead_entries"] == [{"machine": "Default Printer", "process": "Default Setting",
                                     "filaments": ["AliZ PLA @System"], "reason": "default_printer"}]


def test_snorca_slicer_and_backups_page(snorca, fake_home):
    page = snorca["slicer_page"]
    assert (page["slicer"], page["version"], page["source"], page["user_folder"]) == (
        "Snapmaker Orca", "2.4.0", "manual", "user/default")
    assert page["conf"] == {"file": "Snapmaker_Orca.conf", "size": 6650, "indent": "spaces", "indent_width": 4,
                            "checksum": False, "sections": 9, "credentials": {}}
    assert page["system_refresh"] == {"value": True, "code": "every_start"}
    notes = {p["name"]: p["note"] for p in page["packages"]}
    assert notes == {"OrcaFilamentLibrary": "library", "Snapmaker": "installed_for"}
    assert page["profile_counts"]["filament"] == {"system": 24, "system_selectable": 11, "own": 2}
    backups = snorca["backups_page"]
    assert (backups["backups"], backups["count"], backups["total_size"]) == ([], 0, 0)
    assert backups["now"]["files"] == page["totals"]["backup_files"] > 0
    assert backups["location"] == str(settings.DATA_DIR / "backups" / snorca["id"])


def test_snorca_top_level(snorca):
    assert (snorca["slicer"], snorca["app_key"], snorca["kind"], snorca["storage"]) == (
        "Snapmaker Orca", "Snapmaker_Orca", "snorca", "json")
    assert (snorca["running"], snorca["running_reason"], snorca["manual"]) == (False, None, True)
    assert snorca["filament_list"] == {"mode": "list", "count": 13}
    assert snorca["selected_printer"] == U1_04
    assert [w["name"] for w in snorca["without_printer"]][:2] == ["Snapmaker ABS", "Snapmaker ABS @0.2 nozzle"]
    json.dumps(snorca, allow_nan=False)


def test_running_slicer_is_reported(fake_home):
    process = SlicerProcess(4711, "Snapmaker_Orca", (FIXTURES / "snorca").resolve())
    data = build(FIXTURES / "snorca", [process])
    assert (data["running"], data["running_reason"]) == (True, {"code": "process", "pids": [4711], "lock": None})
    assert data["slicer_page"]["running"] is True


def test_orca(orca):
    assert (orca["kind"], orca["storage"], orca["version"]) == ("orca", "opc", "2.5.0-dev")
    models = {m["model"]: [p["variant"] for p in m["printers"]] for m in orca["models"]}
    assert models == {"Generic Klipper Printer": ["0.2", "0.4", "0.6", "0.8"],
                      "Snapmaker U1": ["0.2", "0.4", "0.4+0.6", "0.6", "0.8"]}
    # In Orca main Generic PLA @System stays for the U1, 23 other library profiles go (FINDINGS 4.6).
    assert "Generic PLA @System" in on(orca, U1_04)
    assert len(on(orca, U1_04, "displaced")) == 23
    assert orca["slicer_page"]["system_refresh"] == {"value": False, "code": "missing_only"}
    assert orca["slicer_page"]["conf"]["indent"] == "tab"
    assert orca["slicer_page"]["conf"]["credentials"] == {"access_code": 1}
    assert [c["drops_package"] for c in orca["printers_page"]["system"]] == [False, False]
    assert [p["format"] for p in orca["slicer_page"]["packages"]] == ["opc", "opc", "opc"]
    assert orca["warnings"] == [] and orca["printers_page"]["dead_entries"] == []


def test_unknown_opc_version_is_a_warning(fake_home, tmp_path):
    data_dir = copy_fixture("orca", tmp_path / "orca")
    cache = data_dir / "system" / "Snapmaker.opc"
    cache.write_bytes(patched(cache.read_bytes(), cache_version=3))
    data = build(data_dir)
    warning = next(w for w in data["warnings"] if w["code"] == "package_unreadable")
    assert (warning["names"], warning["problem"]) == (["Snapmaker"], "opc_unsupported_version")
    assert [m["model"] for m in data["models"] if m["printers"]] == ["Generic Klipper Printer"]
    package = next(p for p in data["slicer_page"]["packages"] if p["name"] == "Snapmaker")
    assert package["error"] == "opc_unsupported_version"


def test_profiles_on_an_unreadable_package_are_unresolved_not_orphaned(fake_home, tmp_path):
    """FINDINGS, .opc rules: with a package OrcaOne cannot read, own profiles whose parent is not
    found are "nicht auflösbar". They must not look orphaned and land in the clean-up."""
    data_dir = copy_fixture("orca", tmp_path / "orca")
    cache = data_dir / "system" / "Snapmaker.opc"
    cache.write_bytes(patched(cache.read_bytes(), cache_version=3))
    user = data_dir / "user" / "default"
    for kind, name, parent in (("filament", "Mein PLA", "Panchroma PLA @Snapmaker U1"),
                               ("machine", "Mein U1", "Snapmaker U1 (0.4 nozzle)")):
        (user / kind).mkdir(parents=True)
        (user / kind / f"{name}.json").write_text(json.dumps(
            {"name": name, "version": "2.5.0.0", "inherits": parent, "from": "User"}), encoding="utf-8")
    data = build(data_dir)
    filament = next(f for f in data["filaments"] if f["name"] == "Mein PLA")
    printer = next(p for p in data["printers_page"]["own"] if p["name"] == "Mein U1")
    assert (filament["status"], filament["problem"]) == ("unresolved", "parent_unreadable")
    assert (printer["status"], printer["problem"]) == ("unresolved", "parent_unreadable")
    assert {(w["code"], w["level"]) for w in data["warnings"] if w.get("problem") == "parent_unreadable"} == {
        ("unresolved", "warning")}
    # The last choice for the U1 may still be valid: no clean-up offer.
    assert data["printers_page"]["dead_entries"] == []


def test_build_all_finds_default_and_manual_instances(fake_home, monkeypatch, tmp_path):
    monkeypatch.setattr(overview.guard, "find_processes", lambda: [])
    monkeypatch.setattr(instances.platform, "system", lambda: "Linux")
    copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    manual = copy_fixture("orca", tmp_path / "portable" / "OrcaSlicer")
    instances.add_manual_path(str(manual))
    data = overview.build_all()
    assert [(i["kind"], i["source"], i["manual"]) for i in data["instances"]] == [
        ("snorca", "auto", False), ("orca", "manual", True)]
    assert [f["key"] for f in data["core_values"]][:2] == ["nozzle_temperature", "hot_plate_temp"]
    field = next(f for f in data["editable_fields"] if f["key"] == "hot_plate_temp")
    assert field == {"key": "hot_plate_temp", "group": "temperatures", "type": "int", "default": "45", "min": 0, "max": 300}
    assert data["instances"][0]["slicer_page"]["path"] == "~/.config/Snapmaker_Orca"


def test_one_unreadable_installation_does_not_hide_the_others(fake_home, monkeypatch, tmp_path):
    monkeypatch.setattr(overview.guard, "find_processes", lambda: [])
    monkeypatch.setattr(instances.platform, "system", lambda: "Linux")
    copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    copy_fixture("orca", fake_home / ".config" / "OrcaSlicer")
    real = overview.build_instance

    def build_instance(instance, *args, **kwargs):
        if instance.slicer == "OrcaSlicer":
            raise TypeError("a bug in OrcaOne")
        return real(instance, *args, **kwargs)

    monkeypatch.setattr(overview, "build_instance", build_instance)
    data = overview.build_all()
    assert [i["kind"] for i in data["instances"]] == ["snorca"]
    assert [(f["slicer"], f["path"], f["code"]) for f in data["failed"]] == [
        ("OrcaSlicer", "~/.config/OrcaSlicer", "scan_failed")]


def test_odd_types_in_hand_edited_files(fake_home, tmp_path):
    data_dir = copy_fixture("snorca", tmp_path / "snorca")
    conf_path = data_dir / "Snapmaker_Orca.conf"
    conf = json.loads(conf_path.read_text(encoding="utf-8"))
    conf["orca_presets"].append({"machine": ["Liste"], "process": ""})
    conf["models"].append({"vendor": ["Snapmaker"], "model": "Snapmaker U1", "nozzle_diameter": "0.4"})
    conf["models"].append({"vendor": "Snapmaker", "model": ["Snapmaker U1"], "nozzle_diameter": "0.4"})
    conf_path.write_text(json.dumps(conf, indent=4), encoding="utf-8")
    filament = data_dir / "user" / "default" / "filament"
    profile = json.loads((filament / "Mein PLA.json").read_text(encoding="utf-8"))
    profile["compatible_printers"] = [["Snapmaker U1 (0.4 nozzle)"], "Snapmaker U1 (0.4 nozzle)"]
    (filament / "Mein PLA.json").write_text(json.dumps(profile), encoding="utf-8")
    (filament / "Mein PLA.info").write_text("updated_time = " + "9" * 5000 + "\n", encoding="utf-8")
    data = build(data_dir)
    mein_pla = by_name(data)["Mein PLA"]
    assert mein_pla["compatible_printers"] == ["Snapmaker U1 (0.4 nozzle)"]
    assert mein_pla["info"]["updated_time"] is None
    assert [m["model"] for m in data["models"] if not m.get("own")] == ["Snapmaker U1"]
    assert all(isinstance(d["machine"], str) for d in data["printers_page"]["dead_entries"])


def test_bundle_profiles_are_marked(fake_home, tmp_path):
    data_dir = copy_fixture("orca", tmp_path / "OrcaSlicer")
    add_bundle(data_dir)
    data = build(data_dir)
    record = by_name(data)[f"{BUNDLE}/Paket PLA"]
    assert (record["origin_kind"], record["bundle"]) == ("bundle", "Mein Paket")
    assert record["printers"]["Snapmaker U1 (0.4 nozzle)"]["status"] == "visible"
    printer = next(p for p in data["printers_page"]["own"] if p["name"] == f"{BUNDLE}/Paket U1")
    assert (printer["origin"], printer["bundle"], printer["visible"]) == ("bundle", "Mein Paket", True)
    assert next(m for m in data["models"] if m["model"] == f"{BUNDLE}/Paket U1")["bundle"] == "Mein Paket"
    # Removing the U1 does not offer the bundle filament for deleting along: OrcaOne never deletes it.
    u1 = next(m for m in data["printers_page"]["system"] if m["model"] == "Snapmaker U1")
    assert all(x["name"] != f"{BUNDLE}/Paket PLA" for x in u1["only_here"])


def test_when_the_slicer_saved_its_choices(snorca):
    # The time of the .conf, so "Übersicht" can say how current the choices it shows are.
    conf = Path(snorca["data_dir"]) / "Snapmaker_Orca.conf"
    assert abs(datetime.fromisoformat(snorca["conf_saved"]).timestamp() - conf.stat().st_mtime) < 1


def test_processes_and_the_last_choice(snorca):
    records = {r["name"]: r for r in snorca["processes"]}
    standard = records["0.20mm Standard @Snapmaker U1 (0.4 nozzle)"]
    assert (standard["alias"], standard["origin_kind"], standard["layer_height"]) == ("0.20mm Standard", "vendor", "0.2")
    u1 = next(m for m in snorca["models"] if m["model"] == "Snapmaker U1")
    by_nozzle = {v["variant"]: v for v in u1["printers"]}
    # No "process" in "presets": the choice kept in "orca_presets" counts.
    assert by_nozzle["0.4"]["process"] == "0.08mm Standard @Snapmaker U1 (0.4 nozzle)"
    # A remembered process the printer does not offer any more is no choice.
    assert by_nozzle["0.2"]["process"] is None
    # The filament per head the slicer remembers, with its colour (orca_presets, FINDINGS 4.3).
    heads = by_nozzle["0.4"]["heads"]
    assert [(h["name"], h["colour"]) for h in heads] == [("Snapmaker ABS @U1 0.4 nozzle", c) for c in ("#26A69A", "#00C1AE", "#F4E2C1", "#ED1C24")]
    assert heads[0]["material"] == "ABS"
    assert [v["heads"] for k, v in by_nozzle.items() if k not in ("0.2", "0.4")] == [[] for k in by_nozzle if k not in ("0.2", "0.4")]


def test_profile_details_follow_the_chain(fake_home):
    instance = instances.load_instance((FIXTURES / "snorca").resolve(), "manual")
    details = overview.profile_details(instance, "process", "0.20mm Standard @Snapmaker U1 (0.4 nozzle)")
    assert [(c["name"], c["file"], c["abstract"]) for c in details["chain"]][0] == \
        ("fdm_process_U1_0.20", "system/Snapmaker/process/fdm_process_U1_0.20.json", True)
    assert details["file"] == "system/Snapmaker/process/0.20mm Standard @Snapmaker U1 (0.4 nozzle).json"
    assert details["values"]["layer_height"] == {"value": "0.2", "source": "fdm_process_U1_common", "own": False}
    # No profile sets it: the slicer's default.
    assert details["values"]["brim_type"] == {"value": "auto_brim", "source": None, "own": False, "default": True}
    assert not {"inherits", "name", "print_settings_id"} & set(details["values"])

    own = overview.profile_details(instance, "filament", "Mein PLA")
    assert (own["file"], own["origin_kind"], own["problem"]) == ("user/default/filament/Mein PLA.json", "user", None)
    assert own["chain"][0]["origin_kind"] == "vendor"
    orphan = overview.profile_details(instance, "filament", "Altes PETG")
    assert orphan["problem"] == "parent_missing" and not orphan["chain_complete"]
    assert overview.profile_details(instance, "process", "Gibt es nicht") is None


def test_opc_profiles_name_their_cache_file(orca):
    instance = instances.load_instance((FIXTURES / "orca").resolve(), "manual")
    details = overview.profile_details(instance, "filament", "Generic PLA @System")
    assert details["file"] == "system/OrcaFilamentLibrary.opc"
    assert all(c["file"] == "system/OrcaFilamentLibrary.opc" for c in details["chain"])


def test_high_flow_is_marked(snorca):
    """Snapmaker Orca declares the variants a profile has values for (FINDINGS 4.4)."""
    records = {r["name"]: r for r in snorca["processes"]}
    assert records["0.20mm Standard @Snapmaker U1 (0.4 nozzle)"].get("high_flow") is True
    assert "high_flow" not in records["0.08mm Standard @Snapmaker U1 (0.4 nozzle)"]



def test_address_from_the_dialog_physical_printer(fake_home, monkeypatch):
    """The slicer saves "Hostname, IP or URL" of its dialog "Physical Printer" into an own printer
    as print_host (PhysicalPrinterDialog::OnOK); it becomes the address of that printer model."""
    monkeypatch.setattr(overview.guard, "find_processes", lambda: [])
    monkeypatch.setattr(instances.platform, "system", lambda: "Linux")
    data_dir = copy_fixture("orca", fake_home / ".config" / "OrcaSlicer")
    machine = data_dir / "user" / "default" / "machine"
    machine.mkdir(parents=True)
    (machine / "Mein U1.json").write_text(json.dumps({
        "name": "Mein U1", "from": "User", "version": "2.5.0", "inherits": "Snapmaker U1 (0.4 nozzle)",
        "host_type": "octoprint", "print_host": "http://10.30.40.174/"}), encoding="utf-8")
    own = {p["name"]: p for p in build(data_dir)["printers_page"]["own"]}
    assert (own["Mein U1"]["model"], own["Mein U1"]["print_host"]) == ("Snapmaker U1", "http://10.30.40.174/")
    overview.build_all()
    assert camera.printers() == {"Snapmaker U1": {"host": "10.30.40.174", "from": "slicer", "slicer": "OrcaSlicer", "model": "Snapmaker U1"}}


def test_the_scan_reports_its_steps(fake_home, monkeypatch):
    """What GET /api/data does, step by step with its numbers, for the boot screen (GET /api/progress)."""
    monkeypatch.setattr(overview.guard, "find_processes", lambda: [])
    monkeypatch.setattr(instances.platform, "system", lambda: "Linux")
    copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    overview.build_all()
    got = overview.progress()
    assert [s["code"] for s in got["steps"]] == ["processes", "discover", "profiles", "resolve", "folders", "news"]
    assert got["total"] == 6 and all(s["done"] for s in got["steps"])
    steps = {s["code"]: s for s in got["steps"]}
    assert steps["processes"]["running"] == [] and steps["discover"]["count"] == 1
    assert steps["profiles"]["instance"] == "Snapmaker Orca 2.4.0"
    assert steps["profiles"]["system"] > 0 and steps["profiles"]["own"] > 0 and steps["resolve"]["printers"] > 0
    assert steps["folders"]["size"] > 0 and steps["news"]["count"] == 0


def test_address_of_a_printer_snapmaker_orca_connected_to(fake_home, monkeypatch):
    """Snapmaker Orca keeps a printer it connected to in the .conf under "devices", with its address
    (seen on Windows, 24.09.2026). Its preset names the printer model; the dialog "Physical Printer"
    goes first."""
    monkeypatch.setattr(overview.guard, "find_processes", lambda: [])
    monkeypatch.setattr(instances.platform, "system", lambda: "Linux")
    data_dir = copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    conf = read_conf(data_dir / "Snapmaker_Orca.conf")
    conf.data["devices"] = [
        {"dev_name": "Dr. Klippers U1", "ip": "10.30.40.174", "model_name": "U1",
         "preset_name": "Snapmaker U1 (0.4 nozzle)", "password": "geheim"},
        {"dev_name": "ohne Adresse", "ip": "", "preset_name": "Snapmaker U1 (0.4 nozzle)"},
        {"dev_name": "von Hand", "ip": "10.30.40.5", "model_name": "Voron 2.4 300", "preset_name": ["kaputt"]},
    ]
    (data_dir / "Snapmaker_Orca.conf").write_bytes(dump_conf(conf))
    assert build(data_dir)["printers_page"]["devices"] == [{"model": "Snapmaker U1", "host": "10.30.40.174"},
                                                           {"model": "Voron 2.4 300", "host": "10.30.40.5"}]
    overview.build_all()
    assert camera.printers()["Snapmaker U1"] == {"host": "10.30.40.174", "from": "slicer", "slicer": "Snapmaker Orca", "model": "Snapmaker U1"}

    printer = data_dir / "user" / "default" / "machine" / "Mein U1.json"
    printer.write_text(json.dumps({**json.loads(printer.read_text(encoding="utf-8")), "print_host": "10.30.40.9"}),
                       encoding="utf-8")
    overview.build_all()
    assert camera.printers()["Snapmaker U1"]["host"] == "10.30.40.9"


def test_profile_details_hide_a_printers_key(fake_home):
    """The side panel of a profile: a printer's API key masked, any device in the LAN may see it."""
    data_dir = copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    machine = data_dir / "user" / "default" / "machine"
    machine.mkdir(parents=True, exist_ok=True)
    (machine / "Mein U1.json").write_text(json.dumps({
        "name": "Mein U1", "from": "User", "inherits": U1_04, "printer_settings_id": "Mein U1",
        "print_host": "10.30.40.174", "printhost_apikey": "geheim"}), encoding="utf-8")
    values = overview.profile_details(instances.load_instance(data_dir, "manual"), "machine", "Mein U1")["values"]
    assert (values["printhost_apikey"]["value"], values["print_host"]["value"]) == ("***", "10.30.40.174")

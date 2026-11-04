"""The page "Import/Export" (orcaone/importer.py): every file kind built here in memory, analysed
and imported into a copy of tests/fixtures/snorca, never a real data directory."""

import io
import json
import urllib.error
import urllib.request
import zipfile

import pytest

from conftest import call, copy_fixture
from orcaone import importer, scanner
from orcaone.resolver import Resolver, first
from test_opc import build_cache_v2

U1_04 = "Snapmaker U1 (0.4 nozzle)"
BASIC = "Snapmaker PLA Basic @U1"
MINE = json.loads((copy_fixture.__globals__["FIXTURES"] / "snorca/user/default/filament/Mein PLA.json").read_text(encoding="utf-8"))


def zip_of(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content if isinstance(content, (str, bytes)) else json.dumps(content))
    return buffer.getvalue()


def filament(name, **values):
    return {"name": name, "filament_settings_id": [name], "version": "2.3.0.0", "from": "User", **values}


PROJECT = {  # a 3MF of Snapmaker Orca: the process changed without saving, filament 1 an own profile
    "print_settings_id": "0.20mm Standard @Snapmaker U1 (0.4 nozzle)", "filament_settings_id": ["Projekt PLA"],
    "printer_settings_id": U1_04, "inherits_group": ["", BASIC, ""],
    "different_settings_to_system": ["sparse_infill_density;wall_loops", "nozzle_temperature", ""],
    "sparse_infill_density": "25%", "wall_loops": "3", "nozzle_temperature": ["225"],
}


@pytest.fixture
def target(tmp_path):
    data_dir = copy_fixture("snorca", tmp_path / "Snapmaker_Orca")
    return Resolver(scanner.scan(data_dir, "Snapmaker_Orca"))


def test_reads_every_kind_of_file():
    got = importer.read(json.dumps(MINE).encode(), "Mein PLA.json")
    assert got["format"] == "json" and [(f.kind, f.name) for f in got["profiles"]] == [("filament", "Mein PLA")]

    # The slicers' export dialog, a vendor pack: the manifest and a stray JSON are no profiles.
    got = importer.read(zip_of({"filament/A.json": filament("A", inherits=BASIC), "process/B.json": {"name": "B", "print_settings_id": "B"},
                                "Vendor.json": {"name": "Vendor", "filament_list": []}, "notes.json": {"x": 1}}), "Filament presets.zip")
    assert got["format"] == "zip" and [f.name for f in got["profiles"]] == ["A", "B"]
    assert got["skipped"] == [{"where": "notes.json", "code": "not_a_profile"}]

    bundle = {"bundle_structure.json": {"bundle_type": "filament config bundle", "filament_name": "SUNLU PLA+"},
              "Snapmaker/SUNLU PLA+ @U1.json": filament("SUNLU PLA+ @U1", inherits=BASIC)}
    assert importer.read(zip_of(bundle), "SUNLU PLA+.orca_filament")["format"] == "bundle"

    # A backup of OrcaOne: the own profiles of every user folder, nothing of system/.
    backup = {"orcaone-backup.json": {"reason": "manual"}, "Snapmaker_Orca.conf": "{}",
              "user/default/filament/Mein PLA.json": MINE, "system/Snapmaker/filament/X.json": filament("X")}
    got = importer.read(zip_of(backup), "2026-09-23_manual.zip")
    assert got["format"] == "backup" and [f.where for f in got["profiles"]] == ["user/default/filament/Mein PLA.json"]

    # A 3MF: the own profile it embeds, complete, and the process it changed without saving.
    project = {"3D/3dmodel.model": "<model/>", "Metadata/project_settings.config": PROJECT,
               "Metadata/filament_settings_1.config": filament("Projekt PLA", inherits=BASIC, nozzle_temperature=["225"], **{"from": "project"})}
    got = importer.read(zip_of(project), "Benchy.3mf")
    assert got["format"] == "3mf" and [(u["kind"], u["name"]) for u in got["project"]["uses"]] == [
        ("process", "0.20mm Standard @Snapmaker U1 (0.4 nozzle)"), ("filament", "Projekt PLA"), ("machine", U1_04)]
    assert [(f.kind, f.name, f.full) for f in got["profiles"]] == [
        ("filament", "Projekt PLA", True), ("process", "0.20mm Standard @Snapmaker U1 (0.4 nozzle) (Benchy)", False)]
    assert got["profiles"][1].data == {"name": "0.20mm Standard @Snapmaker U1 (0.4 nozzle) (Benchy)",
                                       "inherits": "0.20mm Standard @Snapmaker U1 (0.4 nozzle)", "sparse_infill_density": "25%", "wall_loops": "3"}

    # Bambu Studio 1.8 writes no inherits_group: system profiles only, nothing to take.
    older = {"3D/3dmodel.model": '<model><metadata name="Application">BambuStudio-01.08.04.51</metadata></model>',
             "Metadata/project_settings.config": {"print_settings_id": "0.16mm Optimal @BBL A1M", "printer_settings_id": "Bambu Lab A1 mini 0.4 nozzle",
                                                  "filament_settings_id": ["Generic PLA @BBL A1M"] * 4, "layer_height": "0.16"}}
    got = importer.read(zip_of(older), "m3Sorter.3mf")
    assert got["profiles"] == [] and got["project"]["application"] == "BambuStudio 01.08.04.51"
    assert [u["name"] for u in got["project"]["uses"]] == ["0.16mm Optimal @BBL A1M", "Generic PLA @BBL A1M", "Bambu Lab A1 mini 0.4 nozzle"]

    with pytest.raises(importer.ImportFailed) as err:
        importer.read(b"hello", "hello.txt")
    assert err.value.code == "file_unknown"


def test_a_project_names_its_profiles_with_the_values_it_prints_with():
    # Happy Shark (Bambu Studio 1.9.3): one filament in three slots, each with its colour; "red" is none.
    project = {"print_settings_id": "0.28mm Extra Draft @BBL A1", "printer_settings_id": "Bambu Lab A1 0.4 nozzle",
               "filament_settings_id": ["Bambu PLA Basic @BBL A1"] * 3, "filament_colour": ["#FFFFFF", "#0080ff", "red"],
               "filament_type": ["PLA"] * 3, "nozzle_temperature": ["220"] * 3, "layer_height": "0.28", "wall_loops": "2",
               "sparse_infill_density": "15%", "nozzle_diameter": ["0.4"], "printer_model": "Bambu Lab A1"}
    got = importer.read(zip_of({"Metadata/project_settings.config": project}), "Happy_Shark.3mf")["project"]
    assert got["nozzle"] == "0.4" and got["uses"] == [
        {"kind": "process", "name": "0.28mm Extra Draft @BBL A1",
         "values": {"layer_height": "0.28", "wall_loops": "2", "sparse_infill_density": "15%"}},
        {"kind": "filament", "name": "Bambu PLA Basic @BBL A1", "values": {"filament_type": "PLA", "nozzle_temperature": "220"},
         "colours": ["#FFFFFF", "#0080FF"]},
        {"kind": "machine", "name": "Bambu Lab A1 0.4 nozzle", "values": {"printer_model": "Bambu Lab A1", "nozzle_diameter": "0.4"}}]

    # Snapmaker Orca keeps a value per filament and hotend variant: a slot shows its first.
    project = {"filament_settings_id": ["A", "B"], "nozzle_temperature": ["220", "230", "240", "250"], "filament_colour": ["#111111", "#222222"]}
    uses = importer.read(zip_of({"Metadata/project_settings.config": project}), "p.3mf")["project"]["uses"]
    assert [(u["name"], u["values"], u["colours"]) for u in uses] == [("A", {"nozzle_temperature": "220"}, ["#111111"]),
                                                                      ("B", {"nozzle_temperature": "240"}, ["#222222"])]


def test_a_cleaned_3mf_keeps_the_model_and_leaves_the_printer_out():
    # What makes the slicer set up the project's printer, process and filaments, and the G-code for them.
    bound = {"Metadata/project_settings.config": {"printer_settings_id": "Bambu Lab A1 0.4 nozzle"},
             "Metadata/filament_settings_1.config": filament("Projekt PLA"), "Metadata/print_setting_1.config": "{}",
             "Metadata/slice_info.config": "<config/>", "Metadata/plate_1.gcode": "G28", "Metadata/plate_1.gcode.md5": "abc"}
    kept = {"3D/3dmodel.model": '<model><metadata name="Application">BambuStudio-01.09.03.50</metadata></model>',
            "Metadata/model_settings.config": "<config/>", "Metadata/plate_1.png": b"\x89PNG", "_rels/.rels": "<Relationships/>"}
    cleaned = importer.clean_3mf(zip_of({**kept, **bound}))
    with zipfile.ZipFile(io.BytesIO(cleaned)) as archive:
        assert sorted(archive.namelist()) == sorted(kept) and archive.read("Metadata/plate_1.png") == b"\x89PNG"
    # Read again: still a 3MF, without a project; cleaning it twice has nothing to do.
    again = importer.read(cleaned, "Hai (bereinigt).3mf")
    assert (again["format"], again["profiles"], "project" in again) == ("3mf", [], False)
    for raw, code in ((cleaned, "nothing_to_clean"), (zip_of({"a.json": "{}"}), "file_unknown"), (b"kein ZIP", "file_unknown")):
        with pytest.raises(importer.ImportFailed) as err:
            importer.clean_3mf(raw)
        assert err.value.code == code


def test_reads_the_slicers_own_backup(tmp_path):
    # user_backup-v<version>: the slicer's copy of user/ at the first start of a version (FINDINGS 4.2).
    data_dir = tmp_path / "Snapmaker_Orca"
    old = data_dir / "user_backup-v2.3.0" / "default"
    (old / "filament" / "base").mkdir(parents=True)
    (old / "machine").mkdir()
    (old / "filament" / "Alt PLA.json").write_text(json.dumps(filament("Alt PLA", inherits=BASIC)), encoding="utf-8")
    (old / "filament" / "Alt PLA.info").write_text("sync_info = \n", encoding="utf-8")
    (old / "filament" / "base" / "Wurzel.json").write_text(json.dumps(filament("Wurzel")), encoding="utf-8")
    (old / "machine" / "kaputt.json").write_text("{", encoding="utf-8")
    outside = tmp_path / "Woanders.json"
    outside.write_text(json.dumps(filament("Woanders")), encoding="utf-8")
    try:
        (old / "filament" / "Link.json").symlink_to(outside)
    except OSError:
        pass  # Windows without the right to make symlinks
    (data_dir / "user_backup-v2.4.0").mkdir()
    (data_dir / "user").mkdir()

    assert {b["name"]: b["profiles"] for b in importer.slicer_backups(data_dir)} == {"user_backup-v2.3.0": 3, "user_backup-v2.4.0": 0}
    got = importer.read_backup(data_dir, "user_backup-v2.3.0")
    assert got["format"] == "slicer_backup" and sorted(f.name for f in got["profiles"]) == ["Alt PLA", "Wurzel"]
    assert got["profiles"][0].where == "user_backup-v2.3.0/default/filament/Alt PLA.json"
    assert got["skipped"] == [{"where": "user_backup-v2.3.0/default/machine/kaputt.json", "code": "not_readable"}]
    # Only a copy the slicer made, by its name: no other folder, nothing outside the data directory.
    for name in ("user", "../Snapmaker_Orca/user_backup-v2.3.0", "user_backup-v9.9.9", ""):
        with pytest.raises(importer.ImportFailed) as err:
            importer.read_backup(data_dir, name)
        assert err.value.code == "folder_unknown"


def test_an_entry_too_big_is_left_out(monkeypatch):
    monkeypatch.setattr(importer, "MAX_ENTRY", 50)
    got = importer.read(zip_of({"a.json": filament("A" * 80)}), "a.zip")
    assert got["profiles"] == [] and got["skipped"] == [{"where": "a.json", "code": "too_big"}]

    # The model of a 3MF carries the meshes, megabytes (Happy Shark: 11 MB); its head names the application.
    model = '<model><metadata name="Application">BambuStudio-01.09.03.50</metadata>' + "<vertex/>" * 20 + "</model>"
    got = importer.read(zip_of({"3D/3dmodel.model": model, "Metadata/project_settings.config": {"print_settings_id": "P"}}), "shark.3mf")
    assert got["project"]["application"] == "BambuStudio 01.09.03.50"


def test_analysis_against_the_installation(target):
    files = {
        "Fremdes PLA.json": filament("Fremdes PLA", inherits=BASIC, nozzle_temperature=["230"]),
        "Mein PLA.json": MINE,                                                        # the same file as there
        "Mein PLA 2.json": {**MINE, "nozzle_temperature": ["199"], "name": "Mein PLA"},   # twice in one file
        "Kaputt.json": filament("Kaputt", inherits="Gibt es nicht @X"),
        "Bambu.json": filament("Bambu PLA", compatible_printers=["Bambu Lab X1 Carbon 0.4 nozzle"]),
        # A vendor pack: its base profile builds on a template, which cannot be a parent.
        "M4P base.json": filament("M4P PLA @base", inherits="fdm_filament_pla", instantiation="false", filament_vendor=["Material4Print"]),
        "M4P.json": filament("M4P Orange", inherits="M4P PLA @base", compatible_printers=[U1_04]),
    }
    source = importer.read(zip_of(files), "mixed.zip")
    assert source["skipped"] == [{"where": "Mein PLA 2.json", "code": "twice", "name": "Mein PLA"}]
    got = {e["name"]: e for e in importer.analyse(source, target, "Snapmaker_Orca")}
    assert (got["Fremdes PLA"]["status"], got["Fremdes PLA"]["parent"], got["Fremdes PLA"]["values"]["nozzle_temperature"]) == (
        "new", BASIC, "230")
    assert got["Mein PLA"]["status"] == "same"
    assert (got["Kaputt"]["status"], got["Kaputt"]["params"]) == ("parent_missing", {"parent": "Gibt es nicht @X"})
    assert got["Bambu PLA"]["status"] == "no_target_printer"
    assert got["M4P PLA @base"]["status"] == "template"
    m4p = got["M4P Orange"]
    assert (m4p["status"], m4p["parent"], m4p["from_file"], m4p["printers"]) == ("new", None, ["M4P PLA @base"], [U1_04])
    assert m4p["values"]["filament_vendor"] == "Material4Print" and m4p["values"]["filament_type"] == "PLA"

    # Another value under a name there: renamed or replaced on the page's choice.
    other = importer.read(json.dumps({**MINE, "nozzle_temperature": ["199"]}).encode(), "Mein PLA.json")
    assert importer.analyse(other, target, "Snapmaker_Orca")[0]["status"] == "name_taken"
    system = importer.read(json.dumps(filament(BASIC, inherits=BASIC)).encode(), "x.json")
    assert importer.analyse(system, target, "Snapmaker_Orca")[0]["status"] == "system_name"
    # A printer bundle of the slicer holds its system printer written out in full: here already, no copy.
    bundle = {"bundle_structure.json": {"bundle_type": "printer config bundle", "printer_preset_name": U1_04},
              f"printer/{U1_04}.json": {"name": U1_04, "printer_settings_id": U1_04, "from": "System", "inherits": "", "printer_model": "Snapmaker U1"},
              "filament/Mein PLA.json": MINE}
    got = {e["name"]: e["status"] for e in importer.analyse(importer.read(zip_of(bundle), f"{U1_04}.orca_printer"), target, "Snapmaker_Orca")}
    assert got == {U1_04: "system_here", "Mein PLA": "same"}
    # Hidden with instantiation "false" is still here: the slicer loads it and only does not show it.
    folder = target.scan.data_dir / "user" / "default" / "filament"
    (folder / "Mein PLA.json").write_text(json.dumps({**MINE, "instantiation": "false"}), encoding="utf-8")
    hidden = Resolver(scanner.scan(target.scan.data_dir, "Snapmaker_Orca"))
    assert importer.analyse(importer.read(json.dumps(MINE).encode(), "Mein PLA.json"), hidden, "Snapmaker_Orca")[0]["status"] == "same"
    # Complete, from a 3MF: lands even without its parent, as a root profile.
    alone = {"Metadata/filament_settings_1.config": filament("Alleine", inherits="Fehlt @X", nozzle_temperature=["210"], filament_type=["PLA"])}
    entry = importer.analyse(importer.read(zip_of(alone), "p.3mf"), target, "Snapmaker_Orca")[0]
    assert (entry["status"], entry["parent"]) == ("new", None)


def test_analysis_against_a_cache_v2_installation(tmp_path):
    """OrcaSlicer 2.5 delivers system profiles as .opc CACHE_VERSION 2: the analysis resolves
    parents and include layers from it instead of reporting every parent as missing."""
    data_dir = tmp_path / "OrcaSlicer"
    (data_dir / "system").mkdir(parents=True)
    (data_dir / "system" / "TestMaker.opc").write_bytes(build_cache_v2(filament=[
        ("Basis", {"nozzle_temperature": "220", "filament_type": "PLA"}, "", [], "false"),
        ("Träger", {"filament_vendor": "TestMaker"}, "", ["Basis"], "true")]))
    res = Resolver(scanner.scan(data_dir, "OrcaSlicer"))
    assert not [p for p in res.scan.packages if p.error]
    source = importer.read(json.dumps(filament("Neu", inherits="Träger")).encode(), "Neu.json")
    entry = importer.analyse(source, res, "OrcaSlicer")[0]
    assert (entry["status"], entry["parent"]) == ("new", "Träger")
    assert entry["values"]["nozzle_temperature"] == "220"    # from the include layer of "Träger"


def test_hang_a_filament_onto_a_printer_here(target):
    # Made for a printer that is not here; its base in the file holds the brand's values.
    base = filament("Fremd PLA @base", inherits="fdm_filament_pla", instantiation="false", filament_vendor=["Fremd"],
                    filament_type=["PLA"], nozzle_temperature=["215"], filament_flow_ratio=["0.95"], filament_start_gcode=["M142 P1"])
    child = filament("Fremd PLA @BBL X1C", inherits="Fremd PLA @base", compatible_printers=["Bambu Lab X1 Carbon 0.4 nozzle"],
                     filament_max_volumetric_speed=["18"])
    entry = {e["name"]: e for e in importer.analyse(importer.read(zip_of({"a.json": base, "b.json": child}), "fremd.zip"),
                                                    target, "Snapmaker_Orca")}["Fremd PLA @BBL X1C"]
    assert entry["status"] == "no_target_printer"
    # Hung onto the U1: the child of its "Generic PLA", with the material's values only, not the start G-code.
    got = importer.analyse_attach(target, "Snapmaker_Orca", entry["profile"], entry["parents"], U1_04)
    assert (got["status"], got["target"], got["parent"], got["printers"]) == ("new", f"Fremd PLA @{U1_04}", "Generic PLA", [U1_04])
    assert {"filament_vendor", "nozzle_temperature", "filament_flow_ratio", "filament_max_volumetric_speed"} <= set(got["taken"])
    assert "filament_start_gcode" not in got["taken"] and got["values"]["nozzle_temperature"] == "215"
    # Nothing of that material for the U1 here, or no such printer: nothing to hang it onto.
    assert importer.analyse_attach(target, "Snapmaker_Orca", filament("Hart", filament_type=["PPS"]), [], U1_04) == {
        "status": "no_base", "params": {"printer": U1_04, "material": "PPS"}}
    assert importer.analyse_attach(target, "Snapmaker_Orca", filament("X", filament_type=["PLA"]), [], "Gibt es nicht")["status"] == "unknown_printer"


def upload(server, inst_id, raw, name):
    request = urllib.request.Request(f"{server}/api/instances/{inst_id}/import?name={urllib.request.quote(name)}", data=raw,
                                     method="POST", headers={"Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def apply(server, base, changes):
    plan = json.loads(call(f"{base}/plan", "POST", {"changes": changes})[1])["plan"]
    assert plan["blocked"] is None, plan
    status, body = call(f"{base}/apply", "POST", {"plan_id": plan["id"]})
    assert status == 200, body
    return plan


def test_import_through_the_plan(server, fake_home):
    data_dir = copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    inst = json.loads(call(f"{server}/api/data")[1])["instances"][0]
    base = f"{server}/api/instances/{inst['id']}"
    files = {"Fremdes PLA.json": filament("Fremdes PLA", inherits=BASIC, nozzle_temperature=["230"], filament_type=["PLA"]),
             "Mein PLA.json": {**MINE, "nozzle_temperature": ["199"]}}
    status, got = upload(server, inst["id"], zip_of(files), "Geteilt.zip")
    assert status == 200 and got["file"] == "Geteilt.zip" and [p["status"] for p in got["profiles"]] == ["new", "name_taken"]
    op = lambda p, **extra: {"op": "profile_import", "kind": p["kind"], "profile": p["profile"], "parents": p["parents"],
                             "full": p["full"], "source": got["file"], **extra}
    fresh, taken = got["profiles"]
    plan = apply(server, base, [op(fresh), op(taken)])
    assert {w["code"] for w in plan["warnings"]} >= {"import_from"}
    folder = data_dir / "user" / "default" / "filament"
    written = json.loads((folder / "Fremdes PLA.json").read_text(encoding="utf-8"))
    # A child keeps only what differs from its parent: filament_type is the parent's already.
    assert (written["inherits"], written["nozzle_temperature"], "filament_type" in written) == (BASIC, ["230"], False)
    assert json.loads((folder / "Mein PLA (2).json").read_text(encoding="utf-8"))["nozzle_temperature"] == ["199"]
    # Replacing keeps the name.
    apply(server, base, [op(taken, replace=True)])
    assert json.loads((folder / "Mein PLA.json").read_text(encoding="utf-8"))["nozzle_temperature"] == ["199"]
    # What OrcaOne wrote counts as seen on the page "Änderungen".
    assert json.loads(call(f"{base}/news")[1])["count"] == 0
    assert upload(server, inst["id"], b"kein Profil", "x.txt") == (400, {"error": "file_unknown"})

    # A 3MF: what the project uses, whether it is here, and its nozzle for the page to find what fits.
    project = {"print_settings_id": "0.20mm Standard @Snapmaker U1 (0.4 nozzle)", "printer_settings_id": "Bambu Lab A1 0.4 nozzle",
               "filament_settings_id": [BASIC], "filament_colour": ["#0080FF"], "nozzle_diameter": ["0.4"]}
    status, got = upload(server, inst["id"], zip_of({"Metadata/project_settings.config": project}), "Hai.3mf")
    assert status == 200 and got["profiles"] == [] and got["project"]["nozzle"] == "0.4"
    assert [(u["name"], u["here"]) for u in got["project"]["uses"]] == [
        ("0.20mm Standard @Snapmaker U1 (0.4 nozzle)", True), (BASIC, True), ("Bambu Lab A1 0.4 nozzle", False)]
    assert got["project"]["uses"][1]["colours"] == ["#0080FF"]


def test_import_hung_onto_a_printer_and_renamed(server, fake_home):
    data_dir = copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    inst = json.loads(call(f"{server}/api/data")[1])["instances"][0]
    base = f"{server}/api/instances/{inst['id']}"
    foreign = filament("Fremd PLA @BBL X1C", compatible_printers=["Bambu Lab X1 Carbon 0.4 nozzle"], filament_type=["PLA"],
                       nozzle_temperature=["215"], filament_start_gcode=["M142 P1"])
    status, body = call(f"{base}/import/attach", "POST", {"profile": foreign, "parents": [], "printer": U1_04})
    assert (status, json.loads(body)["parent"]) == (200, "Generic PLA")
    change = {"op": "profile_import", "kind": "filament", "profile": foreign, "parents": [], "full": False, "source": "fremd.json",
              "printer": U1_04, "name": "Fremdes PLA für den U1"}
    plan = apply(server, base, [change])
    assert {w["code"] for w in plan["warnings"]} >= {"import_from", "import_attached"}
    written = json.loads((data_dir / "user" / "default" / "filament" / "Fremdes PLA für den U1.json").read_text(encoding="utf-8"))
    assert (written["inherits"], written["nozzle_temperature"]) == ("Generic PLA", ["215"])
    # Only what differs from "Generic PLA" is written: its printer list is the U1 0.4 already.
    assert "filament_start_gcode" not in written and "compatible_printers" not in written
    res = Resolver(scanner.scan(data_dir, "Snapmaker_Orca"))
    mine = next(o for o in res.own_profiles("filament") if o.name == "Fremdes PLA für den U1")
    assert res.loaded(mine) and res.compatible_printers(mine) == [U1_04]
    # A name the slicer cannot take stops the plan; a request without printer is refused.
    made = json.loads(call(f"{base}/plan", "POST", {"changes": [{**change, "name": "a/b"}]})[1])["plan"]
    assert made["blocked"] == "name_invalid"
    assert call(f"{base}/import/attach", "POST", {"profile": foreign, "printer": ""})[0] == 400


def test_filament_for_a_nozzle_it_lacks(server, fake_home):
    # "Für andere Düse" on the page "Filamente": Snapmaker's PLA Basic is there for the 0.4 nozzle only.
    data_dir = copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    inst = json.loads(call(f"{server}/api/data")[1])["instances"][0]
    base = f"{server}/api/instances/{inst['id']}"
    u1_02 = "Snapmaker U1 (0.2 nozzle)"
    plan = apply(server, base, [{"op": "filament_attach", "source": BASIC, "printer": u1_02}])
    assert "filament_attached" in {w["code"] for w in plan["warnings"]}
    name = f"Snapmaker PLA Basic @{u1_02}"
    written = json.loads((data_dir / "user" / "default" / "filament" / f"{name}.json").read_text(encoding="utf-8"))
    assert written["inherits"] == "Generic PLA @U1 0.2 nozzle"
    res = Resolver(scanner.scan(data_dir, "Snapmaker_Orca"))
    mine = next(o for o in res.own_profiles("filament") if o.name == name)
    assert res.loaded(mine) and res.compatible_printers(mine) == [u1_02]
    # The material's values are those of PLA Basic, the rest those of the 0.2 nozzle's PLA.
    basic = res.collection["filament"][BASIC]
    assert first(res.value(mine, "nozzle_temperature")) == first(res.value(basic, "nozzle_temperature"))
    made = json.loads(call(f"{base}/plan", "POST", {"changes": [{"op": "filament_attach", "source": "Gibt es nicht", "printer": u1_02}]})[1])["plan"]
    assert made["blocked"] == "unknown_profile"


def test_import_from_the_slicers_backup(server, fake_home):
    data_dir = copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    old = data_dir / "user_backup-v2.3.0" / "default" / "filament"
    old.mkdir(parents=True)
    (old / "Alt PLA.json").write_text(json.dumps(filament("Alt PLA", inherits=BASIC, nozzle_temperature=["205"])), encoding="utf-8")
    inst = json.loads(call(f"{server}/api/data")[1])["instances"][0]
    base = f"{server}/api/instances/{inst['id']}"
    backups = json.loads(call(f"{base}/import/slicer-backups")[1])["backups"]
    assert [(b["name"], b["profiles"]) for b in backups] == [("user_backup-v2.3.0", 1)]
    got = json.loads(call(f"{base}/import/slicer-backup?name=user_backup-v2.3.0")[1])
    assert (got["file"], got["format"], [(p["name"], p["status"]) for p in got["profiles"]]) == (
        "user_backup-v2.3.0", "slicer_backup", [("Alt PLA", "new")])
    p = got["profiles"][0]
    apply(server, base, [{"op": "profile_import", "kind": p["kind"], "profile": p["profile"], "parents": p["parents"],
                          "full": p["full"], "source": got["file"]}])
    written = json.loads((data_dir / "user" / "default" / "filament" / "Alt PLA.json").read_text(encoding="utf-8"))
    assert (written["inherits"], written["nozzle_temperature"]) == (BASIC, ["205"])
    assert call(f"{base}/import/slicer-backup?name=user")[0] == 404


def test_clean_3mf_over_the_api(server):
    request = urllib.request.Request(f"{server}/api/clean-3mf", method="POST", headers={"Content-Type": "application/octet-stream"},
                                     data=zip_of({"3D/3dmodel.model": "<model/>", "Metadata/project_settings.config": {}}))
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers["Content-Type"] == "model/3mf"
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert archive.namelist() == ["3D/3dmodel.model"]


def test_export(server, fake_home):
    data_dir = copy_fixture("snorca", fake_home / ".config" / "Snapmaker_Orca")
    printer = data_dir / "user" / "default" / "machine" / "Mein U1.json"
    printer.write_text(json.dumps({**json.loads(printer.read_text(encoding="utf-8")), "print_host": "10.0.0.5",
                                   "printhost_apikey": "geheim"}), encoding="utf-8")
    inst = json.loads(call(f"{server}/api/data")[1])["instances"][0]
    base = f"{server}/api/instances/{inst['id']}"

    def export(flat):
        request = urllib.request.Request(f"{base}/export", method="POST", headers={"Content-Type": "application/json"},
                                         data=json.dumps({"profiles": [{"kind": "filament", "name": "Mein PLA"},
                                                                       {"kind": "machine", "name": "Mein U1"}], "flat": flat}).encode())
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.headers["Content-Type"] == "application/zip"
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                return {n: json.loads(archive.read(n)) for n in archive.namelist()}

    got = export(False)
    assert got["filament/Mein PLA.json"] == MINE
    assert "print_host" not in got["machine/Mein U1.json"] and "printhost_apikey" not in got["machine/Mein U1.json"]
    flat = export(True)["filament/base/Mein PLA.json"]
    assert (flat["inherits"], flat["nozzle_temperature"], flat["filament_type"]) == ("", ["215"], ["PLA"])
    assert flat["filament_id"].startswith("P") and "setting_id" not in flat
    # Read in again, the flat copy is the same filament as the one there.
    status, again = upload(server, inst["id"], zip_of({"Mein PLA.json": flat}), "OrcaOne-Export.zip")
    assert status == 200 and again["profiles"][0]["status"] == "same"
    status, body = call(f"{base}/export", "POST", {"profiles": [{"kind": "filament", "name": "Gibt es nicht"}]})
    assert (status, json.loads(body)) == (404, {"error": "unknown_profile", "name": "Gibt es nicht"})


def test_nothing_that_runs_on_this_computer_and_no_keys_shown(target):
    """post_process runs on this computer after slicing (both slicers): never from a file, said like
    any key left out. A printer's API key never goes to the page, any device in the LAN may see it."""
    process = {"name": "Fremd 0.16", "inherits": "0.20mm Standard @Snapmaker U1 (0.4 nozzle)", "from": "User",
               "print_settings_id": "Fremd 0.16", "layer_height": "0.16", "post_process": ["C:\\Temp\\evil.bat"]}
    copy = importer.convert(target, "Snapmaker_Orca", "process", process, [], False)
    assert "post_process" not in copy.data and "post_process" in copy.dropped and copy.data["layer_height"] == "0.16"
    printer = {"name": "Mein U1", "inherits": U1_04, "from": "User", "printer_settings_id": "Mein U1",
               "print_host": "10.0.0.5", "printhost_apikey": "geheim", "printhost_password": ""}
    entry = importer.analyse(importer.read(json.dumps(printer).encode(), "Mein U1.json"), target, "Snapmaker_Orca")[0]
    assert (entry["profile"]["printhost_apikey"], entry["profile"]["printhost_password"], entry["profile"]["print_host"]) == ("***", "", "10.0.0.5")

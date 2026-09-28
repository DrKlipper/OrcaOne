# Profilverwaltung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vollstaendige Profilbearbeitung fuer beide Slicer mit nutzerbestimmtem Umfang, lokaler verzweigter Historie und gepruefter Uebernahme in Orca.

**Architecture:** Versionierte Parameterkataloge und reine Profiloperationen liefern bearbeitbare Dokumente. Unveraenderliche Revisionen, Staende und Branch-Referenzen liegen im Dateisystem. Ausschliesslich der vorhandene Planner schreibt in Slicer-Daten; Historie und Oberflaeche sind davon getrennt.

**Tech Stack:** Python >= 3.11, Standardbibliothek, bestehendes FastAPI, pytest, bestehendes Vue 3 ohne Build-Schritt. Keine neue Runtime-Abhaengigkeit, Datenbank oder Git-Installation fuer Endnutzer.

**Spec:** [Profil-Editor und Timeline](../specs/2026-09-27-profile-management-design.md).

## Global Constraints

- Mindestversionen: OrcaSlicer 2.4.2 (`8500fcdccaa10b5099ac20d252af3a7c560046f1`), Snapmaker Orca 2.4.0 (`b1831e5dcb464172de33783142425aafda834fbc`).
- Eine neue Version bekommt nicht allein wegen einer groesseren Versionsnummer Schreibfreigabe.
- Je Aktion bestimmt der Nutzer den Umfang: ein Profil, mehrere Profile oder ein ausgewaehltes Profilset. Keine automatische Ausweitung auf Abhaengigkeiten.
- Beim Zusammenfuehren effektive Werte uebernehmen, unabhaengig vom alten Elternprofil.
- Gleicher Duesendurchmesser darf mehrere Varianten haben, etwa Standard/High Flow.
- Bei Duesenwechsel Anpassungen vorschlagen, keine stillen Parameterveraenderungen.
- Historie lokal und unabhaengig vom Slicer-Sync speichern.
- Strukturelle Fehler blockieren; drucktechnische Plausibilitaet gesondert warnen.
- Neue Historie unter `data/snapshots/profiles/<installation-id>/`; bestehende Snapshots und `data/history/` erhalten.
- Nur `user/**` und Slicer-`.conf` beschreiben; keine Herstellerressourcen oder Systemprofile.
- Slicer-Schreiben nur bei geschlossenem Slicer, mit Preview, Bestaetigung, Backup und Nachpruefung.
- Tests nur gegen Fixtures/temporaere Verzeichnisse. Keine echten Slicer-Verzeichnisse automatisch testen, keinen Slicer starten/beenden.
- Sprache der Oberflaeche DE/EN; Code und Kommentare Englisch; UTF-8, Windows und Linux.
- Keine Commits/Pushes ohne gesonderten Auftrag. Die Aufgaben enden mit Diff/Tests, nicht mit automatischen Commits.
- Nutzerprofile nur nach ausdruecklicher Freigabe einlesen; fehlende Praxisfixtures nicht erfinden.

## Review Focus

1. Zwei Browser bearbeiten denselben Entwurf: veraltete Generation liefert 409, erster Stand bleibt erhalten (Aufgaben 5, 8).
2. Selektiver Merge uebernimmt nur ein Feld: spaetere Merges erkennen das andere weiterhin als offen (Aufgabe 6).
3. Slicer schreibt gerade eine Datei neu: kurz fehlende/ungueltige Datei wird nicht als endgueltig geloescht historisiert (Aufgabe 7).
4. Zwei gleichartige reale Drucker haben unterschiedliche Adressen: Modellgruppierung fuehrt keine Geraete/Verbindungen zusammen (Aufgabe 10).
5. Benutzerordner/Version wechselt nach Preview: Uebernahme bricht ab, bevor irgendeine Profildatei geschrieben wird (Aufgabe 9).

## Arbeitsbasis und Ausfuehrung

- Branch `feature/profile-management`, Basis `98e7151`, 377 passed / 12 skipped vor diesen Aenderungen.
- Spezifikation und Fehlerprotokoll sind uncommitted; nicht durch Reset/Clean entfernen.
- Bestehendes Workspace benutzen. Ein neuer Worktree ist fuer den bereits vorbereiteten Branch nicht erforderlich.
- Pro Aufgabe: Test zuerst, gezielt rot nachweisen, implementieren, gezielt gruen nachweisen, Diff pruefen.
- Schritte mit Quellcodeauswertung koennen weitere kleine Testfaelle erfordern; ein unbekannter Quellausdruck ist ein dokumentierter Abdeckungsfehler, keine Erlaubnis zu raten.
- Bei echten Bugfixes ausserhalb des freigegebenen Plans Diagnose mit Evidenz und Nutzerrueckfrage gemaess AGENTS.md.
- Fuer Subagenten nur unabhaengige Dateien parallel bearbeiten; maximal drei Worker neben dem Koordinator. Relevante NOT-TO-DO-Tags weitergeben. Kein Subagent-Commit.

Tests unter Windows: `& '.\.wenv\Scripts\python.exe' -m pytest <Dateien> -q`.
Unter Linux entsprechend `.lenv/bin/python -m pytest <Dateien> -q`.

## Dateigrenzen und gemeinsame Datenvertraege

| Datei | Verantwortung |
|---|---|
| `orcaone/profile_schema.py` | Katalog laden, genaue Version zuordnen, Typ-/Wertpruefung. |
| `orcaone/profile_normalize.py` | Slicerspezifische Defaults, Dimensionsregeln und effektive Werte. |
| `orcaone/profile_edit.py` | Dokumente und selektive Patches, Herkunft, Referenzanalyse. |
| `orcaone/profile_store.py` | Unveraenderliche JSON-Objekte, Integritaet, sichere Pfade, atomare Referenzen. |
| `orcaone/profile_history.py` | Identitaeten, Staende, Branches, Entwuerfe, Restore und externe Beobachtungen. |
| `orcaone/profile_merge.py` | Feld-Diff und Dreiwege-Merge. |
| `orcaone/profile_publish.py` | Planner-Anbindung, Uebernahmebeleg und Wiederanlaufpruefung. Kein eigener Slicer-Writer. |
| `orcaone/profile_variants.py` | Duesen-/Modellzuordnung und begruendete Vorschlaege. |
| `tools/make_profile_schema.py` | Reproduzierbare Katalogerzeugung; bestehenden Extraktor lesend wiederverwenden. |
| `orcaone/profile_schemas/*.json` | Gepinnte Kataloge und Manifest; im Build enthalten. |
| `orcaone/static/pages/profile-*.js` | Gemeinsame Editor-, Timeline-, Batch- und Merge-Komponenten. |

Keine generische Repository-Klasse, kein ORM, kein allgemeines Plugin-System.
JSON-kompatible Dictionaries nach bestehendem Projektstil. Folgende Schluessel
sind verbindlich; Funktionen duerfen intern Dataclasses verwenden, sofern API-Form erhalten bleibt:

```python
# Ein Value ist exakt die Slicer-JSON-Repräsentation: str oder list[str].
option = {"type": "coFloat", "default": "0.2", "nullable": False,
          "min": 0, "max": None, "enums": [], "unit": "mm",
          "dimension": "scalar", "role": "parameter", "complete": True}
document = {"id": "a" * 32, "kind": "process", "name": "Quality",
            "schema_id": "OrcaSlicer@2.4.2", "own": {"layer_height": "0.2"},
            "effective": {"layer_height": "0.2"}, "inherited": {}, "origins": {},
            "context": {"chain_complete": True, "extruder_count": 1,
                        "filament_count": 1, "flow_variants": []},
            "references": [], "unknown": {}, "complete": True}
patch = {"profile_id": "a" * 32, "op": "set", "key": "layer_height",
         "value": "0.25", "indices": None}
issue = {"severity": "error", "code": "out_of_range", "profile_id": "a" * 32,
         "key": "layer_height", "indices": None, "params": {}}
```

`None` als Default heisst unbekannt/nicht bestimmbar, nicht `nil`; dies setzt
`complete=False`. Fehlend, leere Zeichenkette, leere Liste, `nil` und Reset sind
unterschiedliche Zustaende. Metadaten/Secrets erhalten Rollen statt normale Textfelder.
Die Beispieldaten sind synthetisch; sie behaupten keinen echten Defaultwert.
`inherited` enthaelt die fuer diesen Stand aufgeloesten Werte vor den eigenen
Ueberschreibungen. Damit kann Reset ohne Raten neu berechnet werden. Herkunft und
Schema-ID binden diese Werte an ihren historischen Stand; Publish prueft die heutige
Eltern-/Slicerbasis erneut. Geschuetzte Verwaltungsfelder benoetigen keinen erfundenen
Druckparameter-Default, muessen aber vollstaendig klassifiziert sein.

### Aufgabe 1: Versionierter Katalogvertrag und sichere Versionsauswahl

**Files:** Create `orcaone/profile_schema.py`, `tests/test_profile_schema.py`;
Create `orcaone/profile_schemas/manifest.json`.

**Interfaces:** `load_catalog(slicer: str, version: str) -> dict | None`;
`validate_value(option: dict, value: str | list[str]) -> list[dict]`.
Katalog: `id`, `slicer`, `version`, `source_commit`, `complete`, `options` nach Profilart.
Manifest ist eine Liste explizit getesteter Versionen, keine offene Semver-Range.

- [ ] Test fuer unbekannte Version und explizite Typpruefung schreiben:

```python
from orcaone.profile_schema import load_catalog, validate_value

def test_future_version_is_not_guessed():
    assert load_catalog("OrcaSlicer", "999.0.0") is None

def test_invalid_numeric_text_is_rejected():
    spec = {"type": "coFloat", "min": 0, "max": None, "nullable": False,
            "enums": [], "dimension": "scalar", "complete": True}
    assert validate_value(spec, "nan")[0]["code"] == "invalid_number"
    assert validate_value(spec, "0.2") == []
```

- [ ] `pytest tests/test_profile_schema.py -q` rot nachweisen.
- [ ] Loader mit exaktem Manifest-Lookup implementieren. Pfade nur aus Manifest,
  keine Pfadbildung aus frei uebergebenen Slicer-/Versionsstrings.
- [ ] Validierer fuer Bool/Int/Float/Percent/FloatOrPercent, String, Enum, Vektoren,
  Nullable und strukturierte Typen aufbauen. Zahlen mit `Decimal`, endliche Werte;
  Bool nicht als beliebige Zahl akzeptieren. Unbekannter Typ liefert `unsupported_type`.
  `0`/`1`, `nil`, Stringliste und Prozentzeichen entsprechend jeweiligem Katalog pruefen.
- [ ] Tests fuer Infinity, leere Werte, Enum unbekannt, `nil` nur nullable und falsche
  Listenform ergaenzen. Keine Normalisierung unbekannter Felder.
- [ ] Tests gruen; Loader hat bis Aufgabe 2 keine behauptete vollstaendige Release-Abdeckung.

### Aufgabe 2: Reproduzierbare Parameterkataloge beider Releases

**Files:** Create `tools/make_profile_schema.py`, `tools/profile_schema_rules.json`,
`tests/test_make_profile_schema.py`, `orcaone/profile_schemas/orca-2.4.2.json`,
`orcaone/profile_schemas/snorca-2.4.0.json`; Modify Manifest aus Aufgabe 1.
Read `tools/make_options.py`; alte `options.json` und Transfer-Semantik nicht ersetzen.

**Interfaces:** `extract_catalog(config_text: str, preset_text: str, rules: dict) -> dict`;
`build_catalog(slicer: str, version: str, source_dir: Path) -> dict`.
Fehlerklasse `SchemaBuildError` mit `code`, `key`, `expression`, `source_line`.

- [ ] Synthetischen Quellen-Test schreiben; keine fremden Tooltiptexte in Fixtures kopieren:

```python
import pytest
from tools.make_profile_schema import extract_catalog, SchemaBuildError

def test_unknown_default_expression_blocks_build():
    config = 'def = this->add("speed", coFloat); def->set_default_value(new ConfigOptionFloat(compute_unknown()));'
    preset = 'static std::vector<std::string> s_Preset_print_options {"speed"};'
    with pytest.raises(SchemaBuildError) as exc:
        extract_catalog(config, preset, {})
    assert exc.value.code == "unresolved_default"
    assert exc.value.key == "speed"
```

- [ ] `pytest tests/test_make_profile_schema.py -q` rot nachweisen.
- [ ] Extraktion in getrennten Schritten implementieren: Definitionsbloecke, Profilart-
  Mitgliedschaften, Default-Konstruktoren, Enum-Mappings, Grenzen, Dimensionen und Rollen.
  Verschachtelte Klammern/Strings mit kleinem Tokenizer erfassen; nicht mit unbeschraenktem
  Regex bis zum naechsten `add` semantische Zuordnung vortaeuschen. Kein `eval`/C++-Ausfuehren.
- [ ] Literalparser erlaubt Zahlen, Bool, Strings, Listen, Prozentkonstruktoren und
  Punkte. Symbolische Konstanten, Enum-Defaultnamen, kopierte Definitionen und Schleifen
  explizit anhand der gepinnten Quelle aufloesen. Jede manuelle Regel enthaelt Commit,
  Feld, Quellfundstelle und erwarteten Ausdruck; geaenderter Ausdruck stoppt den Build.
- [ ] Alle Vektoren klassifizieren: Reihenfolge/Dimension niemals aus Listenlaenge
  raten. Flow-, Kopf-, Material- und Punktlisten getrennt. Technische Metadaten,
  Referenzen und bekannte Secrets als Rollen markieren.
- [ ] Protokoll ausgeben: erwartete/gelesene Profilfelder, nicht klassifizierte Felder,
  Defaults, Dimensionen und Regelabdeckung. Ein fehlendes Feld, Default oder ungepruefte
  Normalisierung verhindert `complete=True`; kein stilles Weglassen aus dem Nenner.
- [ ] Build gegen vorhandene gepinnte Quellen; fehlende benoetigte Header gezielt
  unter `slicer-src/` vom exakten Commit nachladen. Ausgabe zunaechst temporaer,
  erst nach vollstaendiger Pruefung als Release-Katalog uebernehmen.
- [ ] Tests fuer Inline-Enums, Makro-Konstanten, Nullable-Schleifen, kopierte Defaults,
  Kommentare/escaped Strings, strukturierte Werte und deterministische Ausgabe.
  Katalogtests offline ohne `slicer-src/` lauffaehig halten.
- [ ] `pytest tests/test_make_profile_schema.py tests/test_profile_schema.py tests/test_transfer.py -q` gruen.

**Gate:** Falls die Quellabdeckung nicht beweisbar ist, Report liefern und an diesem
Punkt die Katalogarbeit fortsetzen. Keine Editier-/Publish-Freigabe durch Raten erzeugen.

### Aufgabe 3: Effektive Werte und slicerspezifische Normalisierung

**Files:** Create `orcaone/profile_normalize.py`, `tests/test_profile_normalize.py`;
Create `tests/fixtures/profile_editor/normalization.json` samt Herkunftsangaben.
Modify `orcaone/resolver.py` nur um einen zusaetzlichen Aufrufweg; bestehende APIs erhalten.

**Interfaces:** `resolve_values(catalog: dict, kind: str, layers: list[dict], context: dict) -> dict`.
`layers` von Wurzel zu Kind; Ergebnis `values`, `origins`, `complete`, `issues`.
Context: `chain_complete`, `extruder_count`, `filament_count`, `flow_variants`.

- [ ] Herkunft und fehlende Kette testen:

```python
from orcaone.profile_normalize import resolve_values

def test_incomplete_chain_cannot_be_flattened():
    catalog = {"id": "test", "options": {"process": {}}, "complete": True}
    result = resolve_values(catalog, "process", [{"id": "child", "values": {}}],
                            {"chain_complete": False})
    assert result["complete"] is False
    assert any(x["code"] == "parent_missing" for x in result["issues"])
```

- [ ] `pytest tests/test_profile_normalize.py -q` rot nachweisen.
- [ ] Reihenfolge implementieren: bekannte Defaults kopieren, Elternwerte in Reihenfolge,
  Kindwerte, dann kataloggebundene Normalisierung. Herkunft je Feld inklusive Default-
  Schema-ID erhalten; unknown getrennt konservieren. Eingabedaten nie mutieren.
- [ ] Folgende Regelgruppen je Release aus `Preset::normalize` abbilden: fehlende
  Prozesswerte, Extruder-/Filamentzahl, deklarierte Flow-Varianten und vektorielle
  Erweiterung. Keine pauschale "ein Wert fuer alle"-Regel ausser bei nachgewiesener Semantik.
- [ ] Referenzfixture fuer Single-Extruder, mehrere Koepfe und verschiedene Flow-
  Laengen anlegen, jeweils Quelle und erwartete Ausgabe angeben. Durch Quelle abgeleitete
  Fixtures als solche markieren; sie ersetzen keine echte Slicer-Roundtrip-Abnahme.
- [ ] Tests: Defaults plus zwei Eltern, Zyklus, fehlender Default, unbekanntes Feld,
  String gegen Liste, Prozent erhalten, Flow != Kopfzahl und nicht veraenderte Eingaben.
- [ ] `pytest tests/test_profile_normalize.py tests/test_resolver.py tests/test_overview.py -q` gruen.

### Aufgabe 4: Dokumente und selektive Einzel-/Batch-Patches

**Files:** Create `orcaone/profile_edit.py`, `tests/test_profile_edit.py`.
Read `scanner.Profile`, `Resolver` und Verwaltungsregeln aus `operations.py`.

**Interfaces:** `make_document(profile_id: str, profile: Profile, resolver: Resolver, catalog: dict) -> dict`;
`apply_patches(documents: dict, patches: list[dict], catalogs: dict) -> dict`;
`reference_impacts(documents: dict, replacements: dict) -> list[dict]`.
Patch-Ergebnis: `documents`, `issues`; bei Fehlern kein partiell veraendertes Ergebnis.

- [ ] Test mit synthetischem vollstaendigem Katalog schreiben:

```python
from copy import deepcopy
from orcaone.profile_edit import apply_patches

def test_batch_does_not_touch_unselected_document():
    field = {"type": "coFloat", "nullable": False, "min": 0, "max": None,
             "enums": [], "dimension": "scalar", "role": "parameter", "complete": True}
    catalog = {"id": "test", "complete": True, "options": {"process": {"speed": field}}}
    docs = {k: {"id": k, "kind": "process", "schema_id": "test", "own": {"speed": "10"},
                "effective": {"speed": "10"}, "unknown": {}, "complete": True}
            for k in ("a", "b")}
    before = deepcopy(docs)
    result = apply_patches(docs, [{"profile_id": "a", "op": "set", "key": "speed",
                                  "value": "20", "indices": None}], {"test": catalog})
    assert result["issues"] == []
    assert result["documents"]["b"] == before["b"]
    assert result["documents"]["a"]["own"]["speed"] == "20"
    assert docs == before
```

- [ ] `pytest tests/test_profile_edit.py -q` rot nachweisen.
- [ ] Patches erst vollstaendig validieren, dann auf Kopien anwenden. `set`, `reset`,
  `bind_add`, `bind_remove` unterscheiden; Verwaltung von Name/ID/Machine-Modell separat.
  Indizes gegen katalogdefinierte Dimension pruefen; nicht ausgewaehlte Elemente erhalten.
- [ ] Strukturfehler mit Profil/Feld/Dimension liefern; Plausibilitaet getrennt.
  Null/leer nie als Reset interpretieren. Unbekannte Felder unberuehrt erhalten.
- [ ] Tests fuer ungueltiges zweites Batch-Profil ohne Teilresultat, Reset nur eigener
  Ueberschreibung, geerbten Vektor, mehrere Flow-Werte, geschuetzte Metadaten und Secrets.
- [ ] Referenzanalyse untersucht alle verbleibenden Profile lesend; ausgewaehlte
  Schreibmenge nie automatisch vergroessern. Nicht auswertbare Bedingung als unknown.
- [ ] Gezielte Tests plus vorhandene Operations-/Transfer-Tests gruen.

### Aufgabe 5: Persistente Revisionen, Branches und Entwuerfe

**Files:** Create `orcaone/profile_store.py`, `orcaone/profile_history.py`,
`tests/test_profile_store.py`, `tests/test_profile_history.py`.

**Interfaces:** Store `put_object(instance_id: str, obj: dict) -> str`,
`get_object(instance_id: str, object_id: str) -> dict`,
`replace_ref(instance_id: str, ref_id: str, expected: int, value: dict) -> dict`.
History `save_revision(instance_id: str, document: dict, parents: list[str], provenance: dict) -> str`,
`save_state(instance_id: str, profiles: dict[str, str], removed: list[str], note: str) -> str`,
`create_branch(instance_id: str, name: str, state_id: str, selected: list[str]) -> dict`,
`save_draft(instance_id: str, branch_id: str, expected: int, documents: dict) -> dict`.
Alle Fehlertypen `HistoryError(code: str, **params)`; API serialisiert keine Pfade.

- [ ] CAS und Unveraenderlichkeit zuerst testen:

```python
import pytest
from orcaone.profile_store import put_object, get_object, replace_ref, HistoryError

def test_stale_generation_does_not_overwrite(data_dir):
    ref = "a" * 32
    first = replace_ref("inst1", ref, 0, {"state": "first"})
    assert first["generation"] == 1
    with pytest.raises(HistoryError) as exc:
        replace_ref("inst1", ref, 0, {"state": "second"})
    assert exc.value.code == "draft_conflict"

def test_objects_survive_later_saves(data_dir):
    old = put_object("inst1", {"value": "old"})
    put_object("inst1", {"value": "new"})
    assert get_object("inst1", old) == {"value": "old"}
```

- [ ] Beide neuen Testdateien rot nachweisen.
- [ ] IDs streng validieren: Instanz-IDs nur bestehendes sicheres ID-Format, Objekt-IDs
  SHA-256, Ref-/Profil-IDs generierte Hex-UUIDs. Pfadtraversal und Symlink-Ausbruch ablehnen.
  JSON kanonisch schreiben, Hash beim Lesen pruefen; bekannte Secrets vor Objekterzeugung
  entfernen, niemals nur in UI verstecken. Persistierte Dokumente enthalten keine Roh-`.conf`.
- [ ] Zuerst Objektdatei flushen/fsync, dann atomar per `settings.replace` veroeffentlichen.
  Ref-CAS unter prozessinterner Sperre plus exklusiver Instanz-Schreibsperre fuer zweite
  OrcaOne-Prozesse. Lock mit PID und Prozessstartzeit; verwaiste Lockdatei nur bei
  nachgewiesen beendetem Eigentuemer freigeben. Bei unklarer Prozessidentitaet Konflikt
  melden; nie einen fremden Prozess beenden oder allein nach Dateialter entsperren.
- [ ] Branchzustand aus ausgewaehlten IDs bilden. Nicht ausgewaehlte Profile sind keine
  Loeschungen; nur `removed` kennzeichnet gewollte Entfernung. Entwurf immer getrennt.
- [ ] Tests fuer Integritaetsfehler, fehlendes Objekt, zweiten Writer, ungueltige ID,
  disk-full beim Objekt/Ref, Branch mit Teilmenge, Notiz Unicode, keine Secretwerte im Store.
- [ ] `pytest tests/test_profile_store.py tests/test_profile_history.py tests/test_snapshot.py -q` gruen.

### Aufgabe 6: Diff, Dreiwege-Merge und selektive Wiederherstellung

**Files:** Create `orcaone/profile_merge.py`, `tests/test_profile_merge.py`;
Modify History/Testdatei aus Aufgabe 5.

**Interfaces:** `diff_values(before: dict, after: dict) -> list[dict]`;
`merge_values(base: dict, target: dict, source: dict, selected_keys: list[str]) -> dict`;
`merge_parents(target_id: str, source_id: str, fully_integrated: bool) -> list[str]`;
`restore_state(instance_id: str, branch_id: str, historical_state: str, selected: list[str], expected: int) -> dict`.
Merge liefert `values`, `conflicts`; fehlende Keys sind separate Anwesenheitszustaende.

- [ ] Offene Aenderungen nach partieller Uebernahme testen:

```python
from orcaone.profile_merge import merge_values, merge_parents

def test_partial_merge_preserves_remaining_source_change():
    base = {"speed": "10", "height": "0.2"}
    source = {"speed": "20", "height": "0.3"}
    first = merge_values(base, base, source, ["speed"])
    assert first["values"] == {"speed": "20", "height": "0.2"}
    assert merge_parents("target", "source", False) == ["target"]
    second = merge_values(base, first["values"], source, ["height"])
    assert second["values"]["height"] == "0.3"
```

- [ ] Test rot; zentrale Entscheidungsregel implementieren:

```python
# b/t/s include presence; MISSING is distinct from None or an empty string.
if t == s:
    result = t
elif t == b:
    result = s
elif s == b:
    result = t
else:
    conflict = {"base": b, "target": t, "source": s}
```

- [ ] Konflikte nie durch Reihenfolge entscheiden. Arrays ohne eindeutige Dimension
  ganz behandeln. G-Code nur vergleichen, nicht ausfuehren oder automatisch zusammensetzen.
  Unterschiedliche Schema-IDs vor Merge kompatibel abbilden oder blockieren.
- [ ] Restore erstellt neue Revisionen nur fuer Auswahl und erhaelt andere Branch-
  Eintraege. Historische Loeschung nur explizit; Referenzfehler werden nicht versteckt.
- [ ] Tests: Remove-vs-edit, Rename-vs-edit auf stabiler ID, ohne gemeinsamen Vorfahren,
  beide gleich, unterschiedliche Default-Herkunft und identische effektive Werte.
- [ ] Gesamte History-/Merge-Tests gruen; partielle Uebernahme bekommt Quellenprovenienz,
  aber keinen falschen zweiten Merge-Elternteil.

### Aufgabe 7: Externe Staende und stabile Profilidentitaet

**Files:** Modify `orcaone/profile_history.py`; Create `tests/test_profile_observe.py`.
Modify `orcaone/overview.py` nur am abgeschlossenen Scan-Hook.

**Interfaces:** `observe(instance: Instance, documents: dict, fingerprint: str, stable: bool) -> dict`;
`match_identity(index: dict, user_folder: str, kind: str, path: str, name: str) -> dict`.
Beobachtungen erhalten eigene Referenz; Branch/Entwurf bleibt unangetastet.

- [ ] Instabile Abwesenheit testen:

```python
from orcaone.profile_history import observe
from orcaone.model import Instance

def test_unstable_read_does_not_record_deletions(tmp_path, data_dir):
    inst = Instance(id="inst1", slicer="OrcaSlicer", data_dir=tmp_path, source="manual")
    result = observe(inst, {}, "fingerprint", stable=False)
    assert result["recorded"] is False
    assert result["removed"] == []
```

- [ ] Test rot; Scan-Konsistenz durch Vor-/Nachfingerprint und parsebaren Bestand
  pruefen. Loeschung erst durch zweiten konsistenten Scan bestaetigen; keine blockierende
  lange Wartezeit im Request. Fehlerzustand anzeigen statt unbegrenzt erneut scannen.
- [ ] Eigene Umbenennung ueber stabile ID verbinden. Externe unklare Umbenennung als
  neuer Kandidat plus fehlender alter Pfad; keine Hash-/Namensaehnlichkeit als Beweis.
  Aktiver Benutzerordner ist Teil der Identitaet und darf keine Zuordnung uebernehmen.
- [ ] Tests fuer unveraenderten Scan ohne neue Revision, externe Bearbeitung bei
  offenem Entwurf, Konto-/Ordnerwechsel und Dateien, die zweimal verschwinden/auftauchen.
- [ ] Keine laufenden Slicer stoppen. Beobachtung nur lesen; Ursache mit "aus Slicer
  eingelesen" benennen, Cloud/User/Update nicht behaupten.
- [ ] Observe-/Snapshot-/Overview-Tests gruen.

### Aufgabe 8: API fuer Katalog, Editor und Timeline

**Files:** Modify `orcaone/app.py`, `orcaone/static/api.js`;
Create `tests/test_profile_api.py`.

**Interfaces:** Unter `/api/instances/{id}/profile-editor`:
`GET /catalog`, `GET /document?kind=&name=`, `POST /patch-preview`,
`POST /branches`, `PUT /drafts/{branch_id}`, `POST /states`,
`POST /diff`, `POST /merge-preview`, `POST /restore-preview`, `GET /history`.
Mutationen an Entwuerfen verlangen `expected_generation`; Scopes immer explizite ID-Listen.
History-Antwort paginiert mit opakem Cursor/Limit 50, maximal 200.

- [ ] API-Tests mit vorhandenem `server`/`call`-Fixture zuerst schreiben:

```python
from conftest import call

def test_unknown_instance_never_creates_history(server, data_dir):
    status, body = call(server + "/api/instances/does-not-exist/profile-editor/branches",
                        "POST", {"name": "Trial", "selected": []})
    assert status == 404
    assert not (data_dir / "snapshots" / "profiles").exists()
```

- [ ] Rot nachweisen. Payloads nach bestehendem dict-Stil pruefen; 400 fuer Formfehler,
  404 unbekannte IDs, 409 Generation/Schema/Referenzkonflikt. Profil-ID immer zur
  Zielinstanz pruefen. Externe Requests unterliegen bestehendem Host-/Origin-Schutz.
- [ ] UI bekommt keine Secretwerte, internen Dateipfade oder Secret-Hashes. Mutation
  schreibt nur Store/Entwurf; Tests pruefen unveraenderte Slicer-Dateibytes.
- [ ] Tests fuer zwei Clients mit gleicher Generation, uebergrossen Scope,
  fremde Instanz-ID, falschen Cursor und Secret in Diff/Fehlermeldung.
- [ ] API-Tests und bestehende `tests/test_app.py` gruen.

### Aufgabe 9: Sichere Uebernahme und Wiederanlauf

**Files:** Create `orcaone/profile_publish.py`, `tests/test_profile_publish.py`;
Modify `orcaone/operations.py`, bestehende `/plan`- und `/apply`-Anbindung.

**Interfaces:** `prepare_changes(instance: Instance, selection: dict, expected: dict) -> list[dict]`;
`check_target(expected: dict, current: dict) -> None`;
`write_receipt(instance_id: str, receipt: dict) -> str`;
`recover_receipt(instance: Instance, receipt_id: str) -> dict`.
Operation `profile_publish` benennt feste Revisionen, Benutzerordner, Schema-ID und
Live-Fingerprint; mutable Branch-Namen reichen nicht als Publikationsquelle.

- [ ] Wechsel nach Preview zuerst testen:

```python
import pytest
from orcaone.profile_publish import check_target
from orcaone.operations import OperationError

def test_changed_user_folder_blocks_before_writing():
    expected = {"folder": "default", "schema_id": "OrcaSlicer@2.4.2", "fingerprint": "a"}
    current = {**expected, "folder": "account"}
    with pytest.raises(OperationError) as exc:
        check_target(expected, current)
    assert exc.value.code == "plan_outdated"
```

- [ ] Rot nachweisen; aus festen Revisionen benoetigte eigene Profile/`.info` und
  ausgewaehlte Referenzpatches erzeugen. Gleichnamige Herstellerprofile nie ueberschreiben.
  Effektiv uebernommene Profile nach bewiesener Root-Semantik speichern, keine kuenstliche
  `is_custom_defined`-Flag setzen. Aktuelle Ziel-Credentials erhalten.
- [ ] Bestehenden Planner ausbauen; unveraenderte Dateien nicht schreiben. Bei
  Abhaengigkeiten ausserhalb der Auswahl blockieren. Geteilte Profile in Preview nennen.
- [ ] Receipt-Zustaende: `prepared`, `writing`, `verified`, `rolled_back`, `needs_review`.
  Vor Schreiben durable Receipt mit Backup-ID und Vor-/Nachfingerprints ablegen.
  Nach Rescan erst `verified`; `not_loaded` ist fuer neue Publikation kein Erfolg.
- [ ] Bei Fehler nur Dateien zurueckrollen, deren aktueller Zustand den eigenen
  geschriebenen Bytes entspricht; fremde Abweichung -> `needs_review`, kein blindes Restore.
  Nach Neustart Receipt und Dateien lesen; vollstaendigen Nachzustand verifizieren,
  Vorzustand als nicht uebernommen erkennen, Mischzustand als reparaturbeduerftig anzeigen.
- [ ] Integrationstests: je eine Aenderung fuer alle drei Profilarten, falsche Version,
  laufender Slicer, geaenderte Datei, disk-full, Abbruch zwischen JSON/INFO, Rescanfehler,
  fehlgeschlagener Rollback und Auswahl ohne Nebenwirkungen auf andere Dateien.
- [ ] `pytest tests/test_profile_publish.py tests/test_operations.py tests/test_backup.py tests/test_guard.py -q` gruen.

### Aufgabe 10: Duesen-/Modellzuordnung und Vorschlaege

**Files:** Create `orcaone/profile_variants.py`, `tests/test_profile_variants.py`;
Modify `orcaone/overview.py`, `orcaone/static/common.js` nur hinsichtlich Gruppierung.

**Interfaces:** `group_profiles(documents: list[dict]) -> list[dict]`;
`variant_changes(source: dict, target_model: str, configuration: dict, choices: dict) -> dict`;
`suggest_nozzle_changes(document: dict, target: dict, catalog: dict) -> list[dict]`.
Gruppen behalten alle Profil-IDs und getrennte Host-Zuordnungen; diameter nicht als ID.

- [ ] Gruppierung ohne Zusammenlegen von Geraeten testen:

```python
from orcaone.profile_variants import group_profiles

def test_grouping_keeps_same_model_profiles_distinct():
    docs = [{"id": x, "kind": "machine", "name": x, "effective": {
        "printer_model": "Custom", "nozzle_diameter": ["0.4"], "print_host": host}}
        for x, host in [("a", "http://printer-a"), ("b", "http://printer-b")]]
    groups = group_profiles(docs)
    members = [p for g in groups for p in g["profiles"]]
    assert {p["id"] for p in members} == {"a", "b"}
    assert len(members) == 2
```

- [ ] Rot nachweisen; Gruppierung aus eindeutigem Modell-/Herstellerbezug plus
  expliziter Nutzerzuordnung bilden. Mehrdeutige Custom-Modelle nicht allein durch
  gleichen Namen verbinden. Physische Adressen nicht in Gruppenidentitaet umschreiben.
- [ ] Variante als eigenes Preset speichern; Modellzuordnung, Duesenarray und
  Druckername getrennt. Referenzpatches und gemeinsame Nutzung/Kopie aus `choices`.
- [ ] Vorschlaege als Daten `key`, `before`, `after`, `reason`, `source` liefern.
  Zunaechst nur aus vorhandenem passenden Zielprofil oder validierten Zielgrenzen ableiten;
  ohne Beleg keinen Zahlenwert erfinden. Keine automatische Skalierung von Temperatur,
  Geschwindigkeit, Flow-Limit oder G-Code. Anwenden nur per gewaehltem Patch.
- [ ] Tests fuer 0,5-mm-Zuordnung mit erhaltenen Werten, gleicher Durchmesser/High Flow,
  gemischte Koepfe, Parent fehlend, widerspruechliche Kompatibilitaetsbedingung und
  Originalentfernung ohne mitgewaehlte Referenzupdates.
- [ ] Variant-/Overview-/Camera-Tests gruen. Dokumentierte native Dropdown-Grenze erhalten.

### Aufgabe 11: Gemeinsamer Editor und Batch-Oberflaeche

**Files:** Create `orcaone/static/pages/profile-editor.js`, `profile-field.js`,
`profile-batch.js`; Modify `filament-editor.js`, `filamente.js`, `prozesse.js`,
`uebersicht.js`, `orcaone/static/style.css`, `orcaone/static/texts/de.js`, `en.js`.
Create `tests/test_profile_ui_contract.py` fuer stabile Server-/Textvertraege.

**Interfaces:** Editor Props `document`, `catalog`, `draftGeneration`; Emits
`patches`, `save-draft`, `open-history`, `close`. Batch emittiert identische Patchform
aus Aufgabe 4; Feldkomponente erhaelt Option/Value/Origin/Issues, keine Dateipfade.

- [ ] Vor Umsetzung vorhandenen UI-Stil und Impeccable-/Frontend-Skill lesen;
  kein neues Layoutsystem oder externe Komponentenbibliothek einfuehren.
- [ ] API-Vertragstest fuer drei Profilarten und Test identischer neuer DE/EN-Keys
  schreiben; rot nachweisen. Test prueft Antworten/Texte, nicht Quellcode-Substringkosmetik.
- [ ] Parametereingaben nach Katalog bauen: Bool, Enum, numerisch/Prozent, String,
  G-Code, Punktlisten und dimensionierte Vektoren. Vue-Escaping erhalten, kein `v-html`.
  Tastaturfokus, Labels, Einheiten und feldbezogene Fehler anbinden.
- [ ] Herkunft und Reset getrennt zeigen; unbekannte Felder lesend. Unterschiedliche
  Batchwerte als "Mehrere Werte"; bloesses Oeffnen/Schliessen erzeugt keinen Patch.
  Listenkompatibilitaet mit Hinzufuegen/Entfernen statt leerer Liste als "aus".
- [ ] Bestehende Seiten um Einstiege erweitern; einfache Filamentaktionen erhalten.
  Grosse Parameterlisten erst beim Oeffnen laden; Suche ueber Label und technischen Key.
- [ ] Isolierten Fixture-Server mit Browser-Skill pruefen: Profil oeffnen, suchen,
  eigenen/geerbten Wert editieren, Reset, ungueltiger Wert, Batch Teilmenge, zweite
  Browseransicht mit Generationkonflikt, schmale Ansicht und Tastaturbedienung.
- [ ] UI-Vertraege/Regressionstests gruen; Browserergebnisse mit konkreten Aktionen
  festhalten. Kein echter Slicer fuer diese UI-Pruefung.

### Aufgabe 12: Timeline-, Merge- und Publish-Oberflaeche

**Files:** Create `orcaone/static/pages/profile-timeline.js`, `profile-merge.js`;
Modify `profile-editor.js`, `profile-batch.js`, `zusammenhaenge.js`, `orcaone/static/plan.js`,
Texte/CSS; Extend `tests/test_profile_api.py` und `tests/test_profile_ui_contract.py`.

**Interfaces:** Timeline Props `instanceId`, `selectedProfileIds`; Emits `select-state`,
`create-branch`, `restore-selection`, `compare`. Merge zeigt `conflicts` aus Aufgabe 6
und liefert ausdrueckliche Feldentscheidungen; Publish nutzt bestehendes Plan-Modal.

- [ ] API-Test fuer selektives Restore und zweites Profil unveraendert schreiben;
  rot nachweisen. Branch-Erstellung ohne versteckte Profilaufnahme pruefen.
- [ ] Timeline mit Notiz/Zeitpunkt/Quelle und Profilfilter anzeigen. Begriffe aus
  Spezifikation verwenden; Versuchszweig und reale Duesenvariante sichtbar unterscheiden.
  Anzeigewechsel nicht mit "In Orca uebernehmen" verbinden.
- [ ] Vergleich mit Einheiten, Herkunft, Dimensionen und Mehrzeilentext darstellen.
  Konflikte je Feld entscheiden; globaler Button darf nur ausdruecklich gewaehlte
  Konflikte loesen, nichts still ueberschreiben.
- [ ] Nutzer waehlt fuer Save/Branch/Diff/Merge/Restore/Publish Scope. Bei fehlenden
  Abhaengigkeiten Auswahlkorrektur anbieten; keinen Checkboxumfang automatisch vergroessern.
- [ ] Publikationsstatus pro Profil aus Receipt/Nachzustand anzeigen. "Gespeichert"
  bedeutet lokale Historie; "In Orca uebernommen" ausschliesslich verifizierte Publikation.
- [ ] Browser-Pruefung: Versuch von altem Stand, zwei abweichende Aenderungen, partieller
  Merge, spaeterer Rest-Merge, Restore eines Profils, externe Aenderung, blockierter
  Publish bei laufendem Slicer, erfolgreiche Fixture-Uebernahme und Rueckkehr zur Timeline.
- [ ] Aktualisierte API-/UI-Tests gruen; gesamte bestehende Profilverwaltung erreichbar.

### Aufgabe 13: Cross-Slicer-Verluste, Build und Abnahme

**Files:** Modify `orcaone/transfer.py`, `orcaone/importer.py` nur am neuen Editor-
Konvertierungsweg; Modify `tools/build.py`; Extend `tests/test_transfer.py`,
`tests/test_importer.py`; Create `tests/test_profile_release.py`,
`docs/PROFILE-ABNAHME.md`; Update `docs/HANDBUCH.md`, `docs/STAND.md`,
`ORCAONE_SPEC.md`, `CLAUDE.md`, gegebenenfalls README-Funktionsliste.

**Interfaces:** `conversion_report(source: dict, target_catalog: dict) -> dict` liefert
`document`, `losses`, `issues`; keine Publikation. Verlust muss pro Feld vor Zieluebernahme
bestaetigt sein. Bestehende Transferaktionen nicht unbemerkt umdefinieren.

- [ ] Test fuer Flow-Wertverlust schreiben:

```python
from orcaone.transfer import conversion_report

def test_scalar_target_reports_discarded_vector_values():
    source = {"kind": "process", "effective": {"speed": ["100", "200"]}}
    target = {"options": {"process": {"speed": {"type": "coFloat", "dimension": "scalar",
                "nullable": False, "complete": True}}}}
    report = conversion_report(source, target)
    assert any(x["key"] == "speed" for x in report["losses"])
```

- [ ] Rot nachweisen; neue Zielkonvertierung nutzt Katalog/Dimensionen und nennt
  geloeschte/unbekannte Felder, Enumwechsel und Vektorkuerzung. Ohne Nutzerentscheidung
  keine verlustbehaftete neue Editor-Uebernahme. Cross-Slicer-Staende als Kopie mit
  Provenienz, keine faelschliche gemeinsame Abstammung.
- [ ] PyInstaller `--add-data` fuer Katalogordner ergaenzen; Release-Test liest Manifest
  und alle benoetigten Kataloge ohne Slicer-Quellen/Netz. Keine neuen Abhaengigkeiten installieren.
- [ ] Handbuch beschreibt tatsaechliche Funktionen, Branch/Variante-Unterschied,
  native Gruppierungsgrenze, lokale Historie, Secrets/Backups und Zukunftsversionen.
  Bisherige ausdrueckliche Nur-Lesen-Beschreibung fuer Prozesse aktualisieren.
- [ ] `pytest -q` komplett ausfuehren, Pass/Fail/Skip berichten; Windows-Build nur wenn
  vorhandene Build-Abhaengigkeiten verfuegbar. Linux-Test/Build als extern ausstehend
  kennzeichnen, falls in dieser Umgebung nicht ausfuehrbar.
- [ ] Abnahmeprotokoll mit Matrix je Slicer/Version/Plattform: Laden/Speichern aller
  Profilarten, 0,5-mm-Fall, Multikopf/Flow, selektives Restore, externer Edit und Backup.
  Ergebnisse nur mit Tester, Version und Datum als bestanden markieren.
- [ ] Nutzer testet OrcaSlicer; Snapmaker-Orca-Ersteller bekommt auf ausdruecklichen
  Sendeauftrag das Protokoll. Ohne Ergebnis keine Behauptung praktischer Snapmaker-Abnahme.
- [ ] Ganzen Branch unabhaengig reviewen, Findings verifizieren und relevante
  Regressionstests wiederholen. Commit-/Push-Workflow erst auf gesonderten Auftrag.

## Abhaengigkeiten und kontrollierte Parallelisierung

```text
1 -> 2 -> 3 -> 4 -> 8 -> 9 -> 10 -> 11 -> 12 -> 13
               5 -> 6 -> 7 -> 8
```

Aufgabe 5 kann nach Festlegung der Dokumentvertraege parallel zu 2/3 laufen;
Store-Worker aendert weder Resolver noch Schema. Aufgaben 6/7 bauen auf 5 auf.
Aufgabe 7 benoetigt zusaetzlich die Dokumentaufloesung aus 3/4; Aufgabe 8 benoetigt
4-7. Aufgabe 13 benoetigt die fertigen Kataloge und alle Nutzerablaeufe aus 1-12.
`app.py`, `operations.py`, Texte und gemeinsame UI-Dateien jeweils nur einem
Implementierer gleichzeitig zuweisen. Koordinator prueft Schnittstellen und Diffs.

## Abdeckungspruefung des Plans

| Spezifikationsabschnitt | Aufgaben |
|---|---|
| Versionen, Parameter, Vererbung, vollstaendige Werte | 1-4 |
| Einzel-/Batch-Bearbeitung und freier Scope | 4, 8, 11 |
| Duesen, gleiche Groesse, Multikopf, Vorschlaege | 2-4, 10-11 |
| Originale, Zusammenfuehren, Referenzen | 4, 6, 9-10 |
| Timeline, Branches, selektive Wiederherstellung | 5-6, 12 |
| Externe Aenderungen, Identitaet, konkurrierende Clients | 5, 7-9 |
| Sichere Uebernahme, Recovery, Cloud-Grenzen | 9, 12 |
| API, vorhandene Seiten, DE/EN, Build | 8, 11-13 |
| Regression, Quellenbelege, praktische Abnahme | 2-3, 9-13 |

Praktische Slicer-Tests, echte 0,5-mm-Referenzdaten, Linux-Ausfuehrung und
Snapmaker-Testperson sind externe Nachweise, keine still uebersprungenen Planaufgaben.
Ein nicht bestandener Katalog-/Roundtrip-Nachweis darf nicht durch eine gruene
selbst geschriebene Unit-Test-Fixture als erledigt markiert werden.

## Ausfuehrungsempfehlung und Freigabe

Empfohlen: Subagent-gestuetzt gemaess Projektworkflow, mit klaren Dateigrenzen und
Review nach jedem Testzyklus. Die Datenverlust-/Referenzrisiken rechtfertigen die
zusaetzliche unabhaengige Pruefung; keine fuenf bis zehn gleichzeitigen Worker bei
vier verfuegbaren Slots. Alternativ Inline-Ausfuehrung mit abschliessendem Review.

Planstatus: zur Nutzerpruefung. Noch keine Produktdateien oder Tests implementiert.
Nach Planfreigabe bei Aufgabe 1 beginnen; Rebase-Basis und uncommittete Dokumente erhalten.

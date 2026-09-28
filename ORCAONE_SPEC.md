# OrcaOne – Spezifikation und Build-Prompt für Claude Code

Erweiterung vom 27.09.2026: vollständiger Profil-Editor für beide Slicer mit nutzerbestimmter Auswahl, effektiver Vererbung, Düsenvarianten und lokaler verzweigter Timeline. Maßgeblich sind [Editor-Design](docs/superpowers/specs/2026-09-27-profile-management-design.md) und [Anleitung](docs/PROFILE_EDITOR.md); frühere Nur-Lesen-Beschränkungen für Prozesse sind damit aufgehoben. Praktische Freigaben stehen ausschließlich im [Abnahmeprotokoll](docs/PROFILE-ABNAHME.md).

OrcaOne = Orca + U1 („One“). Bis 23.09.2026 hieß die App „Orfix“ (Orca + Fix), bis 21.09.2026 „Orcix“. Eine lokale Web-App, mit der man die Profile von OrcaSlicer und Snapmaker Orca (kurz SnOrca) überblicken, aufräumen, importieren und exportieren kann.

Stand: 21.09.2026. Die technischen Fakten in Abschnitt 4 stammen aus dem Quellcode von Snapmaker Orca 2.4.0 (github.com/Snapmaker/OrcaSlicer, Tag `v2.4.0`) und OrcaSlicer (github.com/OrcaSlicer/OrcaSlicer, Branch `main`). Am 21.09.2026 wurden sie gegen den Quellcode und eine echte SnOrca-Installation geprüft. Die Ergebnisse stehen in [docs/FINDINGS.md](docs/FINDINGS.md), der Plan für Phase 0 und 1 in [docs/PLAN.md](docs/PLAN.md). Wo diese Spezifikation und FINDINGS sich widersprechen, gilt FINDINGS.

## Start-Prompt für die erste Session

```
Lies ORCAONE_SPEC.md vollständig. Lege dann eine kurze CLAUDE.md mit den harten
Regeln aus Abschnitt 2, den Konventionen aus Abschnitt 3 und einem Verweis auf
diese Spezifikation an. Prüfe anschließend die Fakten aus Abschnitt 4 rein
lesend gegen meine echten Installationen von OrcaSlicer und Snapmaker Orca und
halte Abweichungen in docs/FINDINGS.md fest. Schlage mir danach den Plan für
Phase 0 und Phase 1 vor. Schreib keinen Anwendungscode, bevor ich den Plan
freigegeben habe.
```

---

## 1. Worum es geht

Die Profilverwaltung in OrcaSlicer und SnOrca ist unübersichtlich. Konkrete Probleme, die OrcaOne lösen soll:

- Es gibt keine Übersicht, welche Drucker, Filamente und Prozessprofile installiert sind und welches Filament zu welchem Drucker gehört.
- Beim Öffnen von 3MF-Dateien landen Profile und Drucker im Slicer, die man nicht haben will.
- SnOrca versteckt die markenübergreifende Filamentbibliothek von Orca (Details in 4.7).
- Profile zwischen Orca und SnOrca zu übertragen ist mühsam, weil Profile voneinander erben und an Druckernamen gebunden sind.

Umfang: beide Slicer, mehrere Installationen parallel, Übertragen zwischen ihnen. Bei OrcaSlicer sowohl stabile Versionen (2.4.x, Systemprofile als JSON) als auch die Nightly (2.5.0-dev, Systemprofile als binäre `.opc`). Linux (Kubuntu, SnOrca 2.4 als AppImage, auch Flatpak möglich) und Windows sind gleichwertige Zielplattformen. macOS wird über die Pfaderkennung unterstützt, aber nicht getestet.

Bedienung: so einfach wie möglich. Zwei Seiten: „Übersicht" (Ist-Zustand) und „Verwalten". Der Kern ist das Filament-Handling: was zu welchem Drucker gehört, worauf ein Profil aufbaut, wie neue Filamente wie SUNLU nach SnOrca kommen und wie U1-Profile zwischen SnOrca und Orca wandern.

Mein Setup als Testfall: Snapmaker U1 (Toolchanger, vier Köpfe), Filamente von SUNLU und Material4Print. Material4Print bietet offizielle U1-Profile als ZIP an – ein guter Testfall für den Import.

Nicht-Ziele: kein Slicen, keine Druckersteuerung oder Geräteverbindungen, keine Cloud-Anbindung, vorerst kein Bearbeiten einzelner Einstellungswerte, kein Mehrbenutzer- oder Serverbetrieb.

## 2. Harte Regeln

Diese Regeln haben Vorrang vor allem anderen.

1. Während der Entwicklung schreibst du niemals in die echten Slicer-Datenverzeichnisse. Lesen ist erlaubt. Tests laufen nur gegen Fixtures im Repo oder gegen Kopien in einem temporären Verzeichnis.
2. OrcaOne schreibt ausschließlich in `user/**` und in die `<APP_KEY>.conf` eines Datenverzeichnisses. Niemals in `system/`, in Programmressourcen, Logs oder Caches.
3. OrcaOne schreibt nur, wenn der betroffene Slicer nicht läuft. Läuft er, zeigt OrcaOne die Instanz schreibgeschützt an und sagt, warum. Als laufend gilt ein Slicer, solange sein Prozess oder seine AppImage-Runtime existiert. Die Sperrdatei allein reicht nicht (FINDINGS 4.1).
4. Vor jedem Schreibvorgang erstellt OrcaOne ein vollständiges Backup des Datenverzeichnisses als ZIP, ohne `log/`, `cache/`, `web/`, `hms/`, `ota/`, `user/Temp/`, `user/*/temp/` und `user_backup-v*/`. Jedes Backup lässt sich in der Oberfläche wiederherstellen. Backups enthalten Zugangsdaten aus der `.conf` und gelten als vertraulich.
5. Jede Änderung läuft in zwei Schritten: Plan mit Liste aller Dateioperationen und Diff der .conf, dann Bestätigung durch mich, dann Ausführung, dann erneuter Scan zur Kontrolle.
6. Die .conf wird gelesen, gezielt an einzelnen Schlüsseln geändert und vollständig zurückgeschrieben. Alle anderen Schlüssel bleiben unverändert. Format wie vorgefunden: Einrückung 4 Leerzeichen (SnOrca, Orca bis 2.3.2) oder Tab (Orca ab 2.4.0), `sort_keys=True`, `ensure_ascii=False`, abschließendes `\n`, atomar schreiben (temporäre Datei plus `os.replace`, Dateirechte der alten Datei übernehmen). Unter Windows gehört eine Prüfsummenzeile ans Ende (siehe 4.3).
7. JSON tolerant behandeln: unbekannte Schlüssel behalten, nicht gegen ein starres Schema validieren, unveränderte Dateien nie neu schreiben. Alles, was OrcaOne nach `user/` oder in die `.conf` schreibt, wird vorher neu geparst und auf die Typen geprüft, die der Slicer erwartet. Fehlerhafte Profile löscht der Slicer beim Start samt `.info` (FINDINGS 4.4).
8. Der Server lauscht nur auf 127.0.0.1. *(Überholt am 25.09.2026: auf allen Schnittstellen, siehe CLAUDE.md, harte Regel 8.)*

## 3. Stack und Konventionen

- Backend: Python ≥ 3.11, FastAPI mit uvicorn, Dataclasses, sonst Standardbibliothek (`json`, `zipfile`, `hashlib`, `pathlib`, `shutil`). Keine eigenen Pydantic-Modelle, kein ORM, keine Datenbank. Das Dateisystem ist die einzige Quelle der Wahrheit, der Index lebt im Speicher und wird bei Bedarf neu aufgebaut.
- Zusätzliche Abhängigkeiten nur nach Rücksprache. Freigegeben: `psutil` für die Prozessprüfung (nötig unter Windows). Python-Umgebung: `.lenv` im Projektordner, unter Windows `.wenv`, Abhängigkeiten in `requirements.txt`, Start über `orcaone.sh` bzw. `orcaone.cmd`.
- Frontend: Vue 3 Composition API ohne Build-Schritt, VanillaJS, ES-Module, eine CSS-Datei. Vue liegt als Datei im Repo, kein CDN. Der Stil lehnt sich am ionpy-Styleguide an. Alle nötigen Dateien werden kopiert, nicht referenziert: OrcaOne läuft eigenständig.
- Start mit `python -m orcaone`: Server auf freiem Port starten und Browser öffnen.
- Code, Bezeichner und Kommentare auf Englisch. UI-Texte auf Deutsch, zentral in einer Datei gesammelt.
- KISS: so wenig Schichten wie möglich, keine Abstraktionen auf Vorrat. Bestehenden, funktionierenden Code nur ändern, wenn das aktuelle Feature es erfordert.
- Keine Platzhalter wie `# ... rest of code ...` und keine halbfertigen Stellen: Nach jedem Schritt muss jede Datei vollständig und lauffähig sein.
- Tests mit pytest. Resolver und alle Schreiboperationen brauchen Tests gegen Fixtures.
- Git-Repo, kleine Commits pro abgeschlossenem Schritt.

Vorschlag für die Struktur, darf begründet angepasst werden:

```
orcaone/
├── __main__.py      Start, Port wählen, Browser öffnen
├── app.py           FastAPI-App und Routen
├── instances.py     Erkennung der Installationen
├── conf.py          .conf byte-genau lesen und schreiben (Einrückung, Windows-Prüfsumme)
├── scanner.py       Dateien lesen, Index aufbauen
├── model.py         Dataclasses (Instance, Preset, VendorBundle, …)
├── resolver.py      Vererbung, Sichtbarkeit, Kompatibilität
├── operations.py    geplante Schreiboperationen, Backup, Wiederherstellung
├── guard.py         Prüfung, ob ein Slicer läuft
├── bundles.py       Import und Export (.json, .zip, .orca_filament, .orca_printer)
├── threemf.py       3MF-Inspektor (Phase 4)
└── static/          index.html, app.js, api.js, texts.js, style.css, vendor/
tests/
└── fixtures/        anonymisierte Ausschnitte echter Datenverzeichnisse
docs/
└── FINDINGS.md      Abweichungen zwischen dieser Spezifikation und der Realität
```

## 4. Fachwissen: Wie Orca und SnOrca Profile speichern

### 4.1 Datenverzeichnisse

| Slicer | Linux | Flatpak | Windows | macOS | Konfigurationsdatei |
|---|---|---|---|---|---|
| Snapmaker Orca | `~/.config/Snapmaker_Orca` | `~/.var/app/io.github.Snapmaker.Snapmaker_Orca/config/Snapmaker_Orca` | `%APPDATA%\Snapmaker_Orca` | `~/Library/Application Support/Snapmaker_Orca` | `Snapmaker_Orca.conf` |
| OrcaSlicer | `~/.config/OrcaSlicer` | `~/.var/app/com.orcaslicer.OrcaSlicer/config/OrcaSlicer` | `%APPDATA%\OrcaSlicer` | `~/Library/Application Support/OrcaSlicer` | `OrcaSlicer.conf` |

Die Konfigurationsdatei heißt `<SLIC3R_APP_KEY>.conf`; der Key steht in `version.inc` des jeweiligen Repos. Zusätzlich muss man Pfade manuell hinzufügen können (portable Installationen, eigenes Datenverzeichnis per Startparameter). Mehrere Instanzen werden gleichzeitig verwaltet.

Prozessnamen für die Laufprüfung (verifizieren): SnOrca startet als `snapmaker-orca` (AppImage: `/tmp/.mount_*/bin/snapmaker-orca`, Windows `snapmaker-orca.exe`), OrcaSlicer als `orca-slicer` bzw. `orca-slicer.exe`, unter macOS über das App-Bundle.

### 4.2 Ordnerstruktur

```
<data_dir>/
├── <APP_KEY>.conf                    App-Einstellungen (JSON)
├── system/                           Herstellerprofile – für OrcaOne nur lesen
│   ├── <Vendor>.json                 Manifest
│   ├── <Vendor>/machine/             Druckermodelle und -varianten
│   ├── <Vendor>/process/             Prozessprofile
│   ├── <Vendor>/filament/            Filamentprofile
│   ├── OrcaFilamentLibrary.json      Manifest der markenübergreifenden Filamentbibliothek
│   └── OrcaFilamentLibrary/filament/ base/, allgemeine *.json, <Marke>/
├── user/
│   └── <preset_folder>/              "default" oder kontoabhängig
│       ├── machine/                  eigene Drucker:   <Name>.json + <Name>.info
│       ├── process/                  eigene Prozesse:  <Name>.json + <Name>.info
│       └── filament/                 eigene Filamente: <Name>.json + <Name>.info
└── weitere Ordner (log, cache, …)    anzeigen, als „nicht verwaltet" markieren
```

Details:

- Aufbau eines Manifests: `name`, `version`, `force_update`, `description`, `machine_model_list`, `machine_list`, `process_list`, `filament_list`. Listeneinträge haben die Form `{"name": …, "sub_path": …}`.
- `system/` wird vom Slicer beim Start aus den Programmressourcen erneuert: die OrcaFilamentLibrary bei jedem Start, andere Hersteller bei Versionsunterschied. Hersteller ohne installierten Drucker entfernt der Slicer aus `system/` (`PresetUpdater::check_installed_vendor_profiles`, `install_bundles_rsrc`). SnOrca kann Profile zusätzlich per Hot-Update vom Server aktualisieren.
- Der aktive Unterordner in `user/` steht in der .conf unter `preset_folder`, ohne Eintrag ist es `default` (`PresetBundle::save_user_presets`). Es kann mehrere Unterordner geben, etwa von verschiedenen Konten: alle anzeigen, den aktiven hervorheben.
- Innerhalb von `user/<preset_folder>/` rekursiv scannen, aber je Datei markieren, ob der Slicer sie lädt: nur `<typ>/*.json` und `<typ>/base/`, bei Orca main zusätzlich `_local/<id>/` und `_subscribed/<id>/` (FINDINGS 4.2).
- OrcaSlicer main (Nightly) legt Hersteller als `system/<Vendor>.opc` ab, ein binäres Format. OrcaOne liest es (Prototyp in `prototypes/opc/`, Format in FINDINGS).

### 4.3 Die .conf

JSON-Datei. Für OrcaOne relevant:

- `"models"`: Liste von Objekten `{"vendor": …, "model": …, "nozzle_diameter": "0.4;0.6"}` – installierte Systemdrucker mit aktivierten Düsenvarianten. Trennzeichen und Escaping in `AppConfig.cpp` prüfen (`unescape_strings_cstyle`).
- `"filaments"`: Liste von Profilnamen – die sichtbaren Systemfilamente.
- `"presets"`: aktuell gewählte Profile. Dazu kommen druckerbezogene Auswahlabschnitte; deren Aufbau an einer echten Datei prüfen.
- `"preset_folder"`: Unterordner der Benutzerprofile.
- `"header"` und alle anderen Einstellungen: unverändert lassen.

Der Slicer schreibt die Datei erst in eine temporäre Datei und benennt sie dann um. Einrückung: SnOrca und Orca bis 2.3.2 mit 4 Leerzeichen, Orca ab 2.4.0 mit Tab. Die Auswahl je Drucker steht im Array `"orca_presets"` (FINDINGS 4.3).

Nur unter Windows endet die Datei zusätzlich mit einer Zeile `# MD5 checksum <32 Hex-Zeichen in Großbuchstaben>`, berechnet über den eingerückten JSON-Text (`appconfig_md5_hash_line` in `AppConfig.cpp`), und der Slicer legt eine `.conf.bak` an. Eine falsche Prüfsumme wird beim Laden nur protokolliert. Ein JSON-Fehler führt unter Windows dagegen zur Wiederherstellung aus der `.bak`, womit OrcaOnes Änderung verloren wäre. OrcaOne berechnet die Prüfsummenzeile deshalb neu und schreibt immer gültiges JSON.

SnOrca benennt beim Laden Filamentnamen in der .conf teilweise um (`update_filament_names` in `AppConfig.cpp`). Nach jedem Slicer-Start also neu scannen.

### 4.4 Aufbau eines Profils

Beispiel aus der Orca-Bibliothek, wie es in SnOrca 2.4.0 liegt:

```json
{
    "type": "filament",
    "name": "SUNLU PLA+ @System",
    "inherits": "SUNLU PLA+ @base",
    "from": "system",
    "setting_id": "OSNLS03",
    "instantiation": "true",
    "compatible_printers": []
}
```

- Wichtige Schlüssel: `type` (`machine_model`, `machine`, `process`, `filament`), `name`, `inherits`, `from`, `instantiation` (`"false"` = abstraktes Basisprofil, nicht wählbar), `setting_id`, `filament_id`, `base_id`, `compatible_printers` (Liste von Druckerprofilnamen, leer = alle Drucker), `compatible_printers_condition` (Ausdruck), `renamed_from`. Fast alle Einstellungswerte sind Arrays von Strings, etwa `"nozzle_temperature": ["220"]`.
- Beispielkette: `SUNLU PLA+ @System` → `SUNLU PLA+ @base` → `fdm_filament_pla` → `fdm_filament_common`.
- Namensbeispiele bei Snapmaker: Filamente `Generic PLA @U1 base`, `Generic PLA @U1 0.2 nozzle`; Drucker `Snapmaker U1 (0.4 nozzle)`.
- Maßgeblich ist das Feld `name`, nicht der Dateiname. Beispiel: Die Datei `SUNLU Marble PLA @System.json` enthält den Namen `SUNLU PLA Marble @System`.
- Benutzerprofile haben `"from": "User"` und speichern nur die Abweichungen zu ihrem Elternprofil (`Preset::save` in `Preset.cpp`). Ohne Elternprofil sind sie unvollständig, Status „verwaist". Daneben liegt `<Name>.info` mit Zeilen der Form `schlüssel = wert`: `sync_info`, `user_id`, `setting_id`, `base_id`, `updated_time` (`Preset::save_info`).
- Profile aus 3MF-Projekten führt der Slicer als Projektprofile nur im Speicher.

### 4.5 Vererbung auflösen

- Effektive Werte = effektive Werte des Elternprofils, überschrieben durch die eigenen Schlüssel, rekursiv.
- Systemprofile werden innerhalb ihres Herstellerpakets aufgelöst. Filamente können zusätzlich auf Basisprofile der OrcaFilamentLibrary verweisen, die der Slicer zuerst lädt. Die genaue Suchreihenfolge in `PresetBundle::load_vendor_configs_from_json` nachlesen und im Resolver dokumentieren.
- Benutzerprofile werden über den Namen gegen alle geladenen Profile aufgelöst.
- Zyklen und fehlende Eltern erkennen und als Status ausweisen, niemals abstürzen.
- Abnahme: Für eine Handvoll echter Profile muss die aufgelöste Ansicht mit dem übereinstimmen, was der Slicer anzeigt. Lege dafür eine Checkliste in `docs/FINDINGS.md` an.

### 4.6 Sichtbarkeit und Kompatibilität

So entscheidet der Slicer, was im Dropdown erscheint:

- Ein Systemdrucker ist sichtbar, wenn Hersteller, Modell und Düsenvariante in `"models"` aktiviert sind.
- Ein Systemfilament ist sichtbar, wenn sein Name oder ein Name aus `renamed_from` in `"filaments"` steht (`Preset::set_visible_from_appconfig`). Abstrakte Profile sind nie wählbar. Fehlt `"filaments"` oder ist es leer bzw. `null`, sind **alle** Systemfilamente sichtbar. OrcaOne schreibt die Liste deshalb nie leer.
- Benutzerprofile haben keinen Hersteller und sind immer sichtbar, sofern sie kompatibel sind.
- Kompatibel mit Drucker P (`is_compatible_with_printer` in `Preset.cpp`) ist ein Profil, wenn `compatible_printers` den Namen von P enthält, wenn die Liste leer ist und keine Bedingung gesetzt ist, oder wenn P ein eigener Drucker ist und das Profil zu dessen System-Elterndrucker passt. Ist eine `compatible_printers_condition` gesetzt, wertet OrcaOne sie nicht aus, sondern zeigt „bedingt" und den Ausdruck an.
- Ausschlussregel der OrcaFilamentLibrary: Ein Bibliotheksfilament mit leerer Druckerliste wird für Drucker P ausgeblendet, wenn ein Hersteller für P ein Filament mit gleichem Alias mitbringt, in der Regel der Name ohne den Zusatz ` @…` (`PresetCollection::update_library_profile_excluded_from`). Mutmaßliches Beispiel, zu prüfen: Die Bibliotheksversion von Generic PLA erscheint beim U1 nicht, weil Snapmaker eigene Generic-PLA-Profile mitbringt.

### 4.7 SnOrca-Besonderheit: die versteckte Orca-Bibliothek

- SnOrca liefert `OrcaFilamentLibrary.json` mit leerer `filament_list` aus. Die Profildateien aller Marken liegen trotzdem unter `system/OrcaFilamentLibrary/filament/`, darunter sieben SUNLU-Profile.
- Mindestens seit 2.3.5 lädt SnOrca diese Dateien bei leerem Manifest direkt von der Platte (`PresetBundle::load_vendor_configs_from_json`, Kommentar „OrcaFilamentLibrary keeps its profiles on disk but ships an empty manifest"). Sie sind trotzdem unsichtbar, weil sie nicht in `"filaments"` stehen. Der Einrichtungsassistent kann sie nicht anbieten, weil er das Manifest liest.
- Das Manifest zu ändern ist zwecklos, der Slicer überschreibt es bei jedem Start.
- Idee „Bibliothek freischalten": die gewünschten Namen bei geschlossenem SnOrca in `"filaments"` eintragen. Laut Code trägt das. Robustere Alternative: ein eigenes Profil mit `inherits` auf das Bibliotheksprofil, es übersteht den Einrichtungsassistenten. Beides ist ungetestet – zuerst mit einem einzigen Profil in einer Kopie des Datenverzeichnisses ausprobieren (`--datadir`).
- Wer den Einrichtungsassistenten erneut abschließt, bekommt `"filaments"` neu geschrieben (`WebGuideDialog.cpp`), und die Einträge sind weg. OrcaOne soll das erkennen und erneutes Freischalten anbieten.
- Hinweis für die Oberfläche: Die Bibliotheksprofile sind oft dünn. „SUNLU PLA+" setzt nur Flow 1,0, maximale Volumengeschwindigkeit, Dichte, Preis und wenige weitere Werte; die Temperaturen kommen aus `fdm_filament_pla`. OrcaOne soll zeigen, welche Werte ein Profil selbst setzt und welche es erbt.

### 4.8 Import- und Exportformate des Slicers

- „Datei → Importieren → Konfigurationen importieren" akzeptiert `.json`, `.zip`, `.orca_printer` und `.orca_filament` (`MainFrame.cpp`, Verarbeitung in `PresetBundle::import_presets`).
- `.orca_filament` und `.orca_printer` sind ZIP-Archive mit einer `bundle_structure.json`. Schlüssel unter anderem: `version`, `bundle_id`, `bundle_type` („filament config bundle" bzw. „printer config bundle"), `filament_name` bzw. `printer_preset_name`, `printer_config`, `filament_config`, `process_config`, `printer_vendor` mit `filament_path`. Den genauen Aufbau aus `CreatePresetsDialog.cpp` (Export) und `import_presets` übernehmen oder ein Beispiel aus dem Slicer exportieren und untersuchen. Nicht raten.

### 4.9 3MF-Projekte

- 3MF ist ein ZIP-Archiv. `Metadata/project_settings.config` enthält die kompletten Projekteinstellungen, dazu kommen `Metadata/model_settings.config` und `Metadata/slice_info.config`.
- Eingebettete eigene Profile liegen als `Metadata/machine_settings_N.config`, `Metadata/filament_settings_N.config` und `Metadata/process_settings_N.config` im Archiv (Konstanten in `src/libslic3r/Format/bbs_3mf.cpp`).
- Beim Öffnen lädt der Slicer sie als Projektprofile und macht referenzierte, versteckte Systemprofile für die Sitzung sichtbar. Was dauerhaft bleibt, hängt von den Entscheidungen in den Dialogen ab. Genau das soll die Ansicht „Neu seit dem letzten Scan" sichtbar machen.

### 4.10 Quellcode-Referenzen zum Nachprüfen

Repos: Snapmaker/OrcaSlicer (Tag `v2.4.0`) und OrcaSlicer/OrcaSlicer (Branch `main`). Einzelne Dateien lassen sich über raw.githubusercontent.com laden, ein kompletter Clone ist nicht nötig.

| Datei | Relevanz |
|---|---|
| `version.inc` | App-Key und damit Name von Datenordner und .conf |
| `src/libslic3r/Preset.hpp` | Ordnernamen (`system`, `user`, `machine`, `process`, `filament`) und JSON-Schlüssel |
| `src/libslic3r/Preset.cpp` | `save`, `save_info`, `set_visible_from_appconfig`, `is_compatible_with_printer`, `update_library_profile_excluded_from` |
| `src/libslic3r/PresetBundle.cpp` | `load_vendor_configs_from_json`, `load_installed_filaments`, `save_user_presets`, `export_selections`, `import_presets` |
| `src/libslic3r/AppConfig.cpp` | Format der .conf, `models`, `filaments`, Prüfsumme unter Windows |
| `src/slic3r/Utils/PresetUpdater.cpp` | Erneuerung von `system/` |
| `src/slic3r/GUI/WebGuideDialog.cpp` | Einrichtungsassistent schreibt `filaments` neu |
| `src/slic3r/GUI/CreatePresetsDialog.cpp` | Export der Bundles, Anlegen eigener Profile und IDs |
| `src/slic3r/GUI/MainFrame.cpp` | Importdialog und erlaubte Dateitypen |
| `src/libslic3r/Format/bbs_3mf.cpp` | Aufbau von 3MF-Projekten |

## 5. Funktionen in Phasen

Jede Phase endet mit einer lauffähigen App, grünen Tests, aktualisierter README (Start, Neuerungen, manuelle Testschritte) und einer Liste offener Punkte. Danach anhalten und auf mein Feedback warten.

### Phase 0 – Grundgerüst

- Repo, CLAUDE.md, Projektstruktur, Startskript.
- Erkennung der Installationen automatisch und per manuellem Pfad.
- Oberflächen-Grundgerüst mit Instanzauswahl.
- Testinfrastruktur mit Fixtures: kleine, anonymisierte Ausschnitte meiner echten Datenverzeichnisse, also einige Systemprofile mit vollständiger Vererbungskette, einige Benutzerprofile mit .info und eine gekürzte .conf. IDs wie `user_id` oder kontoabhängige Ordnernamen durch Platzhalter ersetzen. Frag mich, bevor du etwas kopierst.

### Phase 1 – Übersicht, nur lesend

- Alles auf einer Seite „Übersicht", Details im Seitenpanel oder aufklappbar. Dashboard je Instanz: Slicer und Version, Pfad, ob der Slicer läuft, Anzahl der Profile je Art, Warnungen (verwaist, doppelte Namen, unsichtbar wegen Inkompatibilität, bedingte Kompatibilität).
- Drucker: installierte Systemdrucker mit Düsenvarianten, eigene Drucker mit Elternprofil, je Drucker die Zahl kompatibler Filamente und Prozesse.
- Filamente: filterbare Tabelle mit Name, Hersteller, Materialtyp, Herkunft (Hersteller, Orca-Bibliothek, eigenes Profil), Status (sichtbar, ausgeblendet, verwaist, inkompatibel, bedingt) und kompatiblen Druckern. In der Detailansicht: Vererbungskette, effektive Werte, selbst gesetzte Werte, Dateipfade.
- Prozesse: einfache Liste mit Kompatibilität.
- Dateien: Baum des Datenverzeichnisses mit Erklärung je Ordner, Anzahl und Größe; je Datei erkannter Typ und Status; unbekannte Dateien markiert.
- „Neu seit dem letzten Scan": OrcaOne speichert einen Schnappschuss (Pfad, Größe, Änderungszeit, Hash) und zeigt hinzugekommene, geänderte und entfernte Dateien sowie Änderungen an `"models"` und `"filaments"`. Der Schnappschuss wird nur auf Wunsch aktualisiert („Als gesehen markieren").
- Eigenes Datenverzeichnis von OrcaOne für Einstellungen, Schnappschüsse und Backups: der Ordner `data/` im OrcaOne-Ordner, auf allen Plattformen gleich (geändert am 23.09.2026, vorher `~/.local/share/orcaone` bzw. `%LOCALAPPDATA%\orcaone`).

### Phase 2 – Aufräumen

Alle Schreiboperationen nach den Regeln 2 bis 6.

- Eigene Profile löschen (Drucker, Prozesse, Filamente), jeweils mit .info.
- Systemfilamente aus- und einblenden (`"filaments"` bearbeiten). Dazu, aus Phase 3 vorgezogen: „Bibliothek freischalten" nach 4.7 für SnOrca.
- Systemdrucker oder einzelne Düsenvarianten deinstallieren und wieder installieren (`"models"` bearbeiten). Vorher anzeigen, welche eigenen Profile davon abhängen und ob der Drucker gerade in `"presets"` ausgewählt ist.
- Beim Löschen eines eigenen Druckers die eigenen Filamente und Prozesse auflisten, die nur zu diesem Drucker passen, und anbieten, sie mitzulöschen.
- Mehrfachauswahl und Sammelaktionen.
- Backups auflisten, wiederherstellen, löschen.

### Phase 3 – Import, Export, Übertragen

- Quellen: Dateien (`.json`, `.zip`, `.orca_filament`, `.orca_printer`), eine andere Instanz (Orca ↔ SnOrca) und die OrcaFilamentLibrary aus dem OrcaSlicer-Repo. Ob einzelne Dateien bei Bedarf heruntergeladen oder ein lokaler Clone gewählt wird: Vorschlag machen.
- Zwei Strategien, je Import wählbar:
  - „Flach": komplette Vererbungskette auflösen und ein Profil ohne `inherits` mit allen Werten schreiben; `compatible_printers` = gewählte Zieldrucker.
  - „An Zielprofil hängen": `inherits` = ein gewähltes, wählbares Systemprofil des Ziels, etwa ein U1-PLA-Profil; nur die markenspezifischen Werte als Abweichung übernehmen (Temperaturen, Flow, Dichte, Hersteller, maximale Volumengeschwindigkeit, Preis …). Anzeigen, welche Schlüssel übernommen werden.
- Namenskonflikte: umbenennen, überspringen oder überschreiben (mit Backup). Eindeutigkeit von `setting_id` und `filament_id` prüfen; wie der Slicer IDs für eigene Profile erzeugt, steht in `CreatePresetsDialog.cpp`.
- Ziel standardmäßig: ein Bundle (`.orca_filament` oder `.zip`) erzeugen, das der Slicer selbst importiert – dafür braucht OrcaOne keinen Schreibzugriff. Option: direkt nach `user/<preset_folder>/` schreiben, bei geschlossenem Slicer.
- Druckerzuordnung beim Übertragen: Quelldruckername → Zieldruckername.
- Export ausgewählter Profile unverändert oder flach, als ZIP oder im Bundle-Format.
- SnOrca: „Bibliothek freischalten" nach 4.7, zuerst mit einem einzigen Profil testen.

### Phase 4 – 3MF-Inspektor

- 3MF öffnen (Upload oder Pfad). Anzeigen, welche Drucker-, Filament- und Prozessprofile referenziert und welche eingebettet sind, und welche davon in der gewählten Instanz existieren.
- Optional eine bereinigte Kopie ohne eingebettete Profile speichern. Das Original niemals verändern.

## 6. Oberfläche

- Gegenstand: ein Werkstattwerkzeug für 3D-Druck-Profile. Nutzer: Maker, die ihren Slicer kennen. Hauptaufgabe: Überblick und sicheres Aufräumen. Zwei Seiten: „Übersicht" und „Verwalten", kein Rumgehampel.
- Stil: ionpy-Styleguide (flach, kantig, dicht, Mono-Schrift für technische Werte), aber in Satzschreibung und mit Status als Text plus Farbe. Designplan in docs/PLAN.md.
- Vor dem ersten Oberflächen-Code einen kompakten Designplan vorschlagen (4–6 Farben als Hex-Werte, 1–2 Schriften, Layoutskizze in ASCII) und freigeben lassen. Systemschriften oder lokal mitgelieferte Schriften, keine externen Schriftdienste.
- Informationsdichte vor Dekoration: Tabellen mit Sortierung und Filtern statt Kartenraster, Details in einem Seitenpanel.
- Status immer als Text plus Farbe, nie nur über Farbe.
- Satzschreibung, keine Beschriftungen in Großbuchstaben. Aktionen heißen überall gleich: Der Knopf „Ausblenden" führt zur Meldung „Ausgeblendet".
- Zerstörende Aktionen: Bestätigungsdialog mit der genauen Liste der Änderungen.
- Fehlermeldungen sagen, was passiert ist und was zu tun ist, etwa: „Snapmaker Orca läuft gerade. Schließe das Programm, um Änderungen zu speichern."
- Leere Zustände zeigen den nächsten sinnvollen Schritt.
- Hell- und Dunkelmodus über `prefers-color-scheme`, vollständig per Tastatur bedienbar, sichtbarer Fokus.

## 7. Offene Punkte – bitte mit mir klären

Stand 21.09.2026, Antworten in FINDINGS.

- ~~`psutil` oder `/proc` für die Laufprüfung.~~ psutil.
- Cloud-Synchronisation: Mit Snapmaker- oder Bambu-Konto werden Benutzerprofile womöglich synchronisiert (Hinweis: Felder `sync_info` und `user_id` in der .info). Gelöschte Profile könnten zurückkommen, oder Löschungen könnten sich auf andere Rechner auswirken. OrcaOne soll eine Anmeldung erkennen (`preset_folder` ungleich `default`) und warnen. Das Verhalten des Slicers vorher testen.
- ~~Genaue Suchreihenfolge bei der Vererbung (4.5).~~ Geklärt, FINDINGS 4.5.
- ~~Eindeutigkeit von IDs beim Import (Phase 3).~~ Geklärt, FINDINGS 4.8.
- Ob „Bibliothek freischalten" funktioniert (4.7): laut Code ja, Praxistest steht aus.
- ~~Vue lokal mitliefern oder per CDN laden.~~ Lokal.
- Ideen für später: Kamera des U1 abfragen und aktivieren; Spoolman nur lesend anbinden.

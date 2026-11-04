# Befunde: Spezifikation gegen Wirklichkeit

Stand 21.09.2026. Geprüft wurde Abschnitt 4 der [Spezifikation](../ORCAONE_SPEC.md), und zwar nur lesend.

**Quellen**

- **Snapmaker Orca v2.4.0:** Quellcode (Commit `b1831e5`) und die laufende AppImage mit ihren Programmressourcen.
- **Echtes Datenverzeichnis:** `~/.config/Snapmaker_Orca` (SnOrca 2.4.0, Linux, U1 installiert, noch keine eigenen Profile).
- **OrcaSlicer main:** Quellcode, Commit `45940a5` vom 21.09.2026, 2.5.0-dev. Auf dem Windows-Rechner am 24.09.2026 neu geklont: Commit `0db1dc6`.
- **Firmware des U1:** Snapmakers Klipper und Moonraker auf GitHub (`Snapmaker/u1-klipper`, `Snapmaker/u1-moonraker`), einzelne Dateien per raw.githubusercontent.com gelesen, nicht abgelegt.
- **OrcaSlicer Nightly:** die AppImage, entpackt, nicht ausgeführt.
- **OrcaSlicer-Releases v2.4.0 bis v2.4.2:** nur einzelne Dateien per raw.githubusercontent.com.
- **Nicht vorhanden:** Während der Prüfung war OrcaSlicer auf diesem Rechner noch nie gestartet, es gab kein `~/.config/OrcaSlicer`. Der Erststart kam danach, siehe „Beobachtung: Erststart der OrcaSlicer-Nightly“. Einen Windows-Rechner gab es für die Prüfung nicht.
- **Ablage:** Der Quellcode liegt als Sparse-Clone in `slicer-src/` und steht nicht im Git. Neu anlegen:

  ```bash
  git clone --depth 1 --branch v2.4.0 --filter=blob:none --sparse https://github.com/Snapmaker/OrcaSlicer.git slicer-src/snorca-v2.4.0
  ```

  ```bash
  git clone --depth 1 --branch main --filter=blob:none --sparse https://github.com/OrcaSlicer/OrcaSlicer.git slicer-src/orcaslicer-main
  ```

  Danach in beiden Ordnern die benötigten Teile holen:

  ```bash
  git sparse-checkout set --no-cone '/version.inc' '/CMakeLists.txt' '/src/*.cpp' '/src/*.hpp' '/src/CMakeLists.txt' '/src/libslic3r/*' '/src/slic3r/GUI/*' '/src/slic3r/Utils/*' '/scripts/*' '/resources/web/guide/*' '/resources/profiles/OrcaFilamentLibrary*' '/resources/profiles/Snapmaker*' '/localization/i18n/de/*'
  ```

  Die deutschen Übersetzungen (`localization/i18n/de/`) kamen am 23.09.2026 dazu, für die Bezeichnungen, die OrcaOne nennt.

**Vorgehen:** Sechs Agenten haben je einen Teil von Abschnitt 4 gegen Code und Installation geprüft. Zwei Gegenprüfer haben versucht, die Befunde zu widerlegen. Ein weiterer Agent hat nach Lücken gesucht. Dazu kam ein Prototyp für das neue `.opc`-Format ([prototypes/opc](../prototypes/opc/README.md)). Belege mit Datei und Zeile liegen in den Agentenprotokollen. Hier stehen nur die Ergebnisse und ihre Folgen für OrcaOne.

Schreibweise: **SnOrca** = Snapmaker Orca 2.4.0, **Orca** = OrcaSlicer. Wo Orca-Release (2.4.x) und Orca main unterschiedlich sind, steht es dabei.

---

## Das Wichtigste in Kürze

1. **Die OrcaSlicer-Nightly speichert Systemprofile binär.** Orca main (2.5.0-dev) liefert und installiert Hersteller als `system/<Vendor>.opc` statt als JSON. Ohne `.opc`-Leser sieht OrcaOne dort keine Systemprofile. Das Format lässt sich mit reinem Python lesen, der Prototyp liest alle 65 Dateien der Nightly (Abschnitt „Das .opc-Format“). Alle Releases bis v2.4.2 nutzen noch JSON.
2. **Regel 6 stimmt nur für SnOrca.** Orca schreibt `.conf` und Profil-JSONs seit Release v2.4.0 mit **Tab**-Einrückung, SnOrca und Orca bis v2.3.2 mit 4 Leerzeichen. Beide sortieren alle Schlüssel alphabetisch und enden mit `\n`. OrcaOne muss das Format der vorgefundenen Datei übernehmen.
3. **Orca nimmt den Dateinamen als Profilnamen.** Das gilt für Benutzerprofile ab v2.4.x. SnOrca nimmt das Feld `name`. Stimmen beide nicht überein, heißt dasselbe Profil in den beiden Slicern verschieden.
4. **Benutzerprofile werden nicht rekursiv geladen**, sondern nur `user/<ordner>/<typ>/*.json` und `<typ>/base/**`. Orca main kennt zusätzlich Bundle-Ordner `_local/<id>/` und `_subscribed/<id>/`. Alles andere ignoriert der Slicer.
5. **Der Slicer löscht fehlerhafte Benutzerprofile.** Bei ungültigem JSON, nicht umwandelbaren Werten oder Nicht-String-Metadaten verschwinden `.json` **und** `.info` beim nächsten Start. OrcaOne muss alles, was es nach `user/` schreibt, vorher selbst prüfen.
6. **Abstrakte Profile taugen nicht als Elternprofil für eigene Profile.** Gemeint sind Profile mit `instantiation: "false"`, etwa `@base` oder `fdm_*`. Der Slicer lädt sie gar nicht als Profil. Bei „An Zielprofil hängen“ sind deshalb nur wählbare Profile erlaubt.
7. **„Bibliothek freischalten“ trägt laut Code.** Ein Name aus der OrcaFilamentLibrary in `"filaments"` macht das Profil in SnOrca sichtbar. Kein SUNLU-Profil wird beim U1 ausgeschlossen. Es gibt dazu eine robustere Alternative, siehe 4.7. Ein Praxistest steht noch aus.
8. **Leeres oder fehlendes `"filaments"` heißt: alles sichtbar**, nicht „nichts sichtbar“.
9. **Ob der Slicer läuft, zeigen Prozessliste und Sperrdatei zusammen.** Unter Linux und macOS hält er eine Sperre auf `<data_dir>/cache/<hash>.lock`, rein lesend prüfbar per `F_GETLK`. Am echten System getestet: gesperrt von PID 44867. Die Sperre allein reicht aber nicht, weil der Slicer die `.conf` vor dem Sperren liest und nach dem Entsperren noch schreibt. Windows nutzt einen benannten Mutex, dort hilft nur die Prozessliste.
10. **Die `.conf` enthält Zugangsdaten**, nämlich SnOrca `devices[].api_key/password/…` und Orca `local_machines[].access_code`. Eigene Druckerprofile können `printhost_*` enthalten. OrcaOne muss solche Werte in Diffs maskieren und Backups als vertraulich behandeln.
11. **`preset_folder` gehört dem Slicer.** Er setzt ihn bei jedem Start neu: `""` ohne Anmeldung, sonst die `user_id`. OrcaOne ändert ihn nie.
12. **SnOrca schaltet beim Start alle Düsenvarianten eines Modells wieder ein**, sobald eine aktiv ist. Einzelne Varianten abzuschalten hält also nicht, nur ganze Modelle.
13. **U1-Filamentnamen unterscheiden sich zwischen SnOrca und Orca.** Die Druckernamen sind gleich. Von 129 wählbaren U1-Filamenten in SnOrca und 107 in Orca main heißen nur 43 gleich, zum Beispiel heißt `Snapmaker ABS @U1 0.4 nozzle` in Orca `Snapmaker ABS @U1`. Das ist wichtig für das Übertragen.

---

## 4.1 Datenverzeichnisse und Prozesse

| Spezifikation | Befund | Folge für OrcaOne |
|---|---|---|
| Linux `~/.config/<Key>` | Teilweise. Reihenfolge: `--datadir <pfad>` → Ordner `data_dir` neben der Programmdatei (portabel) → `$XDG_CONFIG_HOME/<Key>` → `~/.config/<Key>`. | `$XDG_CONFIG_HOME` beachten. Einen `data_dir`-Ordner neben gefundenen Programmdateien prüfen. |
| SnOrca-Flatpak: ID unbekannt, per Glob | **Abweichend:** Die ID ist `io.github.Snapmaker.Snapmaker_Orca` (Flatpak-Manifest, metainfo, CI). Pfad: `~/.var/app/io.github.Snapmaker.Snapmaker_Orca/config/Snapmaker_Orca`. Auf Flathub offenbar nicht, die CI baut nur ein `*_Beta.flatpak`. | Feste ID verwenden, Glob nur zusätzlich. |
| Orca-Flatpak `com.orcaslicer.OrcaSlicer` | Stimmt seit v2.3.2. Bis v2.3.1 hieß die ID `io.github.softfever.OrcaSlicer`. Orca main kopiert den Altordner beim ersten Start, der alte bleibt liegen. | Beide IDs suchen. Den Altordner als „veraltete Kopie“ zeigen, nicht als aktive Instanz. |
| Windows `%APPDATA%\<Key>`, macOS `~/Library/Application Support/<Key>` | Bestätigt. | – |
| Pfade manuell ergänzen | Bestätigt: `--datadir` gibt es in beiden Slicern. | – |
| AppImage-Portabelmodus | Neu: Ein Ordner `<datei>.AppImage.config` neben der AppImage setzt `XDG_CONFIG_HOME`, `<datei>.AppImage.home` setzt `HOME`. | Bei gefundenen AppImages zusätzlich `<datei>.config/<Key>` und `<datei>.home/.config/<Key>` prüfen. |
| Prozessnamen | Bestätigt: `snapmaker-orca` und `orca-slicer`. Die AppImage läuft zusätzlich als eigener Prozess. `comm` wird auf 15 Zeichen gekürzt. Windows: `snapmaker-orca.exe`, `orca-slicer.exe`. macOS: `Snapmaker Orca.app/Contents/MacOS/Snapmaker_Orca`, `OrcaSlicer.app/Contents/MacOS/OrcaSlicer`. | Prozesse nach dem exe-Pfad erkennen, nicht nach `comm`. |

### Laufprüfung (neu)

- **Linux und macOS:** Der Slicer hält eine POSIX-Schreibsperre auf `<data_dir>/cache/<hash>.lock`, auf Byte 0 mit Länge 1.
  - Der `hash` ist `std::hash` über den kanonischen Pfad der Programmdatei. Bei einer AppImage ist das `$APPIMAGE`, also die `.appimage`-Datei selbst, nicht der Mount-Pfad. Jede Programmdatei hat deshalb ihre eigene Lock-Datei, und OrcaOne muss **alle** `*.lock` in `cache/` prüfen.
  - Prüfen geht rein lesend: `os.open(O_RDONLY)` und `fcntl(F_GETLK)` liefern die PID des Halters. OrcaOne darf die Sperre **nie selbst setzen**. Ein startender Slicer würde sich sonst für eine Zweitinstanz halten.
  - Nach einem Absturz bleibt die Datei ohne Sperre liegen. Nur die Sperre zählt, nicht die Datei.
  - Nur die erste Instanz einer Programmdatei hält die Sperre. `single_instance` ist standardmäßig `false`, eine zweite Instanz läuft also ohne Sperre.
- **Die Sperre allein reicht nicht.** Beim Start liest der Slicer die `.conf` im Konstruktor von `GUI_App`, bevor er die Sperre setzt. Beim Beenden löscht er erst die Lock-Datei und schreibt danach die `.conf`, beobachtet am 21.09.: Lock weg um 13:12:00.384, `.conf` geschrieben um 13:12:00.387. Die Sperre dient nur dazu, einen Prozess einem Datenordner zuzuordnen.
- **Die AppImage-Runtime zählt mit.** Die Runtime läuft als eigener Prozess vor und nach dem Slicer. Sie ist **nicht** der Elternprozess des Slicers: Der Startprozess wird per `exec` zum Slicer, die FUSE-Runtime löst sich ab und hängt an `systemd --user`. Zuordnen lässt sie sich über die Umgebungsvariable `APPIMAGE` des Slicer-Prozesses, die auf dieselbe `.appimage`-Datei zeigt. Ihr `exe` ist die `.appimage`-Datei, ihr `comm` der gekürzte Dateiname. Beim Start wechselt die PID des Slicers per `exec` von `AppRun` über das Env-Skript zu `snapmaker-orca`.
- **Prozessnamen exakt vergleichen.** `/usr/bin/orca` ist der GNOME-Screenreader.
- **Datenordner eines Prozesses (Linux):** Ohne `--datadir` wechselt der Slicer nach `<data_dir>/log`, dann zeigt `/proc/<pid>/cwd` den Datenordner. Mit `--datadir` steht der Pfad in `/proc/<pid>/cmdline`, relativ zum Startverzeichnis, weil dann kein `chdir` erfolgt. SnOrca hält außerdem eine `flock`-Sperre auf `log_upload_spool/.lock`.
- **macOS:** Dieselbe Lock-Datei. Beendet sich die erste Instanz, übernimmt eine zweite die Sperre per Nachricht.
- **Windows:** Der Slicer nutzt einen benannten Mutex (`wxSingleInstanceChecker`), keine Datei. Der Mutex hängt am Programmpfad, nicht am Datenordner. Es bleibt nur die Prozessliste samt Kommandozeile, also `psutil`.
- **Flatpak:** Das D-Bus-Signal `…InstanceCheck.*` ist im SnOrca-Manifest nicht freigegeben und fehlt dort vermutlich.
- **Umsetzung in `orcaone/guard.py`:**
  - Ein Slicer läuft, solange es einen Prozess `snapmaker-orca` bzw. `orca-slicer` (auch `.exe` und macOS-Bundle) oder eine AppImage-Runtime dieses Slicers gibt.
  - Die Zuordnung zum Datenordner erfolgt über `--datadir`, das Arbeitsverzeichnis oder die Sperre.
  - Kann OrcaOne einen Prozess keinem Ordner zuordnen, zeigt es alle Instanzen dieses Slicers schreibgeschützt.
  - Direkt vor und nach dem Schreiben prüft OrcaOne erneut.
  - Das `struct flock` ist unter macOS anders aufgebaut als unter Linux.

## 4.2 Ordnerstruktur

| Spezifikation | Befund | Folge für OrcaOne |
|---|---|---|
| `system/<Vendor>.json` plus `<Vendor>/{machine,process,filament}/` | Stimmt für SnOrca und Orca bis v2.4.2. **Orca main** lädt `<Vendor>.json` **oder** `<Vendor>.opc` und löscht bei einer Cache-Installation das JSON. | `.opc` lesen (siehe unten). Systemprofile über das Manifest bestimmen, nicht über einen Ordner-Scan. |
| Manifest-Aufbau | Bestätigt. `system/Snapmaker/` enthält aber 5 JSONs, die nicht im Manifest stehen: 4 Regeldateien (`filament_allow_list.json`, `filament_compatibility.json`, `filament_hot_bed_nozzles.json`, `filaments_colours.json`) und ein verwaistes Prozessprofil. | Nur Manifesteinträge sind Systemprofile. Einzige Ausnahme: SnOrca lädt die Bibliothek bei leerer `filament_list` direkt aus `OrcaFilamentLibrary/filament/`, alles dort als Filament (`load_vendor_configs_from_json`, 4.7). OrcaSlicer kennt das nicht. |
| `system/` wird beim Start erneuert | **SnOrca:** OrcaFilamentLibrary jedes Mal. Snapmaker immer geprüft, andere Hersteller nur, wenn sie in `"models"` stehen. Neu kopiert wird bei abweichendem Major/Minor oder älterer Version. Hersteller, die nicht in `"models"` stehen, **löscht** SnOrca. **Orca bis v2.4.2** verhält sich genauso, weil `enabled_config_update` dort an eine fest eingetragene URL gebunden und damit immer wahr ist. **Erst Orca main** (Nightly) verlangt zusätzlich `app.enable_ota = true`. Der Standard ist `false` und in der Oberfläche nicht einstellbar. Dann werden installierte Hersteller weder erneuert noch entfernt, nur fehlende installiert. Die Bibliothek wird immer kopiert. | Versionen von `system/` und Programmressourcen anzeigen. Ändert OrcaOne `"models"`, installiert bzw. löscht SnOrca beim nächsten Start ganze Herstellerpakete. Das gehört in den Änderungsplan. |
| `user/<preset_folder>/`, `""` = `default` | Bestätigt. SnOrca und Orca setzen `preset_folder` bei **jedem Start** neu: angemeldet auf die `user_id`, sonst auf `""`. | `""` und fehlender Schlüssel bedeuten `default`. OrcaOne ändert `preset_folder` nie. |
| Eigene Profile als `<Name>.json` plus `<Name>.info` | Ja. Profile ohne `inherits` (Wurzelprofile) legt der Slicer in `<typ>/base/<Name>.json` ab. | Der Scanner kennt `base/`. |
| Rekursiv scannen | **Abweichend:** Der Slicer lädt nur `<typ>/*.json` und `<typ>/base/`. **Orca main** lädt zusätzlich `user/<ordner>/_local/<id>/<typ>/` und `_subscribed/<id>/<typ>/`, wenn dort eine `bundle_metadata.json` liegt. Diese Profile tragen `"from": "Bundle"`, haben keine `.info` und heißen intern `_local/<id>/<Name>`. Lässt sich `bundle_metadata.json` nicht laden (Syntaxfehler oder falscher Typ, `BundleMetadata::load_from_json`), überspringt Orca das ganze Bundle. Ohne `id` bekommen die Profile kein Präfix (`get_preset_canonical_name`). | Rekursiv scannen, aber je Datei markieren, ob der Slicer sie lädt. Bundle-Profile von Orca main als eigene Herkunft „Bundle“ zeigen. |

**Weitere Einträge im Datenverzeichnis:** Alle gelten als „nicht verwaltet“ und stehen nicht in OrcaOne-Diffs als Profile.

| Eintrag | Bedeutung | Backup |
|---|---|---|
| `log/` | Logdateien | nein |
| `cache/` | Lock-Dateien, bei Orca main auch `cookies.db` | nein |
| `user_backup-v<Version>/` | Einmalige Kopie von `user/` je Programmversion, wird nie aktualisiert oder zurückgespielt. `PresetBundle::backup_user_folder` läuft bei jedem Start (`GUI_App.cpp`) und kopiert nur, wenn es den Ordner für die laufende Version noch nicht gibt; in SnOrca und Orca main gleich. OrcaOne importiert daraus (Seite „Import/Export“) | nein (Slicer-eigen) |
| `user/Temp/` | Flüchtige Vollkopien aller sichtbaren Drucker, solange der Export-Dialog offen ist | nein |
| `user/<ordner>/temp/` | Rest eines abgebrochenen Imports. SnOrca nutzt immer `user/default/temp` | nein |
| `hms/`, `ota/`, `web/`, `log_upload_spool/` | SnOrca: Meldungstexte für Bambu-Drucker (geerbt, von `e.bambulab.com`, nicht für den U1; `HMS.cpp`, `AppConfig::get_hms_host`, geprüft 26.09.2026), Hot-Updates, Flutter-Gerätepanel (darin die Texte der U1-Fehlercodes, IDEEN 10), Telemetrie-Warteschlange | nein |
| `.snapmaker_orca_machine_id` (Orca: `.orcaslicer_machine_id`) | Zufällige UUID für Telemetrie und Update-Check | ja, nie übertragen, nie anzeigen |
| `printers/`, `plugins/`, `orca_plugins/`, `models/`, `cameratools/`, `SVG/`, `vendor/` | je nach Version und Nutzung | nein |
| `<Key>.conf.<pid>` | Temporäre Datei beim Speichern | Zeichen für laufenden Schreibvorgang |
| `<Key>.conf.bak` | nur Windows | ja |
| `system/<Vendor>.new`, `.old` | Reste nach Absturz (SnOrca) | nein |
| `simplyprint_oauth.json`, `3dprinteros_api_cred.json`, `orca_refresh_token.sec` | Zugangstoken | vertraulich |
| `user/hints.cereal` | Zustand der Tipps, beim Beenden geschrieben. Weder Konto- noch Profilordner | ja |

**Außerhalb des Datenordners** legt die eingebaute Web-Oberfläche (WebKitGTK) eigene Ordner nach dem Programmnamen an. SnOrca nutzt `~/.local/share/snapmaker-orca` (localstorage, u. a. für die Snapmaker-Anmeldung) und `~/.cache/snapmaker-orca`. Alle SnOrca-Datenordner teilen sich diese Ordner, auch bei `--datadir`. OrcaOne verwaltet sie nicht und sichert sie nicht mit, es nennt sie nur.

## 4.3 Die .conf

| Spezifikation | Befund | Folge für OrcaOne |
|---|---|---|
| JSON, 4 Leerzeichen, temporäre Datei plus Umbenennen | **SnOrca:** `setw(4)`. **Orca bis v2.3.2:** 4 Leerzeichen. **Orca ab v2.4.0 (auch 2.4.2) und main:** Tab (`dump(1, '\t')`). Alle sortieren Schlüssel auf allen Ebenen alphabetisch (nlohmann mit `std::map`), schreiben Nicht-ASCII roh als UTF-8, nutzen LF und enden mit `\n`. Temporäre Datei `<Key>.conf.<pid>`, dann `rename`. Die echte SnOrca-Datei ist byte-identisch mit `json.dumps(obj, indent=4, ensure_ascii=False, sort_keys=True) + "\n"`. | Einrückung aus der vorgefundenen Datei übernehmen, `sort_keys=True`, abschließendes `\n`. |
| `"models"`: `{vendor, model, nozzle_diameter "0.4;0.6"}` | Stimmt. Der Wert unter `nozzle_diameter` sind `printer_variant`-Werte, beliebige Zeichenketten wie `"0.4+0.6"` in Orca. Verbunden mit `escape_strings_cstyle`, sortiert, Werte mit Leerzeichen in Anführungszeichen. `model` ist der Manifestname des Modells (`Snapmaker U1`), nicht `model_id` (`SM_U1`). | Varianten als unveränderte Zeichenketten behandeln. |
| `"filaments"`: Liste von Profilnamen | Stimmt. Sortiert, ohne Duplikate. Ein vorhandener, aber leerer Abschnitt wird als `null` geschrieben. **Fehlend, `[]` und `null` bedeuten beim Laden dasselbe: kein Abschnitt, alle Systemfilamente sichtbar.** | Drei Zustände unterscheiden (siehe 4.6). |
| `"presets"` plus druckerbezogene Auswahlabschnitte | **Präzisiert:** `"presets"` enthält nur noch `machine` und `filaments` (meist `null`). Die Auswahl je Drucker steht im Array **`"orca_presets"`**: ein Objekt pro Druckername mit `machine`, `process`, `filament`, `filament_01…NN` (weitere Köpfe, beim U1 bis `_03`), `curr_bed_type`, `filament_colors` usw. Alle Werte sind Strings. Echte Datei: drei Einträge, darunter ein veralteter für `Default Printer`. | Abhängigkeiten eines Druckers über `presets.machine` **und** `orca_presets` prüfen. Veraltete Einträge markieren, nicht automatisch löschen. |
| `"preset_folder"` | liegt unter `app`, siehe 4.2 | – |
| `"header"` und alles andere unverändert | `header` wird bei jedem Speichern neu erzeugt (`"Snapmaker Orca 2.4.0"`, `"OrcaSlicer 2.5.0-dev"`). Das ist die **einzige zuverlässige Versionsangabe**, denn `app.version` ist `SLIC3R_VERSION` (`01.10.01.50`). Unbekannte Schlüssel überleben nur als Objekt mit String- oder Bool-Werten. | Version aus `header` anzeigen. OrcaOne legt keine eigenen Schlüssel in der `.conf` ab. |
| Windows-Prüfsumme | Gehasht wird der JSON-Text **ohne** abschließenden Zeilenumbruch, im Format der Slicer-Version (`dump(4)` bzw. `dump(1, '\t')`). Datei = JSON + `\n` + `# MD5 checksum <HEX>` + `\n`. HEX sind Großbuchstaben (`boost::algorithm::hex`). Bei jedem Speichern entsteht eine `.bak`. | `hashlib.md5(text).hexdigest().upper()` über den LF-Text. Ob die Datei auf der Platte CRLF hat, klärt erst eine echte Windows-Datei. |
| Falsche Prüfsumme: nur Log | Bestätigt. | – |
| JSON-Fehler: Wiederherstellung aus `.bak` (Windows) | **Präzisiert, gilt für alle Plattformen:** Bei einem Syntaxfehler probiert nur Windows die `.bak`. Sonst meldet der Slicer den Verlust und setzt alle Einstellungen auf Standard. **Typfehler** in gültigem JSON, etwa ein Nicht-String in `models`, `filaments` oder `presets`, brechen das Laden mittendrin ab: Die Abschnitte vor dem Fehler sind übernommen, alles danach geht verloren. Ein Nicht-String in `orca_presets[].filament` lässt SnOrca beim Start mit „GUI initialization failed“ abbrechen. Unter Windows wirft eine Datei, die direkt auf `}` ohne Zeilenumbruch endet, eine nicht abgefangene Ausnahme. | Nach dem Erzeugen die Datei neu parsen und die Typen der bekannten Abschnitte prüfen. Immer mit `\n` enden. |
| SnOrca benennt Filamentnamen um (`update_filament_names`) | Nur eine feste Tabelle von etwa 70 alten J1- und Dual-Namen. Betrifft `"filaments"` und `orca_presets`. | Für den U1 ohne Bedeutung. |
| Wann der Slicer die .conf schreibt | Beim Start (Linux und macOS ohne Bedingung, noch vor dem Laden der Profile), im Leerlauf, sobald sich ein Wert geändert hat, und beim Beenden. Nicht periodisch. Unter POSIX löscht der Slicer das Ziel vor dem Umbenennen, die `.conf` kann also kurz fehlen. | Bestätigt Regel 3. Fehlt die `.conf` beim Scan, versucht OrcaOne es erneut, statt einen Fehler zu melden. Die neue Datei übernimmt die Dateirechte der alten, denn `mkstemp` legt sie mit 0600 an. |
| Escaping in `"models"` und `renamed_from` | Gelesen wird in beiden Slicern gleich (`unescape_strings_cstyle`). Beim Schreiben setzt Orca main einen Wert auch bei `;` in Anführungszeichen, SnOrca nur bei Leerzeichen, Tab, `\`, `"`, CR, LF und leerem Einzelwert. | Beim Schreiben die Variante des Ziel-Slicers nehmen. |

**Zugangsdaten in der .conf:** SnOrca speichert unter `"devices"` je LAN-Gerät `api_key`, `user`, `password`, `ca`, `cert`, `key` und `clientId`, Orca unter `"local_machines"` den `access_code`. OrcaOne maskiert diese Werte im Diff (Regel 5) und in der Anzeige.

## 4.4 Aufbau eines Profils

| Spezifikation | Befund | Folge für OrcaOne |
|---|---|---|
| Beispiel `SUNLU PLA+ @System` | Zeichen für Zeichen bestätigt. | – |
| Wichtige Schlüssel | Metaschlüssel sind `version`, `name`, `type`, `from`, `inherits`, `instantiation`, `setting_id`, `filament_id`, `description`, `renamed_from`, `url` und `is_custom_defined` (nur SnOrca), dazu `include` (nur Orca 2.5: ein Name oder eine Liste von Basisprofilen, eingeschichtet unter die eigenen Werte). **`base_id` steht nie in einer Profil-JSON**, nur in der `.info`. **`type` fehlt in Benutzer-JSONs.** | Typ aus dem Ordner ableiten. `base_id` aus der `.info` lesen. |
| `from`: `system` bzw. `User` | Systemdateien haben `"system"`. Beim Speichern schreibt der Slicer `"User"`, `"Project"`, `"System"` oder `"Default"`, Orca main auch `"Bundle"`. Der Exportdialog schreibt `""`. In Orca main hat sogar eine Systemdatei `"from": "User"`. | Herkunft **nie** aus `from` ableiten, sondern aus dem Speicherort. |
| `renamed_from` | Immer ein **String**, mehrere Namen mit `;` getrennt, optional in Anführungszeichen mit C-Escapes. Fehlt der Schlüssel und enthält der Name ein `@`, gilt der Name ohne `@` als impliziter Eintrag: `Generic PLA @System` wird zu `Generic PLA System`. | Den Resolver und die Sichtbarkeit auch über implizite Namen prüfen. |
| Werte als String-Arrays | Nur Strings oder String-Arrays. Zahlen und Bools verwirft der Slicer. Derselbe Schlüssel kann skalar oder als Array vorkommen. SnOrca hat Flow-Varianten `*_flow_support = ["standard","high_flow"]` mit einem Wert je Variante, die Orca nicht kennt. | `"x"` und `["x"]` beim Vergleich gleich behandeln. Arrays als „Standard / High Flow“ beschriften. Beim Übertragen SnOrca → Orca nur den ersten Wert übernehmen. |
| Name statt Dateiname maßgeblich | **Systemprofile:** Stimmt (6 Abweichungen im echten `system/`, darunter das Marble-Beispiel). **Benutzerprofile:** SnOrca nimmt `name`, **Orca ab v2.4.x nimmt den Dateinamen** und ignoriert `name`. | Beim Schreiben sind Dateiname und `name` immer gleich. Abweichungen zeigt OrcaOne als Warnung. |
| Benutzerprofile speichern nur Abweichungen | Stimmt: `diff(parent)` plus immer `version`, `name`, `from`, `inherits` und den passenden `*_settings_id`. Wurzelprofile ohne Elternprofil speichern die komplette Konfiguration nach `<typ>/base/`. | Beim flachen Schreiben alle Werte, beim Anhängen nur die Differenz plus Pflichtschlüssel. |
| Ohne Elternprofil „verwaist“ | Der Slicer **lädt** solche Profile nicht (Log „can not find parent“), die Datei bleibt liegen. Vorher versucht er `renamed_from` und einen Rückgriff: Namen mit `Generic` werden auf `Generic <Material> @System` der Bibliothek abgebildet. Nur SnOrca lädt sie mit `is_custom_defined = "1"` trotzdem, dann mit Standardwerten. | Den Status „verwaist“ als „im Slicer unsichtbar“ erklären. Zusätzlicher Status „Ersatz-Elternprofil“, wenn der Generic-Rückgriff greift. |
| `.info`-Format | Bestätigt: `sync_info`, `user_id`, `setting_id`, `base_id`, `updated_time`. SnOrca schreibt eine vorhandene `.info` beim Laden neu, wenn `updated_time` fehlt. | `.info` immer mit `updated_time` schreiben. |

**Wann der Slicer Benutzerprofile löscht oder überspringt:**

| Fall | Folge |
|---|---|
| Ungültiges JSON, ein Wert, der sich nicht umwandeln lässt (z. B. `"abc"` für eine Zahl), ein Nicht-String in einem der Metaschlüssel oben (alle landen in einer `std::map<std::string, std::string>`, `ConfigBase::load_from_json`) | **`.json` und `.info` werden gelöscht.** Ungültig heißt im Sinne von nlohmann::json: eine UTF-8-BOM am Anfang stört nicht, `NaN`, `Infinity` und unpaarige Surrogate wie `\ud800` sind Fehler. |
| `version` fehlt oder ist kein gültiges Semver (2 bis 4 numerische Teile, führende Nullen erlaubt) | still übersprungen |
| Name gleich einem schon geladenen Profil, etwa einem Systemprofil | übersprungen („already present“) |
| `type` passt nicht zum Ordner (nur SnOrca) | übersprungen |
| `"instantiation": "false"` | geladen, aber unsichtbar |
| Ungültige Enum- oder Bool-Werte | durch den Standardwert ersetzt |

**Dateien, die der Slicer von sich aus ändert:**

- Orca main füllt bei Wurzel-Filamenten mit leerer `compatible_printers` den Text nach `@` als Druckernamen ein und speichert die Datei sofort.
- Orca trägt ein per Rückgriff gefundenes Elternprofil in `inherits` ein.
- SnOrca bindet die Kopie eines Systemfilaments mit leerer Druckerliste beim „Speichern unter“ an den aktuellen Drucker.

Deshalb zeigt der Schnappschussvergleich nach einem Slicer-Start auch Änderungen, die nicht vom Nutzer kommen.

## 4.5 Vererbung auflösen

| Spezifikation | Befund | Folge für OrcaOne |
|---|---|---|
| Effektive Werte = Elternwerte, überschrieben durch eigene, rekursiv | Die Wurzel ist nicht leer, sondern die **Standardkonfiguration aus `PrintConfigDef`**, gefiltert auf den Typ. Danach füllt `Preset::normalize` Lücken und verlängert Vektoren auf die Extruderzahl bzw. die Flow-Varianten. Bei `SUNLU PLA+ @System` kommen rund 50 Schlüssel nur aus den Standardwerten, etwa `pressure_advance 0.02`. | Werte aus der Kette exakt zeigen, den Rest als „Standardwert des Slicers“ ausweisen. Eine Tabelle der Standardwerte ist ein eigener, späterer Schritt. |
| Systemprofile im Paket, Filamente auch gegen die Bibliothek | Bestätigt. Ladereihenfolge: OrcaFilamentLibrary zuerst, dann die übrigen Hersteller. Fehlt ein Elternprofil oder ist ein Name doppelt, **fällt der ganze Hersteller weg**. Bei der Bibliothek entfernt der nächste Hersteller auch die schon geladenen Bibliotheksprofile. | Warnung „Hersteller würde im Slicer nicht laden“. |
| Benutzerprofile gegen alle geladenen Profile | **Präzisiert:** Aufgelöst wird gegen die Sammlung desselben Typs. Darin stehen **nur wählbare** Systemprofile, das Default-Profil und die eigenen Wurzelprofile aus `base/`. Suchreihenfolge `find_preset2`: exakter Name, dann `renamed_from`, dann der Generic-Rückgriff. Beim **Import** sucht SnOrca dagegen nur exakt, Orca auch hier per `find_preset2`. | Der Resolver bildet `find_preset2` nach. Beim Anhängen nur wählbare Systemprofile oder eigene Wurzelprofile anbieten. |
| Zyklen und fehlende Eltern als Status | Bestätigt. | – |

## 4.6 Sichtbarkeit und Kompatibilität

**Systemdrucker** sind sichtbar, wenn `get_variant(vendor_id, printer_model, printer_variant)` in `"models"` steht. `vendor_id` ist der Dateistamm von `system/<Vendor>.json`. Nur SnOrca schaltet beim Start alle Varianten eines aktiven Modells ein (`install_missing_variants_for_enabled_models`). Drucker gruppieren beide Slicer im Dropdown nach Modell.

**Systemfilamente** in drei Zuständen:

| `"filaments"` in der .conf | Wirkung |
|---|---|
| fehlt, `[]` oder `null` | **Alle** Systemfilamente sind sichtbar, auch die ganze Bibliothek. |
| Liste mit Namen | Sichtbar ist, wessen `name` oder `renamed_from` (auch implizit) exakt in der Liste steht. |

Beim Start ergänzen beide Slicer die `default_materials` jedes sichtbaren Systemdruckers, für den kein kompatibles Filament in der Liste steht. Die Folgen sind je Slicer verschieden:

- **SnOrca:** Keins der 19 Snapmaker-Modelle hat `default_materials`, es wird also nichts ergänzt. Wer in SnOrca alle Filamente ausblendet, bekommt eine leere Liste, und dann ist **alles** sichtbar. **OrcaOne darf `"filaments"` in SnOrca nie leer schreiben.**
- **Orca main:** Alle 19 Snapmaker-Modelle haben `default_materials`. Wer alle Filamente eines Druckers ausblendet, bekommt dessen Standardfilamente zurück. Das zeigt OrcaOne vorher im Plan an.

**Prozesse** hängen nicht an der `.conf`. Sichtbar sind sie, wenn sie zum gewählten Drucker kompatibel sind.

**Kompatibilität mit Drucker P** (`is_compatible_with_printer`), in dieser Reihenfolge geprüft:

1. Ist das Profil ein Bibliotheksfilament und steht P in dessen Ausschlussliste, ist es inkompatibel.
2. Ist `compatible_printers` leer und `compatible_printers_condition` gesetzt, entscheidet allein die Bedingung. Ein Parserfehler zählt als kompatibel. Bei nicht leerer Liste ignoriert der Slicer die Bedingung.
3. Sonst ist das Profil kompatibel, wenn die Liste leer ist, P in der Liste steht oder P ein eigener Drucker ist, dessen **direktes** Elternprofil in der Liste steht.

Folge: OrcaOne zeigt „bedingt“ nur bei leerer Liste und gesetzter Bedingung. Im echten `system/` ist keine Bedingung gesetzt.

**Ausschlussregel der Bibliothek:**

- Der Alias ist der Text vor dem ersten `@`, rechts ohne Leerraum. Ohne `@` ist es der volle Name. Groß- und Kleinschreibung zählen.
- Bibliotheksprofile mit leerer Druckerliste werden für jeden Drucker ausgeblendet, für den ein anderer Hersteller ein Profil mit gleichem Alias und expliziter Druckerliste mitbringt.
- Orca main wendet den Ausschluss zusätzlich über `inherits` auf eigene Drucker an. Dort verdrängen auch Bibliotheksprofile mit eigener Druckerliste.

Das Beispiel aus der Spezifikation stimmt **für SnOrca**: `Generic PLA @System` ist für alle vier U1-Varianten ausgeblendet, weil Snapmaker `Generic PLA` und `Generic PLA @U1 …` mitbringt. Beim U1 0.4 sind 16 Bibliotheksprofile betroffen (Generic ABS, ASA, PETG, PLA, TPU usw.). **Kein SUNLU-Profil ist betroffen**, 126 von 142 Bibliotheksprofilen passen zum U1 0.4.

In **Orca main** ist es umgekehrt: Dort bringt Snapmaker kein Generic-Profil für den U1 mit. `Generic PLA @System` ist kompatibel und steht sogar in den `default_materials` des U1. Ausgeblendet werden dort 23 andere, nämlich Panchroma, PolyLite, PolyTerra und Polymaker HT.

**Weitere Befunde:**

- **SnOrca zeigt bei gleichem Alias nur ein Filament.** Die Seitenleiste legt Systemfilamente nach Alias ab. Von mehreren sichtbaren, kompatiblen Filamenten mit gleichem Alias erscheint nur das erste. Orca nimmt den vollen Namen. OrcaOne warnt davor.
- **Weitere Stellen schreiben `"filaments"` und `"models"` neu:**
  - der Einrichtungsassistent, auch über „Add/Remove presets“ im Kontextmenü;
  - in SnOrca der `WebPresetDialog`, wenn man einen Drucker bindet;
  - in Orca `apply_vendor_config` beim Cloud-Sync.

  OrcaOne vergleicht deshalb bei **jedem** Scan, ob Freischaltungen verloren gingen.
- **Aktueller Stand der echten `.conf`:**
  - In `"filaments"` stehen 13 Namen, alle von Snapmaker. Nur 5 passen zum U1. Die übrigen 8 (`@J1`, `@Dual` usw.) hat der Assistent mitgenommen, weil er nach Kurzname gruppiert.
  - Im Dropdown für U1 0.4 erscheinen aus dem System nur `Snapmaker ABS @U1 0.4 nozzle` und `Snapmaker PLA Basic @U1`.

## 4.7 Die versteckte Bibliothek in SnOrca

| Spezifikation | Befund |
|---|---|
| Leeres Manifest, Dateien trotzdem da, 7 SUNLU-Profile | Bestätigt: 7 × `@System` und 7 × `@base`. Die Programmressourcen haben ebenfalls ein leeres Manifest. |
| SnOrca lädt die Dateien seit 2.3.5 direkt von der Platte | Bestätigt, der Kommentar steht in `load_vendor_configs_from_json`. |
| Unsichtbar, weil nicht in `"filaments"`; der Assistent kann sie nicht anbieten | Bestätigt. |
| Manifest ändern ist zwecklos | Bestätigt: Die Bibliothek wird bei jedem Start ersetzt. |
| Assistent schreibt `"filaments"` neu | Bestätigt. Dazu kommen die weiteren Auslöser aus 4.6. |
| „SUNLU PLA+“ ist dünn | Präzisiert: `SUNLU PLA+ @System` setzt selbst nur `compatible_printers = []`. Die 12 Werte kommen aus `SUNLU PLA+ @base`: Preis 18,99, Dichte 1,23, Flow 1,0, Volumengeschwindigkeit 12, Hersteller SUNLU, Scarf-Naht, Erweichungstemperatur 54. Die Temperaturen (220 °C, Bett 55 °C) kommen aus `fdm_filament_pla`. |

**Kann man die Bibliothek freischalten? Laut Code ja.**

- Die Bibliotheksprofile stehen als Systemprofile in der Filament-Sammlung.
- `set_visible_from_appconfig` macht jeden Namen aus `"filaments"` sichtbar. Nichts entfernt unbekannte Namen beim Laden.
- Für den U1 ist kein SUNLU-Profil ausgeschlossen.

**Zwei Wege:**

| Weg | Vorteil | Nachteil |
|---|---|---|
| **A: Eintrag in `"filaments"`** | kein zusätzliches Profil | geht verloren, wenn der Assistent, der WebPresetDialog oder die Druckerbindung läuft |
| **B: eigenes Profil** mit `inherits: "SUNLU PLA+ @System"` und ohne weitere Abweichungen | übersteht Assistent und Druckerbindung, weil `find_preset2` auch unsichtbare Bibliotheksprofile findet und eigene Profile nicht an `"filaments"` hängen | zusätzliches Benutzerprofil, das bei Anmeldung womöglich in die Cloud synchronisiert wird |

Das eigene Profil aus Weg B erbt `compatible_printers = []` und passt damit zu jedem Drucker.

**Kleinster sicherer Test:**

1. SnOrca schließen.
2. Das Datenverzeichnis in ein temporäres Verzeichnis kopieren.
3. Nur in der Kopie `"SUNLU PLA+ @System"` an `"filaments"` anhängen.
4. SnOrca mit `--datadir <Kopie>` starten.

Weg B testet man genauso. Beide Tests stehen noch aus.

**Weitere Befunde:**

- Die Bibliothek in SnOrca ist älter als in Orca main: Manifest 02.03.01.10 gegen 02.04.00.09, 274 gegen 543 Dateien. Außerdem hat sie **eigene IDs**. Bei 232 von 272 gemeinsamen Profilen unterscheiden sich nur `setting_id` und `filament_id`, bei 40 auch Werte. Profile werden deshalb zwischen den Slicern über den **Namen** zugeordnet, nie über IDs.
- SnOrca setzt bei Systemfilamenten ohne eigene `filament_id` zuerst die `setting_id` ein. Bei `SUNLU PLA+ @System` ist die `filament_id` also `OSNLS03`. SnOrcas `@base` hat `OGFSNL03`, in der Orca-Nightly heißt `SUNLU PLA+ @base` dagegen `OFMUWNkp` (main `…/SUNLU PLA+ @base.json:6`, geprüft 23.09.).
- Material4Print gibt es in keinem U1-relevanten Paket. Es kommt nur per Import herein, damit bleibt der ZIP-Import ein guter Testfall für Phase 3.

## 4.8 Import und Export

| Spezifikation | Befund | Folge für OrcaOne |
|---|---|---|
| Import von `.json`, `.zip`, `.orca_printer`, `.orca_filament` | Bestätigt für SnOrca. **Orca** zusätzlich `.orca_bundle`. | OrcaOne liest auch `.orca_bundle`. |
| `.orca_*` sind ZIPs mit `bundle_structure.json` | Bestätigt, mit zwei Formaten (Beispiel unten). | – |
| Wie der Import arbeitet | Den Typ erkennt der Slicer **nur** am Vorhandensein von `printer_settings_id`, `print_settings_id` oder `filament_settings_id`, `type` ignoriert er. Ohne gültige `version` überspringt er die Datei still. `inherits` muss exakt ein geladenes, wählbares Profil treffen. Eltern müssen im ZIP vor ihren Kindern liegen. Gleichnamige Systemprofile überspringt er ohne Meldung. Bei Konflikten fragt er „Ja / Nein / für alle“, ohne Umbenennen. Eine Kompatibilitätsprüfung findet trotz Meldungstext nicht statt. Rohdateien aus `system/OrcaFilamentLibrary` haben weder `version` noch `*_settings_id` und werden deshalb **still ignoriert**. | Von OrcaOne erzeugte Importdateien bekommen immer `version`, `name` und `*_settings_id`. |
| Ziel des Imports | SnOrca schreibt immer flach nach `user/<ordner>/<typ>/` (Wurzelprofile nach `base/`). **Orca** legt ein Archiv **mit** `bundle_structure.json` als lokales Bundle unter `_local/<neue UUID>/` ab. Ein zweiter Import desselben Bundles erzeugt dort Dubletten. | Für Orca-Ziele standardmäßig eine `.zip` **ohne** `bundle_structure.json` erzeugen, dann entstehen normale Benutzerprofile. |
| IDs eigener Profile (Phase 3) | **`setting_id` wird lokal nie erzeugt**, sondern kommt nur aus der Cloud. `filament_id` ist `"P"` plus die ersten 7 Hex-Zeichen von `md5(<Name vor " @">)`. Hat ein Filament mit gleichem Namensstamm schon eine ID, wird sie wiederverwendet. Bei einer Kollision kommt ein Zeitstempel in den Hash. Der Slicer prüft beim Import keine Eindeutigkeit. | `setting_id` nie mitkopieren. `filament_id` nur für flache Filamente vergeben, nach demselben Algorithmus, und gegen alle Filamente des Ziels prüfen. |

**`bundle_structure.json`** (Export-Code, hier lesbar formatiert; der Slicer schreibt kompakt und sortiert):

```json
{
    "bundle_id": "offline_My U1_20260921143000",
    "bundle_type": "printer config bundle",
    "filament_config": ["filament/SUNLU PLA+ @My U1.json"],
    "printer_config": ["printer/My U1.json"],
    "printer_preset_name": "My U1",
    "process_config": ["process/0.20mm Standard @My U1.json"],
    "version": ""
}
```

```json
{
    "bundle_id": "offline_SUNLU PLA+_20260921143000",
    "bundle_type": "filament config bundle",
    "filament_name": "SUNLU PLA+",
    "printer_vendor": [
        {"vendor": "Snapmaker", "filament_path": ["Snapmaker/SUNLU PLA+ @Snapmaker U1 (0.4 nozzle).json"]}
    ],
    "version": ""
}
```

**Inhalt der Bundles beim Export:**

- `printer/` enthält Vollkopien der Drucker ohne `print_host` und `printhost_*`. Auch ein Systemdrucker steht so darin, mit `"from": "System"` und ohne `inherits` (SnOrca, `Snapmaker U1 (0.4 nozzle).orca_printer` vom Nutzer, 24.09.2026). OrcaOne nennt ihn beim Import „Systemprofil, gibt es hier“ und übernimmt ihn nicht.
- `filament/` und `process/` enthalten die Rohdateien mit `inherits`.
- Elternprofile sind nie dabei.

**Export-Dialog:** Er erzeugt `.orca_printer`, `.orca_filament` oder die festen ZIPs `Printer presets.zip`, `Filament presets.zip` und `Process presets.zip`. Solange er offen ist, legt er `user/Temp/` an. Die ZIPs eignen sich direkt als Importquelle für OrcaOne.

**Filamente nur für eine Düse (24.09.2026, SnOrca):** Manche Herstellerfilamente gibt es nur für die 0,4-mm-Düse des U1, etwa „Polymaker General PLA Family @U1“, „… Silk PLA Family @U1“ und „… Tough PLA Family @U1“: im Paket nur `… @U1` und `… @U1 base`, Druckerliste nur `Snapmaker U1 (0.4 nozzle)`. Andere, etwa „Generic PLA“, liefert Snapmaker je Düse (`Generic PLA @U1 0.6 nozzle`). Mit der 0,6er-Düse bietet der Slicer die ersten deshalb nicht an.

**Muster „Flach“:** „Filament erstellen“ legt je Drucker ein flaches Profil an: `<Hersteller> <Typ> <Serie> @<Druckername>`, `compatible_printers = [<Drucker>]`, abgelegt in `filament/base/`. Nach diesem Muster kann OrcaOne die Strategie „Flach“ umsetzen.

**Profile in Projekten und Drucken (geprüft 23.09.2026, für den Import, docs/IMPORT-QUELLEN.md):**
- **3MF:** Eigene Profile, die ein Projekt nutzt, bettet der Slicer vollständig ein, als `Metadata/{machine,filament,process}_settings_N.config`. Er schreibt sie mit `save_to_json(…, "project", version)` (`bbs_3mf.cpp`), also mit allen Werten, `inherits` und `"from": "project"`. Den Namen nimmt er beim Lesen aus `*_settings_id`. Systemprofile stehen nur mit Namen in `Metadata/project_settings.config`. Dort zeigen `inherits_group` (Prozess, Filament 1…n, Drucker) und `different_settings_to_system`, was abweicht.
- **G-Code:** Jeder Druck trägt die ganze Konfiguration als `; Schlüssel = Wert` zwischen `; CONFIG_BLOCK_START` und `; CONFIG_BLOCK_END`, bei Bambu-Druckern am Anfang, sonst am Ende (`GCode.cpp`). Am U1 enthält die Datei des letzten Drucks 564 Werte, darunter `filament_settings_id = "M4P Orange";…`, `filament_vendor = Material4Print`, `inherits_group = ;"Snapmaker PLA Basic @U1";…` und `different_settings_to_system`. Orcas `PresetBundle::load_config_file` liest Einstellungen nur aus G-Code.
- **3MF aus Bambu Studio:** Zwei Projekte des Nutzers, aus Bambu Studio 1.8.4 (`prototypes/m3Sorter_04_mini.3mf`, Bambu Lab A1 mini) und 1.9.3 (`prototypes/Happy_Shark_3MF.3mf`, Bambu Lab A1), haben in `project_settings.config` alle Werte (335 bzw. 355) und die Namen der Profile, aber weder `inherits_group` noch `different_settings_to_system` und keine eingebetteten Profile. Sie nutzen nur Systemprofile; ob Werte davon abweichen, steht nicht darin. OrcaOne nennt dann Herkunft (`Application` in `3D/3dmodel.model`) und die genutzten Profile. Das Modell trägt die Netze und kann groß sein (Happy Shark: 11 MB), die Metadaten stehen an seinem Anfang.
- **3MF im Slicer öffnen** (Quellcode, `Plater.cpp`): Die Einstellung „Ladeverhalten“ (`project_load_behaviour` in der `.conf`) kennt „Alle laden“, „Fragen, wenn relevant“, „Immer fragen“ und „Nur Geometrie laden“. Vorgabe ist „Fragen, wenn relevant“, so steht es auch auf diesem Rechner in beiden Slicern. Das fragt nur, wenn schon Objekte auf der Platte liegen; sonst öffnet der Slicer das 3MF als Projekt, samt Drucker, Filamenten und Prozess des Projekts. Beim Nutzer kam so der Bambu Lab A1 in den Slicer. Nach dem Beenden standen in `Snapmaker_Orca.conf` ein Eintrag in `orca_presets` für „Bambu Lab A1 0.4 nozzle(Happy_Shark_3MF.3mf)“ mit Prozess, drei Filamenten „…(Happy_Shark_3MF.3mf)“ und ihren Farben, dazu die Datei in `recent_projects`; in `user/` nichts. Die Frage bietet „Als Projekt öffnen“ und „Nur Geometrie importieren“ (`determine_load_type`, `ProjectDropDialog`). Strg+I („Importiere 3MF/STL/STEP/SVG/OBJ/AMF“) lädt in Snapmaker Orca 2.4.0 nur die Geometrie (`Plater::add_model`, `LoadStrategy::LoadModel`). In OrcaSlicer main öffnet Strg+I ein einzelnes 3MF dagegen wie „Öffnen“ (`Plater::add_file` → `open_3mf_file`). Snapmaker Orca bringt nur die Herstellerpakete Snapmaker und die Orca-Bibliothek mit, einen Bambu-Drucker kann man dort nicht einrichten.
- **Was der Slicer aus einem 3MF liest** (`bbs_3mf.cpp`, `Plater::priv::load_files`): `Metadata/project_settings.config` immer, auch beim Import nur der Geometrie. Die eingebetteten Profile (`Metadata/print_setting_*`, `process_settings_*`, `filament_settings_*`, `machine_settings_*`), `slice_info.config`, den G-Code der Platten und die Bilder nur beim Öffnen als Projekt. Drucker, Prozess und Filamente legt er nur an, wenn die Einstellungen nicht leer sind (`load_config && !config_loaded.empty()`) oder Profile eingebettet sind. G-Code einer Platte lädt er nur, wenn die Datei da ist. Ein 3MF ohne diese Teile öffnet er deshalb als Projekt mit dem gewählten Drucker; so bereinigt OrcaOne (`importer.clean_3mf`). Beim Nutzer geprüft: Die bereinigte Happy-Shark-Datei öffnet Snapmaker Orca mit dem U1, ohne neuen Eintrag in `orca_presets`. Snapmaker Orca 2.4.0 übernimmt beim Import nur der Geometrie auf eine leere Platte die Farben und die Zahl der Filamente des Projekts (`geometry_only_project_import`); ein bereinigtes 3MF hat keine Farben mehr.
- **„Import Configs“** (`MainFrame::load_config_file`, in beiden Slicern gleich) nimmt `.json`, `.zip`, `.orca_printer`, `.orca_bundle` und `.orca_filament` und importiert alles auf einmal, ohne Vorschau und ohne Auswahl. 3MF-Projekte nimmt er nicht.

## 4.9 3MF-Projekte

| Spezifikation | Befund |
|---|---|
| Archivaufbau und Dateinamen der eingebetteten Profile | Bestätigt (`bbs_3mf.cpp` und `.hpp`). In `project_settings.config` haben `inherits_group` und `different_settings_to_system` die Reihenfolge `[Prozess, Filament 1…n, Drucker]`. |
| Beim Öffnen Projektprofile im Speicher, versteckte Systemprofile werden sichtbar | Bestätigt. Einen Projektnamen `<Name>(<Datei>.3mf)` gibt es nur, wenn der Originalname nicht existiert oder bei weiteren Filamenten mit abweichenden Werten. |
| Was dauerhaft bleibt | **Präzisiert:** Das Öffnen selbst schreibt **nie** nach `user/` und ändert weder `"filaments"` noch `"models"`. Es ändert nur `"presets"`, den Druckereintrag in `"orca_presets"` sowie `app.import_project_action` und `app.project_load_behaviour`. Dateien in `user/` entstehen erst über Speichern-Dialoge. |

- Folge für „Neu seit dem letzten Scan“: Neben Dateien, `"models"` und `"filaments"` auch `"presets"`, `"orca_presets"` und die beiden `app`-Schlüssel vergleichen.
### Fremde Drucker aus 3MF-Projekten (geprüft am 22.09.2026)

Frage des Nutzers: „Ich hatte extrem oft auf einmal einen Bambu-Drucker in meiner Auswahl.“ Zwei Agenten haben das am Quellcode geprüft, der zweite als Gegenprüfer. Ausprobiert ist nichts davon.

- **Ohne Rückfrage:** Beide Datenordner stehen auf `ask_when_relevant`. Ist die Platte leer, lädt der Slicer eine 3MF **ohne Frage** als ganzes Projekt samt Druckerprofil. Das gilt auch für Drag & Drop und für Strg+I „Importieren“ (Plater.cpp:19777–19786, MainFrame.cpp:672–674). Nur bei belegter Platte fragt er, und dann ist „Als Projekt öffnen“ vorgewählt. Das erklärt das „auf einmal“.
- **Im Speicher:** Der Drucker heißt dann `"<Name>(<Datei>.3mf)"` und steht nur im Speicher. Ist ein gleichnamiges Systemprofil installiert, wählt der Slicer stattdessen dieses und markiert es als geändert. Geschrieben wird nichts nach `user/`, auch nichts in `"models"` oder `"filaments"`.
- **Nach „Neues Projekt“ oder Schließen** wählt der Slicer einen Ersatzdrucker und speichert die Auswahl. Übrig bleiben:
  - ein `"orca_presets"`-Eintrag für den Projektdrucker, der nie gelöscht wird;
  - vermutlich Anzahl und Farben der Filament-Plätze aus dem Projekt, dann am Ersatzdrucker. Das ist aus dem Code abgeleitet.
- **`presets.machine` mit `(….3mf)`** bleibt nur nach einem Absturz stehen.
- **Dauerhaft wird der Drucker nur auf drei Wegen:**
  1. **Aktiv gespeichert:** Im Speichern-Dialog umbenannt und „Benutzervoreinstellung“ gewählt. Oder, bei installiertem BBL-Paket, im Dialog für ungespeicherte Änderungen „Speichern“ geklickt, dann entsteht `… - Kopie.json`. Zeigt `inherits` auf einen nicht installierten Bambu-Drucker, überspringen beide Slicer die Datei beim Start. Sie ist dann **unsichtbar verwaist**.
  2. **Wiederherstellen nach Absturz:** beide Slicer, wieder nur im Speicher.
  3. **Orca mit Cloud-Anmeldung** und `sync_user_preset = true`: Ein Cloud-Profil auf Bambu-Basis installiert das BBL-Paket nach `system/` und ergänzt `"models"` und `"filaments"`. SnOrca hat diesen Weg nicht.
- **Die aktuellen Datenordner** wurden am 21.09. neu angelegt. Sie enthalten keinen Bambu-Eintrag. Der `orca_presets`-Eintrag „Default Printer“ in SnOrca stammt vom ersten Start vor dem Assistenten.

**Was OrcaOne erkennt (Seite „Drucker“, Aufräumen):**
- `"orca_presets"`-Einträge, deren `machine` sich nicht auflösen lässt, mit oder ohne `(….3mf)`.
- Eigene Profile mit `(….3mf)` im Namen, mit fehlendem Elternprofil (unsichtbar verwaist) oder mit `printer_model` eines nicht installierten Herstellers.
- In Orca `BBL` in `"models"` ohne eigenen Auftrag.

- Herkunft der 3MF: SnOrca schreibt `Application = Snapmaker_Orca-2.4.0`. Orca erkennt diesen Tag nicht und behandelt die Datei als „fremd“, lädt die Einstellungen laut Code aber trotzdem. Getestet ist das nicht.

## 4.10 Quellcode-Referenzen

Die Liste ist richtig. Folgende Dateien fehlen darin:

- `src/libslic3r/PresetCacheFormat.{hpp,cpp}` (Orca main, `.opc`)
- `src/libslic3r/utils.cpp` (Installation von Herstellern)
- `src/slic3r/GUI/InstanceCheck.cpp` (Lock-Datei)
- `src/slic3r/GUI/ExportPresetBundleDialog.cpp` (Orca, `.orca_bundle`)
- `src/libslic3r/Semver.hpp` und `semver.c` (gültige `version`-Werte)

---

## Beobachtung: Erststart der OrcaSlicer-Nightly (21.09.2026, 13:24)

Der Nutzer hat OrcaSlicer 2.5.0-dev gestartet und den Einrichtungsassistenten mit „Generic Klipper Printer“ (Hersteller `Custom`) abgeschlossen. Das Datenverzeichnis `~/.config/OrcaSlicer` bestätigt die Befunde:

- `system/` enthält nur `Custom.opc` und `OrcaFilamentLibrary.opc`, keine JSON-Dateien und keine Herstellerordner.
- Die `.conf` ist mit Tab eingerückt, `header` = `OrcaSlicer 2.5.0-dev`. `"filaments"` enthält 10 `Generic … @System`.
- Weitere Einträge: `printers/` (Druckerbeschreibungen wie `BL-P001.json`, keine Profile), `orca_plugins/`, `python/`, `ota/`, `user_backup-v2.5.0-dev/` und `user/hints.cereal`.
- `user/default/{filament,machine,process}` ist leer.

Um 13:28 hat der Nutzer in Orca zusätzlich den Snapmaker U1 installiert:

- `system/Snapmaker.opc` ist dazugekommen, 414.364 Byte, byte-gleich mit der Datei aus der AppImage.
- `"models"`: `{"model": "Snapmaker U1", "nozzle_diameter": "0.2;0.4;0.4+0.6;0.6;0.8", "vendor": "Snapmaker"}`. Die Variante `0.4+0.6` gibt es nur in Orca.
- Orca hat die `default_materials` des U1 selbst in `"filaments"` eingetragen, etwa `Panchroma PLA @Snapmaker U1` und `Snapmaker PLA SnapSpeed @U1 0.2 nozzle`. Das bestätigt 4.6.

## Das .opc-Format (OrcaSlicer main)

Der Prototyp liegt in [prototypes/opc](../prototypes/opc/README.md). Er hat alle 65 `.opc` der Nightly vom 21.09.2026 gelesen, zusammen 12.618 Profile in 2 s.

- **Abgleich:** Namen, `inherits`, `setting_id`, `filament_id` und `instantiation` stimmen mit den JSON-Quellen gleicher Version überein. Werte gleich nach Normalisierung: 99,95 %.
- **Woher der Rest kommt:** Orca schreibt beim Laden alte Werte um, der Cache enthält also, was der Slicer tatsächlich verwendet.

```
Kopf, 20 Byte, little endian
  u32 magic 0x4F52435A ("ZCRO" auf der Platte) · u32 version · u64 data_size · u32 crc32 (zlib.crc32 über den Rumpf)
Rumpf (cereal binär; Längen u64, Anzahlen in Listen, Konfiguration und Enums u32)
  u32 cache_version · str vendor_name · str vendor_version ("2.4.0.15")
  Wörterbuch: vec<str> keys · vec<u16> types (ConfigOptionType) · vec<str> enum_values ([0] = "")
  VendorMap: size + (str, VendorProfile{name, id, config_version, …, vec<PrinterModel> models, set default_filaments, …})
  3 Listen: process, filament, machine – je u32 count × {str name, str sub_path,
      config: u32 n × (u16 key_index, Wert nach Typ), str inherits, [ab Version 2: vec<str> includes],
      str description, str instantiation, str setting_id, str filament_id, vec<str> renamed_from}
  u64 parse_errors
```

**Versionen:** `1` war die Nightly vom September 2026. **`2` seit dem 24.09.2026** (Commit `2b602943a5`, „Load profile includes so synced Bambu Lab presets get their G-code back“, damit in der 2.5.0-Alpha): Jeder Eintrag trägt nach `inherits` die Liste `includes` (Profil-JSONs: Schlüssel `"include"`, ein Name oder eine Liste). Der Slicer schichtet die Werte eines solchen Basisprofils zwischen Elternkette und eigenen Werten ein, in der angegebenen Reihenfolge (`load_vendor_preset`): Die Basis liefert ihre aufgelöste Konfiguration als Differenz zur Standardkonfiguration, Includes bleiben im selben Herstellerpaket, ein fehlender Include wird nur geloggt, das Profil lädt trotzdem. OrcaOne bildet das in `resolver.layers()` ab (Näherung: die volle Kette des Includes statt der Differenz).

**Typcodes:**

| Typ | Code | Wert |
|---|---|---|
| Float | `0x01` | f64 |
| Int | `0x02` | i32 |
| String | `0x03` | str |
| Percent | `0x04` | f64 |
| FloatOrPercent | `0x05` | f64 plus bool |
| Point | `0x06` | 2 × f64 |
| Point3 | `0x07` | 3 × f64 |
| Bool | `0x08` | u8 |
| Enum | `0x09` | u16-Index in `enum_values`. Bei Index 0 folgt ein i32-Rohwert |
| Vektoren | `0x4000` + Skalarcode | – |
| PointsGroups | `0x400A` | – |
| IntsGroups | `0x400B` | – |

Nil-Werte: NaN, `INT_MAX` bzw. 255.

**Was im Cache fehlt:**

- `from`, `type` und Schlüssel, die `print_config_def` nicht kennt.
- Die Rohformatierung: Aus `"1.0"` wird `"1"`, aus Kommazahlen in Ganzzahl-Optionen werden Ganzzahlen.
- Die machine_model-Dateien liegen nicht einzeln vor, stecken aber vollständig in `VendorProfile.models`.

**Regeln für OrcaOne:**

- `CACHE_VERSION` 1 und 2 parsen, vorher Magic, Größe und CRC prüfen.
- Bei unbekannter Version nicht raten. Liegt daneben ein JSON, dieses lesen. Sonst den Hersteller als „vorhanden, Format nicht unterstützt“ zeigen und abhängige Benutzerprofile als „nicht auflösbar“ markieren.
- Liegen `.opc` und JSON nebeneinander, nimmt Orca den Cache, wenn dessen Stempel mindestens so neu ist wie das JSON (`cache_covers`). OrcaOne wendet dieselbe Regel an.
- Eigene Profile schreibt Orca main weiter als JSON plus `.info` (`Preset::save`, `load_presets` in `Preset.cpp`), `.opc` gibt es nur in `system/`. Auf einer Kopie des echten Ordners geprüft (23.09.2026): Ein neues eigenes Profil auf einem Profil aus `Snapmaker.opc` bekommt `version` 2.5.0 und eine `.info` mit der `base_id` aus der `.opc`. Die `.conf` bleibt mit Tab eingerückt, Wiederherstellen ergibt die Kopie Byte für Byte.

---

## Schnappschuss: was sich ohne Zutun des Nutzers ändert (Phase 1)

| Was ändert sich | Wann |
|---|---|
| die `.conf` | bei Start, Leerlauf und Beenden, z. B. durch Fenstergrößen oder die Auswahl |
| `system/OrcaFilamentLibrary*` | bei jedem Start: die Änderungszeit immer, der Inhalt nur nach einem Programm- oder Hot-Update |
| `hms/`, `log/`, `cache/` | bei jedem Start, die Lock-Datei entsteht und verschwindet |
| `user_backup-v<Version>/` | einmal je Programmversion |
| die Änderungszeit von Ordnern | durch das Umbenennen der `.conf` |
| `.info` mit `updated_time` 0 | SnOrca schreibt sie neu |
| Wurzel-Filamente mit `@` und leerer `compatible_printers` | Orca main schreibt sie neu |
| `user/hints.cereal` | nach dem Beenden |

„Neu seit dem letzten Scan“ vergleicht deshalb nur per Hash: `user/**` ohne `Temp`/`temp`, die Manifeste in `system/` und in der `.conf` nur `models`, `filaments`, `presets`, `orca_presets` sowie `app.project_load_behaviour` und `app.import_project_action`. Nicht verglichen werden `log`, `cache`, `hms`, `ota`, `web` und die Änderungszeiten von Ordnern.

## Abschnitt 7 der Spezifikation

| Punkt | Stand |
|---|---|
| `psutil` oder `/proc` | Entschieden: `psutil`, gebraucht wird es unter Windows. Unter Linux ergänzen Sperrdatei und Arbeitsverzeichnis die Prozessliste. |
| Cloud-Synchronisation | **Teilweise geklärt.** In **SnOrca** wird `preset_folder` nur mit dem Bambu-Netzwerk-Plugin und einer Bambu-Anmeldung zur `user_id`. Die Snapmaker-Anmeldung in der Web-Oberfläche ändert ihn nicht. In **Orca main** setzt die Anmeldung bei OrcaCloud `preset_folder`. Synchronisiert wird in beiden Slicern nur mit `app.sync_user_preset = true`, auf diesem Rechner steht der Wert auf `false`. Bei einem Sync lädt der Slicer Profile, die lokal fehlen, aus der Cloud nach. **Löscht OrcaOne ein synchronisiertes Profil nur lokal, kommt es also zurück.** Der Slicer selbst markiert es beim Löschen mit `sync_info=delete`. Folge: OrcaOne warnt bei angemeldetem Konto und `sync_user_preset = true` und löscht solche Profile nicht selbst. Der Praxistest fehlt noch. |
| Suchreihenfolge der Vererbung | Geklärt, siehe 4.5. SnOrca liest die Bibliothek bei leerem Manifest so ein: `base/` rekursiv, dann `filament/*.json`, dann die Markenordner alphabetisch. In jeder Gruppe kommt `fdm_filament_common` vor `*@base`, dann `*_common`, dann der Rest. |
| Eindeutigkeit von IDs | Geklärt, siehe 4.8. |
| „Bibliothek freischalten“ | Laut Code funktioniert es, siehe 4.7. Der Praxistest steht aus. |
| Vue lokal oder CDN | Entschieden: lokal. |

---

## Abnahme-Checkliste Resolver (4.5)

Für jedes Profil: in OrcaOne die aufgelöste Ansicht öffnen, im Slicer dasselbe Profil öffnen und die genannten Werte vergleichen. Die Punkte 6 bis 8 sind in SnOrca unsichtbar. Sie lassen sich erst nach dem Freischalt-Test oder in einer OrcaSlicer-Installation vergleichen, dort mit gleichen Werten, aber anderen IDs.

- [ ] **1. Drucker `Snapmaker U1 (0.4 nozzle)`:** → `fdm_U1` → `fdm_toolchanger` → `fdm_klipper`. `printable_height` 270.05 (eigen), `retraction_length` 1.5 je Extruder × 4 (eigen), `nozzle_type` hardened_steel (eigen), `gcode_flavor` klipper (`fdm_U1`), `machine_max_acceleration_x` 20000 (`fdm_toolchanger`).
- [ ] **2. Prozess `0.20mm Standard @Snapmaker U1 (0.4 nozzle)`:** → `fdm_process_U1_0.20` → `fdm_process_U1_common` → `fdm_process_U1`. `layer_height` 0.2, `initial_layer_print_height` 0.25 (eigen), `wall_loops` 2, `top_shell_layers` 5, `outer_wall_speed` 200 Standard / 500 High Flow (eigen). Hat `renamed_from` mit zwei Namen.
- [ ] **3. Prozess `0.08mm Standard @Snapmaker U1 (0.4 nozzle)`:** `layer_height` 0.08, `top_shell_layers` 9, `bottom_shell_layers` 7, `initial_layer_print_height` 0.2 (`fdm_process_U1`), `inner_wall_speed` 120 (eigen, skalar gespeichert).
- [ ] **4. Filament `Snapmaker PLA Basic @U1`:** → `… @U1 base` → `fdm_filament_pla_category` → `fdm_filament_common`. `nozzle_temperature` 220, `hot_plate_temp` 65, `filament_max_volumetric_speed` 15, `filament_flow_ratio` 0.98, `filament_density` 1.32.
- [ ] **5. Filament `Snapmaker ABS @U1 0.4 nozzle`:** `nozzle_temperature` 265 Standard / 280 High Flow, `hot_plate_temp` 100, `chamber_temperature` 60, `filament_type` ABS (`fdm_filament_abs_category`), `filament_vendor` Snapmaker (`@U1 base`).
- [ ] **6. Bibliothek `SUNLU PLA+ @System`:** → `@base` → `fdm_filament_pla` → `fdm_filament_common`. `nozzle_temperature` 220, `hot_plate_temp` 55 (`fdm_filament_pla`), `filament_flow_ratio` 1.0, `filament_density` 1.23, `filament_cost` 18.99 (`@base`), `pressure_advance` 0.02 (nur Standardwert).
- [ ] **7. Bibliothek `SUNLU PLA Marble @System`** (Datei `SUNLU Marble PLA @System.json`): `filament_cost` 31.99, `filament_density` 1.25, `filament_retraction_distances_when_cut` 18 (eigen), `temperature_vitrification` 45.
- [ ] **8. Bibliothek `AliZ PETG-CF @System`** (Kette mit 5 Gliedern: → `AliZ PETG-CF @base` → `AliZ PETG @base` → `fdm_filament_pet` → `fdm_filament_common`): `nozzle_temperature` 275 (überschreibt 250), `filament_max_volumetric_speed` 10, `fan_max_speed` 35, `filament_density` 1.27.

---

## Übertragung OrcaSlicer → SnOrca: Filamente (geprüft 23.09.2026)

Anlass: Die Bibliothek der Orca-Nightly (`OrcaFilamentLibrary.opc` 2.4.0.8) hat 307 wählbare Filamente, die von SnOrca 2.4.0 (02.03.01.10) 142. SnOrca fehlen 166, davon zeigt Orca 144 beim U1, etwa FilAr, Elegoo, Eolas Prints, COEX 3D und FILL3D. Keines dieser 144 hat einen Schlüssel, den SnOrca nicht kennt, einen Mehrfachwert, einen unbekannten Enum-Wert oder eine Namenskollision. Belege ohne Präfix: SnOrca 2.4.0, `src/libslic3r/`.

**Wie SnOrca eigene Filamente lädt** (`Preset.cpp:1238-1425`):
- `filament/base/` wird vor `filament/` geladen. Profile ohne Elternprofil gehören nach `base/` (1246-1249).
- Der Name kommt aus `"name"` in der Datei, nicht aus dem Dateinamen. Ein schon geladener Name wird still übersprungen (1313-1322). Orca main nimmt den Dateinamen.
- `version` ist Pflicht und muss gültig sein, sonst wird die Datei still übersprungen (1324-1327).
- Fehlt das Elternprofil, lädt SnOrca das Profil nicht und lässt die Datei liegen (1357-1364). Mit `is_custom_defined: "1"` lädt es trotzdem, dann aber mit den Standardwerten des Slicers.
- Mit Elternprofil ersetzt SnOrca die `filament_id` durch die des Elternprofils (1355).
- Ein unbekannter Schlüssel wird still verworfen, das Profil lädt (`PrintConfig.cpp:7621-7624`). Ein unbekannter Enum- oder Bool-Wert wird durch den Standardwert ersetzt (`Config.cpp:647-679`). Ein Wert, der sich nicht umwandeln lässt, etwa Text als Zahl, lässt SnOrca `.json` **und** `.info` löschen (`Preset.cpp:1290-1300`). Einen Hinweis beim Start gibt es in keinem Fall.
- Eigene Profile sind unabhängig von `"filaments"` sichtbar, sobald sie kompatibel sind (801). Eine gesetzte `compatible_printers` geht vor der Bedingung (769-784). SnOrca füllt `compatible_printers` nicht aus dem Namen, das tut nur Orca main.

**Empfohlenes Format (Variante A, Wurzelprofil):** `user/<ordner>/filament/base/<Alias> @U1.json` plus `.info`.
- Alle Werte der Orca-Kette ausgeschrieben, ohne Elternprofil (`inherits ""`). So legt auch SnOrcas eigener Dialog „Filament erstellen“ Filamente an (2360-2409). Die Standardwerte beider Slicer sind bei allen 102 gemeinsamen Filamentschlüsseln gleich.
- Variante B (Kind eines SnOrca-Systemprofils) ist schwächer: Die `filament_id` kommt dann vom Elternprofil. Werte, die die Orca-Kette nicht setzt, kämen samt High-Flow-Werten von Snapmaker. Und benennt Snapmaker das Elternprofil um, verwaist das Kind, denn die Snapmaker-Filamente haben kein `renamed_from`.
- Nur Filamentschlüssel von SnOrca, je Schlüssel ein Wert als String-Liste; `nil` nur bei den Rückzugswerten, die es erlauben. `filament_flow_support` weglassen: SnOrca füllt dann die High-Flow-Werte mit dem Standardwert auf (409-437).
- Dazu `name`, `from "User"`, `version "2.4.0"`, `inherits ""`, `filament_settings_id [Name]`, `compatible_printers` mit den vier U1-Düsen, `compatible_printers_condition ""`. Nicht schreiben: `type`, `setting_id`, `instantiation`, `renamed_from`, `description`, `is_custom_defined`.
- `filament_id`: eine eigene nach SnOrcas Verfahren, `"P" + md5(Name vor " @")[:7]` (`slic3r/GUI/CreatePresetsDialog.cpp:446-464`), eindeutig im Ziel. Die ID aus Orca nicht übernehmen: Teilt ein Systemprofil sie, fehlt das Filament in der Liste „Eigene Filamente“ des Assistenten. Auf dem U1 selbst spielt die ID keine Rolle, der Drucker meldet Hersteller, Typ und Farbe.
- Name `<Alias> @U1`, nicht `@System`: Nimmt SnOrca das Filament später in seine Bibliothek auf, bliebe die eigene Datei sonst still ungeladen. Die Seitenleiste zeigt den Teil vor „@“.
- Ein Beispiel für „Elegoo PLA @U1“ (71 Schlüssel) besteht OrcaOnes `check_profile` und lädt im Scanner für alle U1-Düsen.

**Probelauf ohne Schreiben (23.09.2026), mit allen echten Profilen:** Orca-Bibliothek → SnOrca 145 von 166 ohne Verlust, 21 abgelehnt, weil ihre Drucker in SnOrca fehlen. SnOrca → Orca alle 222 Filamente und 85 Prozesse; weg fallen nur Einstellungen, die es nur in SnOrca oder bei Bambu gibt.

**Gegenrichtung und Drucker (Stichpunkte):** Orca main lädt kein Profil ohne Elternprofil und bindet eine leere Druckerliste an den Text nach „@“, also immer eine Liste setzen. Von SnOrcas Mehrfachwerten nur den ersten übernehmen. Druckerprofile: Etwa 50 Schlüssel von main kennt SnOrca nicht. `nozzle_volume_type` hat in beiden Slicern andere Werte, SnOrca ersetzt sie still. Bei Druckern nie `is_custom_defined: "1"` setzen, das sperrt „3MF drucken“ (`slic3r/GUI/MainFrame.cpp:1640`).

**Nebenbefund aus Teil B:** SnOrca hat OrcaOnes Hilfsprofil `SUNLU PLA+ (DS)` (Weg B, Kind eines Bibliotheksprofils) geladen, auch mit der Farbe als einzelnem String. „Speichern unter“ machte daraus `SUNLU PLA+ (1DS)` mit `version "2.4.0.0"` und `sync_info = create`.

## Kalibrierung am U1 (geprüft 23.09.2026)

Anlass: Die Anleitung des Nutzers `prototypes/U1 Filament Kalibrierung.md` wird zur Seite „Kalibrieren“. Geprüft gegen SnOrca 2.4.0 (Pfade unter `src/`), die OrcaSlicer-Wiki und den U1 des Nutzers (nur lesend über Moonraker).

**Kalibriertests in SnOrca:**
- YOLO: Jedes Testfeld bekommt `print_flow_ratio = (Flow + Feldwert) / Flow`, gedruckt wird also mit Flow + Feldwert (`slic3r/GUI/Plater.cpp`, `adjust_settings_for_flowrate_calib`). Der neue Wert ist der jetzige plus der Wert des besten Felds, ein Zurücksetzen auf 1,0 ist nicht nötig. „Recommended“: −0,05 bis +0,05 in 0,01er-Schritten; „Perfectionist“: −0,04 bis +0,035 in 0,005er-Schritten (Menütexte in `MainFrame.cpp`, OrcaSlicer-Wiki).
- Max flowrate: Voreinstellung 5 bis 20 mm³/s, Schritt 0,5 (`calib_dlg.cpp`). Durchfluss in Höhe z = Start + z × Schritt (`libslic3r/GCode.cpp`, `Calib_Vol_speed_Tower`).
- Retraction test: Voreinstellung 0 bis 2 mm, Schritt 0,1. Länge in Höhe z = Start + ⌊z − 0,4⌋ × Schritt, sie steigt also je vollem Millimeter ab 0,4 mm (`GCode.cpp`, `Calib_Retraction_tower`). Die Formel „Start + Höhe × Schritt“ der Anleitung ist zu grob.
- Die Tests ändern die bearbeiteten Voreinstellungen: Der Temperaturturm setzt `nozzle_temperature` im Filament auf den Startwert (`Plater::calib_temp`), der Retraction-Test schaltet `use_firmware_retraction` aus. Der Kalibriermodus bleibt, bis ein Modell geladen wird (`Plater::priv::load_files`). Die OrcaSlicer-Wiki rät deshalb, danach ein neues Projekt anzulegen; die geänderten Voreinstellungen dabei verwerfen, nicht in die Kopie speichern.
- Reihenfolge laut OrcaSlicer-Wiki: Temperatur → Max. Volumengeschwindigkeit → Pressure Advance → Flow → Retraction.

**Werte im Filament:**
- `enable_pressure_advance`: „auto calibration result will be overwritten once enabled“. In den U1-Profilen von SnOrca ist es aus (Generic PLA @U1: `0`, `pressure_advance` 0,02, Flow 0,98). SnOrca schreibt bei Klipper `SET_PRESSURE_ADVANCE ADVANCE=…` ohne `EXTRUDER` (`libslic3r/GCodeWriter.cpp:348`).
- `filament_shrink` („Shrinkage (XY)“): 94 % bei 94 statt 100 mm. Daneben gibt es `filament_shrinkage_compensation_z`. Löcher: `xy_hole_compensation` im Prozess.
- `filament_retraction_length` ist der Filament-Override der Retraction.

**Sendedialog:** Den Druck an den U1 schickt SnOrcas Web-Oberfläche (`<Datenordner>/web/flutter_web`). Sie übergibt unter anderem `flow_calibrate`, `flow_calib_extruders`, `shaper_calibrate` und `auto_bed_leveling`; der Text heißt „Flow Calibration“.

**Der U1 selbst (Moonraker, Klipper 1.6.0.267):**
- Die Köpfe heißen `extruder`, `extruder1`, `extruder2`, `extruder3`. Ihr Status liefert `pressure_advance` und `smooth_time` (0,04).
- `print_task_config`: je Kopf Hersteller, Typ, Untertyp und Farbe der Spule (auch von Hand eingegeben), dazu `flow_calibrate` und `flow_calib_extruders` des Auftrags. `filament_detect.info[]`: die RFID-Daten, etwa Temperaturbereich 190–230 °C, Drucktemperatur 220 °C, Trocknen 55 °C für 6 h. Ohne Etikett steht dort überall „NONE“.
- Kopf 4 steht nach dem letzten Druck auf 0,017665, die anderen auf 0,02. Der letzte Druck nutzte Kopf 4 nicht; bei den anderen setzte der G-Code beim Werkzeugwechsel 0,02 („// pressure_advance: 0.020000“ in der Konsole). Eine krumme Zahl ist also ein Messwert, und er bleibt in der Firmware, bis ein Druck den Kopf mit einem anderen Wert belegt. OrcaOne liest das über `printer/objects/query`, ohne etwas an den Drucker zu senden.
- Laut Snapmaker-Forum gilt der Messwert für den Kalibrierdruck; danach setzt ein eingeschalteter Slicer-Wert ihn wieder.

**Kamera der Stock-Firmware (am U1 geprüft 23.09.2026):** Die WebSocket-Methode `camera.start_monitor` mit `{"domain": "lan", "interval": 0}` weckt die Kamera (Antwort „success“ nach 185 ms). Danach liegt das Bild unter `/server/files/camera/monitor.jpg` (117 KB). Wie alt es ist, ergibt die Uhr des Druckers: `Date` minus `Last-Modified`. Das Skript des Nutzers `prototypes/U1Cam/u1cam.py` weckt alle 10 s. Das Licht im Bauraum ist `[led cavity_led]` mit nur `white_pin` (`printer.cfg`). Ist es aus (`color_data` `[[0, 0, 0, 0]]`), liefert die Kamera ein schwarzes Bild, rund 20 KB statt rund 117 KB. `SET_LED LED=cavity_led WHITE=1` über `POST /printer/gcode/script` schaltet es ein, `WHITE=0` aus (am 24.09.2026 einmal ein- und wieder ausgeschaltet).

**Wo die Slicer die Adresse des Druckers ablegen:** Der Dialog „Physischer Drucker“ (Symbol neben der Druckerwahl) speichert „Hostname, IP or URL“ als `print_host`, dazu `host_type`, `print_host_webui` und `printhost_apikey`, in ein eigenes Druckerprofil, dessen Namen man dort vergibt (`PhysicalPrinterDialog::OnOK` → `save_preset`, in OrcaSlicer main und SnOrca gleich). Ein leeres Feld wird nicht gespeichert. Den U1 selbst findet SnOrca ohne gespeicherte Adresse per mDNS (`slic3r/GUI/SSWCP.cpp`, `sw_WakeupFind` und `sw_StartMachineFind`; `slic3r/Utils/Bonjour.cpp`):
- ein UDP-Socket auf Port 5353 mit `SO_REUSEADDR`, der Gruppe 224.0.0.251 auf jeder Schnittstelle beigetreten; die Antworten kommen per Multicast;
- erst „aufwärmen“ mit einer PTR-Anfrage nach `_services._dns-sd._udp.local` (laut Kommentar baut das bei Access Points die Multicast-Weiterleitung auf), dann einmal `_snapmaker._tcp.local`, dann bis zu 20 s lang `_snapmaker._tcp.local` mit 3 Wiederholungen;
- die Anfrage: ID 0, eine Frage, Typ PTR, Klasse ANY (`BonjourRequest::make_PTR`);
- aus der Antwort: Hostname, IPv4 und Port, dazu die TXT-Felder `sn`, `version`, `machine_type`, `link_mode`, `userid`, `device_name`, `ip` und `region`.

Auf diesem Rechner stand die IP in keiner Datei der beiden Slicer (am 23.09. alle Ordner durchsucht, Klartext und UTF-16). Der Grund: Der Rechner erreicht den U1 über WireGuard (`wg0`, 10.30.250.5 → 10.30.40.174), nicht im selben LAN. mDNS ist Link-lokal und geht nicht durch den Tunnel; eine Anfrage genau wie SnOrcas brachte kein einziges fremdes Paket. Von hier findet also auch SnOrca den U1 nicht. OrcaOne sucht auf der Karte eines U1 genauso (`camera.search`); geprüft gegen nachgebaute Antworten und am Windows-Rechner im selben LAN, dort findet es den U1 (Nutzer, 24.09.2026).

**Snapmaker Orca merkt sich einen verbundenen Drucker in der `.conf`** (SnOrca 2.3.6 unter Windows, 24.09.2026; im Quellcode nicht nachgelesen): `devices[]` mit `ip` (10.30.40.174), `dev_name` („Dr. Klippers U1“), `model_name` („Snapmaker U1“), `preset_name` („Snapmaker U1 (0.4 nozzle)“), `sn` und `dev_id`, `port` 8883, `connected`, dazu die Zugangsdaten (`api_key`, `user`, `password`, `ca`, `cert`, `key`, `clientId`). Ein eigenes Druckerprofil mit `print_host` gab es dort nicht. OrcaOne nimmt `ip` als Adresse des Druckermodells, das das Preset nennt (sonst `model_name`), hinter der aus „Physischer Drucker“. Die OrcaSlicer-`.conf` (2.3.0) hat weder `devices` noch `local_machines`; OrcaSlicer hält die Adressen seiner Klipper-Drucker nur als `print_host` in den eigenen Druckerprofilen.

**Was ein Drucker über sich sagt (24.09.2026, am U1 nur gelesen; für die Karte auf „Drucker“, `camera.info`):**
- Standard-Moonraker, also bei jedem Klipper-Drucker: `/printer/info` (Zustand, Klipper `1.6.0.267_20260815150420`), `/server/info` (Moonraker 1.6.0), `/server/files/directory?path=gcodes` (`disk_usage`: 27,4 GB, 24,2 GB frei), `/server/files/list?root=…` (Größen je Ordner), `/server/history/totals` (28 Drucke, 88,6 h Druckzeit, 759 m Filament, längster Druck 20,8 h), `/machine/proc_stats` (Laufzeit, CPU 40 °C, Arbeitsspeicher 187 von 985 MB) und `/machine/system_info` (Betriebssystem Buildroot 2024.02, WLAN `wlan0`).
- Nur Snapmaker: `product_info` in `/machine/system_info` mit dem Namen am Drucker („Dr. Klippers U1“), `firmware_version` 1.6.0, `nozzle_diameter` je Kopf (4 × 0,4) und der Seriennummer, die OrcaOne nicht zeigt. `snapmaker/product_info.json` im Konfigurationsordner nennt noch 1.4.0 und ist veraltet.

**Was ein Drucker gerade tut (24.09.2026, am U1 nur gelesen; für die Seite „Status“, `orcaone/monitor.py`):**
- `/printer/objects/list` nennt 196 Objekte. Heizungen und Temperatursensoren nennt Klipper selbst im Objekt `heaters` (`available_heaters`: Bett und vier Köpfe; `available_sensors`: dazu `temperature_sensor cavity`); Sensoren liefern auch `measured_min_temp` und `measured_max_temp`.
- Lüfter mit `speed` (0 bis 1) und `rpm`: `fan` ist laut `printer.cfg` der Bauteillüfter von Kopf 1 (Pin `e0:PB3`), `fan_generic e1_fan` bis `e3_fan` die der Köpfe 2 bis 4, `heater_fan e0_nozzle_fan` bis `e3_nozzle_fan` die Hotend-Lüfter, dazu `heater_fan power_fan` (ohne Drehzahl) und `fan_generic cavity_fan`.
- Je Kopf `filament_motion_sensor eN_filament` (`filament_detected`, `enabled`) und `filament_entangle_detect eN_filament` (nur `detect_factor`); `filament_feed left` und `right` mit dem Zustand der Zuführung je Kanal.
- Das Objekt `extruder` des U1 hat mehr als bei Klipper üblich: `nozzle_diameter`, `switch_count` (Kopfwechsel, bei Kopf 1 665), `retry_count`, `error_count`, `state` (`PARKED`).
- `motion_report` (`live_velocity`, `live_extruder_velocity`, `live_position`), `gcode_move` (`speed_factor`, `extrude_factor`), `toolhead` (`homed_axes`, `max_velocity` 500, `max_accel` 20000, `axis_minimum` und `axis_maximum`: X 0 bis 271, Y 0 bis 335, Z −6 bis 275 mm), `webhooks` (Zustand von Klipper). `bed_mesh` hat `mesh_min` 3, 3 und `mesh_max` 267, 267 (13 × 13 Punkte laut Konfiguration): die Platte ist 270 × 270 mm, Y bis 335 ist der Bereich, in dem die Köpfe hinter dem Bett parken.
- `/machine/proc_stats`: CPU-Last je Kern, `cpu_temp` (40 °C), Arbeitsspeicher (962 MB), je Netzwerkschnittstelle Bytes und `bandwidth` (`wlan0`, ein unbenutztes `wlan1`, `can0`), Laufzeit, WebSocket-Verbindungen; `throttled_state` ist leer.
- `/server/temperature_store` hält je Heizung und Sensor 1200 Werte, also 20 Minuten, bei Heizungen auch Soll und Heizleistung: genug für Diagramme ohne eigenen Speicher.
- Eine Abfrage für „Status“ (Liste, Abfrage, `proc_stats`) dauerte von hier über WireGuard 0,4 bis 0,5 s.

**Druckstatus für die Seite „Kamera“ (23.09., am U1 nur gelesen):**
- `print_stats` liefert `state`, `filename`, `print_duration`, `total_duration`, `filament_used` und `info` mit `current_layer` und `total_layer`; die Schichten setzt der G-Code mit `SET_PRINT_STATS_INFO`. `print_duration` zählt laut Klipper ohne das Aufheizen vor der ersten Extrusion und ohne Pausen.
- **Statistik der Mikrocontroller** (27.09.2026, nur lesend über `/printer/objects/query`): `mcu` und `mcu e0` … `mcu e3` liefern `last_stats` mit den Feldern wie bei Klipper (`mcu_awake`, `mcu_task_avg`, `mcu_task_stddev`, `bytes_write`, `bytes_read`, `bytes_retransmit`, `bytes_invalid`, `send_seq`, `receive_seq`, `retransmit_seq`, `srtt`, `rttvar`, `rto`, `ready_bytes`, `upcoming_bytes`, `freq`, bei den Köpfen `adj`), dazu `err_len`, `err_dest`, `err_sync`, `err_crc`. `srtt` und `rttvar` stehen auf 0. Die Hauptplatine meldet `SERIAL_BAUD` 921600 und `CLOCK_FREQ` 240 MHz, die Köpfe laufen mit 144 MHz. `toolhead` liefert `stalls`, `print_time` und `estimated_print_time`, `system_stats` liefert `sysload`, `cputime` und `memavail`.
- Weitere Temperaturen: `heater_bed` und `temperature_sensor cavity` (Bauraum). `printer/objects/list` nennt außerdem `machine_state_manager`, `timelapse`, `defect_detection` und `purifier`; OrcaOne nutzt sie nicht.
- `/server/files/metadata?filename=…` liefert die Schätzung des Slicers als `estimated_time`, dazu `layer_count`, `filament_weight_total`, die Filamentnamen und Vorschaubilder. Beim letzten Druck schätzte SnOrca 2.3.6 5289 s, `print_duration` am Ende betrug 5333 s. Die Restzeit in OrcaOne ist deshalb `estimated_time` minus `print_duration`, ohne Schätzung rechnet sie aus dem Fortschritt (`camera._left`).

**Nicht geprüft:** der genaue Text der Konsolenmeldung („Got pressure advance“ laut Anleitung, „measure k“ laut Forum), die 32 mm³/s des Hotends und der Rat zur 0,2-mm-Düse (die Snapmaker-Wiki zeigt ihren Inhalt nur per JavaScript).

## Dateien, Druckstart und SSH am U1 (geprüft 24.09.2026)

Für die Seiten „Dateien“, „Konsole“ und „SSH“; am U1 nur gelesen, auch per SSH. Mehr zu den Ordnern in [IDEEN](IDEEN.md).

- **Ordner** (`/server/files/roots`): `gcodes` schreibbar (`/userdata/gcodes`), `camera`, `logs` und `config` nur lesbar. In `gcodes` liegen druckereigene Ordner: `.thumbs`, `.udisk`, `calibration_data`, `shaper_calibrate`. `GET /server/files/directory?path=gcodes&extended=true` liefert alle Druckdateien samt Metadaten in einer Antwort (Druckzeit, Schichten, `filament_type` und `filament_colour` mit `;` getrennt, `filament_weight` je Kopf, Vorschaubilder).
- **Zeitraffer:** Snapmakers Dienst `unisrv` führt die Liste in `/userdata/.tmp_timelapse/timelapse.json`, die Videos liegen in `/userdata/.tmp_timelapse/<date_index>/`, in `camera` stehen nur Verknüpfungen. Über Moonrakers WebSocket liefert `camera.get_timelapse_instance` die Liste (Größe, Dauer, `video_local_url_suffix`). `camera.delete_timelapse_instance` mit `{"date_index": …}` löscht ein Video; so macht es Snapmaker Orca (`SSWCP.cpp`, `sw_DeleteCameraTimelapse`). `unisrv` nimmt laut seinen Meldungen auch `date_indices` oder `all`. Am U1 noch nicht ausprobiert.
- **Druckstart:** JSON-RPC `server.files.start_local_print` mit `{"path", "options"}` (`snapmakercloud.py`), **nicht über HTTP**: Snapmaker meldet den Aufruf mit `TransportType.all() & ~TransportType.HTTP` an, der U1 beantwortet `POST /server/files/start_local_print` mit 404 „Not Found“ (geprüft 24.09.2026, im Log des U1 zweimal). Snapmaker Orca schickt ihn über MQTT (`Moonraker_Mqtt::async_start_local_print`, wartet bis 80 s), OrcaOne über den WebSocket. Ebenso nur ohne HTTP: `/printer/emergency_stop` (`klippy_apis.py`); `/printer/print/start`, `/cancel`, `/pause` und `/resume` gehen über HTTP, antworten aber erst nach dem Makro (siehe „WLAN des U1 und Druck steuern“). Vorher prüft der U1 die Datei und dass er frei ist (Klipper bereit, `print_stats` weder `printing` noch `paused`, `machine_state_manager.main_state` IDLE), sonst `{"state": "error", "message": "Printer is busy, cannot start print"}`. Moonraker macht daraus `SDCARD_PRINT_FILE_WITH_PARAMETERS FILENAME="…" SCHLÜSSEL="Wert"` (`klippy_apis.start_print_advanced`), Klipper liest die Werte in `print_task_config.cmd_SET_PRINT_TASK_PARAMETERS`: `BED_LEVEL`, `FLOW_CALIBRATE`, `FLOW_CALIBRATE_EXTRUDERS`, `SHAPER_CALIBRATE`, `TIME_LAPSE_CAMERA`, `END_UNLOAD_FILAMENT` und `MAP_TABLE`. `MAP_TABLE` ist eine Liste `[[Werkzeug, Kopf], …]`, 0-basiert, gelesen mit `ast.literal_eval`; ohne sie druckt T0 auf Kopf 1 und so weiter. Die Antwort ist `{"state": "success"}` oder `{"state": "error", "message"}`. Die Werte des letzten Drucks stehen im Klipper-Status `print_task_config` (`auto_bed_leveling`, `flow_calibrate`, `shaper_calibrate`, `time_lapse_camera`), dazu die Spule je Kopf. Klipper liest die vier Schalter mit `get_int` (0 oder 1), `MAP_TABLE` mit `ast.literal_eval` (`print_task_config.py` in `u1-klipper`). Über den WebSocket am U1 noch nicht ausprobiert. OrcaSlicer startet bei Moonraker mit `POST /printer/print/start` und JSON-Body `{"filename"}` (`Moonraker::start_print`); einen Notstopp haben weder OrcaSlicer noch Snapmaker Orca. Am 25.09.2026 bestätigt: ein Druck über „Drucken“ in OrcaOne lief am U1 an (der Nutzer).
- **G-Code:** `/server/gcode_store?count=…` liefert Befehle und Antworten mit Zeit und Art (`command`, `response`), auch die anderer Programme; Fehler schreibt Klipper dort als „!! …“. `/printer/gcode/help` nennt 220 erweiterte Befehle, darunter STATUS, GET_POSITION, QUERY_ENDSTOPS, QUERY_PROBE und BED_MESH_OUTPUT; M115 antwortet mit `FIRMWARE_VERSION:1.6.0.267_20260815150420`.
- **Befehle in der Kommandozeile:** coreutils statt BusyBox, dazu `ip` aus iproute2 6.7, `ss`, `iwconfig`, `htop` und `python3`. Klipper und Moonraker zeigt `ps` dort nicht. Bettnetz, Input Shaper und Pressure Advance je Kopf liegen als JSON in `/oem/printer_data/config/snapmaker/` (`bed_mesh_default.json` 11 × 11, `input_shaper.json`, `flow_calibrator.json`).
- **SSH:** Root Access am Touchscreen startet Dropbear 2022.83, Anmeldung mit Schlüssel oder Passwort. `/etc/init.d/S01aoverlayfs` leert bei jedem Start `/oem/overlay`, das beschreibbare Overlay über `/`, außer es gibt `/oem/.debug` (gibt es nicht). Ein Schlüssel in `/root/.ssh/authorized_keys` ist nach einem Neustart also weg, und der Host-Schlüssel in `/etc/dropbear` entsteht neu.

## Druckdateien für die 3D und 2D Ansicht (geprüft 24.09.2026)

Für die Seiten „3D Ansicht“ und „2D Ansicht“; die Dateien des U1 über Moonraker nur gelesen (Puzzle: Snapmaker Orca 2.3.6, Dragon: 2.0.32).

- **Schichten:** je Schicht `;LAYER_CHANGE` und `;Z:<Höhe>`, dazu `;BEFORE_LAYER_CHANGE` und `;AFTER_LAYER_CHANGE`; im Puzzle-Druck je 19, wie `layer_count` in den Metadaten. Vor dem ersten `;LAYER_CHANGE` liegt die Reinigungslinie des Start-G-Codes, OrcaOne zählt sie zur ersten Schicht.
- **Linien:** `;TYPE:` mit englischen Namen (`Outer wall`, `Inner wall`, `Sparse infill`, `Internal solid infill`, `Prime tower`, `Gap infill`, `Top surface`, `Bottom surface`, `Internal Bridge`, `Custom`), Breite und Höhe als `;WIDTH:` und `;HEIGHT:`.
- **Köpfe und Farben:** Kopfwechsel als `T0` bis `T3` in eigener Zeile; am Ende `; filament_colour = #E2DEDB;#080A0D;…`, `; extruder_colour =` und `; filament_type =`, je Kopf durch `;` getrennt. Extrusion relativ (`M83`).
- **Bögen:** Im Dragon 60.693 `G2`/`G3` mit Extrusion (`I`/`J`, Bogen-Glättung des Slicers), im Puzzle nur 17, alle als Spirale beim Anheben (`G3 Z.84 I-1.2 J.203 P1 F30000`, ohne X/Y also ein voller Kreis). OrcaOne teilt sie wie Klipper (`gcode_arcs.py`) in Stücke, höchstens 0,02 mm neben dem Bogen: aus 284.352 Linien des Dragon werden 329.575.
- **Werte je Linie:** Beschleunigung als `SET_VELOCITY_LIMIT ACCEL=… ACCEL_TO_DECEL=…` je Linienart (5.316-mal im Puzzle), einmal `M204 S10000`. Bauteillüfter `M106 S…`, dazu `M106 P2 S…` und `M107 P2` für einen weiteren Lüfter. Düse `M104`/`M109` mit `T` und `S`, dazu Snapmakers `A0`. Bett `M140`/`M190 S65`.
- **Restzeit:** `M73 P<Prozent> R<Minuten>` etwa jede Minute Druckzeit (188-mal im Puzzle von 1 h 28 min). Die Kopfzeile nennt für die erste Schicht 19 s (`estimated first layer printing time`), nach `M73` sind es rund 17 min bei 55,8 m Linien.
- **Einstellungen:** Kopfblock (`; HEADER_BLOCK_START`: Schichtzahl, Dichte, Durchmesser, `max_z_height`), am Ende nach `; CONFIG_BLOCK_START` die Einstellungen als `; schlüssel = wert`, dazu Verbrauch (`filament used [g]`, `total filament change`) und `estimated printing time (normal mode)`. Im Puzzle 668 solche Zeilen mit 568 verschiedenen Schlüsseln (die Linienbreiten stehen je Objekt mehrfach).
- **Teilabruf:** Moonraker liefert ein Stück einer Datei auf `Range: bytes=…` mit 206 und `Content-Range` (Tornados `StaticFileHandler`); die 2D Ansicht holt so den G-Code um eine Linie.
- **Größe:** 3 MB sind 82.144 Linien mit Extrusion, die größte Datei (98,8 MB) 2.935.550 Linien in 715 Schichten. Über WireGuard kommen von Moonraker etwa 2 MB/s, die größte Datei braucht so rund 50 s, 12,5 MB etwa 7 s.
- **Fortschritt:** `virtual_sdcard.file_position` ist die Stelle in der Datei, bis zu der Klipper gelesen hat. Gezeichnet gilt als gedruckt, was davor beginnt.
- **WebGL auf diesem Rechner:** Das Browserfenster der App bekommt in der VM keinen WebGL-Kontext (VMware SVGA3D). Firefox 156 ohne Fenster (`--headless`, eigenes Profil) kann WebGL 2 mit llvmpipe; damit sind die Bilder der Seite angesehen. Der Firefox als Snap lässt sich von außen nicht per Signal beenden, sondern nur über WebDriver BiDi (`browser.close`) oder `systemctl --user stop` seines Scopes.

## Live-Werte über Moonrakers WebSocket (geprüft am U1, 25.09.2026)

Für `orcaone/live.py`; am U1 nur abonniert und zugehört, nichts gesendet außer Abfragen.

- **Verbindung:** `ws://<Adresse>/websocket` mit `Origin: http://<Adresse>`, ohne Anmeldung, wie die REST-Aufrufe. JSON-RPC: `printer.objects.list`, `printer.objects.subscribe` mit `{"objects": {name: [Felder] oder null}}`, `machine.proc_stats`.
- **Abo:** Die Antwort auf `printer.objects.subscribe` enthält alle abonnierten Werte (`status`), danach kommt `notify_status_update` mit `[Änderungen, eventtime]`, je Objekt nur die geänderten Felder. Im Leerlauf etwa 11 Meldungen in 8 s, von den Temperaturen (Bauraum, Köpfe). Ein ganzes `toolhead` ändert sich bei jeder Abfrage Klippers (`estimated_print_time`, `print_time`), also viermal pro Sekunde auch im Stillstand: OrcaOne abonniert davon, von `gcode_move` und `motion_report` nur die gezeigten Felder.
- **Rechner im Drucker:** Moonraker schickt jeder WebSocket-Verbindung jede Sekunde `notify_proc_stat_update` (Prozessor, Speicher, Netzwerk, `cpu_temp`), ohne `system_uptime`; das liefert `machine.proc_stats` einmal.
- **G-Code:** `notify_gcode_response` für jede Antwortzeile Klippers, nicht für die Befehle; die Befehle anderer Programme stehen nur in `/server/gcode_store`.
- **Durch OrcaOne:** `GET /api/live` schickt im Leerlauf 17 Nachrichten in 8 s, die erste 4,4 KB. Eine Nachricht, bevor das Abo steht, hätte nur die Rechnerwerte: gesendet wird erst danach.
- **Nicht am U1 geprüft:** der Takt beim Drucken und ein Neustart Klippers (`notify_klippy_ready`, danach neu abonnieren, wie Moonraker es beschreibt); beides nur gegen einen nachgebauten Moonraker.

## WLAN des U1 und Druck steuern (geprüft 25.09.2026)

Für die Seite „Netzwerk“ (bis 25.09.2026 „WLAN“, `orcaone/network.py`) und die Knöpfe der oberen Leiste.

- **Das Problem:** Übertragungen aus Snapmaker Orca werden zeitweise sehr zäh, nur Aus- und Einschalten half (der Nutzer). Im Snapmaker-Forum berichten andere dasselbe seit Firmware U1_1.4.1.6; genannt werden Roaming zwischen Zugangspunkten, ein eigenes 2,4-GHz-Netz für Geräte und die Router-Einstellung „Maximum WLAN Compatibility“. Der U1 kann nur 2,4 GHz (Snapmaker Wiki, „Snapmaker Orca disconnected from U1“).
- **Der Chip** (am U1 des Nutzers über die Seite „SSH“, Firmware 1.6.0.267, während eines Drucks): `iw dev wlan0 get power_save` sagt `off`; `iw dev wlan0 link` nennt 2437 MHz (Kanal 6), −71 dBm, `rx bitrate` 57,7 und `tx bitrate` 72,0 MBit/s, dazu RX/TX in Bytes und Paketen, aber weder `bss flags` noch `dtim period`. Die Adresse des Zugangspunkts ist lokal vergeben (`ae:…`), typisch für Mesh oder mehrere Netze an einem Gerät.
- **Dienste:** Unter `/etc/init.d` gibt es kein Skript für `wpa_supplicant` oder `dhcpcd`, aber `S36wifibt-init.sh`, `S40network` und `S80dnsmasq`. Die Extended Firmware (paxx12) nimmt `wpa_supplicant` in die cgroup `apps` des Originals auf (neben moonraker, nginx, unisrv, gui) und legt `/var/db/dhcpcd` nach `/oem`: beide laufen also. `ps | grep wpa` fand nichts, weil `ps` (procps) ohne Optionen nur die Prozesse des eigenen Terminals zeigt.
- **Stromsparen:** Die Extended Firmware schaltet es jede Minute wieder aus (`/usr/sbin/wlan-powersave-disable`, gestartet von `S99wlan-powersave-disable`); beim Nutzer war es aus.
- **Neu verbinden:** OrcaOne sendet abgesetzt und 2 s später `wpa_cli -i wlan0 reassociate`, ohne `wpa_cli` oder ohne Antwort `OK` dann `iw dev wlan0 disconnect`, und wartet, bis Moonraker wieder antwortet. **Am U1 noch nicht ausprobiert:** ob es `wpa_cli` gibt und ob `wpa_supplicant` nach einem fremden Trennen selbst neu verbindet (der Quelltext von hostap war nicht erreichbar). Neustart: `reboot`, nur ohne laufenden Druck.
- **Messung vom Rechner während eines Drucks** (nur lesend): Ping 1 bis 77 ms, im Mittel 13 ms, ohne Verlust; `/server/info` 30 bis 91 ms; 4 MB einer Druckdatei per Range mit 16 bis 21 MBit/s. Die Live-Werte kamen 3,9-mal pro Sekunde im Abstand von 250 ms (Klippers Takt), 2,5 KB/s.
- **Pause, Fortsetzen, Abbrechen:** Moonraker antwortet erst, wenn das Makro fertig ist, und der PAUSE des U1 parkt vorher den Kopf. Über HTTP mit 5 s pausierte der U1, OrcaOne meldete aber einen Timeout (der Nutzer). Snapmaker Orca schickt `printer.print.pause`, `resume` und `cancel` über MQTT und wartet wie bei jedem Aufruf bis 80 s (`Moonraker_Mqtt::async_pause_print_job`, `add_response_target`); OrcaOne jetzt ebenso über den WebSocket.

## Netzwerk des U1 und SSH-Schlüssel (recherchiert 25.09.2026)

Für die Seite „Netzwerk“ (`orcaone/network.py`) und den Schlüssel je Drucker (`ssh.py`). Am U1 nichts ausprobiert außer dem, was dabei steht; Quellen: Snapmaker/u1-moonraker (a308cfa), paxx12-snapmaker-u1/SnapmakerU1-Extended-Firmware (develop, 87df4f1), hostap 2.10, iproute2 6.7, Dropbear 2022.83.

- **Ohne SSH, über Moonraker:** `machine.system_info` → `network` nennt je Schnittstelle nur MAC und Adressen (`ip -json -det address`, nur Schnittstellen, die oben sind, vom Typ ether und mit Adresse, etwa alle 10 s neu). `notify_proc_stat_update` kommt jede Sekunde mit allen Einträgen aus `/proc/net/dev` (`rx_bytes`, `tx_bytes`, Pakete, `rx_errs`, `tx_errs`, `rx_drop`, `tx_drop`); `bandwidth` ist die Summe beider Richtungen in Bytes pro Sekunde, der erste Wert 0. SSID oder Signal gibt weder Moonraker noch Klipper heraus (nur `iwgetid` für simplyprint). `/machine/peripherals/usb` listet USB-Geräte, also auch einen USB-LAN-Adapter; ob es das beim U1 gibt, ist ungeprüft, OrcaOne kommt ohne aus. `server.client_manager.info` liefert auch den `access_code`: nicht nutzen.
- **Mit SSH:** iproute2 6.7 hat JSON für `ip -j -s link` (samt `carrier_changes`), `ip -j route` und `ip -j neigh`; `ss` 6.7 kein JSON. Geschwindigkeit und Duplex eines Kabels stehen in `/sys/class/net/<if>/speed` und `duplex` (ohne Kabel -1). `wpa_cli status` und `signal_poll` (RSSI, LINKSPEED, NOISE) gingen, ob es `wpa_cli` auf dem U1 gibt, ist offen; `/etc/wpa_supplicant.conf` nie lesen, darin steht das Passwort des WLANs. Die WLANs in der Nähe: `iw dev wlan0 scan` nimmt den Funk kurz vom Kanal (nur auf Klick), `scan dump` liefert, was der Chip zuletzt gefunden hat.
- **USB-LAN:** Ein Adapter erscheint als `eth0`, der U1 hat Treiber für r8150, r8152, asix, ax88179_178a und cdc_ether; ein RTL8156/8156B scheitert an fehlender Firmware (`rtl_nic/rtl8156b-2.fw`). Der USB-Anschluss ist USB 2.0 (höchstens etwa 480 Mbit/s). Die Extended Firmware hält eine zufällige MAC von `eth0` fest (`/oem/printer_data/network/eth0.address`). Quelle: Issue #239 und PR #410 der Extended Firmware.
- **Router ohne Ping:** Viele Router ignorieren Ping, UniFi etwa aus einem abgeschotteten Netz; am U1 des Nutzers meldete „Prüfen“ deshalb den Router als nicht erreichbar, obwohl das Internet antwortete (26.09.2026). Seither gilt der Router als erreichbar, wenn 1.1.1.1 antwortet oder `ip -j neigh show <Router>` ihn mit MAC und Zustand REACHABLE, STALE, DELAY, PROBE oder PERMANENT nennt; FAILED oder INCOMPLETE heißt, er hat auf ARP nicht geantwortet.
- **Weitere Ursachen für „Netz instabil“:** Snapmaker Orcas MQTT-Sitzungen teilen sich eine Client-ID und verdrängen sich gegenseitig (Snapmaker/OrcaSlicer#497, offen); `machine.heartbeat` scheitert vor der Veröffentlichung (Extended Firmware #537); ein WiFi-7-Zugangspunkt, der auch 2,4 GHz sendet, und Roaming (Forum 41574); nach Updates halfen feste IP im Router und getrennte 2,4/5-GHz-Netze (Extended Firmware #378, #230, #309).
- **SSH-Schlüssel dauerhaft?** Nein, nicht sauber. `S01aoverlayfs` leert das Overlay über `/` bei jedem Start, außer es gibt `/oem/.debug`; dann bleiben alle Änderungen am System, nicht nur der Schlüssel, und jedes Firmware-Update löscht die Datei wieder (Extended Firmware, `docs/data_persistence.md`, Issue #125). Die „Data Persistence“ der Extended Firmware ist genau dieses `touch /oem/.debug`, mit Rettung per USB-Stick (`full-recover.txt`); das Original hat keine. Dropbear 2022.83 liest immer `<home>/.ssh/authorized_keys` (`-D` erst ab 2025.87), `/etc/default/dropbear` liegt ebenfalls im Overlay; nur `/home/lava/printer_data` bleibt. OrcaOne bietet deshalb „Auf den Drucker bringen“ nach jedem Neustart an und legt `/oem/.debug` nie an. Solange Root Access an ist, geht beim Original das Passwort `snapmaker` ohnehin immer.
- **paramiko:** probiert `key_filename`, dann den Agent, dann `~/.ssh/id_rsa`, `id_ecdsa`, `id_ed25519`, dann das Passwort; mit Passwort und ohne Passphrase nimmt es das Passwort als Passphrase des Schlüssels (deshalb nie beides). `PKey.from_path` wirft bei einem Schlüssel mit Passphrase `TypeError`. Unter Windows fragt paramiko Pageant und die Pipe von OpenSSH, egal was `SSH_AUTH_SOCK` sagt, und `os.path.expanduser` folgt `USERPROFILE`: die Tests schalten beides ab.
- **LAN (harte Regel 8, 25.09.2026):** Unter Windows lässt ein gewöhnliches Binden von `0.0.0.0` einen anderen Lauscher auf `127.0.0.1` desselben Ports zu und umgekehrt; erst `SO_EXCLUSIVEADDRUSE` lehnt jedes solche Paar ab (Microsoft, „Using SO_REUSEADDR and SO_EXCLUSIVEADDRUSE“). asyncio setzt für IPv6 immer `IPV6_V6ONLY`, `host="::"` hieße also nur IPv6. Die Windows-Firewall fragt beim ersten Lauschen; ein Abbruch legt Sperrregeln an, die jede Freigabe schlagen. Über `http://<LAN-IP>` ist die Seite kein sicherer Kontext: keine Zwischenablage (Kopieren meldet es), keine Installation als App.

## Logdateien der Slicer (23.09.2026)

- Eine Datei je Start in `<Datenordner>/log/`. Zeilenformat beider Slicer: `[warning]⇥2026-09-23 09:24:21.294249[Thread 0x…]:Text`. Zeilen ohne diesen Anfang gehören zum Eintrag davor, etwa OrcaSlicers Systeminfo.
- SnOrca schreibt fast alles als `warning`, OrcaSlicer als `info`.
- OrcaSlicers Logs erreichen 10 MB mit rund 21.600 Einträgen. Zwei davon sind je 2,7 MB groß, die ganze Profilliste als JSON (`SaveProfile`, `on_profile_loaded`). OrcaOne filtert deshalb auf dem Server und schickt nur die letzten 2000 Einträge mit höchstens 2000 Zeichen.
- SnOrcas Updater meldet in allen 16 Logs dieses Rechners „Update install failed“ für `printers/`. Das ist ein Problem von Snapmaker.

## Windows (per Quellcode geprüft, 23.09.2026)

Ohne Windows-Rechner geprüft; die Prüfliste für den echten Rechner steht in [STAND](STAND.md).

- Python öffnet Dateien unter Windows ohne `FILE_SHARE_DELETE`. Solange ein Leser `settings.json` offen hat, scheitert das atomare Ersetzen. OrcaOne liest deshalb unter derselben Sperre, unter der es schreibt, und versucht `os.replace` bei `PermissionError` dreimal (Virenscanner).
- `recvfrom` meldet bei UDP ein früheres ICMP „unreachable“ als `ConnectionResetError`. Die LAN-Suche läuft dann weiter.
- `urllib` nimmt unter Windows den System-Proxy aus der Registry. Anfragen an den U1 gehen deshalb ohne Proxy.
- Passt schon: die Programmnamen `snapmaker-orca.exe` und `orca-slicer.exe` (`OUTPUT_NAME` in `src/CMakeLists.txt`); `fcntl` und `chmod` nur unter POSIX; Logs lesen, während der Slicer schreibt, denn MSVC öffnet sie ohne Schreibsperre für andere; `SO_REUSEPORT` gibt es unter Windows nicht und wird übersprungen.

## Windows am echten Rechner (24.09.2026)

Windows 10 Pro, Python 3.13.3 und 3.12 von python.org, dazu die Variante „free-threaded“ 3.13t. SnOrca 2.3.6 installiert, OrcaSlicer 2.3.0 nur entpackt auf dem Desktop (ohne Ordner `data_dir` neben der exe), beide Datenordner in `%APPDATA%`.

- **`py -3` nimmt die Variante 3.13t**, wenn sie installiert ist: `py -0p` markiert sie mit `*` als Standard (Launcher von 3.13.3). Dort baut `cffi` nicht („CFFI does not support the free-threaded build of CPython 3.13“), paramiko braucht es, pip bricht ab. `orcaone.cmd` prüft deshalb `sysconfig.get_config_var("Py_GIL_DISABLED")` und probiert jede Version aus `py -0`.
- **psutil ist hier langsam:** `name()` und `exe()` brauchen 0,1 bis 0,25 s je Prozess, schon der Rohaufruf `proc_exe`. Bei 369 Prozessen über 40 s, `/api/data` blieb bei „Lese Installationen …“. `tasklist` braucht 3,3 s, eine Toolhelp32-Momentaufnahme (`CreateToolhelp32Snapshot`) 0,2 s für alle Namen. `guard.py` fragt psutil unter Windows deshalb nur nach den Slicer-Prozessen.
- **Datenordner eines laufenden Slicers:** SnOrca 2.3.6 läuft als `snapmaker-orca.exe` im Arbeitsverzeichnis `<Datenordner>\log`, wie unter Linux.
- **`.conf`:** Auf der Platte CRLF, die MD5-Zeile in Großbuchstaben, 4 Leerzeichen Einrückung, kein BOM; die `.conf.bak` gleicht ihr. `parse_conf` → `dump_conf` ergibt alle vier Dateien (SnOrca und OrcaSlicer, je mit `.bak`) Byte für Byte, samt neu berechneter MD5.
- **NTFS listet Ordner alphabetisch.** Zwei Sicherungen derselben Sekunde mit verschiedenem Anlass bekamen dieselbe laufende Nummer und standen dann falsch herum. Die Nummer zählt jetzt über alle Anlässe.
- asyncio meldet in der Konsole `ConnectionResetError [WinError 10054]`, wenn der Browser eine Verbindung abbricht, etwa beim Neuladen. Harmlos.

## Druckerbilder der Slicer (geprüft 27.09.2026)

- Beide Slicer laden das Bild eines Modells zur Laufzeit aus `<resources>/profiles/<Hersteller>/<Modell>_cover.png` (Orca `Plater.cpp` `update_printer_thumbnail`, `WebGuideDialog.cpp` `BuildProfileJson`, dort ersatzweise `web/image/printer/`). `<Hersteller>` ist der Stamm der Vendor-JSON (das `package` der `.conf`), `<Modell>` genau der Modellname, Leerzeichen und Klammern unverändert. In Snapmaker Orca 2.4.0 weichen drei Dateien in der Groß- und Kleinschreibung ab (`ginger G1_cover.png` für „Ginger G1“ u. a.); unter Linux findet der Slicer sie nicht, OrcaOne sucht ersatzweise ohne Beachtung der Schreibung.
- In den Datenordner kopiert keiner der Slicer ein Bild: `install_vendor_bundles_from_resources` bzw. `PresetUpdater` filtern `.png`, `.svg`, `.stl`, `.3mf` heraus.
- `<resources>` (Orca `OrcaSlicer.cpp`, SnOrca `Snapmaker_Orca.cpp`, aus `program_location()`): Windows neben der exe, AppImage und `/opt` bei `<exe>/../../resources`, Flatpak und mit `SLIC3R_FHS` gebaute Pakete fest `<prefix>/share/<APP_KEY>` (Flatpak: `/app` = `/var/lib/flatpak/app/<id>/current/active/files` bzw. unter `~/.local/share/flatpak/app/`). Eine AppImage ist nur eingehängt, solange sie läuft.
- Am Rechner des Nutzers: `C:\Program Files\Snapmaker_Orca\resources\profiles` mit 328 Bildern in 56 Herstellerordnern; der Installer trägt sich unter `HKLM\SOFTWARE\WOW6432Node\...\Uninstall\Snapmaker_Orca` ein, ohne `InstallLocation`, der Ordner ist der der `Uninstall.exe`. OrcaSlicer liegt nur entpackt auf dem Desktop (266 Bilder, ohne U1) und ist nur über den laufenden Prozess zu finden.
- GitHub liefert dieselben Dateien ohne Anmeldung: `https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/main/resources/profiles/<Hersteller>/<Modell>_cover.png`, für Snapmaker Orca `Snapmaker/OrcaSlicer` (Standardzweig `main`); `image/png`, 0,2 bis 0,4 s, sonst 404 mit `text/plain`. Das U1-Bild ist dort ein anderes (OrcaSlicer 39.838 B, Snapmaker Orca 348.177 B).

## Offen: nur am laufenden Slicer prüfbar

Auf dem Entwicklungsrechner laufen diese Tests direkt im echten Datenverzeichnis, weil die Slicer dort nur Testinstallationen sind (23.09.2026). Vor jeder Änderung legt OrcaOne eine Sicherung an.

- [ ] „Bibliothek freischalten“, Weg A und Weg B, mit `SUNLU PLA+ @System` (4.7). Weg B: SnOrca lädt das Hilfsprofil (23.09., siehe Übertragung).
- [x] Übertragung Orca → SnOrca (23.09., Nutzer: „geht“): „COEX ABS (Orca)“ aus der Orca-Bibliothek lädt in SnOrca bei den Düsen seiner Druckerliste (U1 0,2, 0,4, 0,6). SnOrca hat die Datei danach selbst neu gespeichert: `version "2.4.0.0"` statt „2.4.0“, 111 statt der geschriebenen Einstellungen, weil es bei Wurzelprofilen den vollständigen Satz schreibt.
- [x] Übertragung SnOrca → Orca (23.09.): „Snapmaker Support For PLA @U1 0.4 nozzle (SnOrca)“ lädt in OrcaSlicer 2.5.0-dev, Log: „load config successful“, Alias „Snapmaker Support For PLA“, ohne Fehler; der Nutzer hat es beim U1 0,4 gewählt. Orca hat die Datei nicht neu geschrieben (`version "2.5.0"` von OrcaOne).
- [ ] Noch offen: Nimmt der G-Code mit High-Flow-Düse die Standardwerte? Erscheint ein übertragenes Filament im Assistenten unter „Eigene Filamente“?
- [x] Ein eigenes Filament mit `instantiation: "false"` blendet SnOrca aus (23.09., „COEX ABS (Orca)“, Nutzer: „ist ausgeblendet“). Die Datei bleibt unverändert, auch die Druckerliste; SnOrca setzt nichts zurück. OrcaOne nutzt das, wenn ein eigenes Filament bei keiner Düse mehr an ist. In OrcaSlicer noch nicht ausprobiert, laut Quellcode dieselbe Regel (Preset.cpp, load_presets).
- [ ] SnOrca mit fehlendem bzw. `null`-`"filaments"`: Sind wirklich alle Systemfilamente sichtbar?
- [x] Windows: Hat die `.conf` auf der Platte CRLF? Sind die MD5-Ziffern Großbuchstaben? (24.09.) Ja, beides; OrcaOne schreibt sie Byte für Byte gleich, siehe „Windows am echten Rechner“.
- [ ] Flatpak: Zeigt `/proc/<pid>/cwd` bzw. `F_GETLK` aus Sicht des Hosts dasselbe wie bei der AppImage?
- [ ] Was steht in `"version"` eines Bundles, das SnOrca ohne Anmeldung exportiert?
- [ ] Wie sieht die Material4Print-U1-ZIP aus: Ordner, `version`, `*_settings_id`, `inherits`? Die Datei liegt lokal nicht vor. Teilantwort vom 23.09.: Ein Druck am U1 zeigt „M4P Orange“ mit `filament_vendor` Material4Print auf „Snapmaker PLA Basic @U1“.
- [ ] Cloud-Sync bei angemeldetem Konto: Bekommen importierte Profile eine `setting_id`? Kommen gelöschte Profile zurück? Auf diesem Rechner ist `sync_user_preset = false`.
- [ ] Orca main: Werden installierte Hersteller bei `enable_ota = false` nach einem Programmupdate wirklich nie erneuert?

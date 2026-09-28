# Profil-Editor und Timeline fuer OrcaOne

Stand: 27.09.2026. Status: fachliche Freigabe durch den Nutzer; Implementierungsplan zur Pruefung.
Arbeitsbranch: `feature/profile-management`; Recherchebasis: `fb34c1b`, nach Rebase aktuelle Basis: `98e7151`.

## 1. Ziel und vereinbarter Umfang

OrcaOne bekommt einen vollstaendigen Editor fuer die in unterstuetzten Versionen
speicherbaren Drucker-, Prozess- und Filamentparameter. Er erweitert die bestehenden
Seiten um Bearbeiten, Kopieren, Zuordnen, Zusammenfuehren und Batch-Aktionen.
Eine lokale Timeline erlaubt gespeicherte Staende, Versuchsvarianten, Vergleiche
und selektive Wiederherstellung. Erst die ausdrueckliche Aktion "In Orca uebernehmen"
aendert die Profile der gewaehlten Slicer-Installation.

Verbindliche Nutzerentscheidungen:

- OrcaSlicer und Snapmaker Orca ab dem aktuellen Stand unterstuetzen; zukuenftige
  Versionen nach Pruefung ihrer Definitionen und ihres Speicherverhaltens.
- Je Aktion bestimmt der Nutzer den Umfang: ein Profil, mehrere Profile oder ein
  ausgewaehltes Profilset. Keine automatische Ausweitung auf Abhaengigkeiten.
- Gemeinsam genutztes Profil oder unabhaengige Kopie individuell entscheiden.
- Beim Zusammenfuehren effektive Werte uebernehmen, unabhaengig vom alten Elternprofil.
- Gleicher Duesendurchmesser darf mehrere Varianten haben, etwa Standard/High Flow.
- Werte je Extruder, Filament oder Flow-Variante entsprechend ihrer wirklichen Bedeutung.
- Bei Duesenwechsel Anpassungen vorschlagen, keine stillen Parameterveraenderungen.
- Historie lokal und unabhaengig vom Slicer-Sync speichern.
- Strukturelle Fehler blockieren; drucktechnische Plausibilitaet gesondert warnen.
- Praktische OrcaSlicer-Abnahme durch den Nutzer. Snapmaker-Abnahme durch den
  OrcaOne-Ersteller vorgesehen; dessen Zusage und Ergebnis stehen aus.

Das Startbeispiel: Ein bisher separat angelegtes Druckerprofil mit 0,5-mm-Duese
einem bestehenden Modell zuordnen und ausgewaehlte Prozesse/Filamente passend
verknuepfen, ohne seine individuellen Druckeinstellungen zu verlieren.

## 2. Gepruefte Ausgangslage

### 2.1 Offizielle Versionen und Quellen

Die offiziellen Latest-Release-Seiten zeigten am Untersuchungstag:

| Slicer | Mindestversion | Gepruefter Commit |
|---|---|---|
| OrcaSlicer | 2.4.2 | `8500fcdccaa10b5099ac20d252af3a7c560046f1` |
| Snapmaker Orca | 2.4.0 | `b1831e5dcb464172de33783142425aafda834fbc` |

Quellen: [OrcaSlicer-Release](https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.4.2),
[Snapmaker-Release](https://github.com/Snapmaker/OrcaSlicer/releases/tag/v2.4.0).
OrcaSlicer 2.5.0-dev ist keine austauschbare 2.4.2-Basis: vorhandenes Lesen bleibt,
vollstaendiges Schreiben erfordert einen gesondert geprueften Build/Commit.

Die relevanten Quelldateien liegen nur zur Recherche in den ignorierten Ordnern
`slicer-src/orcaslicer-v2.4.2` und `slicer-src/snorca-v2.4.0`.

### 2.2 Wiederverwendbare Teile

| Bestehender Teil | Verwendung und Grenze |
|---|---|
| `orcaone/operations.py` | Planner, Datei-Diffs, Prozesssperre, Fingerprints, Backup, Schreiben, Rollback und erneuter Scan weiterverwenden. Noch kein vollstaendiger generischer Editor. |
| `orcaone/resolver.py:179` | Vererbungsketten inklusive fehlender Eltern/Zyklen; `value_entry` ergaenzt nur die wenigen `EDITABLE_DEFAULTS`, nicht alle effektiven Slicer-Werte. |
| `tools/make_options.py` / `orcaone/options.json` | Vorhandener Extraktor fuer Typen, Enums, Nullable und Profilarten. Bisher ein Katalog je Slicer, Orca aus main; keine vollstaendigen Defaults, Grenzen oder Abhaengigkeiten. |
| `orcaone/transfer.py` | Slicer-Konvertierung bereits vorhanden; kann Werte entfernen oder Vektoren kuerzen. Diese Verluste duerfen im neuen Editor nicht still passieren. |
| `orcaone/snapshot.py` | Ein veraenderbarer Vergleichsstand je Installation, teilweise nur Hashes. Kein wiederherstellbares Versionsarchiv. Bestehende Seite "Aenderungen" erhalten. |
| `orcaone/backup.py` | Vollstaendige ZIP-Backups fuer Slicer-Schreiboperationen bleiben bestehen; Timeline ersetzt sie nicht. |
| `orcaone/overview.py:658` | Jedes eigene Druckerprofil erscheint derzeit als eigenes Modell. Gruppierung braucht hier eine gezielte Erweiterung. |
| `static/pages/filament-editor.js`, `prozesse.js`, `zusammenhaenge.js`, `plan.js` | Bestehende Einstiege und Stil weiterverwenden; gemeinsame Feldkomponenten ergaenzen. |

### 2.3 Parameterdefinitionen und effektive Werte

Die typisierten Definitionen stehen in `PrintConfig.cpp`, die Zuordnung zu
Profilarten und Normalisierung in `Preset.cpp`; weitere Regeln liegen unter anderem
in `Config.hpp` und `GUI/Tab.cpp`. Eine JSON-Profildatei allein ist kein Schema.

Ein lesender Lauf der vorhandenen Extraktorfunktionen ueber die beiden Releases
erkannte alle von diesen Funktionen gelesenen Listenmitglieder:

| Slicer | Prozess | Filament | Drucker |
|---|---:|---:|---:|
| OrcaSlicer 2.4.2 | 355 | 126 | 160 |
| Snapmaker Orca 2.4.0 | 319 | 106 | 134 |

Das sind Kandidaten inklusive technischer Felder, keine Zahl fertiger Editorfelder.
Die Regex-basierte Erfassung beweist weder Vollstaendigkeit aller dynamischen
Definitionen noch korrekte Defaults, Vektordimensionen oder Validierungsregeln.

Belege: [Orca-Definitionen](https://github.com/OrcaSlicer/OrcaSlicer/blob/8500fcdccaa10b5099ac20d252af3a7c560046f1/src/libslic3r/PrintConfig.cpp),
[Snapmaker-Definitionen](https://github.com/Snapmaker/OrcaSlicer/blob/b1831e5dcb464172de33783142425aafda834fbc/src/libslic3r/PrintConfig.cpp),
[Snapmaker-Normalisierung](https://github.com/Snapmaker/OrcaSlicer/blob/b1831e5dcb464172de33783142425aafda834fbc/src/libslic3r/Preset.cpp#L384).

Vollstaendige effektive Werte erfordern: versionsabhaengige Defaults,
Elternkette, eigene Werte und die jeweiligen Normalisierungsregeln. Eine Liste
von zwei Werten bedeutet nicht automatisch zwei Extruder: Snapmaker verwendet
auch Flow-Varianten, Orca ebenfalls eigene dimensionsabhaengige Regeln.

### 2.4 Grenze der Darstellung im Slicer

Beide untersuchten Drucker-Dropdowns gruppieren System-/Default-Presets anhand
von `printer_model`; eigene Presets gehen in eine separate Liste nach Profilname.
Allein `printer_model` zu aendern garantiert daher keine zusammengefasste
Darstellung eigener Varianten im Slicer-Dropdown.

Belege: [Orca-Auswahl](https://github.com/OrcaSlicer/OrcaSlicer/blob/8500fcdccaa10b5099ac20d252af3a7c560046f1/src/slic3r/GUI/PresetComboBoxes.cpp#L1238),
[Snapmaker-Auswahl](https://github.com/Snapmaker/OrcaSlicer/blob/b1831e5dcb464172de33783142425aafda834fbc/src/slic3r/GUI/PresetComboBoxes.cpp#L1359).

Zusage: korrekte, ladbare eigene Profile mit passenden Daten und Referenzen;
gemeinsame Darstellung in OrcaOne. Keine Zusage einer identischen Slicer-Oberflaeche.
Hersteller-Manifeste oder `system/` werden dafuer nicht umgeschrieben.

## 3. Architekturvorschlag

Die vorhandene Python/FastAPI-/Vue-Struktur und das Dateisystem bleiben erhalten.
Kein zusaetzlicher Server, keine Datenbank und keine Git-Installation beim Endnutzer.
Git liefert das Bedienkonzept; die Historie wird als kleines Dateiformat mit
unveraenderlichen Staenden und Elternbeziehungen umgesetzt.

| Baustein, vorgeschlagener Ort | Verantwortung |
|---|---|
| `profile_schema.py` und versionierte Kataloge | Slicer-/Build-Auswahl, Typen, Defaultwerte, Grenzen, Enums, Einheiten, Dimensionen, Normalisierung und Regelstatus. |
| `profile_edit.py` | Editierbares Dokument, effektive Werte, Feldherkunft, Batch-Patches und Strukturvalidierung. Resolver wiederverwenden. |
| `profile_history.py` | Unveraenderliche Revisionen, Branches, Entwuerfe, Vergleiche, selektive Wiederherstellung und beobachtete externe Staende. |
| `profile_merge.py` | Dreiwegevergleich, Konfliktentscheidungen und Uebernahme effektiver Werte; keine Dateischreibrechte im Slicer. |
| `operations.py` | Bestehenden Planner um Profile-Operationen erweitern; einziger Weg zum Schreiben in Slicer-Daten. |
| Gemeinsame Vue-Komponenten | Felder, Batch-Auswahl, Timeline und Konfliktansicht in bestehenden Seiten. DE/EN-Texte parallel. |

Dies sind fachliche Grenzen, keine Aufforderung zu einem allgemeinen Plugin-Framework.
Dateien erst im Implementierungsplan aufteilen; bestehenden Code nur aufgabenbezogen aendern.

## 4. Versionskatalog und Editorvertrag

Je Slicer und verifiziertem Release/Build gibt es einen reproduzierbaren Katalog
mit Quellcommit, Katalogversion und dokumentierten Sonderregeln. Die Weiterentwicklung
des bestehenden Extraktors ist der Ausgangspunkt; sie muss bei unbekannten
Konstruktionen scheitern statt unvollstaendige Kataloge als vollstaendig auszugeben.

Ein Parameter beschreibt mindestens:

- Schluessel, Profilarten, Datentyp und Serialisierung als String oder Stringliste.
- Defaultwert, Nullable-/`nil`-Semantik und zulassige Enum-Schluessel.
- Einheit, feste Grenzen, Prozent-/Absolutwertsemantik und Sonderwerte wie "auto".
- Dimension: Skalar, Extruder, Filament, Flow-Variante oder strukturierter Wert.
- Anwendbarkeit, bekannte Abhaengigkeiten und strukturelle Regeln.
- Eigene DE/EN-Bezeichnung, Gruppe und Herkunftsbeleg der technischen Definition.
- Schreibbarkeit: Druckparameter, gesonderte Verwaltungsaktion oder geschuetzte Metadaten.

Mehrzeiliges G-Code, Punktlisten/Bettgeometrie, Prozentwerte, Farben und Vektoren
brauchen passende Eingaben. Metadaten, IDs und Referenzen werden nicht als beliebige
Textparameter freigegeben. Herstellerprofile werden als eigene Profile abgeleitet.

Unbekannte vorhandene Felder bleiben erhalten und werden als unklassifiziert angezeigt.
Sie werden nicht automatisch geloescht, normalisiert oder als sicher editierbar erklaert.
Eine neue Version bekommt nicht allein wegen einer groesseren Versionsnummer Schreibfreigabe.
Bestehende Lesefunktionen und gesicherte alte Bedienwege bleiben davon getrennt.

Beim normalen Bearbeiten geerbter Profile bleiben nicht ausgewaehlte Felder und
Vererbungsbeziehungen erhalten. "Auf geerbten Wert zuruecksetzen" entfernt nur die
ausgewaehlte Ueberschreibung. Beim vereinbarten Zusammenfuehren dagegen werden alle
benoetigten effektiven Werte materialisiert und das Ergebnis als unabhaengiges
Benutzerprofil serialisiert. Fehlende Defaults/Eltern blockieren diese Materialisierung.

Fuer Referenzbedingungen wie `compatible_printers_condition` ist eine nachgewiesene
Auswertung oder eine explizite Ersetzung durch gewaehlte Zuordnungen erforderlich.
Der heutige Resolver meldet nur "conditional". Unbekannte Ausdruecke niemals als
"passt" behandeln oder ohne Auswahl entfernen.

## 5. Nutzerablaeufe und Aktionsumfang

### 5.1 Bearbeiten und Batch

Einstieg am Profil auf "Uebersicht", "Prozesse" oder "Filamente". Der Editor zeigt
Suchfeld, Parametergruppen, geaenderte Werte und Herkunft. Timeline ist am Profil
und fuer die aktuelle Auswahl erreichbar; kein zweiter unabhaengiger Profilbrowser.

Batch-Eingaben fuer Profile derselben Art zeigen bei Abweichungen "Mehrere Werte".
Nur beruehrte Felder werden gepatcht. Jeder Patch benennt Profil-ID, Feld und bei
Vektoren die ausgewaehlte Dimension. "Setzen", "Ueberschreibung entfernen" und
"Zuordnung ergaenzen/entfernen" sind unterschiedliche Operationen; leer ist kein Reset.

Der Nutzer sieht betroffene und nicht passende Profile. Bei strukturellen Fehlern
wird die ausgewaehlte Uebernahme blockiert. Er kann die Auswahl selbst aendern;
kein stilles Ueberspringen oder Hinzufuegen. Ein Profilset darf gemischte Arten
enthalten; daraus entstehen getrennt typisierte Patches.

### 5.2 Duesenvariante und Zusammenfuehren von Druckern

Quelle, Zielmodell, Profilname, Duesen-/Kopfkonfiguration und optionale
Variantenbezeichnung werden explizit gewaehlt. Ein Durchmesser ist keine Identitaet.
Modellzuordnung und physische Druckeradresse werden getrennt behandelt: zwei
gleichartige reale Drucker duerfen nicht versehentlich zu einem Geraet verschmelzen.

Die Vorschau zeigt Unterschiede, Vererbung, abhaengige Prozesse/Filamente sowie
Profil- und Standardauswahlreferenzen. Namen, Einstellungen und Referenzen werden
nicht allein anhand aehnlicher Anzeigenamen zusammengelegt.

Fuer jedes relevante Prozess-/Filamentprofil waehlt der Nutzer die gemeinsame
Nutzung, Kopie oder keine Aenderung. Die Vorschau nennt bei gemeinsamer Nutzung
auch die weiteren Duesen, fuer die spaetere Profilbearbeitungen wirken.

Vorschlaege fuer Duesenwechsel betreffen nachvollziehbare Parametergruppen, etwa
Schichthoehe und Linienbreite. Jeder Vorschlag nennt Grund und Ausgang/Zielwert.
Fehlende Hardwaredaten ergeben keinen geratenen sicheren Wert; insbesondere
G-Code, Temperatur und maximale Foerderleistung nicht pauschal skalieren.

### 5.3 Originale und Referenzen

Keine pauschale Original-Loeschung. Bei einer reinen Neuzuordnung bleibt dieselbe
Profilidentitaet bestehen. Bei Erstellung eines neuen Ergebnisses bleiben Quellen
bestehen, sofern der Nutzer ihre Entfernung nicht in den Aktionsumfang aufnimmt.
Eine ausgewaehlte Entfernung wird nur ausgefuehrt, wenn verbleibende Referenzen
gueltig sind. Erforderliche Aenderungen an nicht ausgewaehlten Profilen werden
angezeigt und blockieren; der Nutzer erweitert die Auswahl selbst.

## 6. Timeline und lokale Speicherung

### 6.1 Sprache und Bedienung

| Aktion | Bedeutung |
|---|---|
| Stand speichern | Ausgewaehlte Entwuerfe dauerhaft speichern, optionale Notiz. |
| Variante ausprobieren | Vom gewaehlten Stand einen Branch fuer die gewaehlten Profile erstellen. |
| Staende vergleichen | Zwei Staende und beliebige Profilauswahl vergleichen. |
| Stand wiederherstellen | Historische Werte der Auswahl als neuen aktuellen Entwurf/Stand uebernehmen. |
| Aenderungen uebernehmen | Ausgewaehlte Aenderungen einer Versuchsvariante integrieren. |
| In Orca uebernehmen | Gewaehlte Staende nach Preview in genau eine Slicer-Installation schreiben. |

Ein Timeline-Branch ist keine Duesenvariante. Der erste ist ein Versuchszweig,
die zweite eine reale Profilkonfiguration. Beide Beziehungen getrennt speichern.
Wechsel des angezeigten Branches schreibt niemals in Orca.

### 6.2 Datenmodell

Neue Historie unter `data/snapshots/profiles/<installation-id>/`; bestehende
`data/snapshots/<id>.json` unveraendert weiterfuehren. `data/history/` ist bereits
fuer Druckerdiagramme belegt und wird nicht zweckentfremdet.

- **Profil-ID:** lokale stabile ID, unabhaengig von Dateiname und Anzeigename.
  Slicer, Installation und aktiver Benutzerordner gehoeren zur Zuordnung.
- **Profilrevision:** unveraenderliche eigene Werte, materialisierte effektive Werte,
  Herkunft, Schema-ID, Aufloesungsstatus, Referenzen, Zeitpunkt, Notiz und Elternrevisionen.
  Unvollstaendig aufgeloeste Beobachtungen sind erkennbar, keine gueltige Flatten-Vorlage.
- **Stand:** unveraenderliche Abbildung der ausgewaehlten Profil-IDs auf Revisionen;
  explizite Loeschungen separat. Nicht ausgewaehlt bedeutet nicht geloescht.
- **Branch:** benannte Referenz auf einen Stand mit Ausgangspunkt und Auswahl.
  Aufnahme weiterer Profile ist eine ausdrueckliche Aktion.
- **Entwurf:** separat gespeicherte, noch nicht abgeschlossene Aenderungen mit
  Basisrevision und Generation fuer konkurrierende Browserzugriffe.
- **Uebernahmebeleg:** ausgewaehlte Revisionen, Zielinstanz/-ordner, Plan-/Backup-ID,
  Fingerprint, Status und verifizierter Nachzustand. Kein globales "alles aktiv".

Mehrere historische Staende koennen teilweise in Orca aktiv sein. Aktivstatus daher
pro Profil bestimmen, nicht aus einem Branch-Namen ableiten. Externe Umbenennungen
ohne eindeutigen Identitaetsbeleg als Zuordnungsvorschlag behandeln; nicht raten.

Dateinamen nur aus internen IDs, keine ungeprueften Nutzerpfade. Unveraenderliche
Objekte zuerst schreiben, dann Referenzen atomar ersetzen. Schreibzugriffe mit
Generation/Fingerprint vergleichen; bei Konflikt Entwurf erhalten und Vergleich anbieten.
Historie in dieser Ausbaustufe nicht automatisch ausduennen oder Branch-Daten vernichten.

Bekannte Zugangsdaten werden nicht als editierbare Druckparameter oder lesbarer
Timeline-Inhalt ausgeliefert. Der aktuelle Zielwert bleibt bei Profiloperationen
erhalten; fuer vollstaendige vertrauliche Ruecksicherungen bleibt das bestehende
geschuetzte ZIP-Backup zustaendig. Keine Hashes von Secrets an die Oberflaeche.

### 6.3 Vergleich und Merge

Diff auf Parameterbasis mit Einheiten und Vektordimensionen, getrennt nach eigenen
und effektiven Werten. Unterschiede durch neue Slicer-Defaults separat kenntlich machen.
G-Code/Mehrzeilentext zusaetzlich als Zeilendiff; keine Ausfuehrung von Inhalten.

Bei gemeinsamer Abstammung Dreiwegevergleich aus Ausgang, Ziel und Quelle:
einseitige Aenderungen vorschlagen, identische Aenderungen vereinigen, widerspruechliche
Aenderungen sowie Loeschen/Umbenennen gegen Bearbeiten als Konflikt behandeln.
Strukturierte Werte nur dann elementweise kombinieren, wenn ihre Zuordnung eindeutig ist.
Ohne gemeinsame Basis muss der Nutzer Ausgang und zu uebernehmende Werte bestimmen.

Nur eine vollstaendige Integration einer Profilrevision erzeugt zwei Merge-Eltern.
Bei selektiver Feldübernahme bleibt es eine neue Revision mit Ziel als Elternteil
und separater Quellenprovenienz. Sonst wuerden spaetere Vergleiche faelschlich auch
nicht uebernommene Quellaenderungen als bereits integriert behandeln.

Wiederherstellung setzt keine Historie zurueck: Sie erzeugt neue Revisionen fuer
die Auswahl; alle anderen Profile bleiben unveraendert. Historische fehlende
Abhaengigkeiten werden angezeigt. Materialisierte Werte koennen eine unabhaengige
Kopie ermoeglichen, ersetzen aber keine benoetigten Kompatibilitaetsreferenzen.

## 7. Externe Aenderungen, Sync und Uebernahme

Beim stabilen erneuten Einlesen externe Unterschiede als beobachteten Stand
erfassen, ohne einen Entwurfsbranch umzuschreiben. Quelle "aus Slicer eingelesen";
keine Behauptung, ob Benutzer, Cloud oder Update die Aenderung verursacht hat.
Zwischen zwei Scans liegende Zwischenstaende sind nicht rekonstruierbar.
Voruebergehend fehlende/halb geschriebene Dateien nicht als sichere Loeschung verbuchen.

Beim Uebernehmen gilt der bestehende Ablauf plus Timeline-Beleg:

1. Auswahl, Zielordner, Schema, Referenzen und effektive Werte pruefen.
2. Live-Daten mit Entwurfsbasis vergleichen; Konflikte vor dem Plan aufloesen.
3. Datei-/Parameter-Preview und Auswirkungen anzeigen; Nutzer bestaetigt.
4. Prozesssperre und Fingerprints erneut pruefen, vollstaendiges Backup erstellen.
5. Dauerhaften vorbereiteten Uebernahmebeleg schreiben; ausgewaehlte Dateien ueber
   den Planner schreiben und danach Dateien sowie Ladbarkeit pruefen.
6. Beleg mit tatsaechlichem Nachzustand abschliessen; erst dann als uebernommen markieren.

Der heutige Writer ersetzt Dateien einzeln und kann bei Fehlern zurueckrollen;
das ist keine atomare Transaktion ueber alle Dateien. Fuer die neue Uebernahme
braucht es einen Wiederanlaufbeleg: Nach Absturz Ziel mit Vor-/Nachzustand vergleichen,
unklaren Zustand markieren und eine gepruefte Wiederherstellung anbieten.
Bei Schreib-/Ladefehlern kein Erfolgssignal. Ein Rollback darf zwischenzeitlich fremd
geaenderte Dateien nicht blind ueberschreiben.

Entwuerfe duerfen bei laufendem Slicer bearbeitet werden; Slicer-Dateien nicht.
Cloud-Sync wird nicht manipuliert. Eine spaetere Cloud-Ueberschreibung wird beim
naechsten Scan sichtbar; die lokale Timeline bleibt erhalten.
Eine Uebernahme umfasst genau eine Installation; keine vorgetaeuschte atomare
Transaktion ueber OrcaSlicer und Snapmaker Orca. Cross-Slicer-Uebertragung bleibt
explizit, mit feldweiser Verlustanzeige und eigener Zielvalidierung.

## 8. Schnittstellen und Integration

Bestehende `/plan`- und `/apply`-Endpunkte erweitern, keinen zweiten Writer bauen.
Neue API-Vertraege betreffen Katalog, Dokument/Entwurf, Historie, Branches, Diff
und Merge-Preview. Schreibende Entwurfsaufrufe benoetigen die erwartete Generation;
Slicer-Uebernahmen die feste Revisionsauswahl und den geprueften Plan.
Ein Fehler liefert Code, Profil-ID, Feld/Dimension und maschinenlesbare Details.

Alte Filament-, Import-, Transfer-, Backup- und Aenderungsfunktionen bleiben
regressionsgetestet. Versionierte Kataloge muessen in den PyInstaller-Build gelangen.
Unbekannte JSON-Schluessel und vorgefundene Dateiformate bleiben erhalten.
Abweichungen vom bisherigen Produktumfang in `CLAUDE.md`, Spezifikation und Handbuch
erst mit der freigegebenen Implementierung aktualisieren, keine Vorab-Erfolgsaussagen.

## 9. Verifikation und Freigabekriterien

Automatische Tests ausschliesslich mit Fixtures/temporaeren Verzeichnissen.
Kein Slicer wird durch diese Recherche oder ungefragt fuer Tests gestartet/beendet.

| Pruefung | Nachweis |
|---|---|
| Katalogabdeckung | Alle speicherbaren Parameter je Profilart erfasst oder explizit als Verwaltungsfeld klassifiziert; unbekannte Extraktionsfaelle brechen den Katalogbau ab. |
| Effektive Werte | Defaults, mehrstufige Vererbung und Normalisierung gegen aus dem jeweiligen Slicer gespeicherte Referenzprofile vergleichen. Fehlende Eltern blockieren Flatten. |
| Roundtrip | Lesen, ausgewaehlten Wert aendern, schreiben, Slicer laden/speichern und erneut vergleichen; unbekannte unberuehrte Felder nicht verlieren. |
| Dimensionen | Ein-/Mehrkopf, gleiche/gemischte Duesen, Standard/High Flow, Nullable, Prozentwerte und strukturierte Werte. |
| Nutzerumfang | Selektive Bearbeitung, Merge, Restore und Publish aendern keine nicht ausgewaehlten Profile; Abhaengigkeiten erweitern die Auswahl nicht automatisch. |
| Historie | Branches, alte Staende, partielle Uebernahme, Umbenennung und Loeschkonflikte bleiben nachvollziehbar; keine falsche Merge-Abstammung. |
| Konkurrenz | Zweiter Browser, externer Edit, aktiver Ordnerwechsel und Slicer-Update machen veraltete Entwuerfe/Plaene erkennbar. |
| Fehlerpfade | Disk-full, Abbruch zwischen Dateischritten, fehlgeschlagener Rescan und Rollback; Historie meldet keinen falschen Erfolg. |
| Datenschutz | Bekannte Secrets weder als Timeline-Felder noch in Diffs/Logs/API exponieren; Backupzugriff wie bisher. |
| 0,5-mm-Fall | Eigenes Profil dem Zielmodell zuordnen, Werte erhalten, gewaehlte Prozesse/Filamente im Slicer nutzbar; native Dropdown-Grenze dokumentieren. |
| Plattformen | Windows/Linux, UTF-8, Dateinamen, Einrueckung und `.conf`-Checksumme pruefen. |
| Praktische Abnahme | OrcaSlicer durch Nutzer; Snapmaker mit externer Testperson. Ohne diese bleibt Snapmaker praktisch unbestaetigt. |

Ausgangsbasis wurde vor dieser Recherche getestet: 364 passed, 12 skipped,
0 failed. Das ist keine Verifikation des neuen Editors.

## 10. Arbeitspakete und verbleibende Nachweise

Umsetzungsreihenfolge nach Review dieses Entwurfs:

1. Versionskatalog, Normalisierung, vollstaendige effektive Werte und Referenzfixtures.
2. Lokaler Revisionsspeicher mit Auswahlsemantik, Branches, Diff und Entwuerfen.
3. Gemeinsamer Parametereditor und Einzel-/Batch-Patches fuer alle drei Profilarten.
4. Planner-Integration, sichere Uebernahme und Wiederanlaufbeleg.
5. Duesen-/Modellzuordnung, Vorschlaege, Zusammenfuehren und Referenzpflege.
6. End-to-End-Abnahme beider Slicer, Dokumentation und Build-Pruefung.

Vor verbindlichen Implementierungszusagen nachzuweisen:

- Vollstaendige Default-/Normalisierungsabdeckung beider Releases; der bisherige
  Extraktor ist nur ein Startpunkt. Technische Definitionen nachvollziehbar
  erfassen, fremde Quelltexte/Tooltips nicht pauschal in das Produkt kopieren.
- Exaktes Speicher-/Ladeverhalten unabhaengiger eigener Druckerprofile und
  deren Modell-/Duesenauswahl an Referenzfixtures und echten Slicer-Roundtrips.
- Ein anonymisiertes Profilset fuer den konkreten 0,5-mm-Fall und Snapmaker-
  Referenzprofile fuer die Flow-/Mehrkopf-Regeln; Nutzerprofile nicht ungefragt auslesen.
- Verfuegbarkeit der praktischen Snapmaker-Abnahme.

Der Entwurf empfiehlt die Dateisystem-Timeline statt eines eingebetteten Git-Repos:
keine Git-Abhaengigkeit, selektiver Profilumfang und keine sichtbare Git-Komplexitaet.
Alternativen waeren ein echtes Git-Backend (zusatzlicher Betriebs-/Metadatenaufwand)
oder nur lineare Backups (erfuellen Branches/Merge nicht). Diese Entscheidung
sowie die Grenzen der nativen Slicer-Gruppierung sind Teil des Nutzerreviews.

Nach Freigabe dieses Dokuments folgt der konkrete Implementierungsplan.
Keine Commits, Pushes oder Nachrichten an den OrcaOne-Ersteller durch diese Spezifikation.

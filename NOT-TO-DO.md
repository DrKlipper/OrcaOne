# NOT-TO-DO

| Datum | Tag | Fehler | Vermeidung |
|-------|-----|--------|------------|
| 2026-09-26 | shell | `taskkill` auf eine unbesehene PID beendete den laufenden OrcaOne-Server | Vorher PID pruefen (Kommandozeile, `netstat -ano` auf Port 4711); nur selbst gestartete Prozesse per Task-ID beenden |
| 2026-09-26 | shell | `cat > datei` ohne Heredoc/Eingabe blockierte auf stdin, Skript nie geschrieben | Dateien mit dem Write-Tool anlegen |
| 2026-09-26 | git | `gh pr create --head feature/x` scheiterte ("Head sha can't be blank"): gh zielt auf upstream DrKlipper/OrcaOne | `gh pr create --repo DrKlipper/OrcaOne --base main --head Avatarsia:feature/x` |
| 2026-09-27 | api | OrcaSlicer.cpp im Snapmaker-Repository angefragt: HTTP 404 | Quelldateinamen je Fork per Repository-Inhalt pruefen; Snapmaker verwendet Snapmaker_Orca.cpp |
| 2026-09-27 | python | coPoint wie coPoints mit nur x-Trenner validiert | Scalar-Punkte akzeptieren Komma oder x; Vektorpunkte und Serialisierung separat gegen Config.hpp pruefen |
| 2026-09-27 | python | Decimal akzeptierte Unterstriche und Unicode-Ziffern als Slicer-Zahlen | Vor Decimal eine explizite ASCII-Zahlengrammatik validieren |
| 2026-09-27 | python | Verwaiste Lockdatei per compare/unlink erzeugte Cross-Process-Race | Kernel-Dateilocks verwenden; fremde Locks nie per zeitabhaengigem Unlink entsperren |
| 2026-09-27 | python | Filament-Varianten trotz Flow-Ausnahme gekuerzt | Preset-Normalisierung anhand Quell-Keylisten steuern, nicht allein dimension |
| 2026-09-27 | api | Nicht freigegebener Katalog liess Credential-Felder als unknown durch | Secret-Filter auch ohne Katalogrollen anwenden |
| 2026-09-27 | api | Scan.of_kind fuer eigene Profile verwendet | Eigene Profile aus scan.own explizit einbeziehen |
| 2026-09-27 | python | Normaler Profil-Edit materialisierte Vererbung wie ein Merge | Normale Edits aus eigenen Werten serialisieren; Flatten nur fuer explizite Kopie/Variante |
| 2026-09-27 | js,api | Parallele Dokumentabfragen kollidierten beim erstmaligen Anlegen im gemeinsamen Profilidentitaetsindex | Neue Profilidentitaeten im Assistenten sequenziell einlesen; Gleichzeitigkeit im UI-Test pruefen |
| 2026-09-27 | python | Materialisierung entfernte geerbte Druckerverbindungen beim Aufloesen von inherits | Connectionfelder aus der aktuellen Live-Vererbung pro Profil uebernehmen, nie aus Historie oder einem anderen Drucker |
| 2026-09-27 | js | Defaultwert am zweiten Vue-setup-Parameter setzte function.length auf 1 und Vue uebergab null statt Context | setup(props, context) ohne Default deklarieren; Tests muessen den echten Vue-Context-Aufruf abbilden |
| 2026-09-28 | slicer,ui | Lokale Druckergruppe als native Orca-Zusammenfuehrung dargestellt, obwohl User-Presets einzeln bleiben | Native Dropdown-Gruppierung am gepinnten Slicer-Quellcode pruefen; Systemmodell und User-Preset getrennt behandeln |
| 2026-09-28 | python | Ungeordnete Receipt-Pfade konnten beim Rollback das Ownership-Manifest vor Paketdateien entfernen | Schreibpfade geordnet halten; beim Rollback verwaltete Paketdateien vor dem Manifest entfernen |

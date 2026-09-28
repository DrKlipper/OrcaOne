# Abnahme der Profilverwaltung

Stand: 27.09.2026. **Praktische Abnahme offen.** Es liegen keine freigegebenen
Praxisfixtures oder bestätigten Slicer-Abnahmeergebnisse für diese Erweiterung vor.
Automatische Fixture-Tests sind kein Nachweis, dass ein echter Slicer jedes Profil
lädt, speichert und beim Drucken wie erwartet verwendet.

OrcaSlicer prüft der Nutzer. Für Snapmaker Orca ist eine Rückmeldung des
Snapmaker-Orca-Erstellers vorgesehen; Zusage und Ergebnis stehen aus. Dieses
Dokument wurde niemandem gesendet. Eine Weitergabe erfolgt nur auf ausdrücklichen
Sendeauftrag.

## Protokoll je Testlauf

Vor dem Test ausfüllen:

- Tester und Datum:
- Betriebssystem und Version:
- Slicer, exakte Version und gegebenenfalls Build:
- OrcaOne-Version/Commit:
- Verwendete, ausdrücklich freigegebene Testprofile:
- Backup vor Beginn und nachvollziehbare Wiederherstellung:

Keine Zugangsdaten oder vollständigen vertraulichen Backups an das Protokoll
anhängen. Für Fehler reichen anonymisierte Feldwerte, Fehlermeldungen und die
betroffenen Profilarten, soweit diese zur Reproduktion nötig sind.

## Testmatrix

Eine Zelle gilt erst mit Tester, Datum, exakter Version und Ergebnis als bestanden.
„Offen“ bedeutet ungeprüft, nicht fehlgeschlagen.

| Prüfschritt | OrcaSlicer 2.4.2 Windows | OrcaSlicer 2.4.2 Linux | Snapmaker Orca 2.4.0 Windows | Snapmaker Orca 2.4.0 Linux |
|---|---|---|---|---|
| Eigenes Druckerprofil laden, ändern, speichern, erneut laden | Offen | Offen | Offen | Offen |
| Eigenes Filamentprofil laden, ändern, speichern, erneut laden | Offen | Offen | Offen | Offen |
| Eigenes Prozessprofil laden, ändern, speichern, erneut laden | Offen | Offen | Offen | Offen |
| Herstellerprofil als eigene Kopie; Original unverändert | Offen | Offen | Offen | Offen |
| 0,5-mm-Variante einem Modell zuordnen; nur ausgewählte Referenzen ändern | Offen | Offen | Offen | Offen |
| Mehrere Druckköpfe: Werte und Zuordnung erhalten | Offen | Offen | Offen | Offen |
| Standard/High Flow bei gleicher Düse: Reihenfolge und Werte erhalten | Offen | Offen | Offen | Offen |
| Vorschlag nach Düsenwechsel einzeln annehmen/ablehnen | Offen | Offen | Offen | Offen |
| Lokaler Stand und Branch verändern keine Slicer-Datei | Offen | Offen | Offen | Offen |
| Selektives Restore verändert nur ausgewählte Profile/Felder | Offen | Offen | Offen | Offen |
| Externer Edit erscheint stabil in der Timeline | Offen | Offen | Offen | Offen |
| Kurzzeitig ungültige/fehlende Datei erzeugt keine falsche Löschung | Offen | Offen | Offen | Offen |
| Zwei Browser: veralteter Entwurf überschreibt keinen neueren Stand | Offen | Offen | Offen | Offen |
| Laufender Slicer blockiert die Übernahme | Offen | Offen | Offen | Offen |
| Geänderte Basis nach Vorschau erzwingt neue Prüfung | Offen | Offen | Offen | Offen |
| Backup und Nachprüfung der Übernahme; Wiederherstellung prüfen | Offen | Offen | Offen | Offen |
| Cross-Slicer-Kopie nennt Feldverluste vor Bestätigung | Offen | Offen | Offen | Offen |

## Erwartete Grenzen

- Eigene Presets können im nativen Dropdown weiterhin getrennt von den
  Herstellerprofilen erscheinen. Das allein ist kein Fehler der Modellzuordnung.
- Nicht geprüfte Slicer-Versionen erhalten keine automatische Schreibfreigabe.
- Ein Cross-Slicer-Verlustbericht ist eine Vorschau. Er ersetzt weder die
  Feldbestätigung noch die spätere Übernahmevorschau und ihr Backup.
- Drucktechnische Plausibilität und tatsächliche Druckqualität separat bewerten;
  strukturell gültige Dateien garantieren keine geeigneten Druckeinstellungen.

## Fehler oder Abschluss

Je Befund notieren: Prüfschritt, erwartetes Ergebnis, beobachtetes Ergebnis,
betroffene Profilart/Felder, Reproduktionsschritte und gegebenenfalls anonymisierte
Logs. Ein behobener Befund benötigt einen erneuten Lauf genau dieses Prüfschritts.

Gesamtergebnis: **offen**. Tester, Datum und Freigabe: **ausstehend**.

# Printer Merge Implementation Plan

**Goal:** Mehrere eigene Druckerprofile visuell und explizit zu einer Modellkarte
mit Duesenvarianten zusammenfuehren und geprueft in Orca uebernehmen.
**Spec:** ../specs/2026-09-27-printer-merge-design.md
**Architecture:** Bestehende History/Publish-Pipeline erweitern; lokaler expliziter
Gruppenindex, serverseitige Preview, separate UI-Komponente.
**Tech Stack:** Python/FastAPI, Vue, bestehende JSON Settings, keine Dependencies.

## Aufgaben und Ownership

- [x] Backend: profile_printer_merge.py, profile_api.py, profile_publish.py;
  Tests fuer beliebige Auswahl, Konflikte, Prozessentscheidungen, stale Preview,
  Publish-Scope und Recovery. normalize_edit.
- [x] Gruppenindex und Overview: profile_groups.py, overview.py; Tests fuer
  vier+ Drucker, nicht ausgewaehlte Profile, gleiche Duese, stabile IDs und Replay.
  history_workflows.
- [x] Visuelle Zuordnung: printer-merge.js, Session, Texte, CSS und Einstieg;
  Drag & Drop sowie Buttons, Preview-Invalidierung, Auswahl und Vue-Tests.
  schema_generator.
- [x] Integration: common.js Modellnamen, gleiche Duesen in Prozess/Filament-UI,
  bestehender Profileditor-Publish mit vollstaendiger expliziter Gruppenauswahl.
  Root.
- [x] Review, gezielte Tests/Gesamtsuite, isolierter Browser-Smoke, Dokumentation.

## Verifikation und Grenzen

Nur synthetische Fixtures/temp/fake_home. Keine Slicer starten/beenden, keine
echten Profile im Test veraendern. Bestehenden Branch und laufende Userinstanz
erhalten; keine Commits/Push ohne separaten Auftrag. CRLF vorhandener Dateien
erhalten. Keine automatische Zuordnung, kein Credential-Merge, keine Skalierung.

## Ergebnis

- Python: 598 passed, 12 skipped.
- Node: 8 Entry/Group-Tests und Merge-UI-Regression gruen.
- Isolierter Browser: vier Profile (0.4/0.5/0.5/0.6), Drag-and-Drop-Zuordnung,
  automatischer Entwurf, Preview, Backup, Apply und eine gemeinsame Karte verifiziert.
- Prozess gezielt mit zweiter Variante geteilt; Receipt state=verified.
- Native Slicer-Abnahme bleibt separat offen; keine echten Profile im Test geaendert.

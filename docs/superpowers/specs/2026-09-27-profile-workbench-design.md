# Profile Workbench

## Korrigierter Nutzerauftrag

Eigene Seiten links: Profile bearbeiten und Profile zusammenstellen. Keine
Einstiegsbuttons in der Uebersicht. Zusammenstellen zeigt die bestehenden
Beziehungen wie Zusammenhaenge als aufklappbaren Baum und daneben den Zielbaum.
Mehrfachauswahl und Drag & Drop fuer Drucker, Duesen, Prozesse und Filamente.
Neue Duesen entstehen aus einer explizit gewaehlten Vorlage. Namen direkt per
F2 oder Kontextaktion bearbeiten. Namen gelten im Slicer, nicht nur als Label.
Referenzaenderungen werden in der Preview gezeigt und mit Backup uebernommen.
Keine stillschweigende Quellloeschung: Kopieren, Verschieben bzw. zusaetzliches
Zuordnen sind sichtbare Entscheidungen. Bestehende Timeline und Publish nutzen.

## Vertrag

POST profile-editor/composer-preview:
{group_name,target_model,variants:[{key,source_name,name,mode:'move'|'copy',
nozzle_diameter:[string]}],assignments:[{kind:'process'|'filament',source_name,
name,action:'share'|'copy'|'move'|'rename',targets:[variant_key],from:[machine_name]}]}

move bei Varianten verwendet die Quellidentitaet; copy erzeugt eine neue.
rename behaelt Identitaet und passt alle belegbaren Referenzen an. Kein stiller
Rename zu einer Copy. from begrenzt beim Verschieben die zu entfernenden Bindungen.
Preview zeigt zusaetzlich betroffene Profile und Referenzen vor jeder Mutation.
Server baut Dokumente aus eigenen Scans; Clientwerte sind nur Absichten.
Antwort {preview_id,documents,group,issues,impacts}; POST composer-branch mit
{preview_id,name?} -> {created,branch,issues}. Vollstaendige Auswahl beim Publish.
Ein Ziel darf mit einer Variante beginnen. Technischer Scope bleibt begrenzt,
keine Drei-Drucker-Grenze. Unaufloesbare Bedingungen blockieren sichtbar.

## Verifikation

Nur synthetische Fixtures/temp/fake_home, niemals echte Slicer-Profile testen.
Backend: neue Varianten, Mehrfachmerge, echte Renames, Referenzen, IDs, Secrets,
Stale-Preview, atomarer Publish/Rollback und Gruppenindex.
UI: reale Vue-Mount-Semantik, Baum/Drops/F2/Mehrfachwahl, Sidebar, DE/EN.
Browser: vier Quellen, neue Duese, umbenannter Prozess, Diff/Backup/Apply.

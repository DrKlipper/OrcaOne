# Drucker visuell zusammenfuehren

## Nutzerziel

Mehrere bisher getrennte eigene Druckerprofile als einen Drucker mit mehreren
Duesenkonfigurationen verwenden. Keine Beschraenkung auf die drei Profile aus
dem Beispiel. Eigene Werte, Multiextruder-Konfigurationen und Prozesszuordnungen
bleiben nachvollziehbar. Der Nutzer entscheidet den Umfang jeder Aktion.

## Bedienung

- Assistent ueber Uebersicht/Zusammenhaenge oeffnen und mehrere Drucker waehlen.
- Drucker, Duesen und Prozesse nebeneinander als Beziehungen darstellen.
- Duesenkarten per Drag & Drop in den Zieldrucker aufnehmen, Prozesskarten den
  konkreten Varianten zuordnen. Gleichwertige Buttons fuer Touch/Tastatur.
- Profilname ist keine Duesenangabe: wirksame nozzle_diameter anzeigen. Gleiche
  Duesen behalten getrennte Identitaeten und benennbare Varianten.
- Zielname und technisches Druckermodell explizit festlegen. Prozesse bleiben
  ohne Auswahl unveraendert; Teilen oder Kopieren ist eine explizite Entscheidung.
- Vorschau nennt betroffene Profile/Werte und Konflikte. Lokaler Arbeitsbereich
  entsteht automatisch. Erst bestehendes Publish mit Backup schreibt in Orca.

## Daten und Grenzen

Maschinen behalten Namen/IDs und Verbindungen; keine Dateien werden geloescht.
Explizites Merge materialisiert effektive Werte, setzt den ausgewaehlten
printer_model und nur ausdruecklich geaenderte Duesenwerte. Variantenlabels sind
OrcaOne-Metadaten, keine willkuerlichen printer_variant-Werte.
Der lokale Gruppenindex in settings.json wird erst nach verifiziertem Publish
aktiviert; Replay/Recovery ist idempotent. Nur ausgewaehlte eigene Profile werden
gruppiert, nie alle mit zufaellig gleichem Modellnamen.
In OrcaOne entsteht genau eine Modellkarte; native Orca-Dropdowns koennen die
einzelnen Benutzerpresets weiter separat anzeigen. Herstellerressourcen bleiben
unveraendert. Bestehende Druckerverbindungen werden nicht zusammengemischt.

Serverseitige Preview mit Fingerprint verhindert veraltete oder manipulierte
Uebernahmen. Vollstaendige Gruppe wird gemeinsam publiziert, keine halbe
Gruppierung. Unbekannte Versionen, unvollstaendige Vererbung, Namenskonflikte und
ungueltige Zielwerte bleiben blockiert. Bestehendes technisches Scope-Limit 200
Profile pro Request; keine gesonderte Drei-Drucker-Grenze.

## Abnahme

Fixtures mit mindestens vier Druckern, gleicher Duese, mehreren Extrudern,
abweichenden Namen/Werten, unbeteiligtem Drucker und ausgewaehlten Prozessen.
Preview schreibt keine Slicer-Datei. Publish erzeugt eine sichtbare Gruppe;
erneutes Einlesen und Recovery erhalten sie. Drag & Drop und Buttons bilden
dieselben expliziten Zuordnungen. Echte Slicer-Abnahme bleibt getrennt.

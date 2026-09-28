# Profile bearbeiten und Änderungen aufbewahren

Die Profilverwaltung unterscheidet zwischen deinem lokalen Arbeitsstand in OrcaOne
und den Profilen, die der Slicer tatsächlich lädt. **Lokal speichern verändert keine
Slicer-Datei.** Erst „In Orca übernehmen“ erstellt eine Vorschau der Änderungen für
die ausgewählte Installation.

Aus einem geöffneten Prozess führt „Profile bearbeiten“ direkt zu dessen
Parametern. Der lokale Arbeitsbereich wird automatisch angelegt und nach dem
Profil benannt; andere Profile müssen dabei nicht ausgewählt werden. Über den
Navigationspunkt **Profile bearbeiten** links wählst du die gewünschten Profile und klickst auf
„Ausgewählte Profile bearbeiten“. Auch dort entfällt das manuelle Anlegen eines
Branches. Bewusste Abzweigungen bleiben in der Timeline möglich.

Die praktische Abnahme dieser Erweiterung in beiden Slicern steht noch aus. Die
automatischen Tests benutzen synthetische Fixtures und temporäre Verzeichnisse;
sie ersetzen keinen Druck- oder Speichertest im Slicer. Die offene Testmatrix steht
in [PROFILE-ABNAHME.md](PROFILE-ABNAHME.md).

## Version und Umfang

Die mitgelieferten Parameterkataloge gelten genau für OrcaSlicer **2.4.2** und
Snapmaker Orca **2.4.0**. Eine neuere Versionsnummer erhält keine automatische
Schreibfreigabe. Für unbekannte Versionen bleiben vorhandene Lesefunktionen
nutzbar; der neue vollständige Editor benötigt einen eigens geprüften Katalog.

Du wählst den Umfang jeder Aktion: ein Profil, mehrere Profile oder ein bewusst
zusammengestelltes Profilset. Drucker-, Filament- und Prozessprofile können zusammen
einen Stand bilden. Bei normalen Parameteränderungen erweitern Referenzen die Auswahl nicht automatisch.
Bei einer echten Umbenennung zeigt die Vorschau zusätzlich alle notwendigen
Referenzänderungen; diese werden als zusammengehöriger Vorgang bestätigt.

## Eigene Werte, geerbte Werte und Defaults

Ein Profil kann Werte von einem Elternprofil erben. Der Editor unterscheidet den
eigenen Wert, den geerbten Wert und den Default des geprüften Slicers. Der wirksame
Wert ist derjenige, mit dem dieses Profil nach Auflösung seiner Eltern arbeitet.

„Zurücksetzen“ entfernt eine eigene Überschreibung und stellt den geerbten Wert
wieder her. Das ist etwas anderes als eine leere Zeichenkette, eine leere Liste
oder `nil`. `nil` ist nur für die Felder zulässig, deren Slicer-Typ es erlaubt.
Fehlt ein Elternprofil oder ist seine Herkunft unvollständig, darf OrcaOne keinen
vollständigen bearbeitbaren Stand vortäuschen.

Mehrere Werte eines Feldes können zu Extrudern, Filamenten oder Flow-Varianten
gehören. Zwei Werte bedeuten daher nicht automatisch zwei Druckköpfe. Geometrien,
etwa die Druckfläche, behalten ihre Punktstruktur. IDs, Zugangsdaten und andere
Verwaltungsfelder sind keine frei bearbeitbaren Druckparameter.

Ungültige Typen, Werte außerhalb fester Grenzen und unauflösbare Referenzen können
eine Übernahme blockieren. Hinweise zur drucktechnischen Plausibilität sind davon
getrennt: Eine zulässige Temperatur ist noch keine Empfehlung für dein Material.

## Entwurf, Stand, Branch und Timeline

Ein **Entwurf** ist der veränderbare lokale Arbeitsbereich. Ein **Stand** hält die
ausgewählten Profilrevisionen und eine Notiz fest. Die gespeicherten Revisionen
werden nicht nachträglich überschrieben. Die **Timeline** zeigt diese gespeicherten
Stände und ihre Herkunft; dazu können auch beobachtete Änderungen aus dem Slicer
gehören.

Ein **Branch** ist eine eigene Entwicklungslinie, etwa „Versuch mit weniger
Kühlung“. Er kann dieselben Profile wie ein anderer Branch enthalten. Eine
**Druckervariante** beschreibt dagegen eine konkrete Kombination von Modell und
Ausstattung. Beispielsweise können Standard und High Flow denselben
Düsendurchmesser haben. Ein Branch ist kein zusätzlicher physischer Drucker.

Beim Wiederherstellen bestimmst du wieder den Umfang. Ein einzelnes Profil oder
ausgewählte Werte lassen sich aus einem älteren Stand in einen neuen lokalen
Arbeitsstand übernehmen. Andere Profile werden dabei nicht still mitgenommen.
Beim Zusammenführen werden wirksame Werte verglichen, damit ein anderer alter
Elternname nicht unbemerkt das Ergebnis verändert.

„Ganze Profile wiederherstellen“ zeigt vorher eine Vorschau für die markierten
Profile. Fehlt ein Profil im gewählten Quellstand, wird es im neuen lokalen Stand
als entfernt markiert. Das löscht keine Slicer-Datei; die Übernahme unterstützt
das Anlegen und Aktualisieren vorhandener Profilstände.

Bearbeiten zwei Browser denselben Entwurf, darf eine veraltete Browseransicht
neuere Änderungen nicht überschreiben. Bei einem Konflikt muss der aktuelle
Stand neu geladen werden.

Die neue Profilhistorie liegt lokal unter
`data/snapshots/profiles/<installation-id>/`. Sie ist unabhängig vom Slicer-Sync.
Die bisherigen Snapshots und die Messhistorie unter `data/history/` bleiben
separate Daten. Diese persönlichen Daten gehören nicht in das ausgelieferte
Programm-Paket.

## Herstellerprofile und Druckermodelle

Hersteller- und Systemprofile bleiben unverändert. Wenn du sie als Ausgangspunkt
verwendest, entsteht für deine Änderungen eine eigene Kopie. Die übernommenen
wirksamen Werte sollen nachvollziehbar sein; ein fremdes Elternprofil darf nicht
unbemerkt zur neuen Basis werden.

Du kannst eine vorhandene Variante mit beispielsweise 0,5-mm-Düse einem Modell
zuordnen und ausgewählte Prozesse oder Filamente passend verknüpfen. Ein
Düsenwechsel erzeugt Vorschläge. OrcaOne verändert dazu keine anderen
Druckparameter ohne deine Auswahl.

Die Modellzuordnung in OrcaOne garantiert keine identische Darstellung im Slicer:
Die untersuchten nativen Drucker-Dropdowns führen eigene Presets getrennt von
System-/Default-Presets. Eine Änderung von `printer_model` allein verschiebt ein
eigenes Preset nicht zuverlässig in die native Herstellergruppe. Verschiedene
physische Drucker behalten außerdem ihre eigenen Verbindungen.

## Profile als Beziehungen zusammenstellen

Die linke Navigation enthält **Profile zusammenstellen**. Die Seite zeigt zwei
aufklappbare Bäume wie „Zusammenhänge“: vorhandene Drucker mit Düsen, Prozessen und
Filamenten sowie den neuen Zieldrucker. Strg erlaubt Mehrfachauswahl, Umschalt eine
Bereichsauswahl. Die bisherigen Einstiegsbuttons in der Übersicht entfallen.

Wähle die Aktion vor dem Ablegen: **Kopieren** erzeugt neue Profile,
**Verschieben** erhält die Identität, **Zusätzlich zuordnen** ergänzt bestehende
Prozess-/Filamentbindungen. Ziehe Elemente in den Zielbaum oder verwende
„Auswahl hinzufügen“. Unbeschränkte Kompatibilität wird nicht still eingeschränkt.
Beim Kopieren eines Druckers oder einer Düse werden die zugehörigen Prozesse und
Filamente mitkopiert und den jeweiligen Zieldüsen zugeordnet. Gemeinsam genutzte
Profile werden dabei einmal kopiert und mit allen passenden Zieldüsen verbunden.

Für eine neue Düse wählst du eine vorhandene Düse als Vorlage und dann
„Neue Düse aus Auswahl“. Im Ziel lässt sich ihr tatsächlicher Durchmesser ändern.
Eine Extruderanzahländerung braucht weiterhin einen gesonderten, geprüften Ablauf.
Gleich große Düsen dürfen unterschiedliche Varianten bleiben.

**Zwei linke Titelklicks mit kurzer Pause**, **F2** oder die Kontextaktion benennen Elemente im Zielbaum um. Düsen zeigen ihr Symbol und den tatsächlichen Durchmesser. Der neue Name gilt
auch im Slicer: Referenzen, vererbende Benutzerprofile und gespeicherte Auswahlen
werden entsprechend angepasst. Die Vorschau zeigt die betroffenen Profile und
Vorher-/Nachher-Werte. Herstellerprofile lassen sich nur als eigene Kopie ändern.
Nicht sicher auflösbare Bedingungen verhindern die Übernahme.
Bei unvollständigen Profilen nennt die Prüfung Parameter, Wert, erwarteten Typ
und Herkunft. Für gültige Enum-Einzelwerte im alten Format bietet sie
„Kompatibilität herstellen und prüfen“ an: Umwandlung in Listen, anschließende
Validierung gegen die installierte Slicer-Version und Vorschau aller Änderungen.
Dies ändert noch keine Slicer-Dateien; die spätere Übernahme erstellt ein Backup.
„Fix anwenden“ übernimmt die geprüfte Reparatur ausschließlich in den lokalen
Entwurf und wechselt zu „Zusammenführen“. Das funktioniert auch bei laufendem
Slicer. Erneutes Prüfen berücksichtigt die gewählte Konvertierung. Erst die
endgültige Übernahme schreibt mit Backup; dafür muss der Slicer geschlossen sein.
Fehlende Elternprofile und unbekannte Enum-Werte werden nicht automatisch ersetzt.

Namensänderungen,
die ausschließlich Groß-/Kleinschreibung ändern, werden derzeit gesperrt.

Der Entwurf bleibt beim Wechsel zwischen Seiten im geöffneten OrcaOne erhalten.
Nach der Prüfung wird automatisch ein lokaler Arbeitsbereich angelegt. Im
Profil-Editor folgen Datei-Diff, Backup und Übernahme bei geschlossenem Slicer.
Alle notwendigen Referenzänderungen gehören zu dieser gemeinsamen Übernahme.
Die Timeline bleibt unabhängig vom Slicer-Sync.

Nach erfolgreicher Übernahme zeigt OrcaOne die neue Gruppe als gemeinsamen
Druckereintrag mit einzeln auswählbaren Düsenvarianten. Orcas eigenes Dropdown
kann die Benutzerpresets weiterhin einzeln darstellen. Physische Verbindungen
werden nicht zwischen verschiedenen Druckern zusammengeführt.

## In den Slicer übernehmen

Vor einer Übernahme muss der betroffene Slicer geschlossen sein. OrcaOne erstellt
zuerst eine Vorschau für die ausgewählten Profile. Die Bestätigung gilt für genau
diesen Vorschlag und diese Installation. Wenn zwischen Vorschau und Ausführung
die Profilbasis, der Benutzerordner oder die Version wechselt, ist eine neue
Prüfung erforderlich.

Der bestehende Schreibablauf erstellt ein Backup und kontrolliert anschließend
das Ergebnis. Geschrieben wird ausschließlich in `user/**` und die Slicer-`.conf`.
Herstellerressourcen und Systemprofile werden nicht verändert. Ein lokaler
Timeline-Stand ersetzt dieses Backup nicht.

Backups können Zugangsdaten enthalten und sind vertraulich. Der Editor übernimmt
Zugangsdaten nicht als normale Parameter in seine Dokumente oder Verlustberichte.
Bewahre Backups und den persönlichen `data/`-Ordner entsprechend geschützt auf.

## Zwischen Slicern kopieren

Die bisherige Seite „Übertragen“ behält ihren bisherigen Ablauf. Für den neuen
Editor-Konvertierungsweg gibt es zusätzlich einen versionsbezogenen Verlustbericht.
Er erzeugt zunächst nur einen Vorschlag und veröffentlicht nichts.

Im Editor findest du ihn unter „In eine andere Installation kopieren“. Wähle
Zielinstallation und Namen der Kopien, prüfe die Feldänderungen und bestätige
sie einzeln. „Zielvariante öffnen“ öffnet danach den lokalen Branch im Ziel.

Der Bericht nennt je Feld unbekannte oder entfernte Parameter, ersetzte
Enumwerte und gekürzte Vektoren. Eine Liste mit Standard- und High-Flow-Wert kann
in einem skalaren Zielfeld nur einen Wert speichern. Solche Verluste müssen je
Feld bestätigt werden; ungültige Zielwerte bleiben auch nach einer Bestätigung
blockiert. Eine anschließende Übernahme benötigt weiterhin die normale Vorschau
und Bestätigung.

Die Kopie erhält eine eigene Identität und einen Herkunftsverweis. Sie wird nicht
als gemeinsame Timeline-Abstammung der beiden Installationen ausgegeben.

## Build und derzeitige Nachweise

Der vorhandene portable PyInstaller-Build nimmt das Manifest und die beiden
Release-Kataloge ausdrücklich mit auf. Ein isolierter Pakettest lädt beide
Kataloge ohne Upstream-Quellen oder Netzwerkzugriff. Lokale Historie, Einstellungen
und Backups gehören nicht zu den Build-Assets.

In dieser Windows-Umgebung ist PyInstaller nicht installiert. Es wurde keine
zusätzliche Build-Abhängigkeit installiert und kein neuer Windows-Binary-Build
behauptet. Der Repository-Stand besitzt keinen Wheel-Build; dafür wurde kein neuer
Packaging-Weg eingeführt. Linux-Build und praktische Slicer-Abnahme dieser
Erweiterung stehen aus.

## Entwurf fortsetzen und kompakte Vorschau

Zusammenstellungen werden pro Installation im Browser gespeichert, einschließlich
Zuordnungen, Namen, Düsen und akzeptierter Kompatibilitätskonvertierung. Verwerfen
entfernt diese Aktionen. Der Editor merkt sich den letzten Branch sowie lokale
Parametereingaben und Auswahl. Abweichende Branch-Stände werden als Konflikt
behandelt. Die Speicherung gilt für denselben Browser und dieselbe Serveradresse.

Neu erstellte Zusammenstellungen speichern zusätzlich ihre Aktionen serverseitig.
Bei veralteter Vorschau können unveränderte Zusammenstellungen auf aktuellen
Slicer-Daten neu aufgebaut werden; manuell nachbearbeitete Branches werden nicht
still überschrieben. Die neue Vorschau verlangt erneut eine Bestätigung.
Parameter und umfangreiche Profildiffs sind einklappbar; die Übernahmeaktion bleibt
im Editor sichtbar. Browser-Speicherung kann durch Browser-Einstellungen blockiert sein.

## Fortschritt bei Vorschau und Uebernahme

Die Vorschau und Uebernahme melden serverseitige Phasen im sichtbaren Aktionsbereich:
Pruefen, Vorschau aufbauen, Unterschiede ermitteln, Backup, Schreiben und Ergebnis
pruefen. Profil-, Datei- und Schreibschrittzaehler zeigen tatsaechlich erledigte
Arbeit; unbekannte Restarbeit wird als unbestimmter Balken dargestellt. Bei Fehlern
kann eine Ruecknahme angezeigt werden. Netzwerkunterbrechungen werden benannt,
ohne einen zweiten Schreibauftrag zu starten oder einen Erfolg zu behaupten.
Navigation und Neuladen warnen waehrend einer laufenden Aktion; ein bestaetigtes
Verlassen beendet den Servervorgang nicht und verliert die laufende Anzeige.

Zusammenstellungen fuer OrcaSlicer ab 2.4.2 werden als eigenes natives Modellpaket
gespeichert. Der Druckername entspricht dem gewaehlten Namen der Zusammenstellung;
OrcaOne ist der Paket-Anbieter. Die Duese wird unter diesem gemeinsamen Modell
ausgewaehlt. Prozesse und Filamente bleiben Benutzerprofile mit passenden Referenzen.
Gleiche Duesenkonfigurationen verlangen eine Entscheidung: Durchmesser anpassen
oder eine Variante entfernen und ihre Prozesse/Filamente gezielt einer anderen
Variante zuordnen. Kopieren behaelt die Originale; Verschieben entfernt die gewaehlten
eigenen Quelldrucker. Bereits verwaltete native Varianten koennen in eine andere
Zusammenstellung kopiert, derzeit aber nicht verschoben werden.

Eigene Modellpakete sind in Vorschau, Backup, Rollback und Wiederherstellung
enthalten. Fremde Systempakete werden nicht geaendert. Direkte Aenderungen im Slicer
koennen wieder separate Benutzerkopien erzeugen. Native GUI-Abnahme in OrcaSlicer
steht noch aus; das Paketformat fuer Snapmaker ist nicht freigegeben. Quelldetails:
NATIVE_PRINTER_MODELS.md.

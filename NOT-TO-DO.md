# Fehlerprotokoll

| Datum | Tag | Fehler | Vermeidung |
|-------|-----|--------|------------|
| 2026-09-27 | python,logs | Zu kurzes Tail-Sample bestand nur aus UTF-8-Fortsetzungsbytes und markierte gültigen Text als binär. | Vollständiges überlappendes Tail-Fenster lesen; Multibyte-Zeichen an der Samplegrenze testen. |

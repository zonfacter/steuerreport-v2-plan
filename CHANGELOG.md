# Changelog

## 0.2.0rc13 - 2026-10-26

### Benutzerfuehrung und Hilfe

- Zentrale Hilfeseite mit Suche, Bereichsfilter, 13 Arbeitsablaeufen,
  5 haeufigen Fragen und 10 Begriffserklaerungen.
- Bereichshilfe im separaten Tab ohne Verlust ungespeicherter Eingaben;
  alle mitgelieferten HTML-/PDF-Anleitungen an einer Stelle erreichbar.
- Fragezeichen-Tooltips fuer Hover, Tastatur und Touch mit Escape- und
  Aussenklick-Schliessen sowie Positionierung im sichtbaren Bereich.
- Ablaufnavigation von Einrichtung bis Export; mobil kompakt aufklappbar.
- Konkrete Voraussetzungen bei deaktivierten Import- und KI-Aktionen.
- Gespeicherte KI-Verbindung und technische Administration eingeklappt;
  neue Installationen zeigen die erforderliche KI-Einrichtung weiterhin.
- Leeren Expertenwerkzeug-Umschalter entfernt; aktiven Navigationsbereich
  und globalen Auswertungsstatus eindeutiger gekennzeichnet.

### Pruefung und Betrieb

- Reproduzierbarer Browser-Test mit ausschliesslich synthetischen
  API-Antworten fuer Desktop und Mobilgeraete in die CI aufgenommen.
- Release-Ablauf mit Changelog, unveraenderlichen Tags, GitHub-Entwurf,
  Backup, Rollback und produktiver Nachpruefung in AGENTS.md festgehalten.
- Keine Aenderung an steuerlicher Berechnung, API-Fachvertraegen,
  KI-Berechtigungen oder Nutzerdaten. Kein automatischer Modellaufruf.
- Bestehende Build-Warnung zum grossen Frontend-Haupt-Chunk bleibt offen.
  Durchgaengige Verlassenswarnungen fuer alle aelteren Formulare sind
  nicht Bestandteil dieser Version.

## 0.2.0rc12 - 2026-10-25

- Sieben konfigurierbare KI-Fachagenten mit versioniertem Anwendungswissen
  und Modellzuordnung fuer lokale und Cloud-Verbindungen.
- Enthalten ist der mit RC11 getaggte Korrekturgrundstand: ausgewaehlte
  Datenzeilen, isolierte Berechnungsvorschau, menschliche Freigabe,
  atomare Uebernahme, Audit und gesondert freizugebende Ruecknahme.
- Der damalige native DuckDB-Prozessabsturz im ersten CI-Versuch ist im
  RC12-Pruefbericht dokumentiert. Erfolgreiche Wiederholungen sind kein
  Nachweis einer abschliessend behobenen Absturzursache.

Die vorherigen Versionen sind ueber die bestehenden Git-Tags und
GitHub-Releases nachvollziehbar. Bestehende Tags werden nicht ersetzt.

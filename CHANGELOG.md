# Changelog

## 0.2.0rc14 - 2026-10-26

- API-Einrichtung nach Installation, Datenanbietern, eigenen Verbindungen,
  Abrufsteuerung und KI getrennt; Demo-Modus ausdrücklich schreibgeschützt.
- UUID-basierte Mehrkontenverwaltung mit verschlüsselten Zugangsdaten,
  getrennten Bestands-Snapshots und ausdrücklich bestätigten Test-/Abrufjobs.
- Gemeinsamer persistenter Abrufkoordinator für rollierende Sekunden-/Minutenlimits,
  lokale Endpunktkosten, Parallelität, Pausen, Retries und Gesamtdeadlines.
  Hostlokale Worker teilen atomar dieselben Budgets; kein stiller Fallback.
- Betreiberdeklarierte Tarifobergrenzen, Quellen und tatsächliche Anbieterheader
  getrennt von lokalen Nutzungswerten. Kein automatischer periodischer Sync.
- Secret-Felder maskiert; alte Admin-Schreibwege ebenfalls ohne Klartextfallback.
  Vorhandene Legacy-Zugänge bleiben unverändert lesbar und werden nicht aktiviert.
- Nachprüfung R1: Aufgabenpanel unterscheidet initiales Laden, API-Fehler mit
  Wiederholen und bestätigten Leertreffer. ID-Abfrage bleibt unabhängig von der
  Listenseite; Filter und Rückweg bleiben erhalten. Kontrollierte Verzögerungs-,
  Fehler- und Aufgabenwechseltests im bestehenden Browserlauf ergänzt.
- Review-Nacharbeit: kontobezogene Aufgaben in Quellenliste, Abgleichfilter und
  Quellendetail konsistent verknüpft; Quellen-/Bewertungshinweise bleiben getrennt.
- Direkter Absprung zur betroffenen Konto-/Asset-Ledgeransicht mit Rückweg zur
  Review-Aufgabe; mehrdeutige Zuordnungen werden nicht automatisch entschieden.
- Fester EUR-Referenzwert statt technischem Epochendatum; kompakte Mengen mit
  exaktem aufklappbarem Wert, sprachliche Korrekturen und Testumgebungshinweis.
- Ergänzende F1–F3-Browserprüfung gegen das echte Backend mit isolierter
  synthetischer Datenbank, einschließlich tatsächlichem Testimport und Hashprüfung.
- Eigene Quellen statt Anbieter-Katalog als Einstieg, geführtes Hinzufügen,
  Quellendetail mit Beständen, Transaktionen, Abgleich und Einstellungen.
- Paginierte Transaktionen und Ledger, beleggebundene Details sowie CSV-Export
  mit ausdrücklich gewähltem Umfang. `#flows` und die Flussansichten bleiben erhalten.
- Gemeinsame Filter-, URL-, Lade-/Fehler- und Detailmuster; vertrauliche Suche
  bleibt im Arbeitsspeicher. Dashboard, Review und Jahresberichte aufgeräumt.
- Konservative zentrale Jahresstatusanzeige auf Basis bestehender Fach-Gates;
  Null, unbekannt, leer und laufende Prüfung werden nicht gleichgesetzt.
- Bestätigung externer Abrufe/Neuberechnung, Sperre paralleler zentraler
  Vorgänge, korrekte Kennzeichnung des schreibenden ZIP-Cache-Endpunkts.
- Synthetische Browserabnahme in vier Bildschirmbreiten, isolierte Vorschau
  ohne Betreiberprofil oder externe Verbindungen und dokumentierte Übergabe.
- Keine Änderung der Steuer-/FIFO-/Ownership-Regeln und keine Änderung
  historischer Nutzerdaten. Versionierter Release mit Docker-Image;
  vorhandene Datenvolumes und Vault-Schlüssel bleiben beim Update erhalten.
- Anbieterreferenzen in Docker und Software-ZIP eingeschlossen; der Image-Smoke-Test
  prüft auch Mehrkonten-, Limit- und Anbieterreferenz-Endpunkte einer leeren Installation.
- Grenzen: kein automatischer Sync-Zeitplan, keine Tages-/Monatsabrechnungsbudgets,
  kein eigener persistierter Jobstatus für Anbieterpausen und keine Mehrhost-Koordination.

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

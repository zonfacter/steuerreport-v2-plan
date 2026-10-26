# AGENTS.md fuer Steuerreport V2

Dieses Projekt verarbeitet steuerrelevante Krypto-Daten. Arbeite defensiv:
keine erfundenen Transaktionen, keine stillen Preisannahmen, keine Vermischung
von Handelsvolumen und Netto-Geldfluss.

## Verbindliche Projektregeln

- Schreibe Deutsch in Dokumentation, Issues und Handoffs.
- Verwende DuckDB als interne Datenbank. SQLite ist fuer V2 nicht der Plan.
- Baue vertikal zuerst: ein kleiner Ende-zu-Ende-Pfad ist wichtiger als viele
  unverbundene Module.
- Halte Schnittstellen stabil und versioniert.
- Rohdaten muessen unveraendert erhalten bleiben.
- Jede abgeleitete Zahl muss auf Raw-Objekte, Canonical Events oder Review-
  Entscheidungen zurueckfuehrbar sein.
- Blockpit und V1 sind Referenzquellen, aber nicht primaere Portfolio-Wahrheit.
- PDF-Exporte duerfen maximal 100 Seiten je Datei enthalten.
- Externe KI darf nur nach expliziter Admin-Aktivierung genutzt werden.

## Architekturgrenzen

- `api`: FastAPI-Endpunkte, keine Fachlogik.
- `contracts`: Pydantic-Modelle und stabile Antwortformate.
- `db`: DuckDB-Verbindung, Schema, Migrationen.
- `importers`: Datei- und API-Import, Normalisierung zu Canonical Events.
- `ledger`: reproduzierbare Ledger-Berechnungen.
- `domain`: Tax, Portfolio, Flow, Review und Export Services.
- `ai`: KI-Aufgaben, Redaction, lokale/externe Adapter.

## Harte Regressionen

Diese Fehler duerfen nicht zurueckkommen:

- USDT in Paaren wie `BTCUSDT` darf nicht mit dem BTC-Preis multipliziert
  werden.
- Referenzquellen duerfen Portfolio-Bestaende nicht doppelt erhoehen.
- SOL-, HNT- und andere Asset-Bestaende duerfen nicht aus Vergleichsdaten
  aufgeblasen werden.
- HNT Mining Rewards und Transfers duerfen nicht doppelt als Zufluss gelten.
- Pionex-USDT-Luecken duerfen nicht als erfundene Kaeufe erzeugt werden.
- Alte Preise duerfen nicht still fuer spaetere Jahre wiederverwendet werden.

## Definition of Done

Bei beauftragten produktiven Updates gehoeren GitHub und Deployment zusammen:

- Eigene Aenderungen mit konsistenter Software-, Frontend- und Compose-Version
  committen und auf GitHub pushen; keine unbeteiligten Aenderungen mitnehmen.
- `CHANGELOG.md` pflegen und einen neuen unveraenderlichen Versions-Tag
  erstellen; vorhandene Tags niemals verschieben.
- Einen GitHub Draft Release mit Aenderungen, Grenzen und Pruefnachweisen
  erstellen oder aktualisieren. Veroeffentlichung aus dem Entwurfsstatus nur
  nach entsprechendem Auftrag; ein Image kann per Workflow-Dispatch separat
  fuer einen vorhandenen Tag gebaut und geprueft werden.
- Vor Containerwechsel Datenvolume, Einstellungen und Secrets sichern,
  Rollback ermoeglichen und nachher Daten-/Konfigurationserhalt sowie den
  bestehenden produktiven Zugriff pruefen. Keine neue Vorschau-URL als
  Ersatz fuer ein ausdruecklich beauftragtes produktives Update verwenden.

Eine Aenderung ist erst fertig, wenn:

- Tests oder nachvollziehbare Smoke Checks ausgefuehrt wurden.
- Datenmodell und API-Vertrag bei Schnittstellen-Aenderungen aktualisiert sind.
- Review-Gates erklaeren, warum ein Export erlaubt oder blockiert ist.
- Abweichungen zu V1 dokumentiert sind, falls V1-Vergleich betroffen ist.

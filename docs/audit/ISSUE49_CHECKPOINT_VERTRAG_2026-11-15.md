# Issue 49: Preisauftrag und dauerhafter Speicherbeleg

Integrationsbasis `7397c63fd32750b42003189f12937a3252656223` (Draft #60).
Entwicklungsauftrag, kein produktiver Datenzugriff oder Deployment. Der Vertrag
wird von Koordinator und getrennten Domain-/UI-/Testbearbeitern vor Edits an
zentralen Dateien verwendet; Unklarheiten vor Implementierung melden.

## Fachliche Wirkung

- Vorhandene Preis-, FX-, Identitaets- und Reviewregeln bleiben unveraendert.
- Preisabruf, atomare Speicherung und Pipeline sind getrennte Phasen.
- Preiszeilen und ihr Checkpoint werden gemeinsam committed oder gemeinsam
  zurueckgerollt. Ein verlorenes Commit-Acknowledgement bleibt im Aufruf unklar;
  lesender Status kann den tatsaechlich dauerhaft gespeicherten Beleg zeigen.
- Die ganze Pipeline wird NICHT als atomar behauptet. Ihr Start wird vor dem
  Aufruf festgeschrieben. Abbruch danach bedeutet laufend/unterbrochen oder
  unbekannt, niemals unbestaetigt abgeschlossen.
- Keine automatische Providerwiederholung, kein Keywechsel und keine
  automatische steuerliche Korrektur. Eine neue Kennung ist ein bewusst neuer
  Auftrag, nicht die Wiederholung desselben Auftrags. Gleichzeitige Applys mit
  gleicher Kennung werden durch die persistente Reservierung abgefangen.
- Der vorhandene explizite Pipeline-Neuberechnungsweg bleibt die passende
  Benutzeraktion, wenn eine aktuelle Neuberechnung ohne neuen Providerabruf
  gewollt ist. Ein neuer Lauf bestaetigt nicht rueckwirkend den alten Auftrag.

## Persistenzvertrag

Vorhandene Tabelle `current_price_backfill_requests` weiterverwenden, keine
zweite Preis- oder Journal-Datenbank. Rueckwaertskompatible additive Spalten:
`operation_kind` (Default `current_portfolio`) und `checkpoint_json` (nullable).
Vorhandene Reservierungen und Ergebnisbytes werden nicht ersetzt. Der alte
Tabellenname bleibt als technische Kompatibilitaet, historische Auftraege
erhalten einen getrennten Hashnamensraum.

Checkpointmodell `PriceBackfillCheckpoint`:

| Feld | Vertrag |
| --- | --- |
| format_version | Literal 1 |
| operation_kind | `current_portfolio` oder `historical` |
| stored_at | UTC-Zeit des Speicherbelegs |
| stored_price_ids | eindeutige UUIDs der in dieser Transaktion gespeicherten Preise; bestehende Budgets max. 250 current, max. 1000 historical |
| pipeline_status | `not_started`, `running_or_interrupted`, `completed`, `failed` |

IDs belegen die damalige Speicherung, nicht ihren heutigen Fortbestand,
Preisgueltigkeit oder fachliche Freigabe. Checkpoint-SHA256 bezieht sich auf die
exakten gespeicherten UTF-8-JSON-Bytes; Formatversion und Methode nicht vermischen.

Store-Schnittstellen (Koordinator implementiert):

```python
reserve_current_price_backfill(request_hash: str) -> bool  # bestehend
reserve_historical_price_backfill(request_hash: str) -> bool
prepare_price_backfill(request_hash: str, operation_kind: str,
                       payloads: list[PricePointCreate]) -> list[PricePoint]
mark_price_backfill_pipeline_started(request_hash: str, operation_kind: str) -> None
record_current_price_backfill(request_hash: str, result_json: str) -> None  # bestehend
record_historical_price_backfill(request_hash: str, result_json: str) -> None
price_backfill_operation_record(request_hash: str, operation_kind: str) -> tuple[str | None, str | None] | None
current_price_backfill_record(request_hash: str) -> tuple[str | None] | None  # bestehende Legacy-Sicht
```

Prepare verlangt eine passende offene Reservierung ohne Ergebnis/Checkpoint.
Leere Preislisten erhalten ebenfalls einen Beleg; keine Pipeline ohne Preise.
Mark-start verlangt `not_started` und offene Reservierung. Record-final bindet
gespeicherte IDs und `pipeline_status` an den Checkpoint. Legacy-Reservierungen
ohne Checkpoint bleiben lesbar, werden nicht nachtraeglich als bewiesen markiert.
Alle Uebergaenge pruefen den Operationstyp und verwenden transaktionale CAS-
Bedingungen. Kein blindes Ueberschreiben, kein automatisches Entfernen alter IDs.

## API-/Domainvertrag

- Current-Request-ID und Hash unveraendert, vorhandene Dry-Runs reservieren nicht.
- Historical `ExternalPriceBackfillRequest` erhaelt optionale UUID `request_id`.
  Bei Apply mit Kennung Hash von `{"operation_kind":"historical","request_id":id}`;
  ohne Kennung kanonischer getrennter Fingerprint aus den wirksamen Parametern.
- Beide Domainpfade reservieren vor externem Abruf, speichern mit Prepare,
  markieren Pipelinebeginn, rufen die vorhandene Pipeline auf und dokumentieren
  deren bestaetigtes Ergebnis. Captured Fehler bleiben sanitisiert; Abbruch und
  Deadline werden nicht verschluckt. Keine neue Netzwerkabhaengigkeit.
- Bestehendes finales Current-Result und Warnungen bleiben erhalten. Historisches
  Result erhaelt ebenfalls `result_journal_status` (`not_started/recorded/unknown`).
- Statusmodelle fuer beide Typen: `status` = `recorded`, `checkpointed`,
  `unknown_or_running`, `not_found`; optional typisiertes `result`, optional
  `checkpoint`, optional `checkpoint_sha256`, deutsche `explanation`.
- Current-Statuspfad bleibt unveraendert. Zusaetzlich rein lesender POST
  `/api/v1/prices/backfill/external/status` mit UUID im Body, nicht in der URL.
  Keine Provider-/Pipelineaufrufe beim Lesen, keine internen Pfade/Secrets ausgeben.
- Replay/Reservierungs-/Speicher-/Statusfehler werden getrennt und ohne
  Originalexceptions in den API-Antworten dargestellt. Bestehende strengere
  Caller-Guards bleiben bestehen; Rueckgabe allein ist kein Pipeline-Erfolg.

## Benutzerablauf und Tests

Aktuelle/historische Kennungen getrennt und begrenzt lokal merken. Anzeigen
unterscheiden finale historische Antwort, belegte Preisspeicherung ohne sichere
Pipelinefertigstellung und nur Reservierung. Kein automatischer Wiederholknopf.
Neue IDs nur bei ausdruecklichem Apply, nie beim Lesen/Reload/Filterwechsel.

Pflichtproben mit eigener synthetischer DuckDB und Fake-Providern:
Speichern+Checkpoint atomar, Fehler vor/nach Insert/Commit-Ack, Prozessabbruch
nach Commit/vor bzw. waehrend Pipeline, Finaljournalfehler, altes Journal ohne
Checkpoint, zwei gleiche Kennungen parallel, Neustart/Restoreerhalt,
Current/Historical-Namensraeume, Dry-Run, keine Provider beim Statuslesen,
keine Secrets in Antwort/Logs/URL, keine neue finale Jahresfreigabe.
Unabhaengige neue Gegenproben bleiben unveraendert in CI, vorhandene
Originalreferenzen weiterhin Pflicht. Produktion bleibt unveraendert.

# Issue 44: FX-Grenzen der Backfills

## Geprueft

- `ExternalPriceBackfillService.run` und `AsOfPriceGateService.backfill` lehnen
  V1-FX-Daten ohne originales `source_rate_date`, nichtleeres Quelllabel oder
  gueltige Sieben-Tage-Referenz ab. Der Quelltag muss vor dem Bewertungstag
  liegen; gleichdatierte Referenzen ohne Veroeffentlichungszeit werden nicht
  verwendet. Die V1-Datei wird lesend benutzt.
- `run_current_portfolio` verlangt fuer Frankfurter-USD/EUR die USD-Basis,
  einen Einheitsbetrag und einen frueheren Quelltag innerhalb von sieben Tagen.
  Direkte EUR-Kurse bleiben unabhaengig davon nutzbar; ein verworfener FX-Weg
  wird auch bei erfolgreichem EUR-Fallback als Warnung gemeldet.
- Diese Pruefungen sind technische Ausschlusskriterien, keine nachtraegliche
  Quellen- oder steuerliche Freigabe. Ein Quellstring und ein Datum ersetzen
  weder Originalantwort, Request-Metadaten noch einen hashgebundenen Snapshot.
- Ein leerer Stichtagsplan benoetigt weder FX-Datei noch Provider-Client.
  Er schreibt ein eigenes Laufartefakt, ersetzt aber nicht `latest`. Historische,
  Stichtags- und aktuelle Backfill-Werte ausserhalb des positiven
  `DECIMAL(38,18)`-Bereichs werden als `price_out_of_range` abgewiesen, nicht
  gespeichert. Fuer die begrenzte Dezimalrechnung sind hoechstens 256
  signifikante Eingabeziffern zulaessig.
- Auch eine technisch akzeptierte FX-Tagesreferenz wird als ungeprueft
  ausgewiesen. Die API-Warnung nennt den fehlenden Originalbeleg und die
  nicht nachgewiesene Veroeffentlichungszeit; dies ist keine Freigabe.
- Bei fehlgeschlagenen Teiljobs meldet die API eine Warnung auch dann, wenn
  andere Preise bereits gespeichert wurden. Eine gueltige Ersatzquelle nach
  einem nicht darstellbaren Kandidaten bleibt als solche gekennzeichnet.
  Der aktuelle Backfill stellt bei mehreren Ursachen `additional_reasons`
  zusaetzlich zum bisherigen `reason` bereit; Clients muessen beide beachten.
  Im Stichtagsdialog bleibt die Warnung bei einem Fehler der nachfolgenden
  Ansichtsaktualisierung sichtbar; der Refresh ist kein Rollback des Imports.

## Weiterhin offen

- Der alte historische Preisabruf in `external_price_backfill.py` prueft bei
  DefiLlama nicht den Provider-Zeitstempel und schreibt im historischen und
  Stichtags-Backfill einen Mitternachtsanker. Asset-Identitaet und
  Originalantwort sind dort nicht beweisgebunden. Die neue FX-Pruefung loest
  diese Preis-/Zeit- und Identitaetsfragen nicht.
- Die V1-FX-Referenz enthaelt nur einen Quelltag, keine gepruefte Uhrzeit oder
  Veroeffentlichungszeit. Auch ein frueherer Quelltag beweist nicht, wann die
  Referenz tatsaechlich verfuegbar war. Eine vollstaendige zeitpunktgenaue
  Absicherung und Freigabe bleiben offen.
- Der aktuelle Portfolio-Backfill setzt die Beobachtungszeit als Preiszeit;
  Provider-Kurszeiten und Originalantworten sind nicht vollstaendig gebunden.
  Er schreibt in den gemeinsamen Preis-Ledger und startet die Pipeline. Die
  Decimal-Grenze gilt nicht fuer sonstige Preisimporte.
- `cache_fx_reference` und `_usd_eur_reference` behalten aus Kompatibilitaet
  das alte Verhalten fuer andere Aufrufer. `import_jup_solscan_balance_change_v2.py`,
  `import_helium_solana_reward_evidence_v2.py` und der Blockpit-Preflight
  verwenden diesen nicht verschaerften Hilfspfad. Die beiden Importskripte
  koennen bei entsprechender Ausfuehrung Daten schreiben; keine dieser
  Anwendungen ist durch den neuen Backfill-Guard freigegeben oder abgesichert.
- `domain/jup_perps.py` liest den letzten V1-USD/EUR-Eintrag am oder vor dem
  Stichtag ohne die hier eingesetzte Sieben-Tage-/Quelldatumspruefung.
  `domain/portfolio.py` liest beim Solscan-Livepfad ein ECB-XML ohne Auswertung
  des Datums. Beide Pfade sind gesondert zu beurteilen.
- Die API-Warnung entsteht aus der zurueckgegebenen Jobliste. Historische
  Jobs werden auf 200 Zeilen begrenzt; mindestens ein FX-Fehler wird darin
  erhalten. Aktuelle Laeufe waehlen hoechstens 250 Assets aus. Die Zaehler
  ersetzen keine vollstaendige zeilenweise Diagnose.
- Die beiden Legacy-Repair-CLI-Einstiege bleiben in diesem Stand fuer
  `--execute` gesperrt; ihre einzeln aufgerufenen Hilfsfunktionen und andere
  Programme sind davon nicht pauschal erfasst.
- Der historische Backfill kann Preise speichern, bevor eine anschliessende
  Pipeline-Ausnahme gemeldet wird. Ein Fehler oder Timeout beweist keinen
  Rollback; Zustand und moegliche Duplikate vor erneutem Start pruefen. Eine
  transaktionale bzw. idempotente Loesung fehlt weiterhin.

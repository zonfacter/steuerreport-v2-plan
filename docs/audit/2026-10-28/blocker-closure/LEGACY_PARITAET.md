# Legacy-Zuordnung Und Semantische Datenparitaet

Basis `ce51a9d42963e25cb7b96dda19efce0703c55b26`, eigener Branch
`audit/blocker-parity-20261028`. Vertrag bestaetigt; keine Kinderagenten,
Produktformeln, Methodenaktivierungen, Produktionseingriffe oder Netzwerk-APIs.

## Vorlaeufiger Vorhervergleich

Die unten genannten Vorher-Snapshots sind fertig. Der erneute Vollscan fuer
die Nachher-Stabilitaetspruefung laeuft noch. Deshalb bis zum Abschluss **kein
Nachweis einer unveraenderten Quelle ueber das gesamte Auditfenster**.
`parity-preliminary.json` enthaelt nur Aggregate und private-keyed HMACs,
keine Datensatzinhalte, Kontoidentifikatoren oder Geldbetraege.

| Dimension | Gesicherter Befund / Grenze |
| --- | --- |
| V1, Port8000 | PID158, explizites `STEUERREPORT_DB_PATH`, offener FD13 und gleicher Device/Inode wie die benannte SQLite-Datei: aktive Datei eindeutig zugeordnet. |
| V2-Legacy, Port8010 | PID3145184, systemd `steuerreport-v2-api.service`, cwd und PYTHONPATH zeigen ins Plan-Repo. Kein DB-/Root-Override. Heutiges `app=create_app()` -> `store or DuckDbStore()` -> `PROJECT_ROOT/data/steuerreport_v2.duckdb` ergibt die Kandidatendatei. |
| V2-Laufzeitgrenze | Keine DB-FDs oder DB-mmaps in den punktuellen und passiven Stichproben. Eine30s-Probe hatte1480Samples ohne Treffer; die weitere Probe ist privat protokolliert. Quellmtimes liegen vor Prozessstart27.09.2026; dennoch kein Beweis, welche Python-Module/Globals tatsaechlich geladen sind. Kandidat bleibt **unbestaetigt**. |
| Kein DB-weckendes GET | Health und Admin-Database rufen `connect()` auf; dieser Pfad kann `ensure_schema()` ausloesen. Kein solcher Aufruf. Reines OpenAPI wuerde keine aktive DB-Datei nachweisen und wurde nicht erneut abgefragt. Kein ptrace/Prozessstop/Memorydump. |
| Docker18010 | Laufenden rc32-Container via lokaler Docker-Metadaten und ausschliesslich selektierter DB-Env geprueft. `/state`-Mount und DB-Pfad unter `/proc/PID/root` haben dieselbe Dateiidentitaet. Abfrage nur direkte DuckDB `read_only=True`, keine Store-/API-Initialisierung. |
| Rohdaten | V1 hat55170 Original-row-Projektionen gegen4088Docker-Objekte,0identische vollstaendige JSON-Inhalte. Auch gespeicherte JSON-Payloads unterscheiden sich. Die V2-Kandidatendatei hat49483Objekte gegen4088, ebenfalls0vollgleiche JSON-Inhalte. Kein blosses Countargument: komplette HMAC-Multimengen verglichen. |
| Quellbindung | V1 `confirm_import()` hasht normalisierte `source_name`+`rows`; V2-`file_hash` bezeichnet Dateiinhalt. Kein Gleichsetzen dieser Hashes, keine vermutete Zeilennummernverschiebung oder Symbol-/Quellenalias-Heilung. |
| Events | V1 normalisierte Event-Payloads in `raw_events` und Produktpositionen, V2 separate Canonicals. Vollstaendige Tabellenfingerprints vorhanden, aber kein verlustloser Cross-Schema-Normalisierungsvertrag; keine Eventparitaet behauptet. |
| Reviews | V1 Settings/Transfermatches vs V2 explizite Reviewtabellen und Settings sind verschiedene Modelle. Inhalte voll gehasht statt nur gezaehlt; keine unbelegte Gleichsetzung von Freigaben. |
| Preise | V1 FX-Paare samt Referenztag vs V2 EUR-PriceLedger, Zeit-/Quellen-/Konfidenzbindung erhalten. Keine USD-Paritaet/FX1 und keine Umrechnung fuer einen vermeintlichen Match. |
| Lots | Keine persistierte V1-Einzel-Lot-Tabelle. `inventory_end` ist laut Processor eine Mengenaggregation, kein Beleg individueller Kosten/Erwerbsdaten. Keine Lots aus Raw rekonstruiert oder steuerlich neu berechnet. |
| Tax-Lines | Enge Vergleichsprojektion bewahrt Menge, EUR-Kosten/Erloes/Gewinn, Zeitpunkte und urspruengliche Erwerbs-/Verkaufsereignisrefs. V1 umfasst783772Zeilen ueber **alle historischen Jobs**, Docker0. Dies ist keine gleichjaehrige oder gleichmethodische Ergebnisabweichung. Strikte V1-Tabellenhashes behalten Job-ID/Domain/Status vollstaendig. |
| Methoden | Regeln, Jobs, Integritaetsstaende und Settings komplett einbezogen; V2 Settings/TaxRuns separat. Keine Ableitung gleicher Methode aus einem Schema-/Versionslabel. |
| Archive | Datenbank-Archiv-/Integritaetsinhalte voll gehasht; bekannte V2-Archiv-/Jahrescache-ZIPs werden zusaetzlich byteinhaltlich geprueft. V1 JSON-Snapshots und V2 ZIP-Ketten sind nicht dasselbe Modell; unbekannte V1-Dateiarchive nicht pauschal als leer behandelt. |

**Ergebnis:** Unterschiedliche Rechenbasis ist belegt, Engineparitaet nicht.
Die Count-Luecke wurde fuer die gelesenen Inhalte durch komplette
Datensatz-Multimengen/Fremdschluesselbindung geschlossen. Die Laufzeitzuordnung
8010 und eine vollstaendige cross-schema-/methodengleiche Engineabnahme bleiben
harte, benannte Grenzen. Das ist kein Beweis fuer Datenverlust oder einen
Enginefehler. Ein spaeterer Enginevergleich benoetigt denselben gebundenen
Input-/Methodenstand in isolierten DBs und einen ausdruecklichen Vergleichsvertrag.

## Hash- Und Identitaetsvertrag

Strikte Fingerprints behalten jede DB-Spalte, alle IDs und Duplikate. Semantische
Fingerprints parsen JSON-Objektschluessel ohne Listenreihenfolgen zu sortieren.
Decimal wird ohne Float-Rundung oder28stelligen Normalisierungskontext behandelt;
naive V2-Timestamps gelten wie im Speichervertrag als UTC.

Nur V2 `price_ledger` ignoriert `price_id`/technisches `created_at`. V2-Lots
ignorieren neu erzeugte `lot_id`/`created_at`; Tax-Lines ignorieren
`tax_line_id`/`created_at`. Die Tax-Line-`lot_id` wird durch den gebundenen
Lotinhalt ersetzt, nicht geloescht. `origin_lot_id`, Event-/Raw-IDs,
Source-Refs, Pool und Methode bleiben erhalten. Unaufloesbare Lotrefs bleiben
explizit als solche identifizierbar. Preiszeitpunkt/Quelle, Reviewzeitpunkte,
Archiv-IDs und Revisionsbeziehungen werden nicht weg-normalisiert.

Die gemeinsame Tax-Projektion ist ausdruecklich enger als die vollstaendige
Tabellensemantik; sie beweist weder gleiche Jobauswahl noch steuerlichen Status
oder dieselbe Methode. Die vollstaendigen strikten Hashes bewahren diese Felder.

Private Evidence: `/root/.local/share/steuerreport/migration-audit-20261028/blocker-parity/run-01`,
Verzeichnis0700, Dateien0600. HMAC-Schluessel ausschliesslich dort, niemals im
Repo, Argumentlisten, Public-JSON oder Log. Keine DB-/WAL-Dateikopie;
SQLite `mode=ro`/`query_only`, kein `immutable=1` mit ignoriertem WAL;
DuckDB `read_only=True`, je eine Lesetransaktion fuer alle Tabellen.

## Nutzerquellen Und Originalrepros

Erst in dieser Welle erstmals gelesen: Nutzer-Dockerbericht, BMF-Bericht und
V1-/V2-Repro-Manifeste/Programme/Resultate. Kein Browserprofil und keine
Nutzerdokumente geaendert. Die Quelle ist nicht rueckwirkend ein frueherer
Nachweis. Keine neue Rechtsrecherche oder BMF-Zertifizierung behauptet.

- Dockerbericht SHA256 `d2c3a08f7b2a8577410b9ff3064cdf64ea0a4b4c40c92927d6861f3d8b4d9fc8`.
- BMF-Bericht SHA256 `41f23ab93085d3a48c49d8b27b59067a606d9ac54535264d95d8089e5c18a4f1`.
- `original-repro-results.json`: sanitisiertes originales JSON-stdout beider
  einmaliger Ausfuehrungen in eigenen Offline-Kopien, Exit0. Ausschliesslich
  synthetische Faelle, keine App-/Produktions-Engineabnahme. V1sieben Repros,
  V2vier enge Lookup-/Methodenrumpf-Repros. Keine zweite Ausfuehrung veranlasst.
- Dieselbe Datei enthaelt alle tatsaechlichen Input-SHA256 und
  Git-Blob-Abgleiche. V2 Snapshotchecks stimmen; partielle TXT-Ausschnitte
  werden nicht als bytegleich zum vollstaendigen Upstreamblob ausgewiesen.
- **V1 Herkunft offen:** Alle7Dateien weichen von `manifest.blob_sha` ab.
  `processor.py` deklariert `342480f761a2349d7c5a4472e119780ecb92c789`,
  tatsaechlicher `git hash-object --no-filters` ist
  `52bf36f7f6f179d44c80bb9059f43471bc5f5217`, SHA256
  `075b74ecd2b4ebb54f6e2eae43a1d2a2534ab1d826df8429dab03c54a1818000`.
  Keine CRLF-/BOM-Erklaerung gefunden. Keine Originalkorrektur oder Behauptung,
  diese Bytes seien der genannte V1-Upstreamcommit. Unveraendertheit waehrend
  unserer Kopie/Ausfuehrung ist unabhaengig davon bestaetigt.

## Eigene Helfertests

```sh
python3 -B -m unittest discover -s docs/audit/2026-10-28/blocker-closure \
  -p test_parity_probe.py -v
```

11Tests bestanden: gleiches Count/anderer Inhalt, Multimengen/Duplikate,
Decimal/UTC, unverzichtbare Event-/Originidentitaet, aufgeloeste Lot-FKs,
Preiszeit/Quelle, echte RO-Schreibverweigerung fuer SQLite/DuckDB, fehlende DB
wird nicht angelegt, Archivbyteaenderung und keine Enginefreigabe aus
identischen gespeicherten Inputs. Eigene synthetische Testroot unter `/tmp`,
keine Appimporte und keine externen Aufrufe.

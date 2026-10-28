# Nachtrag: Lesende Lot-Herkunft

28.10.2026. Basis: `87b231b5a40716f41468e56a68048f3abd79f4cc`.
Gepruefter Runtime-Fix: `4026e77efeca6c9a6990e969c64a45abdef9ab92`.
Integrierter Code-/Teststand: `eec6697ff325faa853d118794b9c7c90cb1f05f0`.
Branch: `audit/lot-origin-20261028`. Entwicklungsstand, kein Release.
Kein Push, neues Image, Containerwechsel, produktiver Import, Methodenwechsel,
Preisabruf oder neue fachliche Freigabe.

## Ergebnis Und Beweisgrenze

Implementiert und mit synthetischen Referenzen geprueft: Eine vorhandene
Lot-ID-Kette wird bis zum tatsaechlichen Wurzelereignis verfolgt. Das betrifft
gespeicherte Herkunftsreviews, Global-/Wallet-Vorschauen, BMF-Ereignisbelege,
das globale Review-Gate und den Herkunftsdetaildialog im Steuerjahr.
Die gespeicherten Berechnungsbetraege werden dabei nicht geaendert.

Eine vollstaendige ID-Kette beweist weder die Echtheit einer Quelle noch
eine angemessene positive Kostenbasis, Eigentum oder eine private/betriebliche
Zuordnung. Es wird keine neue steuerliche Regel aktiviert. Ungeklaerte
Sachverhalte bleiben offen; es gibt keine fachliche Jahresabnahme.

Die fruehere Matrix und Originalbelege unter `../blocker-closure/` bleiben
unveraendert. Dieser Nachtrag ersetzt insbesondere keine Legacy-Engineparitaet
und keinen Wiederherstellungsnachweis fuer ein neues Image.

## Behobene Befunde

| Befund | Aenderung | Nachweis |
| --- | --- | --- |
| Zwischenereignis verdeckt Reward-Ursprung | Reiner `LotOriginIndex`, `origin_lot_id` bis zur Wurzel; unmittelbar gespeicherte Source-ID bleibt unveraendert | Referenz 100 HNT/Basis90 -> Eigenuebertrag -> 1 NEW -> Verkauf0.4 fuer60; Basis36, Gewinn24, Restbasis54 |
| Herkunft verschwindet nach Symbolwechsel aus HNT-Filter | Filter trifft veraeussertes oder bestaetigtes Ursprungsasset | Gespeicherter Review und echte kombinierte Vorschau |
| Verwaister Lot fehlt durch INNER JOIN in Pruefung | Review-Gate liest alle gespeicherten Zeilen ohne verdeckenden Join | Fehlender aktueller Lot, fehlender Elternlot und Zyklus blockieren |
| Null-Euro-Delta entfernt Herkunftsproblem | Herkunftspflichtige Zeilen bleiben auch bei Delta0 in der Belegpruefung | Reine Lineage-Probe mit fertigen Roh-/Preisbelegen |
| Zeile/Gruppe blockiert, Gesamtbericht nur review | Gesamtstatus beruecksichtigt blockierte Herkunftszeilen vor dem sichtbaren Limit | Vorher46/47, nachher47/47; keine Lockerung der Erwartung |
| Blockierter Zwischenbeleg fehlt im Zeilenstatus | Alle explizit verknuepften Zwischenereignisse fliessen in Zaehler, Digest und Status ein; Root-Klassifikation bleibt getrennt | Zusaetzliche unabhaengige Zwischenbeleg-Regression |
| Vorjahres-Root fehlt bei Zielasset ausserhalb der Prioritaetsgruppen | Full-Ledger erfasst gespeicherte Lotketten und Staging-Herkunft unabhaengig dieser Gruppen | Zusaetzliche unabhaengige Vorjahres-Regression |
| Historischer Bericht wirkt mit alter Policy aktuell | Additive Policy-ID; alte JSON-Dateien bleiben lesbar, aber ausdruecklich veraltet | Alter Report ohne Marker unveraendert, Inputstatus nicht aktuell |
| Herkunft schwer einsehbar | Zeilenaktion mit bestehendem Detailpanel; Kosten/Erloes/Gewinn weiterhin sichtbar; Gruppensummen als solche erkennbar | Browser390/768/1280/1440, Fokus-Rueckgabe und kein Seitenoverflow |

## Dateien Und Vertrag

- `domain/lot_origin.py`: reine Aufloesung, maximal64Lot-IDs; fehlende,
  doppelte, zyklische und widerspruechliche Referenzen ergeben `unresolved`.
- `domain/business_inventory.py`: gemeinsame Herkunft im gespeicherten Review.
- `domain/bmf_fifo_staging.py`, `bmf_event_evidence.py`: derselbe Ursprung,
  separate direkte IDs/Fehlercodes, Null-Euro- und Gesamtstatuspruefung.
- `domain/review.py`: globale Sperre fuer unaufloesbare gespeicherte Herkunft.
- Additive Contracts und OpenAPI; `origin_trace_policy=linked_lot_origin_v1`.
  Alter JSON-Default bleibt `legacy_direct_origin_v1` und ist kein neuer Beleg.
- `lineage_event_ids` bindet alle bekannten Zwischenereignisse; Wurzelereignisse
  bleiben separat in `acquisition_source_event_ids`. Ein blockiertes
  Zwischenereignis kann dadurch nicht hinter einem fertigen Root verschwinden.
- `frontend/src/workspace/LotOriginDetails.tsx`, `main.tsx`, `workspace.css`:
  lesendes Panel mit unveraenderten Betraegen und nachvollziehbaren IDs.
- `tests/acceptance/test_lot_origin_reference.py`:47 unabhaengige Proben;
  plus2unabhaengige Zwischenbeleg-/Vorjahresproben in
  `test_lot_origin_evidence_reference.py`. Vorhandener Pflicht-CI-Job fuehrt
  alle49neuen Proben zusammen mit den38Vorproben aus.
  Der Browserablauf ist ebenfalls im vorhandenen CI verankert.

Keine Aenderung an `tax.py`, `tax_wallet_fifo.py`, `token_conversion.py`,
DB-Schema, aktiven Methoden, Versions-/Compose-Dateien oder produktiven Daten.
Vertrag: `../LOT_HERKUNFT_VERTRAG.md`. Unabhaengige Herleitung und erklaerte
Testadapterkorrekturen: `../LOT_HERKUNFT_REFERENCE_HANDOFF.md`.

## Tatsaechliche Pruefungen

Vollstaendige Original-JUnit-Dateien, Vorherfehler, Nachherlaeufe, Quellhashes,
Screenshots und Diff stehen in `evidence/manifest.json`. Die Sammlung kopiert
Originale bytegleich und erzeugt keine nachtraeglichen Erfolgsergebnisse.

| Pruefung | Ergebnis |
| --- | --- |
| Vollstaendige Unit-Suite, vier Worker | 2629 bestanden,4 bereits vorhandene private Belegskips;788.83s |
| Urspruengliche unveraenderte Referenzen | 52 bestanden |
| Pflicht-Referenzsuite `tests/acceptance` | 87 bestanden, keine Skips |
| Neue unabhaengige Herkunftsproben separat | 47 bestanden; ferner47 mit beliebigem Basispfad und47 mit Default-Factory |
| Herkunft/BMF-Consumer nach letztem Runtime-Fix | 63 bestanden |
| Fokussierte Herkunft/BMF/Business-Vorpruefung | 61 bestanden am frueheren Integrationsstand |
| Review/Export/BMF/History-Vorpruefung | 64 bestanden,3 bereits vorhandene lokale Datenskips; vollstaendig auch im finalen Unit-Lauf enthalten |
| Browser mit echtem Business-API, sonst synthetischen Nebenpaketen | Vier Breiten bestanden; DB-Fingerprint gleich, keine Browserwrites/externe Requests |
| Bestehender Quellen-/Review-/Preisstand-Browserablauf | F1/F2/F3 bestanden; eigener isolierter Finanzierungsimport, keine Review-Entscheidungen und keine Produktionsdaten |
| Frontendbuild | Bestanden; bestehende Warnung Bundle groesser500kB |
| Ruff, Private-Data-Guard, OpenAPI-/Endpoint-Drift | Bestanden;0private Defaultverstoesse |
| Originalreferenz-Integritaet und URL-/Decimalchecks | Bestanden |
| Gitleaks im exportierten getrackten Laufzeit-/Konfigurationsquellcode |3exakt bereits einzeln freigegebene Nicht-Secrets;0ungepruefte Findings; kein Gesamthistorien-/Dokumentenscan behauptet |
| Zusaetzlicher Gitleaks-Scan der neuen Auditbelege |26SHA-Metadaten-Findings exakt gegen Belegbytes, gebundenen Git-Quellstand oder Build nachgerechnet;0ungeprueft; keine pauschale Scanner-Ausnahme |

Ein erster Browseradapter hatte unvollstaendige JSON-Fixtures; ein erster
CI-Adapter erzwang den Pfad des Agenten. Beide Testfehler wurden korrigiert,
fachliche Erwartungen nicht gelockert. Fehlversuche sind keine Produktfreigabe.
Ein erster Vollsuitelauf wurde nach1608bestandenen Tests mit Exit2 bewusst
abgebrochen, um die spaet gefundenen P1-Belegluecken vor dem endgueltigen Lauf
zu schliessen. Seine XML bleibt erhalten;1608wird nicht als Vollabnahme gezaehlt.
Die beiden spaet gefundenen Belegluecken sind mit identischen Proben vor/nach
gesondert belegt:2Fehler am Stand27703bf,2bestanden nach4026e77. Das sind
gezielte Consumer-/DB-Graphproben, kein zusaetzlicher vollstaendiger Import-Exportlauf.
Integritaet erneut pruefen: `python docs/audit/2026-10-28/lot-origin/verify_evidence.py`.
Die34Belegdateien wurden gehasht; dies bestaetigt Bytes, keine fachliche Wahrheit.
Die gesonderte exakte Hashbewertung steht in `artifact-secret-review.json`;
`review_artifact_scan.py` nimmt keine Scanner-Regel oder Quellkategorie aus.
Originale Fehlermeldungs-XML und der exportierte Patch enthalten Leerzeichen
aus dem jeweiligen Ausgabeformat. Diese werden nicht nachtraeglich formatiert.
`git diff --check` fuer Quellcode/Handdokumentation ist getrennt von diesen
unveraenderten Rohbelegen auszufuehren; der ungefilterte Check meldet sie.

## Reproduktion

Mit den gesperrten Projektabhaengigkeiten und optionalen Browser-/xdist-Tools:

```sh
STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 PYTHONPATH=src python -m pytest tests/unit -n 4 --dist loadfile -q --basetemp=/tmp/sr-lot-unit --junitxml=unit.xml
PYTHONPATH=src python -m pytest docs/audit/2026-10-28/acceptance_tests.py -q --junitxml=original.xml
STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 PYTHONPATH=src python -m pytest tests/acceptance -q --basetemp=/tmp/sr-lot-reference --junitxml=reference.xml
python scripts/check_reference_baseline_v2.py
python scripts/check_private_data_v2.py
python scripts/export_openapi_v2.py --check
python scripts/generate_api_endpoint_reference_v2.py --check
ruff check src tests scripts
npm --prefix frontend run build
node scripts/check_workspace_state_v2.cjs
TZ=Europe/Berlin node scripts/check_workspace_state_v2.cjs
PYTHONPATH=src python scripts/check_lot_origin_browser_v2.py --output /tmp/sr-lot-browser
```

Der lokale Lauf verwendete Python3.11 und bereits vorhandene Tools ueber
`PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025`;
der Browser zusaetzlich `/tmp/steuerreport-browser-tools` und Chromium1187.
Neue Browserdaten und Test-Datenbanken waren ausschliesslich synthetisch.
Die CI-Konfiguration ist committed; ein neuer GitHub-CI-Lauf wurde nicht behauptet.
Die vier Unit-Skips betreffen dreimal benoetigte private Solscan-/Blockpit-/RPC-
Belege und einmal den explizit freizugebenden privaten Usertransfer-Baum.
Kein neuer Skip und kein xfail wurde fuer diese Umsetzung eingefuehrt.
Die vier Python-Warnungen betreffen das vorhandene veraltete `load_module()`.

## Produktion, Speicher Und Offenes

Die Docker-Metadaten vor/nach enthalten dieselbe Container-ID, Image-ID,
Startzeit und `/state`-Volume. Es wurden keine produktiven API-/DB-Aufrufe
ausgefuehrt. Das ist ein Nachweis unveraenderten Deployments, kein laufender
Vollhash aller produktiven Daten oder eine neue Datenparitaetspruefung.
Der Codegraph wurde als reine Entwicklungshilfe aktualisiert (531Dateien,
keine Parserfehler); er ist kein fachlicher Beleg.

Kein neues Dockerimage, kein neues Checkout und keine produktive DB-Kopie.
Erfolgreiche synthetische Test-DBs werden entfernt; Original-XML/JSON,
Screenshots und erzeugte Belegarchive bleiben erhalten. Freier Speicher wird
im Manifest erfasst; keine Loeschung von Rollbackimages, Volumes oder Originalen.
Nach allen Laeufen wurden257geschlossene synthetische DuckDB-/Prepared-Dateien
mit1708011520belegten Bytes entfernt (rund1.59GiB). Header, Dateityp,
Symlink-/Hardlinkstatus, Pfad und offene Handles wurden geprueft. Originale
XML/JSON/CSV/PDF/ZIP und Quellcodes blieben erhalten. Root-Dateisystem danach
rund23GiB frei. Originaler Bereinigungsnachweis: `evidence/storage-cleanup.json`.
Die unveraenderte52erOriginalprobe verwendet ihren vorhandenen festen Root
`/tmp/steuerreport-migration-20261028-acceptance-tests`; ihr Code wird nicht
fuer einen anderen Tmp-Pfad veraendert. Auch dort werden nach Prozessende
nur erzeugte synthetische DuckDB-Dateien, nicht die Belegpakete, entfernt.

Offen bleiben: eindeutige aktive Legacy-V2-DB-Zuordnung8010, ein methoden- und
inputgleicher Alt-/Neu-Enginevergleich, reale Belegvollstaendigkeit und
Kostenbasisherkunft, menschliche Sphaerenentscheidungen sowie ein neuer
Image-/Restore-/Rollbacknachweis. Generische Bridges, LPs und unbelegte
Wirtschaftsbeziehungen werden durch die Herkunftshilfe nicht freigegeben.

Die angeforderten Nutzerberichte und beide Repro-Ordner liegen hier unter
`docs/blockpit-analysis/` (ignorierte lokale Quellen); `/tmp/blockpit-analysis`
existiert aktuell nicht. Nur die benannten Berichte und Reprodateien wurden
beruecksichtigt; kein Browserprofil wurde in einen Beleg oder Commit aufgenommen.

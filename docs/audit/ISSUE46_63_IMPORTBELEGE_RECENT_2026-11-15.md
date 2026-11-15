# Konkrete Importbelege und ehrliche Vorschau-Liste

Unveroeffentlichte Entwicklung auf Draft #64,
`d870c539644bfba4c03d197b22182d776d1aa008`. Vertrag zuerst in `ea1ecf1`
und `13c6189` festgehalten. Keine Produktion, echten Finanzdaten, Vaults,
Methodenentscheidungen oder archivierten Abgabepakete verwendet/veraendert.
Der konkrete integrierte Head steht im nachgelagerten Draft-PR.

## Ausgangsstand nachgeprueft

CI `43745358940` zu exakt obigem Head: alle fuenf Jobs erfolgreich.
Die kleinen Originalartefakte wurden nachgeladen und gelesen; die rund
61-MB-Browserbildsammlung wurde nicht erneut heruntergeladen.

| Originalartefakt | Gelesener Inhalt |
| --- | --- |
| Backend `14174238675` | 4.403 Faelle: 4.399 bestanden, vier bereits bestehende private Skips, null Fehler/Errors; XML-SHA256 `51a7252fd37b649c401c32e1473dff171b842f3479ebbcad50ba7c83d384c4df` |
| Referenzen `14174820495` | 52 Original, 359 erweitert, 68 Checkpoint, 43 Zeitbeleg, 146 Originalzulassung: jeweils null Fehler/Errors/Skips; Artefaktdigest `efbd2ff20b1ee6f5d85f6593fc142ca592c9608360445f7da13e6c56a5f5e9aa` |
| Docker `14173524057` | Isolierte Leerstarts mit leerem Profil, Vault und ohne Legacydienst; Layerreuse dokumentiert. Kein aktueller Betreiberrestore |

PR #64 und Issues #46/#63 wurden mit dem CI-Nachtrag aktualisiert.
Diese Ausgangsbelege beweisen nicht den nachfolgenden Diff.

## Zuordnung und Grenzen

| Anforderung | Umsetzung | Nachweis / Grenze |
| --- | --- | --- |
| #63: Defekte Vorschau darf nicht verschwinden | `HistoricalPricePreviewListItem`, `HistoricalPriceService.recent()`, typisierter GET | UUID bleibt sichtbar, alle nicht bestaetigten Metadaten `null`, separates Warnsignal. Root-/Datenbankausfall nicht als leere Liste verschlucken |
| Laden/Null/leer/fehlerhaft trennen | `PriceWorkspace.tsx` | Vorheriger Stand nach Listenfehler veraltet, keine neue Bestaetigung; `no_prices` mit echtem Nullwert bleibt gueltig |
| Konkrete Preis-ID statt Symbolraten | `_prepare()`, `price_point_fingerprint()` | Metadaten aus tatsaechlich gespeicherten Clone-Zeilen nach Pipeline; Vorschauhash bindet UUID, EUR-Wert, Referenzzeit, Asset, Quelle, Konfidenz |
| Begrenzter lesender Originalzugriff | `PriceImportEvidenceService`, zwei neue GETs | Vorschau/Plan, Importentscheidung, vorhandene Quittung, aktuelle Preiszeile und konkrete Originalbytes pruefen. Keine grossen vorbereiteten DB-Dateien fuer Beleglesen laden |
| Kein Initialisieren beim Lesen | `read_initialized_snapshot()`, Snapshotkonstruktor | Bereits initialisierten Store voraussetzen, Datei ausdruecklich `read_only=True` oeffnen, kein `ensure_schema`/`mkdir`; geloeschte DB nicht neu erzeugen. Kein allgemeiner Offline-Migrations-/WAL-Recoverypfad fuer unbekannte DBs |
| Konkrete Benutzeraktion | `PriceImportEvidence.tsx` | Ausdruecklich Preiszeile waehlen/pruefen; kein automatischer Abruf; Originaldownload nur unter festem ID-/SHA-Pfad |
| Kein falsches fachliches Guetesiegel | Report und UI | `selected_price_only`, `strict_eligible=false`, `admission_status=not_reviewed`; Beobachtungs-/Publikationszeit bleiben unbekannt |

Nur neue Vorschauen erhalten Preis-ID-Bindungen. Keine Archivnachtraege,
keine ersatzweise Suche nach Symbol/Wert, kein automatisches Methodengate.
Bei quantisierten Preisen wird die Originaleingabe mit demselben lesenden
DECIMAL-Cast wie bei der Speicherung verglichen; Originalbytes bleiben exakt.
Dateien werden descriptorgebunden ohne Symlinkverfolgung und nichtblockierend
geoeffnet, danach auf regulaeren Typ, Laenge und SHA256 geprueft.

## Gegenproben und Integration

- Unabhaengige Recent-Probe vor Implementierungslekture eingefroren:
  `test_historical_price_recent_acceptance.py`, 39 Faelle, SHA256
  `d36acb12257d601c19d896d016194caf68c34b7f7200f77edb8b32fec0588f85`.
  Basis `ea1ecf1`: 30 fehlgeschlagen, neun bestanden, null Errors.
  Das sind keine 30 verschiedenen Produktfehler. Nach Integration gemeinsam
  mit 84 eigenen Recent-Proben: 123 bestanden.
- Erste gemischte Fokuspruefung: 218 bestanden, ein `preview_stale` bereits
  beim Fixture-Apply. Waehrend dieses Entwicklungsdurchlaufs wurde die vom
  Konflikthash eingeschlossene Runtime geaendert; dieser Lauf gilt nicht als
  eingefrorene Abnahme. Unveraenderter isolierter Wiederholungslauf: sieben
  bestanden. Die Schutzbedingung wurde nicht abgeschwaecht.
- Unabhaengiger Quellreview fand nichtblockierendes Dateioeffnen und den
  Vergleich unquantisierter mit gespeicherten Preiswerten als notwendige
  Korrekturen. Beide sind umgesetzt; eigenstaendige Laufzeitproben folgen.
- Erste native Browserprobe fand die fehlende UI-Zulassung des bestehenden
  `no_prices`-Zustands. Allowlist korrigiert, kontrollierte Fixture ebenfalls
  auf diesen Zustand gesetzt. Erneuter nativer Lauf besteht mit 20 Bildern,
  vier Breiten, sieben Mock-Provideraufrufen, null echten externen Anfragen.
  Die neuen Recent-Teilfaelle fuehren null POSTs aus und erhalten Quellen,
  Preise und Review-Entscheidungen.
- Kontrollierte Recent-Komponente: 92 Faelle bei 390/768/1280/1440 px,
  120 GETs, null POST-/Provider-/externe Requests. Kein nativer Backendbeleg
  aus diesem separaten Komponentenlauf abgeleitet.
- Unabhaengige Reader-Probe unveraendert uebernommen: 98 Faelle, SHA256
  `164300f4355d8214fd90abb0bf9a79f5529b097687c8e63b93282f2ce6490adf`.
  Alle gruen; erster Agentenlauf hatte einen eigenen Instrumentierungsfehler,
  keinen belegten Implementierungsfehler. Keine Vor-Fix-Rotprobe fuer diese
  Datei behauptet. Mit der Recent-Datei als zwei weitere Hash-CI-Gates gebunden.
- Kontrollierter Importbeleg-Browser: zuerst 176/180 bestanden; vier
  reproduzierte Ueberbreiten durch lange Dateinamen. Layout korrigiert,
  unveraendertes Script danach 180/180, 152 GETs, keine POST-/Provider-/externen
  Anfragen. Links geprueft, in diesem Komponentenlauf kein Download angeklickt.
- Nativer Abschlussbrowser nach letzter Snapshotkorrektur: gesamter Ablauf
  bestanden, **24 Screenshots**, vier Breiten, expliziter Reader-GET und
  tatsaechlicher Originaldownload mit exakten Bytes/Hash. Preis-/Reviewdaten
  durch diese Lese-/Downloadaktion unveraendert; null reale externe Anfragen.
- Letzter begrenzter Review: tiefe JSON-Verschachtelung darf nicht den ganzen
  Recent-Endpunkt ausfallen lassen. Eigene zusaetzliche Gegenprobe: entfernte,
  vorher initialisierte DB darf durch Lesen nicht leer neu angelegt werden.
  Beide vor Korrektur rot. Archiv-Rekursionsfehler nur an der Parsegrenze
  auffangen; Datenbank ausdruecklich read-only oeffnen. FIFO-Archivkandidaten
  vor Oeffnen aussortieren. Danach 192 Fokusfaelle gruen, einschliesslich aller
  98 unveraenderten Reader-Proben. Die eigene Write-Abweisungsprobe erfasste
  zunaechst nur den Transaktionsfehlertyp; explizites Datei-RO liefert den
  anderen konkreten DuckDB-Fehlertyp. Beide bei weiter verpflichtender
  Schreibabweisung/Unveraendertheit zugelassen; unabhaengige Datei unveraendert.
- Die ersten Gesamtlaeufe wurden **vor** dieser Runtimekorrektur kontrolliert
  abgebrochen: 2.453 Unit- und 286 Referenzfaelle bis dahin bestanden, Exit 2.
  Diese Teillaeufe gelten nicht als vollstaendige Abnahme. Original-JUnit blieb
  erhalten; nur ihre vier beendeten disponiblen Testroots wurden entfernt.

## Originalnachweise und Befehle

Alle Pythonbefehle mit vorhandenem Python-3.11-Venv,
`PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1`, keine neuen Pakete.

```bash
python -m pytest tests/unit -n 4 --dist loadfile -q --tb=short \
  --basetemp=/tmp/steuerreport-issue63-reader-full-final-20261115 \
  --junitxml=var/issue63-reader-full-final.xml
python -m pytest tests/acceptance -q --tb=short \
  --basetemp=/tmp/steuerreport-issue63-reader-reference-final-20261115 \
  --junitxml=var/issue63-reader-reference-final.xml
python -m pytest docs/audit/2026-10-28/acceptance_tests.py -q --tb=short \
  --basetemp=/tmp/steuerreport-issue63-reader-original-final-20261115 \
  --junitxml=var/issue63-reader-original-final.xml
python scripts/check_historical_prices_browser_v2.py \
  --output /tmp/steuerreport-issue63-import-reader-native-ro-final-20261115
python scripts/check_price_recent_browser_v2.py \
  --output /tmp/steuerreport-issue63-recent-controlled-final-20261115
python scripts/check_price_import_evidence_browser_v2.py \
  --output var/price-import-evidence-browser-final
python scripts/check_reference_baseline_v2.py
```

Lokale Browserbefehle zusaetzlich mit dem bereits installierten Chromium ueber
`--browser-executable`; kein Browserdownload. TypeScript/Vite-Build bestanden,
bestehende Chunkwarnung. Ruff und OpenAPI-/Endpunktdrift gruen. CI-Struktur:
fuenf Jobs, neue Pflichtreferenzen und beide Komponentenbrowser eingebunden.
Codegraph angefragt, aber leer (`empty_graph/not_ready`); keine Graphabdeckung
behauptet. Quellpruefung und Laufzeitproben stattdessen wie oben dokumentiert.
Private-Default-Guard: null Treffer. Zusaetzlicher lokaler Identifier-Schutz:
1.035 Arbeitsdateien und 7.391 lokale Git-Objekte, null Vorkommen des privaten
132er-Identifier-Satzes. Kein universeller Secretnachweis. `gitleaks` wurde im
aktuellen PATH nicht gefunden und hier nicht ausgefuehrt; keine
Installation zusaetzlicher Werkzeuge behauptet.

| Original | SHA256 |
| --- | --- |
| Agent-Recent vor Fix, 30 rot / neun gruen | `0bdf1a42215f0bf481c6f87e8415a9b5406b2c547fdbb445aa9087c259129d22` |
| `var/issue63-recent-final.xml`, 123 gruen vor spaeteren zwei Eigenproben | `7a4626c59cd44d32c1a5081095a2caeb483d454c11aa702f7b1db99a19c90eac` |
| Agent-Reader, 98 gruen | `0db3f20d512f7e71d0f86c268f05a186585c7cffa7d89c82d3dd6dede9acd4b8` |
| Eigene letzte zwei Rotproben | `af447a25136d967f89f82b0eee51f278f6c30412efba0961b94d8f472d9106c1` |
| Zwischenlauf mit eigenem zu engem Write-Fehlertyp, 190 gruen / einer rot | `20cf70caec7871001f83dc0fe93e85ecb3cbea262135c70aa45c79ca98bd6d98` |
| `var/issue63-reader-final-review-fixed.xml`, 192 gruen | `5418357cc27e2091419844ae17684e862b14fc940b178fc90e6ddbc7853cef8b` |
| Abgebrochene Unit-XML, kein Gesamterfolg | `0dd42ccc5c84cedc46d1944fdb32e8b7b581472147bac03bbfed32a9846a29b7` |
| Abgebrochene Referenz-XML, kein Gesamterfolg | `224ff78dcc0c19414c8be2cea2bc1e90894b24b0643a14eb4af5b47dac1844bf` |
| Importbeleg-UI vor Layoutfix, 176/180 | `94e97c3c349f6659ac8a91e0479f47e9e0bad277e3806d0f7b8f8123571405f4` |
| `var/price-import-evidence-browser-final/summary.json`, 180/180 | `d375c5e79f29b10950fa3816a24a2b181cc06c3a8c0aca79d0746593dfc36cde` |
| Recent-Komponentenbrowser, 92/92 | `ce22618ba3890d4aeb42196833475d22f7a5dfcfa89c068abd8f591ca8290a87` |
| Nativer Abschlussbrowser, `result.json` | `11ddadee0d16129e3e48613cb811e13a100d747545ec5e6bab4810831cf3f69a` |
| `var/issue63-reader-reference-final.xml`, 359 gruen | `768dba0443908e18d1cddc13f24ecb6eb27ce0e9b39159cecdadebd3c6d80569` |
| Referenz-Quellenfreeze, `bootstrap-oicjbvev/source-freeze.json` | `8d79756f805a9f6ac6cf32c71b150c5db94d9be8c9cbe55d4e4a1676f51b6442` |
| `var/issue63-reader-original-final.xml`, 52 gruen | `bcdc32779761027adacfa85a1de481607f38e2ecd66b65d331a44db890002109` |
| `var/issue63-reader-bitget-original.json`, 15 gruen | `1d375f5266a4932e80ec2fdd703ea739b6f0d32102950d84927a5b2e5c70db39` |
| `var/issue63-reader-full-final.xml`, 4.640 gruen / vier bestehende Skips | `9f7d81618a1fb7a04710e1829eba72b6c8b95d4797742cef0de57e1e0f9b2ce0` |
| Unit-Updates-Quellenfreeze | `50ca4ab19d0b0ea3c1663e23e6747cf7fe0d24532d5786bd54bdbb9f368823ca` |
| Lokaler privater Identifier-Schutz, vor Commit | `d04ff7b17fed3f4df0e48503b900ca552a715e7bd950e12f1e63a424e856752f` |

## Integrierte Pruefung

Die 359 erweiterten Referenzen sind vollstaendig bestanden (337,88 Sekunden,
keine Fehler/Errors/Skips, eine vorhandene Starlette-Warnung). Der zugehoerige
Quellenfreeze bestaetigt 450 unveraenderte Runtime-/Konfigurationsdateien.
Die urspruenglichen 52 Sollfaelle bestehen ebenfalls (100,07 Sekunden), ebenso
der unveraenderte oeffentliche Bitget-Reproducer mit 15 Faellen.
Vollstaendiger eingefrorener Backendlauf: **4.640 bestanden, vier bestehende
private Skips, null Fehler/Errors**, 799,43 Sekunden. Die vier konkreten
Skip-Test-IDs wurden gegen das gelesene #64-CI-Original verglichen und sind
identisch: drei private Review-IOT/Solscan-Proben und der private
Usertransfer-Importcoverage-Fall. Keine neuen Skips. Unit-Updates-Quellenfreeze
ebenfalls `unchanged=true`.

Fokussierte und neue unabhaengige Unitproben sind in diesen 4.644 Faellen
bereits enthalten, nicht zusaetzlich als eindeutige Backendfaelle zu zaehlen.
Eine nachfolgende GitHub-CI gilt erst nach tatsaechlichem Abschluss fuer den
gepushten Head; hier ist die lokale integrierte Pruefung dokumentiert.

| Arbeitspaket | Status dieses Diffs |
| --- | --- |
| A Betrieb/Restore | Kein Betreiberzugriff; produktive Alt-/Neu-Paritaet und echter Restore weiterhin nicht bewiesen |
| B Preise/FX | Lesender konkreter Importbeleg implementiert; kein neuer externer Kurs-/FX-Abruf |
| C Steuerlogik | Keine neue Formel, keine aktive Methode/Frist/Zuordnung geaendert |
| D Import/Konten | Kein Neuimport echter Quellen; neue Preisvorschauen erhalten Herkunftsbindung |
| E Reports/UX | Fehlerhafte Vorschauen sichtbar, Originalbeleg explizit erreichbar; keine neue finale Freigabe |
| F Unabhaengige Abnahme | Neue unveraenderte Gegenproben; globale G01-G25-/Betreiberabnahme nicht durch diesen Teilschritt ersetzt |

Die bestehende [G01-G25-Nacharbeitsmatrix](2026-10-28/blocker-closure/MATRIX.md)
bleibt mit ihren Grenzen erhalten. Zusaetzlicher Bezug dieses Diffs:

| G-Bezug | Neuer Teilnachweis | Nicht dadurch geloest |
| --- | --- | --- |
| G10 | Speicherdatum allein wird vom Importreader nicht als belegte Kurszeit zugelassen | Zulassungs-/Jahrespolicy weiterhin separat |
| G18 | Konkrete Preis-UUID und vollstaendiger Fingerprint statt Symbol-/Wertsuche | Kein allgemeiner Multichain-FIFO oder neues Mint-Mapping |
| G21 | Geaenderte Preis-/Entscheidungs-/Originalbindung wird nicht positiv bestaetigt | Keine Heilung fehlender Herkunft |
| G22 | Lesen/Download aendert Preis-/Review-/Quelldaten nicht | Kein neuer allgemeiner Offline-Neulauf/PDF-Bytevergleich |
| G23 | Erfolgreicher Importbeleg bleibt ausdruecklich ohne Methoden-/Jahresfreigabe | Keine fachliche Gesamtfreigabe aus gruenen Tests |
| G04/G08/G09/G19 | Bestehende unabhaengige Sollfaelle werden erneut ausgefuehrt | Keine neue steuerliche Regel oder Erweiterung ihres zuvor begrenzten Scopes |

#46 bleibt offen: menschliche Original-/Zeit-/Methodenannahme mit API/Formular,
gebundenen Entscheidungen und konsistenter Run-/Gate-Policy fehlt weiterhin.
#63 wird nicht allein durch einen Screenshot geschlossen. Keine globale
Fachfreigabe, kein Main-Merge, Tag, Release oder Deployment.

Bestehende Dependencies werden wiederverwendet. Keine neuen venvs, lokalen
Dockerimages oder privaten Datenkopien. Vier eigene beendete Testroots mit
825/453/452/9 MiB nach Erhalt der Original-JUnit entfernt, rund 1,7 GiB.
`calculation.prepared` in den Tests wird von der bisherigen
`*.duckdb`-Erfolgsbereinigung nicht erfasst; konkrete Wachstumsquelle in #30
dokumentiert, keine pauschale Erklaerung aller 20 GiB. Eine allgemeine sichere
Retention fuer Produktivvorschauen ist damit nicht implementiert. Nach dieser
begrenzten Bereinigung rund 219 GiB frei; keine Per-Release-Speicheranalyse.
Nach Abschluss auch die eigenen Endlaufkopien (961 MiB Unitroot und
6,8 MiB Referenzroot) entfernt. Beide Quellenfreeze-Originale vorher nach
`var/issue63-reader-originals/` kopiert; JUnit und Screenshots bleiben erhalten.

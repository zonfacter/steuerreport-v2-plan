# Blocker-Nacharbeit: Pruefbare Uebergabe

Datum: 28.10.2026. Branch `audit/blocker-closure-20261028`.
Ausgangscommit `ce51a9d42963e25cb7b96dda19efce0703c55b26`.
Laufzeit-Codefreeze `f8e60d9e74b3d5ef92c710c0ae75d0cd84ac9fd6`.
Der vollstaendige integrierte Code-/Testcommit und jeder Originalbeleg
werden im abschliessenden `evidence/manifest.json` gebunden. Das ist ein
neuer Nachtrag, keine Aenderung der frueher archivierten Testbelege.
Die Patchdatei bildet exakt den dort angegebenen Ausgangs- und Codecommit ab.
Zusaetzliche Berichte und Belegdateien sind nachfolgende Commits auf demselben
Auditbranch; ein selbstreferenzieller Patch samt eigenem Inhalt wird vermieden.

**Keine produktive Datenmigration, Neuberechnung, Methodenaktivierung,
Containerumschaltung, Veroeffentlichung oder steuerliche Jahresfreigabe.**
Produktion bleibt rc32. Kein neuer Registry-Digest wird vorgetaeuscht.

## 1. Ergebnis Und Grenzen

- G04: separaten Gebuehren-Token genau einmal im zulaessigen Pool verbrauchen;
  Kostenrolle, eigene Tokenverwertung, fehlender Kurs und fehlender Bestand
  getrennt behandeln. Bekannter Kurs allein beseitigt keinen Altbestandsblocker.
- G08/G09: beide FX-Richtungen im echten Consumer, maximal sieben belegte
  vergangene Kalendertage, keine kuenftige Beobachtung und kein Faktor1-Fallback.
  Diese Sieben-Tage-Grenze ist eine dokumentierte technische Policy, keine
  allgemein vorgeschriebene steuerliche Frist oder erfundener Feiertagskalender.
- G18: Original-Chain/Contract/Mint/Dezimalstellen in Planung und Review
  pruefen; gleiche Symbole mit widersprechender Identitaet bleiben blockiert.
  Keine automatische Reparatur oder Zusammenfuehrung der Canonical-Asset-IDs.
  Mehrere gleichnamige Token sind damit sicherheitsgerichtet gesperrt, nicht
  als vollstaendig getrennte positive Multichain-FIFO abgenommen.
- G19: explizit belegte, gleichzeitige Umstellung im selben Konto/Pool mit
  Mengenverhaeltnis und lokalem gehashtem Primaerbeleg. Datum und Kostenbasis
  bleiben erhalten. Unbelegtes Wrapping/Bridge bleibt Review, keine Paritaet1.
- Legacy: V1-Laufzeitdatei und Dockerdatei eindeutig zugeordnet; aktive
  V2-Datei auf8010 weiterhin nicht zweifelsfrei nachgewiesen. Vollstaendige
  RO-Zeilenmultimengen belegen verschiedene Inputs, keine Engineparitaet.

Eine technische Sollprobe ist weder menschliche Methodenfreigabe noch
steuerliche Gesamt-/Jahresabnahme. Die noch offenen Punkte stehen in Abschnitt7.

## 2. Aenderung Und Validierung

| Anforderung | Dateien / Consumer | Nachweis |
| --- | --- | --- |
| G04 Menge und Kosten | `domain/tax.py`, `tax_wallet_fifo.py` | Neue feste Zahlenproben in `test_g04_fee_accounting.py`, Original-G04 und unabhaengige Alt-DB-Regression |
| Aktueller gespeicherter Stand | `review.py`, atomarer Tax-Tabellentausch | Inputbindung plus gespeicherte Fee-Line-Menge; alter/veraenderter Lauf bleibt blockiert |
| G08/G09 | `historical_fx.py`, historische Einzel-/Batch-/AsOf-/V1-Consumer | Echte Mock-HTTP-/DuckDB-Consumer, Originalpaar/Referenztag/Quelle, begrenztes Requestbudget |
| Zukunftsrueckdatierung | `external_price_backfill.py` | Spaeterer Token-/FX-Beleg wird nicht auf frueheres Ereignisdatum geschrieben |
| G18 | `asset_identity.py`, `historical_prices.py`, `review.py` | Netzwerk-/Contract-/Mengeneinheitenkonflikte, unveraenderte Solana-Identitaetsregressionen |
| G19 | `token_conversion.py`, vorhandener Redenomination-Pfad, beide FIFO-Consumer | 100:1, Teilverkauf, Originaldatum/Basis, Reward genau einmal, stale/missing evidence |
| Bedienbarkeit | `InstallationSettings.tsx`, `workspace/PriceWorkspace.tsx` | Private Konfiguration erreichbar; Chain/Contract/Dezimalstellen gespeichert und wieder geladen; vier Browserbreiten |
| Stale-Schutz | `ai_changes._fingerprint`, `wallet_fifo_runs.py` | Auch TXT-Belegbytes und Konvertierungskonfiguration Teil der Eingabebindung |
| Paritaet | `parity_audit.py`, `parity_probe.py` | Echte RO-Vollvergleiche und11synthetische Helferproben |
| Pflicht-CI | `.github/workflows/ci.yml`, `check_reference_baseline_v2.py` | Separate unveraenderte52er- und neue Referenzprozesse; Fehler blockiert CI/Publish |

Die vollstaendige neue G01-G25-Matrix steht in `MATRIX.md`, die urspruenglichen
Beweisgrenzen bleiben erhalten. Fachberechnung und Belegzuordnung wurden nicht
durch Freigabe-Flags oder Skips gruengeschaltet.

## 3. Zwei Zusaetzlich Gefundene P1-Regressionen

1. Ein Konvertierungslot mit derselben Herkunfts-Event-ID wie der urspruengliche
   Reward verdoppelte die an Reward-Ereignisse gebundene Lotbasis; welche
   Einkommensausgabe betroffen war, hing vom jeweiligen Consumer ab. Neu
   referenziert der uebernommene Lot das Ziel-Transferereignis;
   `origin_lot_id` bindet weiterhin die urspruengliche Anschaffung. Erwerbsdatum
   und Basis bleiben erhalten. Reward-, Umstellungs- und Verkaufsprobe sind
   getrennt, auch im unabhaengigen Test.
2. Ein Preis und die neue Berechnungsfunktion beweisen keinen schon gespeicherten
   Gebuehrenverbrauch. Ein atomar gespeicherter Eingabefingerprint bindet jetzt
   Canonicals, Preisstand, Methode und Konvertierungsbelege. Review prueft
   zusaetzlich die gespeicherte Abgangsmenge. Fehlender/veralteter Nachweis
   erzeugt `fee_accounting_recalculation_required`, keinen automatischen Rebuild.

Die wirtschaftliche Privat-/Betriebszuordnung wird nicht automatisch aus dem
neuen Transferereignis abgeleitet. Die Ursprungslot-Referenz bleibt erhalten;
eine reine Transferherkunft bleibt im bestehenden Herkunftsaudit Review statt
automatisch als privater Erwerb zu gelten. Keine allgemeine Sphaerenfreigabe.

Fuer Konvertierungen wird ebenfalls ein aktueller gespeicherter Lauf mit
nachgewiesenen Ziellots verlangt. Eine geaenderte Belegdatei kann weder eine
alte KI-/Preisvorschau uebernehmbar noch alte gespeicherte Ergebnisse aktuell
erscheinen lassen. Das Lesen/Filtern startet keine externe Abfrage.

## 4. Konfiguration Und Migration

Keine zentrale DB-Schemaaenderung. Bestehende private Profile, Raw-Objekte,
Reviewentscheidungen und Abgabepakete bleiben erhalten. Der neue abgeleitete
Admin-Marker entsteht ausschliesslich bei einem ausdruecklichen Rebuild in
derselben Transaktion wie die Tax-Tabellen, nicht beim Oeffnen einer Ansicht.
Bei vorhandenen Gebuehren ohne aktuellen Nachweis ist eine neue isolierte
Vorschau erforderlich; alte Ergebnisse werden nicht rueckwirkend anerkannt.

`token_conversion_mappings.json` ist unter Einrichtung, erweiterte private
Konfiguration erreichbar. Schema: `contracts/token_conversion.py`. Erforderlich:
Event-/Raw-SHA256 beider Beine, positiver Zaehler/Nenner, Aktor, Begruendung,
relative lokale Belegdatei unter dem privaten Konfigurationsverzeichnis und
deren SHA256 sowie zwei echte boolesche Bestaetigungen. Keine absoluten Pfade,
`..`, Symlinks oder automatisch geladenen URL-Belege. Nicht gueltige, doppelte,
veraltete oder nicht aktivierte Zuordnungen bleiben Review. Es wird kein
produktives Mapping vorinstalliert. Netzwerkgebuehren, verschiedene Zeitpunkte,
verschiedene Pools und strittige wirtschaftliche Einordnung sind nicht als
generischer neutraler Konvertierungsfall unterstuetzt.

Wallet-Vorschauversion: `wallet_asset_preview_v48_fee_consumption_evidenced_conversion`.
Keine bestehende Wallet-FIFO-Aktivierung oder Jahresbestaetigung wurde ersetzt.
Neue PriceMapping-Felder sind optional; bestehende gespeicherte Solana-Mints
behalten ihre Schreibweise und bestehenden Provider-/Guard-Regeln.

## 5. Originalquellen Und Alt-/Neu-Vergleich

`/tmp/blockpit-analysis` war nicht vorhanden. Die benannten Unterlagen wurden
im unversionierten Nutzerordner `docs/blockpit-analysis/` des Koordinatorcheckouts
gefunden. Nur die benannten Berichte/Repros wurden gelesen. Browserprofile,
Cookies und Originalberichte wurden weder in das Repository aufgenommen noch
veraendert. Der Ordner ist explizit von Git und Codegraph ausgenommen.

`LEGACY_PARITAET.md`, `parity-summary.json` und `original-repro-results.json`
enthalten Quellenhashes, tatsaechliche Befehle, anonymisierte Aggregate und
Beweisgrenzen. Beide Originalrepros liefen ausschliesslich in eigenen Kopien,
Exit0: V1 sieben synthetische Faelle, V2 vier enge Snapshot-/Methodenproben.
Das Schreiben der V2-`results.json` erfolgte nur in dieser Kopie.

Wichtig: Alle sieben gelieferten V1-Snapshotdateien weichen von den im
mitgelieferten Manifest deklarierten Git-Blob-Hashes ab. Unveraendertheit
unserer Kopie und erfolgreiche Reproduktion bestaetigen nicht ihre Identitaet
mit dem behaupteten Upstreamcommit. V2-Snapshot-SHA256 wurden bestaetigt.

V1 und Docker sind nicht dieselbe Rechenbasis. V1-Tax-Lines umfassen saemtliche
historischen Jobs, keine aktuelle gleichmethodische Jahresgesamtsumme. Fehlende
persistierte Einzel-Lots in V1 werden nicht durch erfundene Lots ergaenzt.
Keine private Zeilenliste, HMAC-Schluessel oder Kontoidentitaet im Publicnachweis.

## 6. Tests, CI Und Reproduktion

Originale JUnit-Dateien, Browser-JSON/Screenshots, Diff und SHA256 stehen nach
Abschluss im neuen `evidence/`-Ordner. `manifest.json` bindet die tatsaechlichen
Ergebnisse und den vollstaendigen Commit, nicht nur eine README-Aussage.
Die vorigen Auditdateien bleiben als historische Belege unveraendert.

| Ausgefuehrter integrierter Lauf | Ergebnis |
| --- | --- |
| Vollstaendige Unit-Suite, vier Worker, Runtime-/Unitbaum unveraendert seit f8e60d9 | 2590passed,4skipped,4DeprecationWarnings;861,50s |
| Unveraenderte urspruengliche Referenzdatei, eigener Prozess |52passed;116,18s |
| Neue unabhaengige Referenzdatei, eigener Prozess im Koordinatorcheckout |38passed;58,90s |
| Dieselben38Proben unabhaengig vor/nach Korrektur | Vorher8failed/30passed; nachher38passed; Original-XMLs erhalten |
| Echte RO-Paritaet und eigene Helfer | Volltabellen/Archive vor/nach stabil;11Helfertests bestanden |
| Browser gegen isolierte DB und Mock-HTTP | Bestanden,12Screenshots, vier Breiten,0reale externe Requests |

Die vier Skips sind unveraendert unterlagenabhaengig: drei Tests zu privaten
IOT-/Solscan-Belegspuren und Annahmevorschlaegen in `test_review`, ein Test des
privaten Importbaums in `test_import_coverage`. Ihre konkreten Test-IDs und
Skiptexte stehen im Original-XML. Damit wird die Vollstaendigkeit dieser
privaten Quellen nicht nachgewiesen. Kein neuer Skip und kein xfail.

```sh
python scripts/check_reference_baseline_v2.py
PYTHONPATH=src python -m pytest docs/audit/2026-10-28/acceptance_tests.py -q --junitxml=reference-original.xml
PYTHONPATH=src python -m pytest tests/acceptance -q --junitxml=reference-additional.xml
pytest tests/unit -n 4 --dist loadfile -q --basetemp=/tmp/steuerreport-unit --junitxml=unit.xml
ruff check src tests scripts
cd frontend
npm run build
```

Die Prozesse bleiben getrennt: Die urspruengliche52er-Datei installiert eine
strenge globale Netz-/DB-Isolation. Kein `continue-on-error`, `xfail`, geaenderter
52er-Sollwert oder stiller Fallback im neuen Pflichtjob. Der bestehende
Publishworkflow haengt ueber `needs: validate` vom gesamten CI-Workflow ab.
GitHub-Branchschutz wurde nicht administrativ geaendert und keine entfernte
CI-Ausfuehrung behauptet: Es gibt keinen Push-/Publishauftrag.

Weitere lokale Checks: OpenAPI-/Endpunkt-/Import-/KI-Dokumentationsdrift,
Ruff, Frontendbuild und URL-/Dezimalzustand in UTC und Europe/Berlin.
Der Frontendbuild meldet weiterhin den bekannten Chunkgroessenhinweis.
Gitleaks meldet im vollstaendigen getrackten Quellenexport zehn bereits
einzeln gepruefte Nicht-Secrets; der exakte Zeilenhash-Guard bestaetigt null
ungepruefte Findings und keine privaten Kontovorgaben. Der unversionierte
Nutzer-/Browserordner wurde nicht exportiert. Die Belegablage wird zusaetzlich
separat gescannt; ein roher Scanner-Exit1 wird nicht als null Findings ausgegeben.
Die Auditablage meldet16weitere Hash-Metadaten-Findings. Sie wurden einzeln
gegen die tatsaechlichen Quell-/Build-/Belegbytes nachgerechnet:
`artifact-secret-review.json` bestaetigt null ungepruefte Findings.
`review_artifact_scan.py` akzeptiert nur diese exakt geprueften Hashfelder,
keine Pfad-/Regel- oder Secret-Fallback-Ausnahme. Die Quellcode-Allowlist wurde
dafuer nicht erweitert. Original-XMLs und Manifest wurden nicht umgeschrieben.
Der Whitespacecheck nimmt ausschliesslich den generierten Patch, die zwei
unveraenderten roten Original-XMLs und die RFC-konforme CRLF-CSV aus.
Ihre Bytes bleiben gehasht erhalten. `.gitattributes` verhindert eine
automatische Zeilenendenkonvertierung dieser Belegdateien beim Checkout.

Entwicklungszwischenlaeufe bleiben benannt: Ein Volltest wurde nach den neuen
P1-Befunden unterbrochen; dabei wurden auch fuenf echte Solana-Integrations-
regressionen gefunden. Diese wurden durch Erhalt vorhandener Guardcodes und
belegter Provider behoben, nicht durch geaenderte alte Assertions. Ein
Browserzwischenlauf erkannte parallel geaenderten Quellcode als anderen
Fingerprint, ein weiterer hatte einen zu strikten Testselektor. Finale
Laeufe erfolgen nach Codefreeze. Vorlaeufe sind keine erfolgreiche Abnahme.

## 7. Verbleibende Blocker Aus Dem Frueheren Abschnitt9

| Punkt | Neuer Stand | Verbleibende Grenze |
| --- | --- | --- |
| 1 G04 | Mengen-/EUR-/Fee-Verwertung und aktuelle Speicherung implementiert, feste technische Proben | Swap-Kostenrollen, fremde Erwerbsbelege und individuelle Einkunftssphaere bleiben fachlich zu pruefen |
| 2 G08/G09 | Gemeinsame begrenzte FX-Policy und unabhaengige Consumerproben | Keine Genehmigung jeder Preisquelle oder persoenlichen Bewertungsmethode |
| 3 G18/G19 | Identitaetskonflikte gesperrt; enger beleggebundener Konvertierungspfad | Keine universelle Multichain-FIFO, generische Bridge-/LP-/Wrappingneutralitaet oder wirtschaftliche Sachverhaltsfreigabe |
| 4 Kostenbasis/Scope | Bestehende Nullbasis-/Herkunftsgates bleiben | Positive unbelegte Basis und Privat-/Betriebszuordnung weiterhin offen; keine Quellen/Entscheidungen erfunden |
| 5 Alt-/Neu-Paritaet | Echte RO-Vollvergleiche; V1/Docker eindeutig | 8010-Laufzeitdatei nicht abschliessend belegt; kein gleicher Input-/Methoden-/Jahres-/Lotstand fuer vollstaendige Engineparitaet |
| 6 Methodik/Abschluss | Gebundene Preis-/Konvertierungsvorschauen und aktuelle Laufpruefung | Menschliche Methoden-/Jahresfreigaben fehlen weiterhin |
| 7 Betrieb | Produktionsidentitaet kontrolliert, keine Umschaltung | Kein neues Image/Restore-/Rollbacknachweis fuer diesen Entwicklungscommit; vor spaeterem Update separat erforderlich |
| 8 Nutzerbelege | Berichte gefunden, gelesen, Repros in Kopien wiederholt | V1-Blobherkunft ist wegen Manifestabweichung nicht bestaetigt |

**Keine Gesamt-Fachabnahme.** Die geschlossenen technischen Regressionen sind
reviewbar; die offenen Daten-/Methoden-/Betriebsnachweise werden nicht durch
einen gruenen Test oder einen Versionsnamen ersetzt.

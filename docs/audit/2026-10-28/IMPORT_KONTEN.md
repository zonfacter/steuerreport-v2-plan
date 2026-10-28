# Paket D: Import Und Konten

Stand: 2026-10-28, isolierte Basis `438cbd3dac11b0f0bfcc7f308f583f3837de5f85`.
AGENTS.md, Koordinator-VERTRAG.md und G_MATRIX.md vor Aenderungen gelesen
und bestaetigt. B/C-Vertraege bleiben eingefroren. Kein Produktionscode
veraendert. Der gesonderte API-Pruefauftrag ist nicht verfuegbar; der Nutzer
wurde nach dem Pfad gefragt. Keine Behauptung, ihn gelesen zu haben.

## Tatsaechliche Kontentrennung

`domain/connections.py:ConnectionService.create/credentials/_run` speichert
Verbindungen unter UUID und Secrets unter `secret.cex.connection.<UUID>.*`.
`contracts/connections.py` erlaubt Binance, Bitget, Coinbase und Pionex.
Anzeigename, Konto und Unterkonto sind beschreibende Metadaten. Eine
Unterkontobezeichnung erzeugt keinen Subaccount-Header und keine zusaetzlichen
Berechtigungen: massgeblich ist der jeweilige Schluessel des Kontos.
Gleiche Anzeigenamen oder gleiche Account-Metadaten verschmelzen keine UUIDs.

`CexBalanceService.fetch` liest die verbindungseigenen Credentials; Snapshot-ID
und Quelle werden mit der Connection-ID versehen. `ConnectionService` speichert
diese Snapshots in seinem eigenen Namensraum, nicht als historische Trades oder
globale Anbieter-Snapshots. Ein Verbindungstest ist ein authentifizierter
Lesezugriff, kein Bestandssync und kein steuerlicher Quellennachweis.

`WorkspaceService.source_scopes` bildet `connection:<UUID>` auf eine stabile
Quellreferenz ab. `HistoryService._target` bindet daran Provider, Account und
Connection-ID. Existieren individuelle Verbindungen, wird eine pauschale
Legacy-Provider-Historie nicht automatisch als deren Historie akzeptiert.
Globale Legacy-Credentials und neue Connection-Credentials sind getrennte Wege.
Providerweite alte Import-Endpunkte besitzen dadurch nicht automatisch eine
neue kontoselektive Semantik.

## Umfang Der Historienadapter

Die folgende Tabelle beschreibt den **gelesenen Implementierungsstand**, keine
neue Verifikation von Anbieterzusagen. Vorhandene Primarreferenzen stehen in
`docs/HISTORY_CEX_PROVIDER_REFERENCES.md` (Stand dort: 27.10.2026). Keine neuen
Herstellerraten, Tarifwerte oder Aufbewahrungszusagen hinzugefuegt.

| Adapter / Fundstelle | Unterstuetzt | Nicht als vollstaendig behauptet |
| --- | --- | --- |
| `history_cex.py:_PATHS/_NOTES`, Binance | Spot-Fills fuer explizite Symbole, Capital-Ein-/Auszahlungsbelege, Marktsymbol-Metadaten | Earn/Convert/Fiat/Margin/Futures/interne Umbuchungen fehlen im generischen Adapter; separate Earn-Funktionen ersetzen keinen Vollstaendigkeitsbeleg |
| Gleiche Datei, Bitget | Classic-Spot-Fills und Wallet-Funding, Cursor-/Zeitfensterfortsetzung | Alte Fills ausserhalb des implementierten Retention-Filters, UTA/Earn/Convert/Margin/Futures; Dateiexporte bleiben erforderlich |
| Gleiche Datei, Pionex | Spot-Fills fuer explizite Symbole | Keine Botstrategie-Rekonstruktion, keine generische Funding-/Earn-/Futures-Historie |
| Gleiche Datei, Coinbase | Advanced-Trade-Spot-Fills des freigegebenen Portfolios | Kein allgemeiner Simple-Buy-/Convert-/Funding-/Reward-Abruf; Cursorende ist kein Vollstaendigkeitsbeweis |
| `history_solana.py`, `history_inventory.py` | Signaturen, Transaktionsdetails, gepruefte Owner-/SPL-/Token-2022-Konten, wiederaufnehmbare Inventare | Geschlossene historische Konten, begrenzte Providerhistorie und ungeklaerte Ownership bleiben Luecken; gespeicherte Adresse ist kein Eigentumsnachweis |

`HistoryPage.complete_history_proven` bleibt bei CEX falsch. Fremde Kontonamen
aus Antworten werden nicht als Zielkonto uebernommen. Die finanzielle Identitaet
enthaelt Provider, ausgewaehltes Account und externe Belegidentitaet; identische
Trade-IDs verschiedener Konten bleiben verschieden. `source_history_importer`
bindet Payload-Hash und Quellreferenz in die Rohzeile. Geaenderte Originalpayloads
unter vorhandener Identitaet blockieren statt alte Belege umzuschreiben.

## Originale Handels- Und Gebuehrensemantik

`history_cex.py:_fill/_funding/_row/_record` behaelt die Originalantwort im
Raw-Beleg. Kauf-/Verkaufsrichtung, Base-/Quote-Menge und Fee-Asset/-Menge werden
separat uebernommen und erst danach durch vorhandene Profile normalisiert.
Unklare Gebuehren, ungueltige Richtung oder unpraezise Mengen werden nicht
durch erfundene Nullwerte oder erfundene Trades geheilt. Erfolgreiche
Auszahlungsbelege mit ungeklaerter Brutto-/Netto-/Gebuehrenwirkung bleiben
klassifikationspflichtige Null-Ereignisse, keine fertig freigegebenen Transfers.
Ein Fill mit identifizierbarem Bot-Order-Bezug beweist keine vollstaendige
Botstrategie oder steuerliche Behandlung aller Bot-Komponenten.

## Wiederholungen Und Kopie

Eigene Tests in `test_migration_import_accounts.py` nutzen echte
ConnectionService-, CexBalanceService-, Limiter-, Collector-, Importer-,
Normalizer-, Pipeline-, Tax- und Workspace-Services. Nur HTTP-Gegenstelle und
verstrichene Wartezeit sind simuliert; zufaellige Vault-Schluessel werden im
eigenen Testverzeichnis erzeugt. Kein echter Anbieter, kein AI-Aufruf.

Nachgewiesen:

- Zwei gleichnamige Binance-Verbindungen liefern mit getrennten Schluesseln
  die synthetischen Bestandswerte 1 und 2 und getrennte Snapshot-IDs.
- Ein 429-Retry, Kontozugriffe und eine weitere Earn-Seite ergeben neun
  tatsaechliche Transportstarts; Provider-, Global- und gemeinsame Budgetgruppe
  zaehlen jeweils neun. Zweites Konto setzt kein Budget zurueck.
- Derselbe externe Fill-ID-Wert in zwei Konten erzeugt zwei getrennte
  Quellidentitaeten. API-Wiederholung erzeugt keine neuen Events/Imports.
- Identische CSV mit anderem Dateinamen bleibt derselbe Importbatch; erneute
  Normalisierung/Rebuild verdoppelt weder Restmengen noch Gewinne.
- DB-Kopie erhaelt Raw-IDs, Batchzuordnung, Payloads, Accounts, Review-ID,
  betroffene Event-ID und gespeicherte Quellreferenz. Secrets bleiben mit dem
  separat vorhandenen Test-Vaultschluessel lesbar. Das ist keine Restoreprobe
  eines echten Volumes und beweist keinen im DB-Backup enthaltenen Vaultkey.

Die Import-Service-Fixture setzt nach dem echten Pipeline-Lauf ausdruecklich
denselben `normalized`-Batchabschluss wie `HistoryPreview.prepare`. Sie ist
kein Test menschlicher Historienfreigabe oder kompletter Job-Approve-Kette.
Ein erster Entwicklungsversuch ohne diesen Workflowabschluss wurde korrekt
mit `history_previous_import_incomplete` abgewiesen; keine Produktlogik wurde
dafuer veraendert.

## Grenzen / G-Matrix

G20 wird hier kontenspezifisch fuer identische CSV-/API-Wiederholungen geprueft,
nicht als allgemeine Cross-Format-Deduplizierung beliebiger Exporte. G25 wird
fuer eine geschlossene eigene DB-Kopie und erhaltene Beleg-/Review-Bindungen
geprueft, nicht als produktive Docker-/Vault-/Artefakt-Restoreabnahme.
Historie, Kontoberechtigung, Ownership, Vollstaendigkeit, Preisqualitaet,
Steuersphaere und menschliche Freigabe bleiben getrennt. Kein allgemeines
API-Sicherheits-, Rechts- oder Herstellerquotenzertifikat.

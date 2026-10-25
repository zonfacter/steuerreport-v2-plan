# Mobile App API Integration

Stand: 2026-08-26

## Zweck und Freigabestatus

Dieses Dokument ist der kanonische Einstieg fuer eine kuenftige Android- oder
iOS-App. Der Server bleibt die einzige Instanz fuer Steuerlogik, FIFO,
Stichtagsbewertung, Quellenregeln und Belegerzeugung. Ein Mobile-Client stellt
diese Ergebnisse dar und darf sie nicht lokal nachberechnen.

Der aktuelle Status lautet
`experimental_read_pairing_wallet_ownership_and_document_inbox`:

- Die empfohlenen Lese-Endpunkte sind fuer einen ersten Mobile-Client geeignet.
- Der Connector-Katalog und ein signierter Solana-Wallet-Eigentumsnachweis
  sind als erste schmale Setup-Oberflaeche vorhanden.
- Mobilgeraete erhalten ueber einen einmaligen Kopplungscode eine gescopte,
  ablaufende und serverseitig widerrufbare Sitzung. Der dauerhafte Setup-Token
  wird nicht auf dem Mobilgeraet gespeichert.
- Das API-Schema ist versioniert und maschinenlesbar eingecheckt.
- Schreibende Endpunkte bleiben grundsaetzlich Expert-/Admin-Oberflaeche.
  Ausnahmen sind die explizit als `recommended-write` markierten, eng
  gescopten Wallet-Nachweis- und Dokumentuploadpfade.
- Die API ist ohne vorgeschaltetes TLS/Auth-Gateway nicht internetfaehig.

Die Laufzeitmerkmale liefert:

```text
GET /api/v1/meta/capabilities
```

## Vertraege und Dokumentation

| Ressource | Pfad | Zweck |
| --- | --- | --- |
| Swagger UI | `/docs` | Interaktive Entwicklung und Request-Tests |
| ReDoc | `/redoc` | Lesbare Schema- und DTO-Referenz |
| Live OpenAPI | `/openapi.json` | Vertrag der laufenden Serverversion |
| Versioniertes OpenAPI | `docs/openapi/steuerreport-v2-openapi.json` | Reproduzierbarer Build-/SDK-Input |
| Endpoint-Inventar | `docs/626_API_ENDPOINT_REFERENZ_VOLLSTAENDIG_2026-07-05.md` | Jede Route mit Zweck und Schreibwirkung |
| Fachvertraege | `docs/API_CONTRACTS_V2.md` | Fachliche Sonderregeln wichtiger Routen |

Das eingecheckte OpenAPI-Schema ist fuer CI und SDK-Generierung massgeblich.
Zur Laufzeit muss die App zusaetzlich `api_version` aus dem Capabilities-
Endpoint protokollieren.

## Basis-URLs

Lokale Entwicklung auf dem API-Host:

```text
http://127.0.0.1:8010
```

LAN-Entwicklung von einem anderen Geraet:

```text
http://<server-ip>:8010
```

Klartext-HTTP darf nur fuer einen kontrollierten lokalen Test verwendet
werden. Eine verteilte App benoetigt eine HTTPS-URL vor einem Auth-Gateway.
Die Basis-URL gehoert in eine Build-/Environment-Konfiguration und niemals
fest in den fachlichen Quellcode.

## Standard-Envelope

JSON-Endpunkte verwenden:

```json
{
  "trace_id": "8cc1198f-5f55-4f34-97e2-42fb0e3394a7",
  "status": "ok",
  "data": {},
  "errors": [],
  "warnings": []
}
```

Client-Regeln:

1. Zuerst HTTP-Status und `Content-Type` pruefen.
2. Bei JSON danach `status`, `errors` und `warnings` pruefen.
3. `data` nur bei fachlich geeignetem Status darstellen.
4. `trace_id` in technische Logs und Fehlermeldungen aufnehmen.
5. Warnungen neben dem betroffenen Wert anzeigen und nicht still verwerfen.

Ein HTTP-Response kann technisch erfolgreich sein und trotzdem einen
fachlichen Status `warning` oder `error` enthalten. Datei- und HTML-Endpunkte
liefern keinen JSON-Envelope; fuer sie sind `Content-Type` und
`Content-Disposition` verbindlich.

## Decimal, EUR und Zeit

### Decimal

Geldbetraege, Kurse und Tokenmengen werden im JSON als Strings transportiert:

```json
{
  "total_value_eur": "7921.793702483289876676596591",
  "quantity": "6172.650000000000000000"
}
```

- Android: `java.math.BigDecimal` verwenden.
- iOS: `Foundation.Decimal` aus dem String erzeugen.
- Niemals zuerst nach `Double` oder `Float` konvertieren.
- Fuer Anzeige in EUR auf exakt zwei Nachkommastellen formatieren.
- Rechen- und Rundungsentscheidungen bleiben serverseitig.

### Zeit

- API-Zeitstempel sind ISO-8601 und UTC.
- Steuerliche Tagesgrenzen bestimmt der Server in `Europe/Berlin`.
- Ein Datum wie `2025-06-13` ist eine fachliche Auswahl, kein vom Client frei
  in UTC umzurechnender Mitternachtszeitpunkt.
- Die App darf UTC-Timestamps lokal anzeigen, muss im Detail aber den originalen
  UTC-Wert erhalten.

## Empfohlene Mobile-Leseoberflaeche

| Endpoint | Verwendung | Cache-Richtwert |
| --- | --- | --- |
| `GET /api/v1/health` | Erreichbarkeit und Schema-Version | 30 Sekunden |
| `GET /api/v1/meta/capabilities` | Version und Client-Faehigkeiten | App-Start |
| `GET /api/v1/cockpit/summary` | Startseite | 30 Sekunden |
| `GET /api/v1/product/readiness` | Abgabe-/Systemstatus | 60 Sekunden |
| `GET /api/v1/connectors/catalog` | Connector-, Vault- und Sicherheitsstatus | 60 Sekunden |
| `GET /api/v1/connectors/connections` | Signierte Wallet-Verbindungen | 60 Sekunden |
| `GET /api/v1/connectors/mobile/session` | Scope und Ablauf der gekoppelten App-Sitzung | App-Start |
| `GET /api/v1/sources/overview` | Eigene Quellen, Live- und Ledgerstatus | 60 Sekunden |
| `GET /api/v1/sources/{source_id}` | Quellen-Drilldown | 60 Sekunden |
| `GET /api/v1/portfolio/snapshot` | Aktueller Bestand | 30 Sekunden |
| `GET /api/v1/portfolio/as-of` | Historischer Stichtag | pro Datum |
| `GET /api/v1/portfolio/value-history` | Historischer Chart | pro Parameterkombination |
| `GET /api/v1/portfolio/token-risk` | Spam-/Tokenrisiken | 5 Minuten |
| `GET /api/v1/review/gates` | Exportfreigabe | 30 Sekunden |
| `GET /api/v1/review/tasks` | Offene Aufgaben | 30 Sekunden |
| `GET /api/v1/tax-years/summary` | Steuerjahr-Liste | 5 Minuten |
| `GET /api/v1/tax-years/{year}` | Steuerjahr-Detail | pro Jahr |
| `GET /api/v1/reports/center` | Berichte und Beleglinks | 5 Minuten |
| `GET /api/v1/divorce/equalization-summary` | Zugewinn-Uebersicht | 5 Minuten |
| `GET /api/v1/divorce/valuation-runs/latest` | Letztes Stichtagsdossier | 5 Minuten |

Der Capabilities-Endpoint enthaelt die kleinere, vom Server empfohlene
Startmenge. OpenAPI kennzeichnet diese Operationen mit
`x-mobile-surface=recommended-read`.

## Solana-Wallet-Eigentumsnachweis

Der erste schreibende Mobile-Flow ist bewusst eng begrenzt:

1. `POST /api/v1/connectors/wallet/challenges` erzeugt eine fuenf Minuten
   gueltige, einmalige Nachricht.
2. Phantom, Jupiter Wallet oder Solflare signiert exakt diese Nachricht mit
   `signMessage`. Es wird keine Transaktion erzeugt.
3. `POST /api/v1/connectors/wallet/verifications` prueft Ed25519-Public-Key,
   Signatur, Ablaufzeit und Replay-Status.
4. Eine bereits registrierte eigene Wallet erhaelt `registry_active`.
5. Eine neue Wallet bleibt `ownership_verified_pending_registry` und
   `review_required`. Sie veraendert weder Canonical Events noch Ledger,
   Portfolio, FIFO oder Steuerdaten.

Vor dem ersten schreibenden Mobile-Aufruf wird das Geraet gekoppelt:

1. Ein Administrator erzeugt mit `POST /api/v1/connectors/mobile/pairings`
   und dem lokalen Setup-Bearer einen zehn Minuten gueltigen Einmalcode.
2. Die App tauscht Kopplungs-ID und Code einmalig ueber
   `POST /api/v1/connectors/mobile/sessions` gegen einen Mobile-Bearer.
3. Der Bearer wird im Android Keystore beziehungsweise in der iOS Keychain
   gespeichert und mit `GET /api/v1/connectors/mobile/session` geprueft.
4. Der Server speichert nur SHA-256-Hashes, Scopes und Auditzeitpunkte.
5. Der Administrator kann jede Sitzung ueber
   `DELETE /api/v1/connectors/mobile/sessions/{session_id}` widerrufen.

Die Wallet-POST-Endpunkte akzeptieren danach:

```text
Authorization: Bearer <mobile-session-token mit wallet:verify>
```

Der dauerhafte Setup-Token liegt weiterhin nur in der root-geschuetzten Datei
aus `STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE`. Er autorisiert alternativ
lokale Administration, gehoert aber niemals in die App. Mobile-Sitzungen und
Setup-Token ersetzen kein OIDC bei Internetbetrieb.

Seed Phrase, Private Key und Wallet-Passwort werden weder abgefragt noch
gespeichert. Die API akzeptiert ausschliesslich Adresse und Signatur.

## Verschluesselter V2-Secret-Vault

`secret.*`-Werte koennen als AES-256-GCM-Envelope in DuckDB gespeichert
werden. Der 32-Byte-Master-Key bleibt ausserhalb von Repository und Datenbank:

```text
STEUERREPORT_V2_SECRET_VAULT_KEY_FILE=/etc/steuerreport-v2/secret-vault.key
STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS=true
```

Jedes Envelope ist per Associated Data an seinen Setting-Key gebunden. Der
Katalog gibt nur Key-ID, Zaehler und Status aus, niemals Secret-Werte.
Migration bestehender V2-Secrets:

```bash
PYTHONPATH=src python3 scripts/migrate_secret_vault_v2.py
PYTHONPATH=src python3 scripts/migrate_secret_vault_v2.py --apply
```

Ohne `--apply` werden nur Zaehler ausgegeben. Die Apply-Migration laeuft in
einer DuckDB-Transaktion und prueft jedes Envelope vor dem Commit.

## OpenAPI-Erweiterungen

Jede Operation besitzt:

- `x-data-effect=read-only`: liest lokale/berechnete Daten.
- `x-data-effect=external-read`: kann einen Provider kontaktieren.
- `x-data-effect=write`: kann Daten, Decisions, Jobs oder Artefakte schreiben.
- `x-data-effect=delete`: loescht den bezeichneten lokalen Datensatz.
- `x-mobile-surface=recommended-read`: freigegebener Mobile-Leseeinstieg.
- `x-mobile-surface=recommended-write`: eng gescopter Mobile-Setup- oder
  Uploadpfad.
- `x-mobile-surface=expert-or-internal`: nicht Teil der ersten App-Oberflaeche.
- `x-long-running=true`: mit langem Timeout und sichtbarem Fortschritt behandeln.

Eine Mobile-App darf ihre Berechtigungen nicht allein aus diesen Feldern
ableiten. Sie sind Dokumentations- und UI-Metadaten; die echte Autorisierung
muss spaeter das Gateway erzwingen.

## Laden, Caching und Fehler

- Startansicht parallel laden, aber Kernwerte bis zum Response als
  `wird geladen` darstellen. Kein vorlaeufiges `0,00 EUR` anzeigen.
- Pro Screen Requests bei Navigation abbrechen oder alte Run-IDs verwerfen.
- Read-Timeout fuer normale Endpunkte: mindestens 60 Sekunden.
- Steuerjahr-/Report-Endpunkte: mindestens 180 Sekunden oder serverseitigen
  Job-/Polling-Pfad verwenden, sobald vorhanden.
- Letzte erfolgreiche Read-Antwort darf offline mit sichtbarem Zeitstempel
  dargestellt werden. Sie darf nicht als live bezeichnet werden.
- Bei `warnings` den Wert darstellen, aber den Warnstatus sichtbar halten.
- Bei `errors` keinen gecachten Wert still als aktuellen Wert ausgeben.
- Retry nur fuer idempotente GET-Aufrufe und mit exponentiellem Backoff.
- POST/PUT/PATCH/DELETE niemals automatisch wiederholen, solange keine
  dokumentierte Idempotenz vorhanden ist.

Der Dokumentupload ist durch den Inhalts-Hash idempotent: Ein bytegleiches
Original erzeugt kein zweites Inbox-Dokument. Die App soll das Ergebnisfeld
`already_present` trotzdem sichtbar auswerten und einen abgebrochenen Request
nicht blind parallel wiederholen.

## Mobile Beleg-Inbox

`POST /api/v1/connectors/mobile/documents` verwendet `multipart/form-data` und
eine gekoppelte Sitzung mit `document:upload`. Unterstuetzt werden PDF, JPEG
und PNG bis 25 MiB. Die App uebergibt neben `file` optional:

- `document_kind`: `bank_statement`, `exchange_statement`,
  `purchase_receipt`, `tax_notice`, `inheritance_evidence`,
  `portfolio_statement` oder `other`,
- `source_hint`: kurze Providerangabe,
- `note`: lokale Review-Notiz,
- `captured_at`: ISO-8601-Zeitpunkt mit Zeitzone.

Der Server prueft Dateiendung, Medientyp und Magic Bytes, bereinigt den
Dateinamen, speichert content-addressed und antwortet mit SHA-256,
`evidence_ref`, Reviewstatus und Downloadpfad. `pending_review` bedeutet
ausdruecklich, dass weder OCR noch Steuer-, FIFO-, Ledger- oder Importlogik
ausgeloest wurde.

Inbox-Liste und Originaldownload sind Adminpfade und akzeptieren keinen
Mobile-Bearer. Dadurch kann ein kompromittiertes Aufnahmegeraet Belege
hochladen, aber den vorhandenen Belegbestand nicht auslesen.

## Downloads und Belege

PDF-, ZIP-, CSV-, JSON- und HTML-Belege werden als Dateiantwort geliefert.
Die App soll:

1. den vom Server gelieferten Dateinamen aus `Content-Disposition` verwenden,
2. in einen geschuetzten App-Container laden,
3. PDF/HTML mit einer Systemvorschau oeffnen,
4. ZIP nicht als Text interpretieren,
5. niemals Secrets oder komplette API-Antworten in Analytics-Dienste senden.

## Android-Modell

Ein minimales Retrofit-Modell kann so aussehen:

```kotlin
@Serializable
data class ApiEnvelope<T>(
    val trace_id: String,
    val status: String,
    val data: T? = null,
    val errors: List<ApiMessage> = emptyList(),
    val warnings: List<ApiMessage> = emptyList()
)

@Serializable
data class PortfolioSnapshot(
    val total_value_eur: String,
    val positions: List<PortfolioPosition>,
    val missing_price_assets: List<String>
)

val total = BigDecimal(snapshot.total_value_eur)
```

Fuer einen LAN-Debugbuild muss Android Klartextverkehr explizit und nur fuer
den lokalen Host erlauben. Release-Builds verwenden ausschliesslich HTTPS.

## iOS-Modell

Ein minimales Swift-Modell:

```swift
struct ApiEnvelope<T: Decodable>: Decodable {
    let traceId: String
    let status: String
    let data: T?
    let errors: [ApiMessage]
    let warnings: [ApiMessage]

    enum CodingKeys: String, CodingKey {
        case traceId = "trace_id"
        case status, data, errors, warnings
    }
}

struct PortfolioSnapshot: Decodable {
    let totalValueEur: String

    enum CodingKeys: String, CodingKey {
        case totalValueEur = "total_value_eur"
    }
}

let total = Decimal(string: snapshot.totalValueEur, locale: Locale(identifier: "en_US_POSIX"))
```

Eine ATS-Ausnahme fuer HTTP ist nur im lokalen Debug-Schema zulaessig. Die
Release-App verwendet HTTPS ohne globale ATS-Ausnahme.

## SDK-Generierung

Schema aktualisieren und pruefen:

```bash
cd /workspace/steuerreport-v2-plan
python3 scripts/export_openapi_v2.py
python3 scripts/export_openapi_v2.py --check
```

Beispiel mit einer im App-Projekt gepinnten OpenAPI-Generator-Version:

```bash
openapi-generator-cli generate \
  -i docs/openapi/steuerreport-v2-openapi.json \
  -g kotlin \
  -o generated/android

openapi-generator-cli generate \
  -i docs/openapi/steuerreport-v2-openapi.json \
  -g swift5 \
  -o generated/ios
```

Generierte Clients gehoeren nicht automatisch in dieses Backend-Repository.
Sie werden im jeweiligen App-Repository erzeugt, formatiert und gegen eine
gepinnte Schema-Revision getestet. Decimal-String-Decoding muss nach der
Generierung explizit verifiziert werden.

## Sicherheitsarchitektur vor App-Store-Betrieb

Die API besitzt noch keine allgemeine Benutzeranmeldung. Connector-Schreibwege
verwenden gescopte Mobile-Sitzungen, und die Kopplungsadministration verlangt
den separaten Setup-Bearer. Dieser enge Schutz aendert nichts an der
LAN-/VPN-Grenze fuer die Gesamt-API.

Mindestens erforderlich:

1. HTTPS-Reverse-Proxy mit gueltigem Zertifikat.
2. OIDC/OAuth2 oder ein gleichwertiger kurzlebiger Token-Mechanismus.
3. Autorisierung getrennt nach read-only, import, review und admin.
4. Restriktives CORS fuer das Web-Frontend.
5. Rate-Limits und Request-Groessenlimits.
6. Keine Secrets in Mobile-App, URL, Git, Logs oder Analytics.
7. Serverseitige Benutzer-/Mandantentrennung vor Mehrbenutzerbetrieb.
8. Auditlog fuer Schreiboperationen mit Akteur und Zeitstempel.
9. Backup-/Restore-Test fuer DuckDB und Belegartefakte.
10. Externer Security-Review vor Internetfreigabe.

Bis diese Punkte umgesetzt sind, ist ein Mobile-Client nur im eigenen VPN oder
vertrauenswuerdigen LAN fuer die dokumentierte Leseoberflaeche vorgesehen.

## Contract- und Release-Checks

```bash
pytest tests/unit/test_openapi_contract.py tests/unit/test_health.py -q
python3 scripts/export_openapi_v2.py --check
python3 scripts/generate_api_endpoint_reference_v2.py --check
curl -fsS http://127.0.0.1:8010/api/v1/health
curl -fsS http://127.0.0.1:8010/api/v1/meta/capabilities
```

Ein Breaking Change an einem empfohlenen Mobile-Endpoint benoetigt eine neue
API-Version oder eine kompatible Migrationsphase. Das Entfernen oder Umbenennen
eines Feldes, ein Wechsel von Decimal-String zu JSON-Number und eine geaenderte
Zeitzonenregel gelten als Breaking Changes.

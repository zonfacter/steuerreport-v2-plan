# API-Einrichtung, Konten und Abrufsteuerung

Stand: 26.10.2026. Unveröffentlichter Branch `feat/bedienkonzept-20261026`.
Fortsetzung von `4800837`. Kein Push, Tag, Release oder produktives Docker-Update.

## Ausgangsbefund und tatsächlicher Umfang

Vorher gab es pro CEX-Anbieter ein Credential-Set unter `secret.cex.<anbieter>.*`.
Anfragen wurden in unterschiedlichen Services unmittelbar über HTTPX oder urllib
ausgeführt. Einzelne Abläufe hatten Seiten-/Requestobergrenzen, individuelle
Timeouts und begrenzte Timeout-Retries; dies war kein gemeinsames Budget für
manuelle Abrufe, Jobs, Seiten und mehrere Prozesse. Der alte Admin-Secret-Editor
war ein unmaskiertes Textarea. Ein interner API-Erfolg war als „API verbunden“
beschriftet. In der synthetischen Vorschau fehlten Vault und Schreibprofil absichtlich.

Die neue Umsetzung umfasst UI **und** Speicherung **und** serverseitige
Durchsetzung. Sie erzeugt keine steuerliche Quellenaktivierung und ändert keine
historischen Finanzdaten. Anbietergrenzen eines echten Kontos werden nicht aus
Mockantworten oder einer Dokumentations-URL als verifiziert ausgegeben.

## Installation und Secrets

- Einrichtung: Installation → Datenanbieter → eigene Verbindungen → Abrufsteuerung
  → KI. Der frühere Einzelzugang bleibt ausdrücklich nachgeordnet erreichbar.
- Die Topbar nennt nur „Backend erreichbar“, nicht „Anbieter verbunden“.
- Profil, Datenpfad, UTC-Serverzeit und Vault-Bereitschaft werden getrennt geprüft.
  Fehlendes Profil, Softwarepfad, Symlink, fehlende Datei-/Verzeichnisrechte oder
  schreibgeschütztes Dateisystem haben konkrete Ursachen und administrative Hilfe.
- Lösungen nennen `STEUERREPORT_PRIVATE_PROFILE`, `STEUERREPORT_STATE_DIR`,
  `STEUERREPORT_V2_DB` und `STEUERREPORT_V2_SECRET_VAULT_KEY_FILE`; kein `chmod 777`.
  Eine Prüfung der Konfiguration beweist nicht die Backupqualität eines Betreiber-Volumes.
- Neue Secrets werden nur mit lesbarem Vault-Schlüssel AES-256-GCM-verschlüsselt
  gespeichert. Das gilt auch für generische Admin-Secret- und alte Jupiter/CEX-Wege.
  Ohne Schlüssel kein Speichern-Erfolg und kein Klartextfallback.
- API-Key, API-Secret und Passphrase sind standardmäßig Passwortfelder. Für
  Coinbase-PEM werden Zeilenumbrüche beim Einfügen maskiert als `\n` erhalten.
  Es gibt keinen automatischen unmaskierten Rücklade- oder Exportweg.
- Neue Verbindungen: leere Secret-Felder behalten vorhandene Werte; Entfernen ist
  eine eigene bestätigte Aktion. Legacy-Secrets bleiben lesekompatibel, auch wenn
  sie vor dieser Änderung unverschlüsselt vorlagen; keine stille Umschreibung.
- Neue UUID-Secret-Namensräume können nicht über den allgemeinen Settings-Editor
  umgangen werden. Validierungsfehler unter `/admin/` geben keine Eingaben zurück.

## Verbindungen und Jobs

`ConnectionService` verwaltet Anbieter, Anzeigename, Konto/Unterkonto, Herkunft,
geheimnisfreie Budgetgruppe, Secret-Metadaten, erfolgreichen Test, letzten Abruf
und festen Fehlercode. Zwei Konten desselben Anbieters bleiben getrennt.

1. Anbieter/Konto benennen und Zugangsdaten ausdrücklich speichern: kein Abruf.
2. Optional ausdrücklich testen: ein authentifizierter Lese-Endpunkt, kein Snapshot.
3. Optional ausdrücklich Bestand abrufen: verbindungseigener Snapshot, kein Historienimport.
4. Eigentum, Quellenregistry und Historie bleiben im vorhandenen Quellen-/Importablauf
   zu prüfen. Ein Credential-Nachweis ist kein Eigentums- oder Steuerfreigabenachweis.

Jobs sind begrenzt, haben feste Deadlines und verhindern Doppelstarts derselben
Verbindung. Auch Änderungen oder Secret-Entfernung während eines laufenden Jobs
werden abgewehrt. Abbruch wird vor Folgeanfragen und nach einem laufenden Aufruf
geprüft; bereits versandte HTTP-Aufrufe lassen sich nicht garantiert zurückholen.
Ein spätes Ergebnis nach Abbruch oder abgelaufener Deadline wird nicht als Erfolg gespeichert.

Zeitablauf allein gibt einen noch laufenden Worker nicht als frei aus. Die UI
zeigt reservierte Slots auch dann, wenn der Auftrag bereits als fehlgeschlagen
angezeigt wird. Keine automatische Fortsetzung persistierter Jobs nach Neustart.

## Durchsetzung und Zustandsformat

`domain/external_http.py` ist der gemeinsame HTTP-Einstieg. Der HTTPX-Transport
reserviert vor jedem Versuch alle geltenden Budgetgruppen gemeinsam. Folgeseiten,
Metadatenabrufe und Redirect-Hops verwenden ebenfalls diesen Transport.
Signaturen werden **nach** Quotenwartezeit und bei jedem Retry neu erzeugt.
Es werden keine API-Keys oder IP-Adressen zur Quotenvervielfachung gewechselt.

Die endgültige Startbuchung prüft die Budgets nach einer möglicherweise langsamen
Signierung erneut und verschiebt die eigene Buchung atomar auf den tatsächlichen
Dispatchzeitpunkt. Andere Requests können die Warte-/Signierzeit nicht als freies
Kontingent doppelt nutzen. Deadline und Abbruch werden erneut geprüft. Datenbank-
Refresh eines Jobabbruchs erfolgt vor der Signierung, außerhalb der Budget-Sperre;
unmittelbare Abbruchprüfungen sind danach rein speicherbasiert.

Rate-Limit-Header und Pausen werden vor dem Freigeben des Parallelitätsslots
persistiert. Ein monotoner Zeitkontext verhindert eine Deadlineverlängerung durch
eine rückwärts gestellte Systemuhr. Credential-tragende Weiterleitungen auf einen
anderen Host werden vor dem Folge-Request abgewiesen. HTTP-Fehler und Logeinträge
enthalten keine vollständigen signierten Request-URLs.

| Dimension | Tatsächliche Umsetzung |
| --- | --- |
| Sekunden / Minute | Gleichzeitig rollierende Fenster `(jetzt - Fenster, jetzt]`, nicht starre Kalenderfenster |
| Burst | Zusätzlicher Token-Bucket; hebt die rollierenden Fenster nicht auf |
| Kosten | Positive lokale Endpunktgewichte; optionales gemeinsames Minutenbudget. Ohne bestätigte Zuordnung keine Behauptung einer CU-/Creditmessung |
| Parallelität | Eigene aktive Reservierungen bis zum Ende des HTTP-Aufrufs einschließlich Body |
| Timeout / Deadline | Anfrage-Timeout und Gesamtdeadline getrennt; API-Operation und explizite Jobs behalten den zeitlichen Kontext über Folgeanfragen |
| Retry | Begrenzte Versuche, Backoff und Jitter; `Retry-After` als Sekunden oder HTTP-Datum. Dauerhafte Authfehler nicht wiederholen |
| Idempotenz | Nur GET/HEAD/OPTIONS und ausdrücklich bekannte lesende RPC-Methoden wiederholbar; keine automatischen KI-POST-Retries |
| Änderungen | Revision/CAS; belegte Starts, bestehende Pausen und aktive Aufrufe werden nicht durch Profiländerung zurückgesetzt |
| Neustart / Defekt | Persistenter Zustand, fail closed bei fehlender/defekter Koordination statt unbegrenztem Ersatzbetrieb |
| Anbieterwerte | Binance-1-Minuten-Gewicht und Jupiter-Rest/Reset sowie beobachtete Limitantworten getrennt von lokaler Nutzung |

Der konservative **lokale** Ausgangswert ist 1/s UND 30/min, Burst 1,
Parallelität 1. Dies ist keine Herstellerempfehlung oder vertragliche Obergrenze.
Betreiber können zusätzliche Profile und Endpunktkosten konfigurieren.
Leere optionale Kostenbudgets bedeuten unbekannt/nicht hinterlegt, nicht „unbegrenzter Tarif“.
Null und negative Pflichtgrenzen werden abgelehnt. Ein nicht vorhandener Zeitplan
wird als deaktiviert angezeigt, nicht als aktiver Scheduler.

Zwingende Gruppen: `provider:<anbieter>` plus `ip:global` für CEX/RPC.
KI verwendet eigene Providerkennungen und `ip:ai`. Zusätzliche Account-/Projekt-/
Budgetgruppen begrenzen gemeinsam. Bei mehreren Verbindungen gelten dieselben
Anbieterbudgets weiterhin. Die Konto-IDs selbst enthalten keine API-Keys.

Persistenz liegt unter `$STEUERREPORT_STATE_DIR/request_limits/`:
`coordinator.lock` und `coordinator.json`, Verzeichnis 0700, Dateien 0600.
Strukturiertes JSON, atomarer Austausch, fsync und hostlokales `flock` koordinieren
auch unabhängige Prozesse. Kein zusätzlicher Datenbankserver und kein SQLite.
Die bestehende Finanzdatenbank bleibt DuckDB. Diese Koordination ist für ein
hostlokales persistentes Volume, nicht für unbestätigte NFS-/Mehrhost-Locks zugesagt.

Bei Workerabsturz werden unbekannte aktive Leases **nicht** zeitgesteuert freigegeben.
Erst alle alten Worker/HTTP-Aufrufe nachweislich beenden, dann unter exklusivem
Zugriff administrative Wiederherstellung prüfen. Historie und Pausen erhalten;
nicht die Zustandsdatei löschen. Es gibt keinen unkontrollierten Resetknopf.

## Betreiberdeklarationen und Quellen

Optionale Tarifobergrenzen benötigen Anbieter, Tarif, Geltungsbereich, Datum und
öffentliche HTTPS-Referenz ohne Credentials oder Query. Sie sind vom Betreiber
deklarierte Werte, **nicht unabhängig verifiziert**. Das Backend erzwingt sie
zusätzlich zum lokalen Wunschlimit; unbekannte Dimensionen bleiben unbekannt.
Sie ersetzen keine nicht passende Anbietersemantik, etwa ein 10-Sekunden-CU-Fenster.

Quellen mit Prüfdatum liegen in `configs/provider_request_references.json` und
werden ohne Anbieterabfrage angezeigt. Maßgeblich bleiben Tarif und Endpunkt:
[Binance](https://developers.binance.info/en/docs/products/spot/rest-api),
[Bitget](https://www.bitget.com/docs/classic/rest-api),
[Pionex](https://www.pionex.com/docs/api-docs/bot-api/general-info/rate-limits),
[Coinbase](https://docs.cdp.coinbase.com/coinbase-app/api-architecture/rate-limiting),
[Solscan](https://pro-api.solscan.io/pro-api-docs/v2.0/docs),
[Helius](https://www.helius.dev/pricing),
[Alchemy](https://www.alchemy.com/docs/reference/throughput),
[Jupiter](https://developers.jup.ag/docs/portal/rate-limits),
[Solana RPC](https://solana.com/docs/references/clusters),
[OpenRouter](https://openrouter.ai/docs/api/reference/limits).

Keine universellen Herstellerzahlen voreingestellt. Negative von Jupiter gemeldete
Restwerte werden unverändert als Anbieterangabe angezeigt; der Reset öffnet einen
Slot und ist keine vollständige Fensterauffüllung.

## Request-Pfad-Inventar

| Bestehender Pfad | Gemeinsamer Einstieg |
| --- | --- |
| CEX-Bestände, neue Verbindungstests | `cex_balances` → `managed_client` |
| Binance Earn/Dividenden/Kapitalhistorie | `binance_earn` → neu signierter gemeinsamer Transport |
| Bitget-Historie | `bitget` → neu signierter gemeinsamer Transport |
| Solana-/Helius-/Alchemy-RPC, Solscan, Wallet-FIFO | `portfolio`, `tax_wallet_fifo`, `solscan_preflight`, `blockpit_solana_preflight`, `bitget_strategy_reconstruction`, `divorce_service_routes` |
| Preise, FX und Metadaten | `jupiter`, `external_price_backfill`, `bmf_event_price_remediation`, `as_of_price_gate`, ECB-Adapter |
| KI und Rechtsquellen | `ai_provider` mit getrenntem Profil; `legal_research` mit explizitem Quellenkontext |
| Optionale alte V1-Abfrage | `AdminService` → `managed_post`; kein automatischer V1-Abruf beim Öffnen der Einrichtung |
| Bisherige CLI-RPC-/Solscan-/KI-Leser | Kompatibler `managed_urlopen` statt direktem urllib-Aufruf |

Interne CLI-Relays an die eigene private `/api/v1/`-Anwendung sind keine externen
Providerrequests. Sie halten keine externe Budgetlease, während der Server seine
nachgelagerten Providerrequests begrenzt; dies verhindert einen Selbst-Deadlock.
JSON-RPC-Einzel-/Batchrequests bleiben auch an privaten Hosts unter `/api/v1/`
budgetpflichtig. Interne Relays folgen keinen HTTP-Weiterleitungen.
HTTP-Aufrufe des Container-Veröffentlichungswerkzeugs an Registry/Healthchecks
sind Infrastruktur, keine Exchange-/RPC-Connectoren; sie wurden nicht umgebaut.
Ein AST-Regressionstest verhindert neue direkte HTTP-Clientkonstruktionen in
den Anwendungsmodulen außerhalb der gemeinsamen Abrufschicht.
Die frühere zweite Timeout-Retryschleife in Binance Earn ist entfernt; die
Konfiguration des gemeinsamen Transports ist dort allein maßgeblich. Historische
CLI-Arbeitsläufe behalten ihre eigenen begrenzten Auftragsabläufe, aber jeder
externe HTTP-Versuch wird erneut durch denselben Budgetkoordinator geführt.

## Nachweise und Grenzen

Tests, Befehle und Abnahmematrix: [`api-setup/2026-10-26/`](api-setup/2026-10-26/).
Screenshots enthalten ausschließlich synthetische Daten; UI-Schreibtests nutzen
vollständig kontrollierte Mockantworten, keine produktiven Endpunkte.

Nicht implementiert oder nicht durch diese Prüfung belegt:

- Kein aktivierter periodischer Sync-Scheduler, kein tägliches/monatliches
  Abrechnungsbudget und keine automatische Tarif-/Credit-Erkennung.
- Keine verteilte Mehrhost-Koordination und kein Versprechen gleichzeitiger
  schreibender DuckDB-API-Worker. Der vorhandene Datenbankbetrieb bleibt maßgeblich.
- Kein neuer vollständiger API-Historienimport für jede Kontoverbindung.
  Verbindungseigene Snapshots werden nicht in alte globale Bestände gemischt.
- Kein vollständiger Exchange-Berechtigungsnachweis allein durch einen bestandenen
  Lese-Endpunkttest. Eigentum und fachliche Aktivierung bleiben eigene Prüfungen.
- Keine echten Providerzugänge oder Belastungsversuche, keine produktive
  Secret-Persistenzgarantie aus der schreibgeschützten Port-18014-Vorschau.
- Kein Sicherheits-/Steuer-/Finanzprodukt-Gütesiegel aus erfolgreichen Mocktests.
  Bestehende Vite-Warnung zum großen Haupt-Chunk bleibt offen.

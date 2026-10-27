# Changelog

## 0.2.0rc26 - 2026-10-27 (Releasekandidat)

- Explizite Auswahl zwischen oeffentlichem Solana-RPC (Free) und eigenem
  Helius-/Alchemy-/Custom-Zugang (Free/Premium). Auftrag an die gewaehlte
  Anbietereinrichtung gebunden; kein stiller Ersatzanbieter bei Fehlern oder
  Keywechsel. Anbieterwechsel erfordert einen neuen Auftrag.
- Kein Tarifnachweis durch einen API-Key und keine automatische Quotenerhoehung.
  Wirksame gemeinsame IP-, Anbieter- und Methodenlimits bleiben massgeblich.
- Zweiphasiges Solana-Inventar mit privaten hashadressierten Originalseiten
  und dedupliziertem Detailabruf. Abgearbeitete RPC-Listen beweisen keine
  vollstaendige Historie; Retention und geschlossene Tokenkonten bleiben Grenzen.
- Geschaetzte Restzeit nur fuer verfuegbare Transaktionsdetails nach fertigem
  Inventar und mindestens fuenf gemessenen Detailabrufen. Discovery, Pause und
  nachfolgende Vorschauberechnung erhalten keine laufende Restzeitschaetzung.
- Doku, aktive Versionsmetadaten und Packaging-Liste auf rc26 erweitert;
  synthetischer Anbieter-/ETA-Browsercheck samt Artefaktpfad in die CI aufgenommen.
  Verbindliche Pruef-, CI-, Image- und Deploymentbelege gehoeren gesondert in
  den Draft Release; lokale Teilnachweise sind in den Releasehinweisen getrennt.
- Keine Aenderung der Steuer-/FIFO-Regeln oder automatische fachliche Freigabe.

## 0.2.0rc25 - 2026-10-27

- Enthaelt die konfigurierbaren Solana-Abruflimits aus dem nicht produktiv
  ausgerollten rc24-Kandidaten. Dessen 1.818 Unit-Tests und Browserpruefungen
  bestanden; der nachfolgende Dokumentationscheck fand veraltete API-Zeilenverweise.
- API-Endpunktreferenz nach den abschliessenden Review-Korrekturen neu generiert.
  Keine weitere Aenderung der Limiter-, Import-, Preis-, Steuer- oder FIFO-Logik.
- Versionsmetadaten, Installationsvorgaben und Leitfaeden konsistent auf rc25.
  rc24-Tag bleibt unveraendert; der Kandidat wird nicht produktiv verwendet.

## 0.2.0rc24 - 2026-10-27 (nicht produktiv ausgerollter Kandidat)

- Solana-Public-Free-Voreinstellung zentral unter Einrichtung / Abrufsteuerung,
  mit ausdruecklicher Bestaetigung, Quellreferenz, Pruefdatum und Konfliktpruefung.
  Konservative gemeinsame Vorgabe: 3 Requests/s, 30 je 10 Sekunden, 180/min.
- Editierbare rollierende 10-Sekunden-Fenster und einzelne Endpunktprofile
  zusaetzlich zu gemeinsamen IP-, Anbieter-, Minuten-, Burst- und Parallelitaetsbudgets.
- Transport reserviert alle passenden Budgets vor jedem Start einschliesslich
  Wiederholungen; Konfigurationsaenderung behaelt bisherige Starts und Pausen.
- Verstaendliche lokale Wartegruende, neue Einstellungen im Benutzerleitfaden
  und dokumentierte Grenzen bei fremdem IP-Verkehr und nicht gemessenem Bytebudget.
- Speichern startet keine externen Abrufe, Importe, Neuberechnungen oder
  Freigaben. Steuer-/FIFO-Regeln und historische Finanzdaten unveraendert.

## 0.2.0rc23 - 2026-10-27

- Die freizugebende Historienvorschau zeigt normalisierte Ereignisse mit
  UTC-Zeitpunkt, Asset, exakter Menge, Gegenmenge und Gebuehren. Unterschiedliche
  Binance-/Bitget-/Coinbase-/Pionex-Rohspalten erzeugen keine leeren Werte mehr.
- Die Stichprobe gehoert zur hashgebundenen Berechnungsvorschau und ist auf
  zehn neue Ereignisse begrenzt. Reine Dubletten ergeben keine neue Ereignisstichprobe.
- Kauf-/Verkaufstest prueft die sichtbaren Vorschauwerte zusaetzlich zur
  unveraenderten Preisuebernahme und reproduzierbaren Gewinnberechnung.
- Handelspaar-Beispiele unterscheiden Pionex (`BTC_USDT`) von Binance (`BTCUSDT`).
- Keine Aenderung der Steuer-, FIFO- oder Preisberechnungsregeln und keine
  automatische Korrektur historischer Finanzdaten.

## 0.2.0rc22 - 2026-10-27

- Ergaenzender Kauf-/Verkaufstest belegt die atomare Uebernahme abgeleiteter
  Preise in `price_ledger`, den Erhalt vorhandener Originalpreise und ein
  identisches Ergebnis nach erneuter Berechnung. Keine fachliche Codeaenderung
  war fuer diesen zusaetzlichen Nachweis erforderlich.
- Enthaelt den automatischen Quellenimport aus dem nicht produktiv ausgerollten
  rc21-Kandidaten. Dessen GitHub-Frontendpruefung fand einen portabilitaetsbedingten
  Testfehler, keine bestaetigte Finanzdatenabweichung.
- Neuer Browser-Test nutzt Playwrights installierten Browser oder einen
  ausdruecklich uebergebenen Pfad. Kein Zugriff auf ein fremdes `/root`-Verzeichnis
  bei Programmstart; Pruefung auch unter einem unprivilegierten Benutzer.
- Versionsvertraege und Leitfaeden aktualisiert; bestehende Tags bleiben
  unveraendert. Keine historische Datenmigration oder automatische Einordnung.

## 0.2.0rc21 - 2026-10-27

- Automatischer Historienabruf fuer die ausgewaehlte Solana-Wallet oder einzelne
  Boersenverbindung; CSV-/Excel-Import bleibt ein zusaetzlicher Weg.
- Solana-RPC und begrenzte Spot-Historienadapter fuer Binance, Bitget Classic,
  Pionex und Coinbase Advanced mit ausdruecklichen Abdeckungsgrenzen.
- Dauerhafte Jobs mit Seitenfortschritt, Pause, Fortsetzen und Abbruch;
  gemeinsame Abruflimits auch fuer Pagination und Wiederholungen.
- Originalbelege und SHA-256-gebundene Vorschau in privater Berechnungskopie;
  erst getrennt bestaetigter Import und Neuberechnung uebernehmen atomar.
- Konto-/Walletbindung und konfliktpruefende Wiederholung; ueberlappende alte
  CEX-Dateidaten blockieren ohne belegte gemeinsame Identitaet statt Doppelbuchung.
- Unklare erfolgreiche Auszahlungen bleiben mit Originalbeleg und blockierendem
  Review erfasst; keine erfundenen Mengen, Gebuehren, Trades oder Rewards.
- Abbruch bleibt auch bei abgelaufenem Workerfenster wirksam; persistierte
  Abbruch-/Pauseabsicht wird ausserhalb der Kontingent-Sperre nachgelesen.
- Hilfe, Benutzerleitfaden, Inbetriebnahme und API-Vertrag erweitert. Keine
  automatische Aenderung historischer Finanzdaten oder steuerliche Freigabe.

## 0.2.0rc20 - 2026-10-27

- Direkter Solana-Historienimport erkennt bereits gespeicherte Transaktionen
  anhand von Wallet und Signatur auch bei ueberlappenden Abrufseiten. Reine
  Wiederholungen starten keine erneute Normalisierung oder Steuerberechnung.
- Netzwerkgebuehr wird nur dem nachgewiesenen Gebuehrenzahler zugeordnet und
  genau einmal abgezogen. Fehlgeschlagene Transaktionen erzeugen keine Trades.
- Bloesse RPC-Bestandsdifferenzen werden nicht automatisch zu Handel, Einkommen
  oder Rewards. Ungeklaerte Bewegungen sperren den finalen Export zur Pruefung.
- Originalantworten bleiben an den erzeugten Rohzeilen erhalten; exakte Mint-
  Identitaeten werden nicht mehr durch Grossschreibung oder Kuerzung vermischt.
- Fehlende Transaktionsdetails brechen eine Seite vor dem Import ab. Abweichende
  Altbelege und unvollstaendige Vorimporte erfordern Pruefung statt Ueberschreiben.
- Gemeinsame dateibasierte Importsperre verhindert konkurrierende Historienimporte
  derselben Datenbank. Keine automatische Migration historischer Finanzdaten.

## 0.2.0rc19 - 2026-10-26

- Gespeicherte Solana-Bestandspositionen erscheinen auch ohne importierte Historie
  und ohne EUR-Preise unter Quellen / Bestaende, mit Datenstand und Abrufbezug.
- Quellenliste zeigt Positionen und fehlende Bewertungen getrennt von Ereignissen.
  Dashboard fuehrt direkt zum Anbieterbestand; unbekannter Live-Wert ist nicht 0 EUR.
- Neue optionale lesende Felder live_balance und Live-Zusammenfassung. Vollstaendig
  bestaetigte Leerbestaende bleiben von fehlenden oder unbewerteten Daten getrennt.
- Bestehender Erfolgsstand bleibt nach fehlgeschlagenem Versuch sichtbar; keine
  Uebertragung des Profilwallet-Snapshots auf andere Beobachtungsadressen.
- Keine neuen Anbieterabrufe durch die Ansicht, keine Umwandlung von Snapshots
  in Transaktionen, Eigentums-, FIFO- oder Steuerfreigaben.

## 0.2.0rc18 - 2026-10-26

- Enthaelt den Solana-RPC- und Fehlermeldungs-Patch des nicht veroeffentlichten
  rc17-Kandidaten, mit erneut geprueftem Gesamtstand.
- Bestehende Test-Isolationsluecke geschlossen: Docker-Bootstrap-Umgebungsvariablen
  werden in der Fixture zurueckgesetzt und laufen nicht in spaetere CEX-Tests aus.
  Produktiver Vault-Zwang und Verschluesselung bleiben unveraendert.
- rc17-Tag bleibt unveraendert; dessen Release-Entwurf wurde nach fuenf Fehlern
  im lokalen Gesamtlauf zurueckgezogen. Kein produktives rc17-Update.

## 0.2.0rc17 - 2026-10-26 (zurueckgezogener Entwurf)

- Solana-Bestandsabruf verwendet den vorhandenen oeffentlichen oder konfigurierten
  RPC auch ohne Alchemy-Schluessel. Gespeicherte Helius-Zugaenge werden beruecksichtigt.
- Nur vollstaendige RPC-Antworten koennen einen leeren Bestand bestaetigen;
  fehlerhafte Teilantworten ersetzen keinen erfolgreichen historischen Stand.
- RPC-Fehler enthalten keine Zugangsdaten, sensiblen Pfade oder Anbieter-Freitexte.
- Quellen zeigen den konkreten letzten Fehler und einen Einrichtungseinstieg.
  Ohne vorherigen Erfolg wird kein angeblich erhaltener Erfolgsstand behauptet.
- Bestehende Abruflimits, Import-, Quellenfreigabe-, Steuer- und FIFO-Regeln bleiben
  unveraendert. Tests nur mit simulierten Anbietern und synthetischen Daten.

## 0.2.0rc16 - 2026-10-26

- Oeffentliche Solana-Adressen im normalen Quelle-hinzufuegen-Ablauf speichern:
  optionaler Name, Adresse, Zusammenfassung und Speichern. Kein Setup-Passwort
  und keine Signatur fuer diese Adresskonfiguration erforderlich.
- Mehrere Adressen getrennt und persistent; doppelte Eingaben sind idempotent.
  Bestehende Pruefungen werden nicht zurueckgesetzt oder automatisch erneuert.
- Eigene Quellen zeigen auch noch nicht importierte Adressen und bestehende
  private Profilwallets. Unbekannte Werte bleiben unbekannt; keine fiktiven Bestaende.
- Optionaler Eigentumsnachweis bleibt getrennt und unveraendert authentifiziert.
  Keine automatische Quellenregistry-, FIFO- oder Steuerfreigabe.
- Anleitung und API-Vertrag aktualisiert; lokale Host-/Origin-Grenzen und
  Demo-Schreibsperre bleiben wirksam. Keine Schemaaenderung erforderlich.

## 0.2.0rc15 - 2026-10-26

- Geschuetzte lokale Connector-Inbetriebnahme mit zufaelligem Passwort in einer
  privaten Datei, idempotenter Aktivierung und ausdruecklicher Konsolenanzeige.
- Neue Docker-Installationen werden vorbereitet; bestehende Installationen
  werden nicht durch ein Update still freigeschaltet. Vorhandene Keys bleiben erhalten.
- Eigener Bereich Wallet-Eigentumsnachweis unter Einrichtung mit Status,
  lokalen Bootstrap-Befehlen und klarer Trennung vom Boersen-/Wallet-Passwort.
- Konkrete Hilfe statt der pauschalen Connector-Schreibfreigabe-Meldung;
  Passwort vor Challenge erforderlich, Authentifizierungsfehler nachvollziehbar.
- Inbetriebnahme und HTML-/PDF-Benutzerleitfaden ergaenzt. Kein Einrichtungspasswort
  ueber Web-API, URL, Browser-Storage oder Export; keine anonyme Freischaltung.
- Strikte Ed25519-Schluessel- und Signaturpruefung mit PyNaCl/libsodium;
  ungueltige beziehungsweise schwache Punkte werden auch bei alten Challenges abgewiesen.
- Wallet-Signatur, Quellenregistry und steuerliche Freigaben bleiben unveraendert.

## 0.2.0rc14 - 2026-10-26

- API-Einrichtung nach Installation, Datenanbietern, eigenen Verbindungen,
  Abrufsteuerung und KI getrennt; Demo-Modus ausdrücklich schreibgeschützt.
- UUID-basierte Mehrkontenverwaltung mit verschlüsselten Zugangsdaten,
  getrennten Bestands-Snapshots und ausdrücklich bestätigten Test-/Abrufjobs.
- Gemeinsamer persistenter Abrufkoordinator für rollierende Sekunden-/Minutenlimits,
  lokale Endpunktkosten, Parallelität, Pausen, Retries und Gesamtdeadlines.
  Hostlokale Worker teilen atomar dieselben Budgets; kein stiller Fallback.
- Betreiberdeklarierte Tarifobergrenzen, Quellen und tatsächliche Anbieterheader
  getrennt von lokalen Nutzungswerten. Kein automatischer periodischer Sync.
- Secret-Felder maskiert; alte Admin-Schreibwege ebenfalls ohne Klartextfallback.
  Vorhandene Legacy-Zugänge bleiben unverändert lesbar und werden nicht aktiviert.
- Nachprüfung R1: Aufgabenpanel unterscheidet initiales Laden, API-Fehler mit
  Wiederholen und bestätigten Leertreffer. ID-Abfrage bleibt unabhängig von der
  Listenseite; Filter und Rückweg bleiben erhalten. Kontrollierte Verzögerungs-,
  Fehler- und Aufgabenwechseltests im bestehenden Browserlauf ergänzt.
- Review-Nacharbeit: kontobezogene Aufgaben in Quellenliste, Abgleichfilter und
  Quellendetail konsistent verknüpft; Quellen-/Bewertungshinweise bleiben getrennt.
- Direkter Absprung zur betroffenen Konto-/Asset-Ledgeransicht mit Rückweg zur
  Review-Aufgabe; mehrdeutige Zuordnungen werden nicht automatisch entschieden.
- Fester EUR-Referenzwert statt technischem Epochendatum; kompakte Mengen mit
  exaktem aufklappbarem Wert, sprachliche Korrekturen und Testumgebungshinweis.
- Ergänzende F1–F3-Browserprüfung gegen das echte Backend mit isolierter
  synthetischer Datenbank, einschließlich tatsächlichem Testimport und Hashprüfung.
- Eigene Quellen statt Anbieter-Katalog als Einstieg, geführtes Hinzufügen,
  Quellendetail mit Beständen, Transaktionen, Abgleich und Einstellungen.
- Paginierte Transaktionen und Ledger, beleggebundene Details sowie CSV-Export
  mit ausdrücklich gewähltem Umfang. `#flows` und die Flussansichten bleiben erhalten.
- Gemeinsame Filter-, URL-, Lade-/Fehler- und Detailmuster; vertrauliche Suche
  bleibt im Arbeitsspeicher. Dashboard, Review und Jahresberichte aufgeräumt.
- Konservative zentrale Jahresstatusanzeige auf Basis bestehender Fach-Gates;
  Null, unbekannt, leer und laufende Prüfung werden nicht gleichgesetzt.
- Bestätigung externer Abrufe/Neuberechnung, Sperre paralleler zentraler
  Vorgänge, korrekte Kennzeichnung des schreibenden ZIP-Cache-Endpunkts.
- Synthetische Browserabnahme in vier Bildschirmbreiten, isolierte Vorschau
  ohne Betreiberprofil oder externe Verbindungen und dokumentierte Übergabe.
- Keine Änderung der Steuer-/FIFO-/Ownership-Regeln und keine Änderung
  historischer Nutzerdaten. Versionierter Release mit Docker-Image;
  vorhandene Datenvolumes und Vault-Schlüssel bleiben beim Update erhalten.
- Anbieterreferenzen in Docker und Software-ZIP eingeschlossen; der Image-Smoke-Test
  prüft auch Mehrkonten-, Limit- und Anbieterreferenz-Endpunkte einer leeren Installation.
- Grenzen: kein automatischer Sync-Zeitplan, keine Tages-/Monatsabrechnungsbudgets,
  kein eigener persistierter Jobstatus für Anbieterpausen und keine Mehrhost-Koordination.

## 0.2.0rc13 - 2026-10-26

### Benutzerfuehrung und Hilfe

- Zentrale Hilfeseite mit Suche, Bereichsfilter, 13 Arbeitsablaeufen,
  5 haeufigen Fragen und 10 Begriffserklaerungen.
- Bereichshilfe im separaten Tab ohne Verlust ungespeicherter Eingaben;
  alle mitgelieferten HTML-/PDF-Anleitungen an einer Stelle erreichbar.
- Fragezeichen-Tooltips fuer Hover, Tastatur und Touch mit Escape- und
  Aussenklick-Schliessen sowie Positionierung im sichtbaren Bereich.
- Ablaufnavigation von Einrichtung bis Export; mobil kompakt aufklappbar.
- Konkrete Voraussetzungen bei deaktivierten Import- und KI-Aktionen.
- Gespeicherte KI-Verbindung und technische Administration eingeklappt;
  neue Installationen zeigen die erforderliche KI-Einrichtung weiterhin.
- Leeren Expertenwerkzeug-Umschalter entfernt; aktiven Navigationsbereich
  und globalen Auswertungsstatus eindeutiger gekennzeichnet.

### Pruefung und Betrieb

- Reproduzierbarer Browser-Test mit ausschliesslich synthetischen
  API-Antworten fuer Desktop und Mobilgeraete in die CI aufgenommen.
- Release-Ablauf mit Changelog, unveraenderlichen Tags, GitHub-Entwurf,
  Backup, Rollback und produktiver Nachpruefung in AGENTS.md festgehalten.
- Keine Aenderung an steuerlicher Berechnung, API-Fachvertraegen,
  KI-Berechtigungen oder Nutzerdaten. Kein automatischer Modellaufruf.
- Bestehende Build-Warnung zum grossen Frontend-Haupt-Chunk bleibt offen.
  Durchgaengige Verlassenswarnungen fuer alle aelteren Formulare sind
  nicht Bestandteil dieser Version.

## 0.2.0rc12 - 2026-10-25

- Sieben konfigurierbare KI-Fachagenten mit versioniertem Anwendungswissen
  und Modellzuordnung fuer lokale und Cloud-Verbindungen.
- Enthalten ist der mit RC11 getaggte Korrekturgrundstand: ausgewaehlte
  Datenzeilen, isolierte Berechnungsvorschau, menschliche Freigabe,
  atomare Uebernahme, Audit und gesondert freizugebende Ruecknahme.
- Der damalige native DuckDB-Prozessabsturz im ersten CI-Versuch ist im
  RC12-Pruefbericht dokumentiert. Erfolgreiche Wiederholungen sind kein
  Nachweis einer abschliessend behobenen Absturzursache.

Die vorherigen Versionen sind ueber die bestehenden Git-Tags und
GitHub-Releases nachvollziehbar. Bestehende Tags werden nicht ersetzt.

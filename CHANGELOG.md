# Changelog

## Unreleased

## 0.2.0rc39 - 2026-10-30 (Releasekandidat)

- GitHub #30: Eine lesende Hostdiagnose zeigt Dateisystem- und Inodekapazitaet
  sowie aggregierte Docker-Werte. Unvollstaendige Abfragen bleiben Teilstatus;
  gemeldeter Reclaimable-Speicher ist keine Bereinigungsfreigabe. Das Werkzeug
  entfernt keine Dateien, Images oder Volumes.
- GitHub #31: Die Installationsanleitung nennt wieder den aktuellen Release und
  einen passenden Image-Tag. Ein Test prueft diese Angaben auf Versionsdrift.
- GitHub #30: Der Docker-Build trennt gepinnte Runtime-Abhaengigkeiten vom
  Quellcode. Ein Zwei-Build-CI-Test prueft die Layer-Wiederverwendung und
  isolierte Containerpfade; alte Images werden nicht automatisch entfernt.

## 0.2.0rc38 - 2026-10-30 (Releasekandidat)

- GitHub #13: Binance-Spot-CSV/API-Abgleich ist im Historienauftrag als
  ausdrueckliche Einzelentscheidung bedienbar. Die Vorschau zeigt beide
  normalisierten Finanzbelege und bindet stabile Trade-ID, Handelspaar,
  Zeilennummer, Dateihash und Verbindung. Nicht bestaetigte Overlaps sowie
  ungebundene Rohimporte bleiben gesperrt; spaete oder widerrufene
  Entscheidungen aendern keine bereits importierten Ereignisse. Entscheidung,
  CSV-Import und komplette lokale API-Vorschauvorbereitung teilen eine Sperre;
  spaetere Aenderungen machen den Vorschauhash ungueltig. Der Lock gilt nur fuer
  den dokumentierten Einprozessbetrieb; keine Benutzeridentitaet wird durch das
  freie Akteursfeld authentifiziert.
- GitHub #22: Gefuehrte Bitget-Dateiimporte speichern Zeitzone und Produktscope
  als Kontext am Importbatch. Alte Rohbelege bleiben unveraendert und werden als
  nicht verifizierter Legacy-Kontext markiert. Das ordnet Futures, Spot,
  Gebuehren oder Gegenlegs nicht automatisch steuerlich zu. Leerzeichenwerte
  umgehen Pflichtfelder nicht; nichtkanonische Quellen werden normalisiert,
  ungueltige Zeitstempel vor dem Speichern blockiert. Eine ungueltige oder
  unvollstaendige gefuehrte Vorschau verwendet keinen irrefuehrenden UTC+08-
  Fallback und meldet betroffene Zeilen nicht als normalisierbar; die
  Kontoidentitaet bleibt stabil an der Verbindung. Legacy-Rohpfade weisen ihren
  UTC+08-Fallback ausdruecklich als nicht verifiziert aus. Widersprueche zwischen
  Zeitwert, UTC-Spaltenkopf und gewaehlter Exportzeitzone blockieren die Vorschau,
  statt still eine widersprechende Zeit anzuwenden.
- GitHub #22: Gefuehrte Isolated-Margin-Imports blockieren eine nicht numerische
  oder nicht null betragende Gebuehr ohne belegtes Gebuehrenasset. Das ist keine
  automatische Zuordnung separater Gebuehren und schuetzt nicht die alten
  Rohimportpfade ohne Produktscope.
- Schema 3 setzt fuer migrierte und neue Importbatches dieselbe NOT-NULL-Regel.
  Neuere Datenbankschemata werden vor Schemaoperationen abgewiesen. Fuer den
  Rueckweg zu einem aelteren Image bleibt ein Schema-2-Backup erforderlich; ein
  separater lesender Vergleichshelfer prueft isolierte Datenbankkopien.
- Die Aenderungen nehmen keine automatische Datenmigration aus dem nativen
  Bestand, keinen Historienimport und keine Methodenaktivierung vor. Eine
  Containeraktualisierung ist getrennt abzusichern und nachzuweisen.

## 0.2.0rc37 - 2026-10-29 (Releasekandidat)

- GitHub #4: MEXC-XLSX mit mehreren Tabellenblaettern verlangt jetzt eine
  ausdrueckliche Blattwahl. Vorher werden keine Tabellenzeilen als gepruefte
  Importvorschau dargestellt.
- GitHub #10: Regression fuer einen formal gueltigen, aber nicht passenden
  Vault-Schluessel. Der Containerstart muss vor Uvicorn abbrechen und den
  bestehenden Zustand bytegleich erhalten.
- GitHub #13: Der Historienabruf erklaert jetzt, dass eine Kontobindung allein
  keinen CSV/API-Belegabgleich beweist. Ungeklaerte Ueberlappungen bleiben
  gesperrt; Zeit und Betrag werden nicht als automatische Identitaet verwendet.
- GitHub #22: Bitget-CSV toleriert ausschliesslich leere Zusatzfelder hinter
  der Kopfzeile. Nichtleere Zusatzfelder werden mit Zeilenhinweis abgewiesen;
  die Preview-API liefert einen strukturierten Fehler statt HTTP 500. Raw-Zeilen,
  Originalhash und identischer Wiederimport sind regressionsgetestet.
- GitHub #26: Bitget-CSV-Text, Base64-Datei und Importassistent verwenden
  dieselbe Ueberhangvalidierung. Strukturfehler liefern ueber Preview-, Raw-
  und Execute-Routen einen zeilengenauen API-Fehler, auch hinter den ersten
  fuenf Vorschauzeilen. Leere Zusatzfelder bleiben erlaubt; Originalhash und
  bisherige Erkennung von Kopfzeilen unter Exporttiteln bleiben erhalten.
- Keine Legacy-Datenmigration, keine Produktiv-Neuberechnung oder
  Methodenaktivierung. #8, #13, #19, #20 und #22 bleiben teilweise offen.

## 0.2.0rc36 - 2026-10-29 (Releasekandidat)

- GitHub #12: Solana-Ownership-Konfiguration wird beim Speichern und Laden
  strikt typisiert. Fehlende optionale Datei, ungueltiger vorhandener Inhalt
  und nicht lesbarer Bestand sind getrennt; ungueltige Datei blockiert die
  Normalisierung statt unowned TxIDs still zu verwerfen. Audit-Metadaten bleiben
  erhalten, ungueltige Speicherversuche schreiben weder Datei noch Revision.
- GitHub #10: Der Docker-Entrypoint blockiert vor Schreibzugriffen und Uvicorn,
  wenn der Vault-Schluessel fehlt oder vorhandene verschluesselte Secrets damit
  nicht entschluesselt werden koennen. Eine Profil-Erstprovisionierung braucht
  einen ausdruecklichen Einmalschalter; vorhandene Schluessel werden nie ersetzt.
- GitHub #13 (Teilumfang): Binance-Spot-Dateiimporte koennen an eine explizit
  ausgewaehlte Verbindung gebunden werden; die Bindung bleibt am Importbatch.
  Alte ungebundene Batches werden nicht still migriert. Quellenuebergreifender
  CSV/API-Identitaetsabgleich und eine dauerhafte Matchentscheidung sind offen.
- GitHub #14 (Teilumfang): Binance-Earn-Historienservice kann Zugangsdaten einer
  konkreten Verbindung nutzen und faellt in diesem Modus nicht auf globale
  Legacy-Secrets zurueck. Vollstaendige HistoryJob-/Importintegration und
  ausgewiesene Kontenabgrenzung bleiben offen.
- GitHub #15: Manueller, hashgebundener Einzelbelegpfad fuer offene historische
  EUR-Preisbedarfe. EUR direkt oder USD nur mit Original-FX-Beleg und
  bestehender Sieben-Tage-Referenzpolicy; Vorschau isoliert, Apply mit Akteur
  und zwei bestaetigten Schritten. Kein Provider-/KI-Aufruf, kein Default-FX,
  keine Aenderung des bestehenden EUR-CSV-Imports.
- BMF-Methoden-Pruefstaende koennen in der Steuerjahresansicht ausdruecklich
  fuer den Gesamtumfang 2021-2025 erzeugt oder erneuert werden. API und UI
  zeigen Eingangsbindung, Laufstatus und Konflikte; veraltete Eingaben werden
  nicht als aktueller Pruefstand dargestellt. Keine Steuerdatenkorrektur oder
  finale Freigabe.
- GitHub #17: Review-Aufgaben und Ereignisdetails fuehren mit stabiler Ziel-ID,
  Jahres-, Quellen-, Aufgaben- und Rohbelegreferenz in den manuellen
  Korrekturablauf. Veraltete Zielrevisionen werden exakt verglichen und nur
  nach ausdruecklicher Pruefung als neue, verknuepfte Entwuerfe angelegt;
  alte Entwuerfe und Freigaben bleiben unveraendert.
- Der manuelle Modus benoetigt keine Anbieter-/Agentenkonfiguration und startet
  keine Modell- oder externen KI-Aufrufe. Bestehende Patchfelder, Vorschau,
  Belegpruefung und menschliche Freigabegates bleiben unveraendert.
- GitHub #18: Steuerjahresbezogene PDF-Vorschauen koennen ausdruecklich erzeugt,
  im append-only Archiv aufgelistet und samt Manifest/Hashes heruntergeladen
  werden. PDF, Manifest und Jahreszahlen sind an denselben Lauf gebunden; jedes
  Artefakt bleibt als Vorschau ohne finale Abgabefreigabe gekennzeichnet.

- GitHub #4: MEXC Spot Statement und Funding Other koennen nach ausdruecklicher
  Konto-, Exportart- und Zeitbasiszuordnung als beleggebundene XLSX-/CSV-Dateien
  geprueft und importiert werden. Die Exportart wird vor der ersten Pruefung
  je Datei festgelegt; Kontextwechsel verwerfen alte Vorschauen und
  Zeilenentscheidungen. Snapshot-/BONUS- und andere Produktbelege
  erzeugen keine erfundenen Erwerbe oder Gewinne; Airdrop bleibt fachlich offen.
  Dublettenkandidaten erfordern eine begruendete Zuordnung.
- Nichtleere Funding-Statuswerte bleiben ohne belegte Anbietersemantik reine
  Rohbelege/Review statt scheinbar abgeschlossener Bestandsbuchungen.
- Der MEXC-Importassistent verwendet eine einzige, korrekt geschlossene
  Auswahlstruktur fuer Konto, Datei und Pruefung; doppelte Dateieingaben wurden
  entfernt.
- GitHub #9: Der Container-Publish prueft vor und nach dem Push einen
  synthetischen Dateiimport bis zum Jahresbericht und Abgabepaket sowie die
  Persistenz ueber einen Containerneustart. Der Ablauf verwendet ein frisches,
  netzwerkisoliertes Testvolume und keine KI-/Provider-Endpunkte.
- GitHub #22: Die CSV-Vorschau toleriert zusaetzliche leere Endfelder, behaelt
  die geparste Raw-Zeile bei und blockiert nichtleere Felder hinter der
  erkannten Kopfzeile, statt sie still zu verwerfen.

## 0.2.0rc35 - 2026-10-28 (Releasekandidat)

- Der reale GitHub-Releasekatalog enthaelt nach Entpacken etwa 606 KB inklusive
  Asset-Metadaten. Das Seitenlimit steigt begrenzt von 512 KiB auf 1 MiB;
  Gesamtbudget 2 MiB, maximal fuenf Starts, zentrale Quoten und keine
  Transport-Retries bleiben unveraendert. Grosse Antworten werden weiterhin
  begrenzt; keine Umgehung des gemeinsamen HTTP-Transports.
- Regression fuer grosse, gueltige Asset-Metadaten im produktiven Transportpfad.
  Keine Aenderung von Steuerformeln oder Finanzdaten durch die Versionspruefung.

## 0.2.0rc34 - 2026-10-28 (Releasekandidat)

- Uebernimmt die unten dokumentierten rc33-Aenderungen. rc33 wurde nicht
  veroeffentlicht; sein vorhandener Tag bleibt unveraendert erhalten.
- Die isolierte HTTP-Transportprobe verwendet fuer Scope und Limiter dieselbe
  kuenstliche Uhr. Neue Faelle fuer kurze und lange Maschinenlaufzeiten
  verhindern die auf frischen CI-Runnern erkannte Zeitdomaenen-Verwechslung.
  Keine Aenderung der Produktivberechnung oder der Abruflimiter-Regeln.

## 0.2.0rc33 - 2026-10-28 (Nicht veroeffentlichter Kandidat)

- GitHub #2: Bitget-Financial-CSV mit Date, signierten Futures-Gebuehren,
  Funding und neutralen Margin-Aktionen; explizite Nettoexporte ohne doppelten
  Gebuehrenabzug. Generische Derivative-Zeilen erhalten ihre Gebuehrenbeine.
  Alte Ableitungen und widerspruechliche Brutto-/Netto-Normalisierung erzeugen
  Review-Sperren statt einer stillen produktiven Datenkorrektur.
- GitHub #3: Backend-Versionsanzeige und Einrichtung fuer stabile/RC-Releases,
  ausdrueckliches Opt-in, begrenzte GitHub-Abfragen und persistenter lokaler Cache.
  Releasegebundener KI-Updateauftrag mit Zwischenablagefallback und TXT/JSON;
  kein automatisches Deployment und keine erfundenen Commit-/Image-Nachweise.
- Update-Praeferenzen und Metadatencache sind explizit von finanziellen
  Vorschau-Fingerprints ausgenommen; neue Fingerprint-Version erfordert fuer
  bereits gebundene alte Vorschauen eine erneute ausdrueckliche Berechnung.
- GitHub-Issue-Abschlusspruefung: 2722 Unit-Tests bestanden, vier bekannte
  private Belegskips; 52 urspruengliche, 104 erweiterte Referenzen und der
  unveraenderte 15-Fall-Bitget-Reproducer bestanden. Gemeinsamer HTTP-Limiter
  auch fuer GitHub, keine Ausnahme vom bestehenden Architektur-Guard.
  Originalnachweise und Browserbilder unter `docs/audit/2026-10-28/issues/`.
- Historische Ersatzkurse, SQL-Coverage und Ableitungen verwenden denselben
  konservativen Tages-/Zeitvertrag; keine verdeckte Altpreis-Wiederverwendung.
- Private Kalenderjahresfrist in Europe/Berlin fuer Python, SQL, Planung und
  CSV; Archivvergleiche erhalten die urspruenglich gespeicherte Klassifikation.
- Technische Vorschau und finale Jahresfreigabe getrennt; gebundene PDF- und
  Jahrespakete sowie Daten-/Methodenbindung der BMF-Pruefstaende.
- Separat ausgewiesene EUR-Erwerbsgebuehren in der Kostenbasis; ungepruefte
  Nullbasis und nicht vollstaendig modellierte Gebuehren-Token bleiben Review.
- Lesende, jahresabhaengige Freigrenzen-Arithmetik erfordert ausdrueckliche
  Angaben zu anderen privaten Veraeusserungen und erteilt keine Jahresfreigabe.
- Drittassetgebuehren mit eigenem Lotverbrauch, richtungsgebundene historische
  FX-Referenzen sowie beleggebundene Tokenidentitaet und Umstellungen.
- Lesende Lot-Herkunft durch Transfers und Umstellungen einschliesslich
  Zwischenbelegen, Vorjahresurspruengen und konsistenten Review-Sperren.
  Herkunftsdetails bleiben im Steuerjahr einsehbar; keine Sphaerenfreigabe.
- Vorherige Lot-Herkunft-Pruefung: 2629 Unit-Tests bestanden, vier bekannte
  private Belegskips; 52 urspruengliche und 87 zusaetzliche Referenztests
  bestanden. Originalausgaben, Matrix, Diff und Grenzen im Auditordner.
- Isolierte Restore-/Browser-/Referenzpruefungen und verbleibende Grenzen im
  Auditordner. Die urspruenglichen Nachweise bleiben als Entwicklungsnachweise
  unveraendert erhalten. Die Veroeffentlichung dieser Version aktualisiert
  keine Finanzdaten automatisch und aktiviert keine neue produktive
  FIFO-Methode.

## 0.2.0rc32 - 2026-10-28 (Releasekandidat)

- Automatische historische Preissuche mit nahen DefiLlama-Zielzeitpunkten
  und belegtem Native-SOL-Fallback nur fuer native SOL-Bewegungen beziehungsweise
  nachgewiesene native SOL-Gebuehren. Keine globale WSOL-Paritaet, kein
  Symbolraten fuer andere Mints und keine automatische Tokenfreigabe.
- Zeitregeln unveraendert: derselbe UTC-Tag, Quote nicht nach erstem Ereignis,
  hoechstens eine Stunde Abstand zum urspruenglichen Ziel. Tatsaechlicher
  Quote-Zeitpunkt und Originalbelege bleiben erhalten; keine Zukunftsquotes.
- Automatische Fortsetzung ausstehender Preisabschnitte nach ausdruecklicher
  Zustimmung. UI-Gesamtbudget standardmaessig 200 HTTP-Starts, einstellbar bis
  1000; hoechstens 50 je Abschnitt einschliesslich alternativer Suche, Retry
  und FX. Kein automatischer Preisimport, keine Uebernahme der Neuberechnung
  oder steuerliche Entscheidung.
- Legacy-Preiszuordnungen lesen grossgeschriebene Asset-Aliase nicht als
  rekonstruierte Original-Mints. Erhaltene Schreibweise aus einer exakten
  `solana:`-Provider-ID bleibt nutzbar; fehlende Identitaetsbelege bleiben offen.
- Synthetische 20-Tage-Regression fuer den begrenzten Native-SOL-Fallback.
  Gefundene Tagespreise schliessen keine Klassifizierungsfragen.
  Reale Installationszahlen und private
  Diagnoseergebnisse sind keine oeffentlichen Release-Artefakte.

## 0.2.0rc31 - 2026-10-27 (Releasekandidat)

- Historische EUR-Ermittlung fuer alle erkannten Token und Jahre direkt in
  der Anwendung, einschliesslich Transfers, Gegenwaehrungen und Gebuehren.
  Engerer steuerlicher Preisbedarf bleibt als separater Modus erhalten.
- Original-Mint-Pruefung, globale Symbol-/Mint-Konflikte, Spam-Sperren und
  echte Same-Day-Deckung statt Altpreisen aus Vorjahren.
- Begrenzte DefiLlama-Sammelabfragen, historische EZB-Serien und fortsetzbare
  Abschnitte mit kumulativer Vorschau; Listenpagination begrenzt keinen Abruf.
  Anbieterfehler, Budgetwartepositionen und bereits vorhandene Preise bleiben
  getrennt. Statuswiederherstellung loest keine externen Abfragen aus.
- Vollstaendige Jahresdownloads als JSON, Markdown und deterministisches ZIP
  mit CSV, Originalantworten und SHA256; keine privaten Skripte oder KI noetig.
- Preisvorschau rechnet eingefrorene Ereignisse neu, ohne Rohnormalisierung
  oder erneutes Einspielen von Ereigniskorrekturen. Quellgleichheit wird vor
  und nach der Berechnung sowie bei atomarer Uebernahme geprueft.
- CSV-Preisimport uebernimmt alle validierten Zeilen, nicht nur die ersten
  50 Vorschauzeilen. Fehler hinter der Vorschaugrenze sperren weiterhin den
  gesamten Import. Kein automatischer Preisimport oder steuerlicher Entscheid.


## 0.2.0rc30 - 2026-10-27 (Releasekandidat)

- Historischer EUR-Preisworkflow aus rc29 einschliesslich Belegen, isolierter
  Vorschau und ausdruecklicher Uebernahme unveraendert enthalten.
- `create_app` normalisiert einen uebergebenen Datenbankpfad zum DuckDbStore;
  bestehende pfadbasierte Aufrufer bleiben mit dem neuen Preisrouter kompatibel.
- Neue Preis-Mocktests nutzen fuer Scope, Transport und Limiter dieselbe
  kontrollierte Uhr. Andere Runner-Systemlaufzeiten duerfen keine kuenstliche
  Deadlineverletzung erzeugen. Keine fachliche Assertion entfernt.
- rc29 wurde nach sechs CI-Fehlern nicht deployt; sein Tag bleibt unveraendert.
  Der abgebrochene Publisher veroeffentlichte kein rc29-Image.

## 0.2.0rc29 - 2026-10-27 (Releasekandidat)

- Gefuehrter historischer EUR-Preisablauf unter Portfolio -> EUR-Preise ermitteln:
  lokal planen, externe Abfrage bestaetigen, isolierte Vorschau pruefen und
  Preise/Neuberechnung getrennt freigeben. Keine V1-Datenbank erforderlich.
- CoinGecko-EUR-Tagesreferenzen oder DefiLlama-USD-Quotes mit historischen
  EZB-USD/EUR-Kursen ueber Frankfurter v2. Keine spaeteren Kryptoquotes,
  heutigen Ersatzkurse oder pauschale Stablecoin-Paritaet.
- Private hashgebundene Originalantworten und Vorschauen, Belegdownloads,
  idempotente Uebernahme, Datenstand-/Integritaetspruefung und atomare
  Uebernahme der isolierten Berechnung mit menschlichem Freigabeprotokoll.
- Private Preiszuordnungen konfigurierbar; bestehende Anbieter-/IP-Limits
  gelten. Das abschnittsweise HTTP-Budget zaehlt auch FX und Wiederholungen.
- Gespeicherte Historienbelege koennen nach Softwarewechsel ausdruecklich
  lokal neu geprueft werden; kein erneuter Anbieterabruf oder Autoimport.
- Aktuelle Portfolio-Marktpreise bleiben separat; unvollstaendige Historie,
  Tokenzuordnung und offene fachliche Hinweise bleiben pruefpflichtig.

## 0.2.0rc28 - 2026-10-27 (Releasekandidat)

- Alchemy, Helius und eigene Solana-RPC-Anbieter sind unter Abrufsteuerung
  direkt als benannte Limitprofile waehlbar, auch vor der ersten Profilspeicherung.
- Geerbtes Standardprofil und eigenes gespeichertes Anbieterprofil bleiben
  unterscheidbar. Erst ausdrueckliches Speichern erzeugt oder aendert ein Profil.
- Gemeinsames IP-Budget direkt erreichbar; niedrigere gemeinsame Limits bleiben
  wirksam und werden bei der Anbieterbearbeitung erklaert. Kein automatisches
  Anheben von Quoten, kein Reset und kein Start von Anbieterabfragen.
- Alchemy CU/s ausdruecklich von Requests/s getrennt. Die bestehenden lokalen
  Kosten pro Minute sind kein CU/s-Limiter; ein Wert von 500 CU/s wird nicht
  als 500 Requests/s gespeichert. Helius RPC-/DAS-Grenzen nicht vermischen.
- Erweiterte Browserpruefung mit echter isolierter Limits-API: zwei getrennte
  Anbieterprofile, 500 Requests/s als synthetischer Testwert, Persistenz und
  gemeinsam strengeres IP-Profil; schreibgeschuetzte Auswahl bleibt gesperrt.

## 0.2.0rc27 - 2026-10-27 (Releasekandidat)

- Enthaelt Anbieterwahl, gepinnte Solana-Auftraege, Inventar und begrenzte
  Abruf-Restzeitschaetzung aus rc26 unveraendert.
- Neuer HTTP-Mocktest verwendet dieselbe kontrollierte Uhr fuer Limiter und
  Transport. Ein GitHub-Runner mit anderer Systemlaufzeit darf keine kuenstliche
  Deadlineverletzung erzeugen. Keine fachliche Assertion oder Produktquote entfernt.
- rc26 wurde nach dem fehlgeschlagenen CI-Test nicht deployt. Sein Tag bleibt
  unveraendert; rc27 ist der neue Kandidat mit konsistenten Anleitungen und Versionen.

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

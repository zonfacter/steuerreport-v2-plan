# Steuerreport V2

Version 0.2.0rc19. Software fuer nachvollziehbare Krypto-Steuer-, FIFO-,
Portfolio- und Belegauswertungen mit DuckDB, FastAPI und React/TypeScript.

[Changelog](CHANGELOG.md) · [Release-Hinweise 0.2.0rc19](docs/RELEASE_0.2.0rc19.md) ·
[Inbetriebnahme](docs/INBETRIEBNAHME.md) ·
[GitHub Releases](https://github.com/zonfacter/steuerreport-v2-plan/releases) ·
[Containerpaket](https://github.com/zonfacter/steuerreport-v2-plan/pkgs/container/steuerreport-v2)

## Docker-Installation

### Fertiges Image aus GHCR

Registry: `ghcr.io/zonfacter/steuerreport-v2`. Das Repository ist oeffentlich;
die Sichtbarkeit des Containerpakets wird bei GitHub separat verwaltet.
Fuer ein privates Paket ein GitHub Personal Access Token (classic) mit
`read:packages` verwenden. Token nur lokal beim Docker-Login eingeben,
nicht in Dateien dieses Repositorys oder in Chats hinterlegen.

```bash
docker login ghcr.io -u zonfacter
docker pull ghcr.io/zonfacter/steuerreport-v2:0.2.0rc19
docker compose -f compose.ghcr.yml up -d
```

Die GHCR-Compose-Datei baut nicht selbst. Mit
`docker compose -f compose.ghcr.yml pull` wird die konfigurierte Version
gezogen. `STEUERREPORT_IMAGE` kann stattdessen eine andere ausdrueckliche
Version oder eine feste `ghcr.io/...@sha256:...`-Referenz setzen.
Die zusaetzliche Kennung `sha-<vollstaendiger Release-Commit>` bezeichnet
denselben veroeffentlichten Quellstand. Vorabversionen erhalten kein `latest`.
Aktuell wird `linux/amd64` gebaut und geprueft, nicht ARM64.

### Lokal aus dem Quellstand bauen

```bash
docker compose up -d --build
```

Danach http://127.0.0.1:8010 oeffnen und **Einrichtung** oeffnen:
Installation, Datenanbieter, eigene Verbindungen, Abrufsteuerung und KI.
Ist der Port belegt: `STEUERREPORT_PORT=18010 docker
compose up -d --build`. Das Image enthaelt keine Betreiberkonten,
Originalimporte oder Zugangsdaten. Neue Installationen starten leer.

### Solana-Adresse einrichten

Unter **Quellen & Wallets > Quelle hinzufuegen > Solana Wallet** die Eingabeart
**Oeffentliche Adresse speichern** verwenden. Optional Name und oeffentliche
Adresse eingeben, Zusammenfassung pruefen und **Adresse speichern** waehlen.
Keine Signatur, kein Setup-Token und kein Private Key erforderlich. Mehrere
Adressen bleiben getrennt; erneutes Speichern erzeugt keine doppelte Quelle.
Die Adresse liegt nur im privaten Datenvolume. Historienimport, Bestandsabruf,
Eigentumsnachweis und steuerliche Aktivierung sind davon getrennt.

### Optionaler Eigentumsnachweis

Unter **Einrichtung > Wallet-Eigentumsnachweis** stehen Status und lokale
Bootstrap-Befehle. Neue Docker-Installationen bereiten ein privates zufaelliges
Connector-Einrichtungspasswort vor. Bestehende Installationen werden durch ein
Update nicht automatisch freigeschaltet. Fuer sie bewusst in der Betreiberkonsole:

```sh
docker compose -f compose.ghcr.yml exec steuerreport python -m steuerreport_v2.connector_setup init
docker compose -f compose.ghcr.yml exec steuerreport python -m steuerreport_v2.connector_setup show-token
```

Die zweite Aktion zeigt das Passwort nur in einer privaten interaktiven Konsole.
Es wird nie von der Web-API zurueckgegeben. Unter **Quellen & Wallets > Quelle
hinzufuegen > Solana-Wallet > Optional: Eigentum per Signatur nachweisen** in das maskierte Feld **Connector-Setup-Token**
einfuegen. Wallet-Nachricht signieren und den vorhandenen Signaturnachweis pruefen;
keine Seed-Phrase, Wallet-Private-Keys oder Boersen-Handelsrechte anfordern.
Details, native/manuelle Installation und Fehlerhilfe: [Inbetriebnahme](docs/INBETRIEBNAHME.md).

DuckDB, private Konfigurationen, Importe, Artefakte und der automatisch
erzeugte Verschluesselungsschluessel liegen ausschliesslich im separaten
Volume `steuerreport-data`. Das Image laeuft ohne Root, mit schreibgeschuetztem
Software-Dateisystem und nur einem API-Worker. Die Portfreigabe ist auf
127.0.0.1 begrenzt. Keine direkte Internetfreigabe; fuer Fernzugriff ist ein
authentifiziertes TLS-Gateway oder VPN erforderlich.
Eine gepflegte Docker-Version verwenden: Bei Docker vor 28.0.0 koennen
localhost-Portfreigaben unter Umstaenden aus demselben Layer-2-Netz
erreichbar sein. Details: https://docs.docker.com/engine/network/port-publishing/

Konto-/Dateieinstellungen und private Quellenkonfigurationen werden ueber
die Settingsseite gespeichert; sie ersetzen keine Belege oder fachlichen
Freigaben und starten keine steuerliche Neuberechnung. Weil die bestehenden
Services diese Werte beim Start laden, ist anschliessend
`docker compose restart` erforderlich. Die Seite zeigt diesen Zustand an.
Provider-Keys (Solscan, Alchemy, Jupiter, Helius) und CEX-Credentials sind bereits
ohne Neustart nutzbar. Provider-Keys werden nicht zurueckgegeben.

Vor Updates das vollstaendige Volume einschliesslich `keys/vault.key` und
gegebenenfalls `keys/connector-setup.token`
sichern. Der Schluessel darf nicht verloren gehen oder ersetzt werden.
Das Volume und seine Sicherungen enthalten private Daten; die Verschluesselung
des Secret-Stores ersetzt weder Dateirechte noch Host-/Backup-Verschluesselung.
`docker compose down` behaelt das Volume, `down -v` loescht es unwiderruflich.
Kein Schluessel, Profil oder privater Export darf in den Build-Kontext oder
in ein Image kopiert werden. `.dockerignore` verwendet eine Positivliste.

### Images veroeffentlichen

Der Workflow `Publish GHCR Image` startet bei veroeffentlichten Releases
oder manuell mit einem vorhandenen Release-Tag. Zuerst muss die vollstaendige
CI bestehen. Die Docker-Eingaben des Tags muessen mit dem geprueften
Quellstand uebereinstimmen; README und reine Test-/Workflow-Infrastruktur
duerfen abweichen. Der Build verwendet ausschliesslich den Release-Commit.

Vor dem Push werden Gitleaks, leere Betreiber-Vorlagen und ein leerer
Containerstart geprueft. Bekannte Scanner-Fehlalarme sind einzeln an exakte
Quellzeilen-Hashes gebunden; neue oder geaenderte Funde blockieren den Push.
Es gibt keine pauschale Ignore-Regel. Bereits vorhandene Versionen werden
nicht ueberschrieben, sondern nur bei passenden Quell-/Versionslabels erneut
geprueft. Ein zweiter frischer Runner zieht anschliessend den Registry-Digest
und prueft Frontend, API und fehlende Betreiberkonten mit neuem Datenvolume.

Nur der Publish-Job erhaelt `packages: write`. Der Pull-Pruefjob hat lediglich
Leserecht. Beide verwenden den kurzlebigen `GITHUB_TOKEN`, keine persoenlichen
Registry-Secrets im Quellstand oder Image. Die Nachweise stehen als
`ghcr-publication-*` und `ghcr-pull-verification-*` bei den Workflow-Artefakten.

## Bedienung Und Import

Das neue Bedienkonzept ist ab 0.2.0rc14 Bestandteil von `main` und des Images.
Implementierung, URL-Schema, Aktionswirkungen, Tests und die Abnahmematrix A01–A24 stehen in der
[UX-Übergabe](docs/UX_BEDIENKONZEPT_2026-10-26.md).
Mehrkonten, Vault und serverseitige Limits sind in der
[API-Einrichtungsdokumentation](docs/API_EINRICHTUNG_ABRUFLIMITS_2026-10-26.md)
beschrieben. Automatische Sync-Zeitplaene, Tages-/Monatsbudgets und verteilte
Mehrhost-Koordination sind noch nicht enthalten.

Unter **Hilfe & Anleitungen** (`/#help`) stehen durchsuchbare Arbeitsablaeufe,
haeufige Fragen, Begriffserklaerungen sowie alle HTML-/PDF-Leitfaeden bereit.
`Hilfe zum Bereich` oeffnet das passende Thema in einem neuen Tab, ohne
ungespeicherte Eingaben im Arbeitsbereich zu verwerfen. Der Hilfeeinstieg
benoetigt keine API-Verbindung und loest keine Modellanfrage aus.
Die Ablaufleiste bietet Orientierung, bestaetigt aber keine erledigten
Pruefungen. Auf schmalen Bildschirmen ist sie aufklappbar. Fragezeichen-Hilfen
funktionieren per Hover, Tastaturfokus und Touch; Escape schliesst sie.
Import und KI-Aufgaben zeigen die jeweils fehlende Voraussetzung direkt an.
Technische Administration und bereits eingerichtete KI-Verbindungen sind
eingeklappt, bleiben aber ausdruecklich zugaenglich.

Der Benutzerleitfaden wird als
[HTML](frontend/public/benutzerleitfaden.html) und
[PDF](frontend/public/benutzerleitfaden.pdf) mitgeliefert. Er beschreibt
Einrichtung, Originalexporte, Importfreigabe, Belegspuren, Jahresberichte und
Sicherungen einschliesslich Grenzen der vorhandenen API-Historienpfade.

Reproduzierbarer Browser-Smoke-Test mit synthetischen Daten (kein echter
Import, keine Modellanfrage): `python scripts/check_ux_browser_v2.py
--base-url http://localhost:5174`. Dafuer separat Playwright und Chromium
installieren. Testbelege und Screenshots landen in `artifacts/ux-browser/`.

Unter `Daten importieren > Dateiimport` koennen mehrere CSV-/Excel-Dateien
mit Quelle, Blattwahl, Vorschau, Originaldatei-Hash und Dublettenpruefung
bearbeitet werden. Erst eine ausdrueckliche Freigabe schreibt die Daten und
startet die vorhandene Pipeline. Der Importverlauf und JSON-Belegspuren
stehen ohne Expertenmodus bereit. Die CSV-Vorlage enthaelt nur Kopfzeilen.

Unterstuetzte Dateitypen: **CSV (UTF-8, Komma/Semikolon), XLSX und XLS**.
Ein erkanntes tabellarisches Layout ist erforderlich. Die
[Importformat-Referenz](docs/IMPORTFORMATE.md) nennt fuer jede angebotene Quelle
die Pflichtfelder, echten Spalten-Aliase, Beispiele und Zeit-/Zahlenregeln.
Sie ist im Importdialog als `Formate & Spalten` und separat als
[HTML](frontend/public/importformate.html) / [PDF](frontend/public/importformate.pdf)
verlinkt. Dort stehen sieben leere CSV-Vorlagen und eine
[Excel-Arbeitsmappe mit sieben Vorlagenblaettern](frontend/public/import-vorlagen/import-vorlagen.xlsx)
bereit. Importierbar bedeutet nicht steuerlich vollstaendig; insbesondere
sind beliebige Solscan-Exporte oder rohe RPC-JSON-Dateien nicht pauschal abgedeckt.

Technische Versionsvergleiche und Legacy-Cache-Aktionen sind keine
Benutzernavigation mehr. Bestehende Referenzdaten und fachliche Exportgates
werden dadurch nicht geloescht oder umgangen.

## KI-Einrichtung

### Zweck Und Grenzen

Der Assistent hilft, **selbst eingegebene** Berichtsauszuege und Hinweise zu
erklaeren, Importspalten vorzuschlagen, moegliche Auffaelligkeiten in kleinen
Textausschnitten zu besprechen und Pruefnotizen zu entwerfen. Zusaetzlich liest
der Modus **Datenkorrekturen** ausgewaehlte Transaktions- und Preiszeilen und
erstellt validierte Vorschlaege fuer echte Datenbankaenderungen. Dateien,
Wallets, URLs oder beliebige Tabellen werden nicht selbststaendig abgefragt.
Jede Aufgabe ist unabhaengig; der Verlauf wird nicht als Chatkontext mitgesendet.
Die vier Aufgabentypen sind Kennzeichnungen, keine getrennten Pruefengines.
Es gibt keine automatische Anonymisierung des eingegebenen Texts.

Der [KI-Einsatzleitfaden](docs/KI_EINSATZLEITFADEN.md) beschreibt sechs konkrete
Einsatzfaelle, Eingaben, erwartbare Hilfen, notwendige Gegenpruefungen und
Beispielaufgaben. Er ist im Assistenten als Leitfaden und separat als
[HTML](frontend/public/ki-einsatzleitfaden.html) / [PDF](frontend/public/ki-einsatzleitfaden.pdf)
verfuegbar. Eine Modellantwort ist kein Beleg, kein exakter Summenabgleich
und keine steuerliche Freigabe. Datenkorrekturen benoetigen Einzelpruefung,
eine isoliert berechnete Vorschau und ausdrueckliche menschliche Freigabe.
Erst danach werden Datensaetze und neu berechnete Auswertungen atomar gespeichert.
Audit-JSON, Quellen-Hashes, Schutz vor veralteten Staenden, Wiederanwendung
bei neuen Laeufen und eine getrennt freizugebende Ruecknahme sind enthalten.
Unterstuetzt sind vorhandene Ereignisse und nicht abgeleitete Preise, nicht
beliebige SQL-, Datei-, Importprofil- oder Serveraenderungen.

### Einrichtung

Sieben konfigurierbare Fachagenten sind enthalten: Koordinator, Import/Quellen,
Krypto-Forensik, Wallet/FIFO, Steuer/Mining/Rewards, Preise/Stichtag und
Dokumentation/Audit. Unter `Fachagent > Agentenprofile einrichten` koennen
Aufgabenbeschreibung und Modell-ID je Anbieter gespeichert werden. Eine leere
Zuordnung verwendet das Standardmodell der aktiven Verbindung. Alle Rollen
nutzen die jeweils aktiv konfigurierte Verbindung, keine eigenen versteckten
Zugangsdaten und keine automatisch wechselnden Anbieter. Es gibt keine
automatische kostenpflichtige Ersatzwahl oder parallele Agentenkette.

Versioniertes Anwendungswissen beschreibt das echte Datenmodell und die
zugelassenen Werkzeuge. Rolle, Aufgabenbeschreibung, Wissens-Hash und
Modellzuordnung werden bei erfolgreichen Aufgaben und Korrekturvorschlaegen
mitgespeichert. Agenten sind Systemprofile, keine zusaetzlich trainierten
Modelle; sie erhalten keine zusaetzlichen Schreibrechte oder ungeprueften
Zugriff auf den gesamten Bestand. GET/PUT `/api/v1/ai/agents` verwaltet die
Profile ohne Modellaufruf. Geaenderte Profile sperren veraltete Auftraege.

Unter `Einrichtung > KI-Einrichtung` beziehungsweise `KI-Assistent` werden
lokale OpenAI-kompatible Server, **OpenRouter** und andere kompatible Cloud-APIs
konfiguriert. OpenRouter verwendet `https://openrouter.ai/api/v1`.
API-Keys werden nur verschluesselt im bestehenden Vault gespeichert und nicht
zurueckgegeben. Anbieter-/Adresswechsel erfordern das Ersetzen oder explizite
Entfernen des bisherigen Keys. Keine persoenlichen Endpunkte oder Modelle
sind vorbelegt. Aenderungen werden ohne Container-Neustart wirksam.

Cloud-Zugriffe bleiben standardmaessig deaktiviert. Modelle werden nur per
ausdruecklicher Aktion abgefragt. `Verbindung testen` sendet einen neutralen
Testtext mit begrenzter Antwortlaenge; auch dieser kann beim Anbieter Kosten
ausloesen. Eine echte Cloud-Aufgabe braucht zusaetzlich eine ausdrueckliche
Textfreigabe. Textaufgaben nutzen ausschliesslich den eingegebenen Text.
Datenkorrekturen senden zusaetzlich die zuvor angezeigten und ausgewaehlten
Datenzeilen; diese koennen echte Konten und Wallet-Adressen enthalten.
Ergebnisse sind Review-Hinweise, keine steuerlichen Entscheidungen.

Die Modellliste besitzt eine sichtbare Auswahl und Namens-/ID-Suche.
Bei OpenRouter ist `Nur Free-Modelle` anfangs aktiviert. Free wird anhand
der veroeffentlichten Prompt-/Completion- und gegebenenfalls Anfragepreise
klassifiziert, nicht anhand des Modellnamens. Unbekannte Preise gelten nicht
als kostenlos. Preise in USD und Kontextgroesse werden fuer die Auswahl
angezeigt. Filteraenderungen ersetzen kein ausgewaehltes Modell; ein bereits
gewaehltes kostenpflichtiges Modell bleibt entsprechend gekennzeichnet.

`POST /api/v1/ai/tasks` bleibt mit bestehenden Clients kompatibel und legt
Aufgaben an. Die explizite Ausfuehrung erfolgt ueber
`POST /api/v1/ai/tasks/{task_id}/execute`. Erfolgreiche Aufgaben werden nicht
erneut gesendet; Fehler werden nicht automatisch wiederholt. Die Anleitung
steht im [Benutzerleitfaden](frontend/public/benutzerleitfaden.html#ki).

## Eigenstaendiger Betrieb

Docker benoetigt keinen V1-Dienst. Binance, Bitget, Pionex und Coinbase werden
mit den in der V2-Administration gespeicherten Zugangsdaten direkt abgefragt.
Nicht verwendete Boersen muessen nicht eingerichtet werden. Fehlende
Zugangsdaten sind kein bestaetigter Nullbestand und loesen ohne explizit
konfigurierte Legacy-API keinen V1-Fallback aus.

Der V1-Credential-Uebernahmecheck ist nicht Bestandteil der Administration.
Die bestehende Legacy-API bleibt fuer ausdruecklich konfigurierte Migrationen
kompatibel, ist ohne Legacy-URL jedoch inaktiv und fuehrt keine externen
Anfragen oder Secret-Schreibvorgaenge aus. Historische Referenzimporte und
vorhandene Steuerstaende bleiben davon unberuehrt.

## Native Installation

Python 3.11+ und Node.js werden vorausgesetzt.

```bash
python3 -m pip install -c requirements-runtime.lock -e '.[dev]'
export STEUERREPORT_V2_ROOT="$PWD"
export STEUERREPORT_V2_DB="/pfad/zu/privaten/daten/steuerreport_v2.duckdb"
export STEUERREPORT_USERTRANSFER_ROOT="/pfad/zu/privaten/importen"
python3 -m uvicorn steuerreport_v2.api.app:app --host 127.0.0.1 --port 8010
```

Ohne expliziten Profilpfad legt die Settingsseite ein neues Profil unter
`~/.local/share/steuerreport/private_profile.json` an. Alternativ kann ein
vorhandenes Profil mit `STEUERREPORT_PRIVATE_PROFILE` und ein externer
Konfigurationsordner mit `STEUERREPORT_PRIVATE_CONFIG_DIR` eingebunden werden.
Eine vorhandene Installation muss ihre privaten Konfigurationen,
Datenbanken und Rohdaten separat sichern. Ohne Profil werden keine
persoenlichen Kontodefaults angenommen. Ein explizit konfiguriertes,
unlesbares Profil fuehrt zu einem Konfigurationsfehler. Fuer den nativen
Secret-Vault einmal initialisieren und den erzeugten Key-Pfad konfigurieren:

```bash
python -c 'from steuerreport_v2.container_entrypoint import initialize_state; initialize_state()'
export STEUERREPORT_V2_SECRET_VAULT_KEY_FILE="$HOME/.local/share/steuerreport/keys/vault.key"
export STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS=true
```

Frontend in einer weiteren Shell:

```bash
cd frontend
npm ci
npm run dev
```

Der lokale Frontend-Server verwendet Port 5174 und leitet API-Anfragen an
127.0.0.1:8010 weiter. Ein Produktionsbuild entsteht mit npm run build.
scripts/start_v2.sh bleibt ein standortspezifischer V1/V2-Deployhelfer.
Frontend und API verwenden standardmaessig denselben Origin. Fuer eine
getrennte Bereitstellung ist `VITE_API_BASE` beim Frontend-Build explizit
zu setzen.
API-Hostnamen werden mit `STEUERREPORT_ALLOWED_HOSTS` explizit freigegeben;
abweichende Browser-Origins nur mit `STEUERREPORT_CORS_ORIGINS` (Kommaliste).
Diese Sicherheitseinstellungen bleiben bewusst Bootstrap-Konfiguration,
nicht ueber eine noch unauthentifizierte Settingsseite veraenderbar.

## Dokumentation und Pruefung

- [Datenschutz und private Konfiguration](docs/750_PRIVACY_CLEAN_SOFTWARE_2026-10-25.md)
- [API-Vertraege](docs/API_CONTRACTS_V2.md)
- [Mobile API](docs/007_MOBILE_APP_API_INTEGRATION_2026-08-26.md)
- [Endpoint-Referenz](docs/626_API_ENDPOINT_REFERENZ_VOLLSTAENDIG_2026-07-05.md)
- [OpenAPI](docs/openapi/steuerreport-v2-openapi.json)

```bash
python3 -m pytest tests/unit -q
python3 scripts/check_private_data_v2.py
python3 scripts/export_openapi_v2.py --check
python3 scripts/generate_api_endpoint_reference_v2.py --check
```

Tests verwenden ausschliesslich generierte Kontokennungen aus einem eigenen
Fixture-Profil. Private Originalimporte und steuerliche Fallberichte sind
kein Teil dieses Software-Repositorys. Oeffentliche Token-Mints und
Protokolladressen sind keine privaten Betreiberkonten.

Die API hat keine globale Benutzeranmeldung. Bestehende Mobile-Sitzungen
schuetzen nur ihre jeweiligen Schnittstellen. Betrieb im vertrauenswuerdigen
LAN/VPN oder hinter TLS und einem Auth-Gateway; keine direkte Freigabe ins
Internet. Ergebnisse bleiben technische Berechnungen mit Beleg- und
Review-Grenzen. PDF-Dateien sind auf jeweils 100 Seiten begrenzt.

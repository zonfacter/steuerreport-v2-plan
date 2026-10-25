# Steuerreport V2

Version 0.2.0rc3. Software fuer nachvollziehbare Krypto-Steuer-, FIFO-,
Portfolio- und Belegauswertungen mit DuckDB, FastAPI und React/TypeScript.

## Docker-Installation

```bash
docker compose up -d --build
```

Danach http://127.0.0.1:8010 oeffnen und **Administration > Installation und
Konten** einrichten. Ist der Port belegt: `STEUERREPORT_PORT=18010 docker
compose up -d --build`. Das Image enthaelt keine Betreiberkonten,
Originalimporte oder Zugangsdaten. Neue Installationen starten leer.

DuckDB, private Konfigurationen, Importe, Artefakte und der automatisch
erzeugte Verschluesselungsschluessel liegen ausschliesslich im separaten
Volume `steuerreport-data`. Das Image laeuft ohne Root, mit schreibgeschuetztem
Software-Dateisystem und nur einem API-Worker. Die Portfreigabe ist auf
127.0.0.1 begrenzt. Keine direkte Internetfreigabe; fuer Fernzugriff ist ein
authentifiziertes TLS-Gateway oder VPN erforderlich.

Konto-/Dateieinstellungen und private Quellenkonfigurationen werden ueber
die Settingsseite gespeichert; sie ersetzen keine Belege oder fachlichen
Freigaben und starten keine steuerliche Neuberechnung. Weil die bestehenden
Services diese Werte beim Start laden, ist anschliessend
`docker compose restart` erforderlich. Die Seite zeigt diesen Zustand an.
Provider-Keys (Solscan, Alchemy, Jupiter, Helius) und CEX-Credentials sind bereits
ohne Neustart nutzbar. Provider-Keys werden nicht zurueckgegeben.

Vor Updates das vollstaendige Volume einschliesslich `keys/vault.key`
sichern. Der Schluessel darf nicht verloren gehen oder ersetzt werden.
Das Volume und seine Sicherungen enthalten private Daten; die Verschluesselung
des Secret-Stores ersetzt weder Dateirechte noch Host-/Backup-Verschluesselung.
`docker compose down` behaelt das Volume, `down -v` loescht es unwiderruflich.
Kein Schluessel, Profil oder privater Export darf in den Build-Kontext oder
in ein Image kopiert werden. `.dockerignore` verwendet eine Positivliste.

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

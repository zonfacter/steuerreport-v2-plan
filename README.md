# Steuerreport V2

Version 0.2.0rc2. Software fuer nachvollziehbare Krypto-Steuer-, FIFO-,
Portfolio- und Belegauswertungen mit DuckDB, FastAPI und React/TypeScript.

## Installation

Python 3.11+ und Node.js werden vorausgesetzt.

```bash
python3 -m pip install -e '.[dev]'
export STEUERREPORT_V2_ROOT="$PWD"
export STEUERREPORT_V2_DB="/pfad/zu/privaten/daten/steuerreport_v2.duckdb"
export STEUERREPORT_USERTRANSFER_ROOT="/pfad/zu/privaten/importen"
export STEUERREPORT_PRIVATE_PROFILE="/pfad/zu/privaten/daten/private_profile.json"
export STEUERREPORT_PRIVATE_CONFIG_DIR="/pfad/zu/privaten/konfigurationen"
python3 -m uvicorn steuerreport_v2.api.app:app --host 127.0.0.1 --port 8010
```

Ein neues Profil kann anhand der leeren Vorlage
configs/private_profile.example.json ausserhalb des Repositorys erstellt
werden. Eine vorhandene Installation muss ihre privaten Konfigurationen,
Datenbanken und Rohdaten separat sichern. Ohne Profil werden keine
persoenlichen Kontodefaults angenommen. Ein explizit konfiguriertes,
unlesbares Profil fuehrt zu einem Konfigurationsfehler.

Frontend in einer weiteren Shell:

```bash
cd frontend
npm ci
npm run dev
```

Der lokale Frontend-Server verwendet Port 5174 und leitet API-Anfragen an
127.0.0.1:8010 weiter. Ein Produktionsbuild entsteht mit npm run build.
scripts/start_v2.sh bleibt ein standortspezifischer V1/V2-Deployhelfer.

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

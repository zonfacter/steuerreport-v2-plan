# Funktionsabgleich Betrieb

Stand: 28.10.2026 UTC, Paket A. Vertrag vor Edits bestaetigt; keine
Fachlogik-, Schema-, API- oder Versionsaenderung. Befunde sind Betriebsnachweise,
keine steuerliche Methodenfreigabe.

## Tatsaechliche Laufwege

| Pfad | Nachweis | Ergebnis |
| --- | --- | --- |
| Produktiv 18010 | Docker-Inspect, HTML/OpenAPI lesend | rc32, lokale Image-ID und Commitlabel entsprechen dem Auftrag; gesund laut Docker-Metadaten |
| Legacy 8000 | PID 158, `/proc/158/cwd`, statische Auslieferung | V1-Prozess aus `/workspace/steuerreport`, liefert auch `/ui/static/v2/index.html` |
| Legacy 8010 | PID 3145184, `/proc/3145184/cwd`, OpenAPI | V2-Prozess aus `/workspace/steuerreport-v2-plan`, meldet API 0.1.0 |
| Altes V2-Bundle auf 8000 | HTML und referenziertes lokales JS | API-Basis im JS: Protokoll/Hostname des Browsers mit Port 8010 |
| Docker-Frontend | HTML und referenziertes lokales JS | anderes Bundle, `location.origin`, kein `:8010`-Literal; HTML entspricht dem isolierten Restore |
| Lokales `frontend/dist` im Plan-Repo | SHA256 der HTML-Datei | weder gleich dem ausgelieferten Legacy-HTML noch dem rc32-HTML |

`scripts/start_v2.sh` im Plan-Repo und im Audit-Ausgangsstand ist nur gelesen:
feste Legacy-Pfade, `npm install/build`, Ersetzen des V1-Unterverzeichnisses,
Beenden und Starten des 8010-Backends. Es ist kein harmloser Statusaufruf und
wurde nicht ausgefuehrt. Keine Legacy-Ports oder Prozesse wurden umgestellt.

## Struktur Ist Nicht Fachparitaet

OpenAPI auf 8010: 374 Pfade / 390 Operationen. Docker: 437 / 463.
390 Operationen sind gemeinsam, keine nur auf Legacy, 73 nur auf Docker.
Zehn gemeinsame Operationsobjekte sowie die Komponentenschemas unterscheiden
sich. Die neuen Bereiche umfassen Installation/Verbindungen, Limits,
historische Preisvorschauen, Workspace und KI-Verwaltung. Kein solcher
Fachendpunkt wurde fuer diesen Abgleich aufgerufen.

Lesender Dateivergleich mit dem rc32-Checkout: `tax.py`, `fifo_methods.py` und
`price_lookup.py` sind auf dem heutigen Legacy-Datentraeger bytegleich;
`reports.py` und `tax_wallet_fifo.py` sind verschieden. Diese Aussage betrifft
Dateien, nicht bereits seit September geladene Python-Module. Auch gleiche
Dateien beweisen weder gleiche aktive Methoden/Eingaben noch gleiche Resultate.
Legacy-Methodenparitaet bleibt **nicht belegt**. Keine private Legacy-DB wurde
kopiert, keine Methode aktiviert, kein Steuerlauf oder Export erzeugt.

## Erhalt Und Grenzen

Der Offline-Restore prueft Start, Neustart und vollstaendigen logischen
Tabellenerhalt mit demselben lokalen Image. Er ist kein Beweis der Gleichheit
mit einem Registry-Image: lokale `RepoDigests` sind leer. Der Registry-Digest
im Manifest ist nur ein erneut gelesener Altbeleg, nicht frisch verifiziert.
Gleiches Commitlabel beweist keine Byteidentitaet und keine Buildreproduzierbarkeit.

Alte Checkouts bleiben unveraendert: V1 11 schmutzige Eintraege (3 tracked,
8 untracked), V2-Plan 123 (58/65). Aktuelle Branches jeweils 0 Commits vor/hinter
gecachtem Upstream. Ueber alle lokalen Branches: V1 5 Commits nicht in lokalen
Remote-Trackingrefs, V2-Plan 0. Kein Fetch; keine Aussage ueber heutige Remotes.

BMF-/Docker-Nachpruefung und die vom Nutzer erwaehnten separaten Reprodateien
sind weiterhin ohne bekannten Pfad. Keine Behauptung, sie gelesen oder exakt
wiederholt zu haben. Die vorliegenden Pruefungen sind eigene Betriebspruefungen.

## Sichere Aufrufe

Nur gepruefte statische GETs, FastAPI-OpenAPI und V1-Health wurden produktiv
abgerufen. V1-Health baut lediglich die Antwort aus Uhrzeit/UUID, ohne DB-Aufruf.
V2-Health oeffnet dagegen `DuckDbStore.connect()`, das beim ersten Zugriff
`ensure_schema()` ausfuehrt. Daher kein manuell angestossener V2-Health-Aufruf
auf Produktion/Legacy8010; nur im isolierten Restore. Der bereits konfigurierte
produktive Docker-Healthcheck wurde nicht geaendert. GET ist nicht generell RO.

Reproduktion der bereinigten Inventur (nur bekannte lokale Dienste):

```sh
python3 -B docs/audit/2026-10-28/ops_inventory.py \
  --output /root/.local/share/steuerreport/migration-audit-20261028/ops/inventory.json
```

Prozesspfade: `ss -ltnp '( sport = :8000 or sport = :8010 or sport = :18010 )'`,
`ps -p 158,3145184 -o pid=,lstart=,args=` und
`readlink /proc/158/cwd /proc/3145184/cwd`. Manifest enthaelt nur freigegebene
Metadaten, keine vollstaendigen Inspect-/Env-Ausgaben oder Finanzwerte.

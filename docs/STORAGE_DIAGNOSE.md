# Speicherdiagnose fuer Betreiber

Der lesende Inventarbefehl zeigt freie Dateisystemkapazitaet und die aggregierte Docker-Speichernutzung. Er scannt keine Dateien, gibt keine Pfade, Dateinamen, Container-, Image- oder Volume-Namen aus und fuehrt keine Bereinigung aus.

## Aufruf

Im Repository:

```sh
python3 scripts/storage_inventory_v2.py
```

Weitere Dateisysteme koennen gezielt angegeben werden. Die Pfade werden nur fuer `statvfs` verwendet und nicht ausgegeben:

```sh
python3 scripts/storage_inventory_v2.py --path / --docker-data-path /var/lib/docker
python3 scripts/storage_inventory_v2.py --json --path /workspace
```

`--docker-data-path` muss ein lokaler, fuer den Operator sichtbarer Pfad sein. Bei einem entfernten Docker-Daemon kann ein lokaler Pfad dieselbe Zeichenfolge haben, ohne dessen Speicher zu messen. Die Ausgabe kennzeichnet den Messpunkt nur als `docker_data_path`; sie bestaetigt nicht, dass ein entfernter Daemon denselben Speicher verwendet.

## Ausgabe verstehen

- `free_bytes` ist laut Dateisystem frei; `available_to_unprivileged_bytes` beruecksichtigt reservierte Bloecke und ist fuer normale Prozesse meist die relevantere Kapazitaet.
- Inode-Kapazitaeten werden, soweit das Dateisystem sie meldet, separat angegeben. Speicher- oder Inode-Quotas werden nicht ermittelt.
- Docker wird ausschliesslich mit `docker system df` ohne `--verbose` abgefragt. Es werden Gesamt-/Aktivzaehler sowie Docker-gemeldete Groessen fuer Images, Container, lokale Volumes und Build Cache gezeigt.
- Docker-`reclaimable` ist eine Daemon-Schaetzung aggregierter ungenutzter Ressourcen. Es ist **keine** Freigabe zur Loeschung und prueft weder Backup-/Rollback-Abhaengigkeiten noch Aufbewahrungspflichten.
- `docker system df` kann laut Docker-Dateisysteme von Images, Containern und Volumes durchlaufen und dadurch CPU/I/O beanspruchen. Auf stark ausgelasteten Hosts daher ausserhalb kritischer Lastspitzen ausfuehren; der Client-Timeout ist keine Garantie fuer eine harte Obergrenze des daemonseitigen Aufwands.
- Ein nicht verfuegbarer Docker-Daemon, ein Timeout, ein unbekanntes Ausgabeformat oder ein nicht lesbarer Dateisystem-Messpunkt wird als Teilstatus mit einem datenfreien Fehlercode ausgegeben. Der Prozess endet dann mit Statuscode `1`.

## Grenzen und Sicherheit

Der Befehl ruft weder `docker system prune` noch `docker rm` auf, listet keine einzelnen Docker-Ressourcen und durchsucht keine Test-, Backup- oder Produktivverzeichnisse. Er misst keine Dateigroessen, Datenbankgroessen oder freien Bytes einzelner Volumes. Die Docker-Groessen bleiben in der vom Docker-CLI gelieferten menschenlesbaren Einheit und werden nicht als exakte Dateisystembelegung umgerechnet; gemeinsam genutzte Image-Layer koennen Aggregatwerte beeinflussen.

Vor Backup, Restore, Pull oder Migration sollte der Betreiber den relevanten lokalen Mount explizit mit `--path` beziehungsweise `--docker-data-path` messen. Fuer eine Entfernung ist eine separate, manuelle Pruefung von Identitaet, Nutzung, Sicherung und Rollback-Abhaengigkeit erforderlich. Dieses Werkzeug markiert nichts als sicher loeschbar.

Auch der Status `complete` bedeutet nur, dass alle angefragten Messungen Antworten lieferten. Er ist keine Speicherfreigabe: Der angegebene Docker-Datenpfad wird nicht gegen die Daemon-Konfiguration verifiziert, Quotas bleiben unbekannt.

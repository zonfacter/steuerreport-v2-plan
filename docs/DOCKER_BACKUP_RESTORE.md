# Docker-Datensicherung und isolierte Wiederherstellung

Dieses Werkzeug sichert und prueft den persistenten Docker-Datenstand, ohne einen
Container umzuschalten. Es benoetigt weder KI noch externe Provider. Es arbeitet
mit dem lokal vorhandenen Anwendungsimage und dem Docker-CLI. Es startet keinen
Produktivcontainer und fuehrt keine Steuerberechnung aus.

## Voraussetzungen

- Docker Engine und Compose funktionieren lokal.
- Das Quellimage ist lokal vorhanden und traegt OCI-Version, Quellrevision und
  Projektlabels. Es wird waehrend der Sicherung nicht heruntergeladen.
- Das private Ausgabeziel liegt auf einem geschuetzten Datentraeger mit genug
  Platz. Sicherungsarchiv und Manifest enthalten Finanzdaten, Originalimporte,
  Profil sowie Vault-Ciphertext **und den dazugehoerigen Vault-Schluessel im
  selben Archiv**. Das Archiv ist damit wie entschluesselbare Zugangsdaten zu
  behandeln. Dateimodus 0600 ist kein Ersatz fuer verschluesselte
  Datentraegersicherung. Sicherungen niemals in Git, ein oeffentliches Release
  oder einen ungeschuetzten Cloudordner legen.
- Fuer externe Bind-Mounts muss der Betreiber bestaetigen, dass auch deren
  Schreibzugriffe ausserhalb von Docker pausiert sind. Unbekannte
  `STEUERREPORT_*_PATH/FILE/ROOT/DIR`-Variablen, nicht persistente konfigurierte
  Pfade, Symlinks, Spezialdateien und ueberlappende Mounts blockieren die
  Sicherung.

Die Befehle unten sind ein Runbook, kein Nachweis einer bereits ausgefuehrten
Sicherung oder Wiederherstellung. `CONTAINER` und die Grenzwerte sind vor Ort
zu bestimmen. Die Skripte koennen mit `python3 scripts/docker_state_v2.py --help`
ohne Appstart eingesehen werden.

## Backup im gestoppten Zustand

1. Wartungsfenster ankundigen und Schreibzugriffe an der Anwendung sowie an
   eingebundenen externen Datenquellen pausieren.
2. Compose-Dienst stoppen und Container-ID notieren:

```sh
docker compose -f compose.ghcr.yml stop steuerreport
docker compose -f compose.ghcr.yml ps --all --quiet steuerreport
docker inspect -f '{{.State.Status}} {{.State.ExitCode}}' CONTAINER
```

3. Erst nach bestaetigtem sauberem Stopp ausfuehren. Bei Bind-Mounts den
   zusaetzlichen Bestaetigungsparameter nur setzen, wenn auch externe Prozesse
   diese Pfade nicht beschreiben:

```sh
python3 scripts/docker_state_v2.py backup \
  --container CONTAINER \
  --output-dir /geschuetzter/pfad/steuerreport-backup-YYYYMMDD \
  --confirm-source-stopped \
  --confirm-external-paths-quiesced
```

Ohne Bind-Mounts ist `--confirm-external-paths-quiesced` entbehrlich.
Das Werkzeug verifiziert den gestoppten Zustand, Exitstatus, weitere laufende
Nutzer der Volumes, konfigurierte Datenpfade, Vault-Entschluesselbarkeit und
liest die Datenbank nur lesend. Alle Dateien in persistenten Volumes und
Bind-Mounts, einschliesslich `.wal`, werden in das Archiv aufgenommen und im
Manifest gehasht. Es entfernt keine WAL-Datei. Ein vorhandener WAL blockiert
spaeter die Restore-Pruefung; vor manueller Bereinigung muss die Ursache
untersucht werden.

## Integritaet pruefen

Grenzwerte in Bytes ausdruecklich passend zum erwarteten Bestand setzen. Die
komprimierte Obergrenze wird vor dem Hashen geprueft. Die Nutzdatenobergrenze
wird gegen Manifest und tatsaechliche regulaere Datei-Groessen geprueft. Eine
separate Grenze zaehlt den gesamten expandierten Tar-Datenstrom einschliesslich
Headern, PAX-Metadaten und Padding. Die Anzahl der Eintraege ist ebenfalls
begrenzt.

```sh
python3 scripts/docker_state_v2.py verify \
  --backup-dir /geschuetzter/pfad/steuerreport-backup-YYYYMMDD \
  --max-archive-bytes 10737418240 \
  --max-uncompressed-bytes 32212254720 \
  --max-expanded-archive-bytes 32768000000
```

`verified` bestaetigt Archivhash, Manifest, Mitgliedshashes, Pfade und die
angegebenen Groessengrenzen. Es bestaetigt noch keinen erfolgreichen
Anwendungsstart oder eine produktive Restore-Freigabe.

## Wegwerfbare Restore-Pruefung

Der Test benoetigt das im Manifest gebundene Image lokal. Er erstellt neue
label-markierte Docker-Volumes, stellt die Daten hinein, startet einen
isolierten Container mit Netzwerk `none`, ohne Portfreigaben und mit
Ressourcenbegrenzung, prueft Health und Dateninvarianten nach Start und Neustart
und versucht anschliessend die eigenen Testressourcen zu entfernen.

```sh
python3 scripts/docker_state_v2.py restore-check \
  --backup-dir /geschuetzter/pfad/steuerreport-backup-YYYYMMDD \
  --evidence-dir /geschuetzter/pfad/restore-check-YYYYMMDD \
  --run-id restore-YYYYMMDD-01 \
  --max-archive-bytes 10737418240 \
  --max-restore-bytes 32212254720 \
  --max-expanded-archive-bytes 32768000000
```

Nur `status: passed` zusammen mit `cleanup: true` belegt diesen isolierten
Testlauf. `cleanup: false` oder fehlende Evidence bedeutet: nicht als bestanden
werten; die gelisteten label-markierten Ressourcen manuell untersuchen. Das
Werkzeug loescht keine Ressource, deren Eigentumslabel es nicht sicher
bestaetigen kann. Ein WAL blockiert den Test statt still ignoriert zu werden.

## Wiederherstellung in neue Volumes

Fuer das Compose-Override muss das Image eine unveraenderliche
Repository-Digestreferenz (`repository@sha256:...`) besitzen. Ein lokaler
Build ohne `RepoDigest` kann weiterhin isoliert geprueft werden, aber dieser
Restore-Schritt blockiert, statt ein veraenderliches Tag zu hinterlegen.

Die dauerhafte Datenwiederherstellung erzeugt ausschliesslich neue Volumes,
prueft Dateien, Datenbankschema, Tabellenanzahl und Vault und schreibt ein
Compose-Override mit einer unveraenderlichen Image-Repository-Digestreferenz.
Sie aktiviert den Dienst nicht und aendert keine bestehenden Volumes.

```sh
python3 scripts/docker_state_v2.py restore \
  --backup-dir /geschuetzter/pfad/steuerreport-backup-YYYYMMDD \
  --output-dir /geschuetzter/pfad/restore-output-YYYYMMDD \
  --run-id restore-YYYYMMDD-02 \
  --max-archive-bytes 10737418240 \
  --max-restore-bytes 32212254720 \
  --max-expanded-archive-bytes 32768000000
```

Vor einer Aktivierung muessen `restore.json`, `compose.restore.override.yml`,
Image-Digest, Schema und die gemeldeten Volumes geprueft werden. Vor dem
Ausfuehren eines Compose-Befehls die zusammengefuehrte Konfiguration lesen:

```sh
docker compose -f compose.ghcr.yml \
  -f /geschuetzter/pfad/restore-output-YYYYMMDD/compose.restore.override.yml config
```

Die Ausgabe kann private Dateipfade enthalten und gehoert nicht in ein Ticket
oder einen oeffentlichen Log. Ein Restore-Override ist kein Rollbackplan und
wird nicht automatisch angewendet.

## Upgrade und Rollback

- Vor einem Schema- oder Imageupgrade zuerst ein verifiziertes Backup und einen
  erfolgreichen isolierten Restore-Test mit dem bisherigen Image ablegen.
- Neue Version und wiederhergestellte Daten zuerst in separaten Volumes pruefen.
- Ein altes Image niemals auf ein Volume starten, das bereits durch eine
  inkompatible neue Version migriert wurde.
- Rollback erfolgt mit dem passenden alten Image und einer separaten
  Wiederherstellung des vor dem Upgrade erstellten Backups. Bestehende
  Volumes bleiben unangetastet, bis ein gesonderter Betriebsentscheid vorliegt.
- Kein `docker compose down -v`, `docker volume prune` oder manuelles Loeschen
  als Teil dieser Prozedur.

Diese Repository-Tests enthalten keinen Docker-Daemon-End-to-End-Test. Vor
produktiver Nutzung muss der Operator die Befehle auf einer isolierten Kopie
mit dem tatsaechlichen Image, den echten Mounts und einem kontrollierten
Rueckweg ausfuehren. Ein erfolgreicher Unit-Test ersetzt diesen Beleg nicht.

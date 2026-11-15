# Docker-Datensicherung und isolierte Wiederherstellung

Integrationsstand vom 15.11.2026, noch kein veroeffentlichtes produktives Update.
Die Herkunft aus PR #11, Korrekturen und tatsaechlich ausgefuehrten Proben
stehen unter `audit/PORTABLE_STATE_INTEGRATION_2026-11-15.md`.

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

Nicht persistierte anwendungsspezifische Umgebungs-Overrides gegenueber dem
Image (zum Beispiel Wallets, Berechtigungen oder Secret-Werte) blockieren
mit `application_environment_not_persisted`. Werte werden nicht ausgegeben
oder still in ein Klartextmanifest kopiert. Solche Einstellungen muessen
bewusst in die unterstuetzte private Persistenz ueberfuehrt oder als konkrete
offene Betriebsabhaengigkeit behandelt werden; der Helfer aendert sie nicht.

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

Nach dem Archivieren werden Quellidentitaet, Start-/Stoppzeit, Konfiguration,
Mounts und andere Docker-Nutzer erneut geprueft. Ein zwischenzeitlicher Neustart
der Quelle verhindert die Erfolgsmeldung. Das ersetzt nicht die ausdrueckliche
Betreiberbestaetigung fuer Schreibpausen ausserhalb von Docker.

Inventar, semantischer Snapshot und Archivierung halten jeweils eine native
DuckDB-Lesesperre in einem getrennten, kurzlebigen Guard-Prozess. Dadurch hebt
das Oeffnen/Schliessen anderer Dateistreams im Helfer die prozessgebundene
Linux-Sperre nicht auf. Ein paralleler nativer Writer oder ein verlorener Guard
blockiert den Erfolg. Das ist keine exklusive Sperre aller anderen Belegdateien;
deren Schreibpause bleibt Voraussetzung.

Unlesbare Verzeichnisse und beschaedigte/mehrdeutige Vault-JSON-Strukturen werden
nicht als leer oder erfolgreich entschluesselbar behandelt. Nicht aufloesbare
relative Konfigurationspfade und Tildepfade werden abgewiesen; keine stillen
Hostpfad-Annahmen. Neben Tabellenwerten werden persistente Schemas, Spalten,
Defaults, Views, Constraints, Indizes, Sequenzen, Typen und unterstuetzte Makros
gehasht. Persistierte parametrisierte Makros sind derzeit nicht unterstuetzt,
weil die verwendete DuckDB-Katalogschnittstelle deren Defaults nicht
vollstaendig offenlegt; sie blockieren den Snapshot.

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

Alle neuen Ressourcen tragen Lauf-ID und zusaetzliche zufaellige
Operator-Eigentuemerkennung. Neue Volumenamen enthalten einen Zufallssuffix;
eine wiederverwendete menschliche Lauf-ID berechtigt nicht zum Loeschen eines
anderen Laufs. Container werden anhand ihrer geprueften unveraenderlichen ID
gestartet und entfernt, nicht anhand eines neu belegbaren Namens. Ein unklar
beendeter Create-Aufruf ohne beobachtete Identitaet gilt auch bei zunaechst
fehlender Ressource nicht als bereinigt. Begrenzte Nachpruefungen koennen eine
spaeter erschienene eigene Ressource entfernen; andernfalls bleibt der Zustand
ausdruecklich unbekannt. Keine allgemeinen Prune-Befehle und keine automatische
Wiederholung eines ungeklaerten Laufs. Der lokale Docker-Administrator bleibt
eine vertrauenswuerdige Betriebsinstanz; dies ist keine Isolation gegen einen
Angreifer mit Zugriff auf den Docker-Daemon.

Neue Manifeste binden auch den Kataloghash. Aeltere Format-1-Manifeste ohne
diesen Zusatz koennen weiterhin integritaetsgeprueft werden. Der Restore
ermittelt dann den Katalog aus der archivgebundenen Datenbank vor dem ersten
Start und vergleicht ihn nach Start und Neustart. `catalog_manifest_bound:
false` bedeutet dabei, dass der urspruengliche Backupmanifest diesen eigenen
Katalognachweis noch nicht enthielt, nicht dass der Katalogvergleich entfaellt.

Bei unbekannter Helfer-/CLI-Bereinigung bleibt eine private Teilarchivdatei zur
administrativen Klaerung erhalten; ohne vollstaendiges Manifest ist sie kein
gueltiges Backup. Abbruch und Fehler werden niemals als erfolgreicher Restore
ausgegeben. Ein gewaltsames Beenden des Operators kann Nacharbeit an dessen
markierten Ressourcen erfordern.

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

Der Docker-Layerjob der CI ruft neu einen streng auf seine markierten
synthetischen Testcontainer begrenzten Harness auf. Er prueft Backup,
Verifikation, Volume-Restore, Vault-Entschluesselbarkeit sowie Start und
Neustart ohne Netzwerk/Ports. Nur ein tatsaechlich bestandener Job beweist
diesen engen synthetischen Umfang. Veroeffentlicht werden allein sanitiserte
Ergebnisflags, niemals die privaten Archive, Manifeste, Keys oder Rohlogs.

Der CI-Harness startet den Operator in einer eigenen Prozesssitzung. Bei
SIGINT/SIGTERM sendet er nur dem Operator ein Abbruchsignal und gibt dessen
Bereinigung begrenzt Zeit, statt ihm per `subprocess.run` sofort den Prozess
zu beenden. Nicht bestaetigter Stopp, Nonzero-Exit, ungueltige Antworten oder
fehlender positiver Cleanup-Nachweis erhalten das private Staging ausserhalb
des Artefaktordners: `cleanup: false`, `private_staging_retained: true`.
Dieses Flag nennt keine Pfade oder Secretwerte. Es ist kein Freibrief fuer
eine automatische Wiederholung; der isolierte Runner muss beendet oder der
Zustand administrativ untersucht werden.

Vor produktiver Nutzung muss der Operator die Befehle auf einer isolierten Kopie
mit dem tatsaechlichen Image, den echten Mounts und einem kontrollierten
Rueckweg ausfuehren. Ein erfolgreicher Unit-Test ersetzt diesen Beleg nicht.

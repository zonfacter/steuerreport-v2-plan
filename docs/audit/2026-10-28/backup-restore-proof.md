# Isolierter Backup-Restore

28.10.2026, Paket A. Zwei eigene isolierte Durchlaeufe, kein Produktivwechsel.
Private Einzelbelege: `/root/.local/share/steuerreport/migration-audit-20261028/ops`
(Verzeichnis 0700, JSON-Dateien 0600). Keine Rohdaten im Repository.

## Quelle Und Konsistenz

Erneut geprueft: vorhandene rc32-Statusnotiz und
`/root/.local/share/steuerreport/deployments/rc32-upgrade-20261028T083400Z/state-before-rc32.tar.gz`.
Archiv: 55.301.759 Bytes, Mode 0600, 3.729 Mitglieder, eine DuckDB, kein WAL,
keine Links/Geraete, Eigentum 10001:10001. SHA256 nur im privaten Ergebnis.
Vorgaengercontainer weiterhin `exited`, Ende 08:34:16.440420129 UTC;
Archivabschluss laut Dateimetadaten 08:34:23.721460 UTC. Aktueller Container
startete 08:34:25.792124179 UTC und wurde durch diesen Auftrag nicht neu gestartet.

Diese Reihenfolge und der erfolgreiche lesbare Restore stuetzen die Konsistenz.
Der historische Archivierungsbefehl liegt hier nicht unabhaengig vor; Zeitstempel
allein waeren kein vollstaendiger Konsistenzbeweis. Zusaetzlich stimmen **alle**
logischen Tabellen des Backups mit den aktuellen produktiven Tabellen ueberein.
Keine aktive DB-Datei wurde kopiert. Nicht-DB-Dateien des heutigen Live-Standes
muessen nicht dem aelteren Backup entsprechen, etwa neuere Vorschauartefakte.

## Ausfuehrung

Aus eigenem Checkout, finaler Helfer:

```sh
python3 -B docs/audit/2026-10-28/ops_restore.py \
  --backup /root/.local/share/steuerreport/deployments/rc32-upgrade-20261028T083400Z/state-before-rc32.tar.gz \
  --evidence /root/.local/share/steuerreport/migration-audit-20261028/ops/restore-02 \
  --run-id restore-20261028-ops-02
```

Zum Wiederholen neue Evidence-Untermappe und neue Run-ID waehlen. Vorhandene
Ressourcen/Nachweise werden nicht ueberschrieben. Der Helfer verwendet lokale
Docker-CLI-Befehle, keinen Pull/Build und keine externe API/KI.

- `docker inspect` waehlt das exakte lokale Image des laufenden rc32-Containers:
  `sha256:eabf14414fd02fb48d098995e52880d6f3d9419ee58aa1972b9c51f5364b877a`.
- Quellsnapshot via `docker exec -i steuerreport-v2-lan python -`, ausschliesslich
  DuckDB `read_only=True`, SELECT innerhalb einer Lesetransaktion, ohne Store-API.
- `docker volume create --label steuerreport.audit.ops.20261028=RUN_ID` fuer eine
  neue Volume; vorher Existenzpruefung. Archivpfade und Mitgliedtypen werden validiert.
- Extraktion mit demselben Image in die neue Volume, Archivdatei read-only gemountet.
  Kein Live-Volume, kein V1-Verzeichnis, keine Live-Env im Restore.
- Alle Helper/Restorecontainer: `--pull=never --network none --read-only`,
  `--cap-drop ALL --security-opt no-new-privileges`, privates `/tmp`-tmpfs,
  **keine** `-p`/`-P`-Option. Extraktionshelper allein mit begrenzten Dateirechte-Caps.
- `docker create` plus Inspect bestaetigt Netzwerk, keine Portbindings und nur
  eigene Datenvolume. Imageeinstieg unter UID/GID 10001; kein Healthcheck nebenher.
- Start, lokales Health ueber `docker exec`, statisches HTML, Stop der eigenen
  Instanz; voller Vergleich. Danach eigener Start/Health/Stop und erneuter Vergleich.
- Zweiter Quellsnapshot und Vergleich; abschliessend nur eigene markierte
  Container und Volumes entfernen. Keine globalen Prune-/Compose-down-Befehle.

## Tatsaechliche Ergebnisse

| Pruefung | Ergebnis |
| --- | --- |
| App beim Erststart und Neustart | 0.2.0rc32, DuckDB |
| Statisches Frontend im Restore | HTTP 200, Root vorhanden, HTML-Hash gleich Produktion |
| Vollstaendige Quelltabellen vor/nach | identisch |
| Alle Nicht-DB-Quelldateien vor/nach | identisch |
| Produktiv-ID, Image, Config/Env, HostConfig, Mounts, Startzeit | im finalen Lauf identisch; weiterhin laufend |
| Alle Restoretabellen vor Start / nach Start / nach Neustart | identisch |
| Alle Restore-Nicht-DB-Dateien in diesen drei Staenden | identisch |
| Vault-Schluessel, Setup-Token, Privatprofil | byteweise Hashidentitaet in allen Restorestaenden |
| Synthetische Operationen auf privaten Restore-Daten | keine |
| Eigene Container/Volumes nach Beweissicherung | entfernt |

Private Nachweise pro Lauf: `source-before.json`, `source-after.json`,
`restore-before.json`, `restore-after-start.json`, `restore-after-restart.json`,
`table-differences.json`, `restore-result.json`. Erster Lauf vor abschliessender
Helferhaertung; zweiter Lauf prueft zusaetzlich unveraenderte Produktivkonfiguration
und liefert bei Erhaltsverletzung einen Fehlerstatus.

Hashverfahren: je Basistabelle alle Spalten/Typen und alle Zeilen, typgebundene
JSON-Serialisierung, SHA256 pro Zeile, sortierte Zeilenhashes mit Duplikaten,
anschliessend SHA256 ueber Schema und vollstaendige Hashfolge. Keine Stichprobe
oder reine Zeilenzaehlung. Dateihashes betreffen alle regulaeren Nicht-DB-Dateien;
DB/WAL/Lock werden nicht als konsistente Dateikopie behandelt. Die Snapshots
geben keinerlei Klartext-Datensaetze aus und bleiben trotzdem privat.

Grenzen: logische Tabellenidentitaet ist keine Byteidentitaet der DuckDB-Datei,
keine fachliche Neubewertung, keine Aussage ueber steuerliche Richtigkeit,
keine externe Entschluesselungs-/Providerprobe und keine Registryverifikation.
Der Restore hat keine V1-Anbindung und kann externe Dienste nicht erreichen.

## Zusaetzlicher Entwicklungsimage-Test

Der Koordinator baute lokal den eingefrorenen Codecommit
`ae8c30eb3e4f36849a6b31ae26a7aaf35c60636e` als `0.2.0rc33.dev0`.
Lokale Image-ID:
`sha256:aebbcdc02ce47bfda6031ac7e2409e3959a14024fac3d843e21d978d967ce6b6`.
Kein Push, kein Registry-Digest und keine produktive Umschaltung.

Mit demselben Backup wurde ausschliesslich eine weitere neue Volume ohne
Netzwerk/Ports gestartet. Wiederholbarer Zusatz zum obigen Aufruf:
`--candidate-image steuerreport-v2:migration-audit-20261028-ae8c30e
--candidate-revision ae8c30e`, eigene Run-ID und neuer Evidence-Ordner.
Der Helfer prueft weiterhin die produktive Quellrevision gesondert und pinnt
das gewaehlte Restoreimage nach Inspect auf seine lokale Image-ID.

Nachweis unter dem privaten Koordinator-Evidencepfad `candidate-restore/`:
Erststart und Neustart melden `0.2.0rc33.dev0`, DuckDB; statisches HTML HTTP200.
Alle Restoretabellen und Nicht-DB-Dateien vor/nach beiden Starts identisch.
Vaultkey, Token und Profil erhalten. Alle produktiven Tabellen/Dateien sowie
Containeridentitaet, Konfiguration und Startzeit unveraendert. Testressourcen
entfernt. Kein Import, Fachlauf oder Providerrequest auf den kopierten Daten.

Dieser Beleg gilt genau fuer das genannte lokale Image. Spaetere Codeaenderungen
benoetigen ihren eigenen Imagebezug; das Commitlabel allein ist kein Digest.

## Finaler Codefreeze

Nach den Integrationskorrekturen wurde der vollstaendig eingefrorene Commit
`b036b8ad4212d08d719fedec7dbc7115cf5704a9` erneut lokal gebaut und mit
demselben Ablauf offline gestartet und neugestartet. Image-ID und Laufzeit
stehen in `candidate-manifest.json`, private Belege in `final-restore-b036b8a/`.
Auch dieser Lauf bestand alle vollstaendigen Tabellen-/Datei-/Key-/Profil-
Erhaltspruefungen; Produktivcontainer, Quellen und Konfiguration blieben
unveraendert. Eigene Testcontainer/Volumes sind entfernt.

Zusaetzlich: leerer Start mit ausschliesslich neuen tmpfs-Pfaden, ohne
Netzwerk/V1 und mit schreibgeschuetzter Software. Health200, Version33.dev0,
DuckDB-Schema1 und0CanonicalEvents. Keine vorgegebenen privaten Konten.
Das ist weiterhin kein produktiver Rollback oder Nachweis fehlender
steuerlicher Sachverhaltsluecken.

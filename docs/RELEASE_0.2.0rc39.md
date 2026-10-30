# Steuerreport V2 0.2.0rc39

Releasekandidat fuer Speicherdiagnose und reproduzierbarere Docker-Builds.
Er ist keine steuerliche Abnahme und bestaetigt keine vollstaendige Migration
der nativen Anwendung.

## Aenderungen

- #30: Eine lesende Hostdiagnose zeigt Speicher und Inodes sowie aggregierte
  Docker-Angaben. Docker-Reclaimable ist keine Freigabe zum Loeschen. Ueber
  Quotas und den tatsaechlichen Pfad eines entfernten Daemons trifft das
  Werkzeug keine Aussage. Keine automatischen Bereinigungen.
- #30: Runtime-Abhaengigkeiten werden getrennt vom Anwendungscode aus dem
  gepinnten Lockfile installiert. Fehlende oder unvertraegliche Abhaengigkeiten
  sollen `pip check` im Build stoppen. Der Zwei-Build-Test muss den Cache-Treffer
  und isolierte Containerstarts gesondert belegen. Er zeigt keine garantierte
  Wiederverwendung zwischen unabhaengigen Release-Runnern.
- #31: README-Version, Releasehinweis und Docker-Pull-Befehl werden auf den
  aktuellen Release abgestimmt und durch einen Regressionstest geprueft.

## Grenzen

Alte Images, Volumes, Testdaten, Belege und Sicherungen werden nicht automatisch
entfernt. Die Bereinigung bereits belegter Kapazitaet bleibt eine gesonderte
Aufgabe. Das Lockfile enthaelt Versionspins, aber keine Artefakt-Hashes; isolierte
PEP-517-Buildabhaengigkeiten bleiben separat zu betrachten. Issue #8, #19 und
#20 bleiben fuer den fehlenden nativen Funktions- und Datenvergleich offen.

Vor einer produktiven Aktualisierung sind freier Speicher, ein konsistentes
Backup, ein getesteter Restore und der zum Schema passende Rueckweg zu pruefen.

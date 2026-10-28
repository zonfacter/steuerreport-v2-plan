# Rollback-Grenzen Und Ablauf

Dieser Auftrag fuehrt **keinen produktiven Rollback** aus. Die isolierten
Probecontainer/-volumes wurden entfernt; ihr Entfernen ist kein Produktivrollback.

## Verifizierter Ausgangspunkt

- Produktiv: `steuerreport-v2-lan`, lokale rc32-Image-ID und Volume im Manifest.
- Vorgaenger: `steuerreport-v2-lan-before-rc32-20261028t083400z`, weiterhin beendet;
  Image-ID `sha256:dc917d68c266651c56d8720c712b6f1db6f7bf12c5538e170312ada67d9db57b`.
- Vor-rc32-Archiv ist vorhanden und wurde zweimal isoliert mit dem **aktuellen**
  lokalen rc32-Image gestartet. Tabellen/Schluessel/Profil/Token erhalten.
- Alte Konfiguration/Env liegen im privaten urspruenglichen Deploymentverzeichnis;
  sie wurden nicht veroeffentlicht und nicht ins Restore-Environment uebernommen.

## Nur Nach Neuem Produktivauftrag

1. Plan/Wartungsfenster und Schreibpause mit Nutzer abstimmen; aktuelle
   vollstaendige Sicherung inklusive DB, WAL falls vorhanden, Profil, Schluessel,
   Token, Imports, Konfiguration und Artefakten konsistent erzeugen. Kein `cp`
   einer aktiv beschriebenen DuckDB und kein laufendes Volume-Tar als Ersatz.
2. Aktuelle und gewuenschte Image-ID sowie DB-/Schemavertraeglichkeit pruefen.
   Ein alter Container allein ist keine Rueckrollgarantie: er referenziert unter
   Umstaenden dieselbe seitdem migrierte Volume.
3. Gewuenschte Image-ID mit passendem historischen Datenstand zuerst in neuer
   privater Volume ohne Netzwerk/Ports pruefen. Die vorliegende Probe beweist
   Startbarkeit mit rc32, **nicht** mit dem Vorgaengerimage; dessen isolierter
   Starttest waere vor einem echten Downgrade noch erforderlich.
4. Konsistentes Backup vollstaendig wiederherstellen, inklusive unveraenderter
   Verschluesselungsschluessel und Token. Kein Secret-/Profilreset und keine
   Methodenumstellung. Historische Snapshots und Abgabepakete nicht umetikettieren.
5. Erst nach Freigabe bestehende URL/Bindadressen umschalten, keine Ersatz-URL als
   Produktivabschluss. Health, statische Dateien und vorher gepruefte RO-Wege
   sowie Volltabellen-/Konfigurationserhalt nachweisen; keine Recalc-/Importprobe.
6. Rueckweg auf den gesicherten aktuellen Stand offenhalten. Erst nach separater
   Abnahme eventuell veraltete Ressourcen entfernen; keine fremden Volumes loeschen.

Dieser Ablauf ist bewusst keine ausfuehrbare Stop-/Restart-Anweisung. Kein
Produktivschritt davon wurde hier ausgefuehrt. Kein Push, Tag, Release oder Deploy.

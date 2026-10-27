# Steuerreport 0.2.0rc20

Release Candidate vom 27.10.2026: defensive Korrekturen am Solana-Historienimport.
Details und Pruefnachweise:
[Fehlerkorrektur Solana-Historie](FEHLERKORREKTUR_SOLANA_HISTORIE_2026-10-27.md).

## Korrekturen

- Deduplizierung nach Wallet und Signatur mit Vergleich des vollstaendigen
  Rohzeilensatzes: ueberlappende Seiten und Wiederholungen erhoehen Bestaende
  nicht erneut; widerspruechliche Belege werden abgewiesen.
- SOL-Gebuehren werden getrennt und genau einmal gebucht, nicht als
  Kaufgegenwert. Bei fehlgeschlagenen Transaktionen wird nur die nachgewiesene
  Gebuehr des Wallet-Gebuehrenzahlers beruecksichtigt.
- Blosse Bestandsdeltas erzeugen keine angenommenen Trades, Einkommen oder
  Rewards. Ungeklaerte Transfers erhalten keinen aus Gegenfluessen erfundenen
  Preis; Solana-Mints werden exakt zugeordnet.
- Unvollstaendige Seiten werden vor dem Import vollstaendig abgewiesen
  (Fail-closed), ohne Teilimport oder Cursorfortschritt.
- Unterbrochene Importe gelten beim Retry nicht als erfolgreich. Ein
  Erfolgscheckpoint entsteht erst nach vollstaendig abgeschlossener Pipeline;
  erfolgreiche leere Seiten bleiben wiederholbar.
- Eine gemeinsame POSIX-Dateisperre schuetzt Pruefung, Schreiben und Pipeline
  auch ueber mehrere Store-Instanzen und Prozesse hinweg.

## Pruefstand

Am finalen Code bereits verifiziert: **1518 Tests bestanden, 4 uebersprungen**;
die fokussierten Mapper-/Integrationstests ergaben **83 bestanden**.
Die Pruefungen verwendeten synthetische Antworten und temporaere DuckDBs, ohne
externe Provider-Aufrufe. Weitere Lint-, Build- und Smoke-Nachweise stehen im
verlinkten Korrekturdokument. Die Funktionspruefungen haben keine produktiven
Historienimporte oder steuerlichen Korrekturen ausgefuehrt.

## Grenzen

- Kein gefuehrter vollstaendiger Historienimport, persistenter Historienjob
  oder neuer Pause-/Resume-Ablauf. Quellen-Sync liest weiterhin nur Bestaende.
- Keine automatische Korrektur historischer Finanzdaten oder bestehender
  Doppelimporte. Abweichende Belege bleiben pruefpflichtig.
- Fachliche Klassifizierung und Review bleiben erforderlich; ungeklaerte
  Bewegungen blockieren den Export. Keine automatische steuerliche Freigabe.
- Die Importsperre ist weder ein transaktionaler Rollback der gesamten Pipeline
  noch ein allgemeiner DuckDB-Mehrprozess-Schreibkoordinator.
- **RC, keine steuerfachliche Gesamtzertifizierung:** Die Tests belegen weder
  eine vollstaendige reale Historie noch die steuerliche Richtigkeit eines
  konkreten Nutzerbestands.

## Image und Bereitstellung

Vorgesehener unveraenderlicher GHCR-Versionstag:
`ghcr.io/zonfacter/steuerreport-v2:0.2.0rc20`.
Ein oeffentliches Repository garantiert kein oeffentliches GHCR-Paket: Das Paket
kann privat sein; anonymer Pull wird nicht zugesichert.

Build, Veroeffentlichung und produktiver Docker-Wechsel liegen beim
uebergeordneten Release-Prozess. Diese Notiz bestaetigt keinen abgeschlossenen
Build, Publish oder Deployment.

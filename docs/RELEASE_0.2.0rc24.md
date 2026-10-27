# Steuerreport V2 0.2.0rc24

**Nicht produktiv ausgerollter Kandidat.** 1.818 Unit-Tests und die Browserpruefungen
bestanden; der anschliessende CI-Dokumentationscheck beanstandete veraltete
API-Zeilenverweise. Die korrigierte Fassung wird als rc25 separat versioniert.
Der rc24-Tag bleibt unveraendert. Keine bestaetigte Finanzdatenabweichung und
kein produktiver rc24-Import oder Containerwechsel.

## Abrufgeschwindigkeit zentral einrichten

**Einrichtung -> Abrufsteuerung** bietet die konservative Voreinstellung
**Solana Public RPC - Free** und weiterhin eigene editierbare Budgetprofile.
Speichern setzt lokale Limits, startet aber keinen externen Abruf oder Import.
Die gemeinsame Vorgabe ist 3 Requests/s, 30/10 s und 180/min, Burst 1,
Parallelitaet 1. Historien-RPC-Methoden erhalten zusaetzliche Endpunktprofile.
Abweichende vorhandene Einstellungen werden nicht still ueberschrieben.

Backend und UI unterstuetzen nun echte rollierende 10-Sekunden-Fenster
zusaetzlich zu den bisherigen Sekunden-, Minuten-, Burst-, Kosten- und
Parallelitaetsgrenzen. Gemeinsam geltende Gruppen werden vor jedem Requeststart
atomar geprueft. Wiederholungen und weitere Historienseiten umgehen sie nicht.
Gespeicherte Starts und Pausen bleiben bei Konfigurationsaenderungen erhalten.

Die Solana-Dokumentation wurde am 27.10.2026 geprueft; ihre veraenderlichen
oeffentlichen Obergrenzen sind keine garantierte Quote. Das Preset ist bewusst
vorsichtig wegen neuer Verbindungen und gemeinsam genutzter IP-Adressen.
Fremde Anwendungen werden nicht koordiniert; das dokumentierte Bytebudget
ist nicht gemessen oder implementiert. Keine garantierte Transaktionsrate,
kein automatischer Key-/IP-Wechsel und keine neue Historienparallelisierung.

## Unveraenderte Fachregeln

Keine Finanzdatenmigration und keine Aenderung von Steuer-, FIFO-, Eigentums-,
Review- oder Importfreigaberegeln. Altdaten und Originalbelege bleiben erhalten.
Die Voreinstellung startet weder pausierte noch abgebrochene Auftraege.

- [Bedienung und Grenzen](SOLANA_ABRUFLIMITS.md)
- [Inbetriebnahme](INBETRIEBNAHME.md)
- [Automatischer Quellenimport](AUTOMATISCHER_QUELLENIMPORT.md)

Tatsaechlich ausgefuehrte Tests, Browsernachweise, Secret-/Datenschutzpruefungen,
Image- und Deploymentverifikation werden als Release-Artefakte beigefuegt.

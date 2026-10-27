# Steuerreport V2 0.2.0rc25

## Solana-Abrufgeschwindigkeit unter Einrichtung

Die neue **Einrichtung -> Abrufsteuerung** bietet die Voreinstellung
**Solana Public RPC - Free** und eigene editierbare IP-, Anbieter- und
Methodenprofile. Gemeinsame konservative Vorgabe: **3 Requests/s, 30 je
rollierenden 10 Sekunden, 180/min**, Burst 1, Parallelitaet 1. Speichern
startet keinen Abruf, Import oder Neuberechnung. Abweichende vorhandene
Profile werden nicht still ueberschrieben.

Echte rollierende 10-Sekunden-Fenster gelten zusaetzlich zu Sekunden-, Minuten-,
Kosten-, Burst- und Parallelitaetsgrenzen. Alle passenden Gruppen werden vor
jedem Requeststart atomar geprueft, auch bei Retries und Historienseiten.
Bestehende Startbuchungen und Pausen bleiben erhalten. Eine unzulaessige
Verengung mit bereits reservierten Requests wird vor dem Speichern abgewiesen.

Doppelklickschutz, Revisionsbindung fuer Profil-/Tarifentwuerfe, explizite
Konfliktbehandlung und mobile Tabellenumbrueche sind abgesichert. Das Profil
bleibt unter den am 27.10.2026 geprueften oeffentlichen Requestobergrenzen,
garantiert aber keine Geschwindigkeit oder Herstellerrestquote. Fremder
IP-Verkehr und das dokumentierte Bytebudget sind nicht koordiniert bzw.
gemessen. Keine neue Historienparallelisierung und kein Key-/IP-Wechsel.

## Korrigierter Kandidat

rc24 wurde nach erfolgreichen Unit-/Browsertests wegen veralteter generierter
API-Zeilenverweise nicht produktiv ausgerollt. rc25 korrigiert diese Referenz
und Versionsmetadaten; die gepruefte Limiter- und Fachlogik bleibt unveraendert.
Der rc24-Tag wird nicht verschoben.

Keine Finanzdatenmigration oder automatische steuerliche Entscheidung.
Originaldaten, FIFO-, Steuer-, Eigentums-, Review- und Importfreigaben bleiben
unveraendert. Pausierte oder abgebrochene Auftraege werden nicht gestartet.

- [Bedienung und Grenzen](SOLANA_ABRUFLIMITS.md)
- [Inbetriebnahme](INBETRIEBNAHME.md)
- [Automatischer Quellenimport](AUTOMATISCHER_QUELLENIMPORT.md)

Tatsaechliche CI-, Browser-, Datenschutz-, Image- und Deploymentnachweise
werden als Release-Artefakte beigefuegt.

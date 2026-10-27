# Steuerreport V2 0.2.0rc27

Stand: **27.10.2026, Releasekandidat**. Verbindliche CI-, Image- und
Deploymentnachweise werden getrennt im Draft Release bereitgestellt.

## Anbieterwahl und Abruffortschritt

- Explizit **Oeffentlicher RPC (Free)** oder **Eigener Anbieter (Free/Premium)**
  mit Helius-, Alchemy- oder Custom-Zugang waehlen. Ein Key beweist keinen
  gebuchten Tarif und erhoeht keine lokalen Quoten.
- Neue Auftraege bleiben an ihre konkrete Anbietereinrichtung gebunden.
  Kein stiller Fallback; ein Anbieterwechsel erfordert einen neuen Auftrag.
- Wirksame gemeinsame IP-, Anbieter- und Methodenlimits bleiben sichtbar.
  Auch ein Premium-Tarif kann durch niedrigere lokale Limits begrenzt sein.
- Erst die verfuegbare Signaturliste inventarisieren, dann eindeutige
  Transaktionsdetails abrufen. Vor abgeschlossenem Inventar kein erfundener
  Gesamtprozentsatz oder Countdown.
- Restzeit nur fuer verbleibende verfuegbare Details, nach mindestens fuenf
  aktuellen Messungen und unter den wirksamen Limits. Budgetpausen, unbekannte
  oder veraltete Daten und nachfolgende Vorschauberechnung sind getrennte Zustaende.

## Testkorrektur Gegenueber rc26

Der unveraenderliche Kandidat rc26 (`9e85c2423e48d994bb39794971422924aeae44d7`)
wurde nicht produktiv deployt. In GitHub-CI 40515031326 scheiterte ein neuer
HTTP-Mocktest: Limiter und Transport nutzten unterschiedliche Uhren, wodurch
die Laufzeit des Runners eine kuenstliche Deadlineverletzung ausloeste.
Der Test verwendet jetzt ausdruecklich dieselben kontrollierten Zeitfunktionen.
Assertions fuer den tatsaechlichen Request, Providerbindung und Budgetverbrauch
bleiben bestehen. Produktiver Abrufcode und Fachberechnung sind gegenueber
rc26 unveraendert. Tag und Fehlbeleg werden nicht ueberschrieben.

## Grenzen Und Nachweise

Die Detailabrufe bleiben sequenziell. Ein hoeheres Parallelitaetslimit startet
keine zusaetzlichen Detailworker. RPC-Aufbewahrung, geschlossene Tokenkonten
und historische Eigentumswechsel bleiben Grenzen; eine abgearbeitete Liste
beweist keine vollstaendige Wallet-Historie. Originalexporte ergaenzen, wo noetig.
Keine automatische steuerliche Klassifizierung oder Freigabe. Vorschau und
ausdrueckliche Import-/Neuberechnungsbestaetigungen bleiben erforderlich.

Browsernachweise verwenden ausschliesslich synthetische Daten und kontrollierte
Providerantworten. Sie belegen keine Prognosegenauigkeit eines echten RPC-Tarifs.
Die verbindlichen ausgefuehrten Pruefungen stehen in den Releaseanhaengen.
Keine steuerliche Vollstaendigkeits- oder Produktfreigabe.

- [Automatischer Quellenimport](AUTOMATISCHER_QUELLENIMPORT.md)
- [Solana-Abruflimits](SOLANA_ABRUFLIMITS.md)
- [Inbetriebnahme](INBETRIEBNAHME.md)
- [Fachliche Funktionsgrenzen des rc26-Kandidaten](RELEASE_0.2.0rc26.md)

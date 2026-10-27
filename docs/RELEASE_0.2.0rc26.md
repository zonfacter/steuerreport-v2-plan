# Steuerreport V2 0.2.0rc26

Stand: **27.10.2026, Releasekandidat**. Verbindliche Pruef-, CI-, Image- und
Deploymentnachweise gehoeren gesondert in den Draft Release und muessen den
jeweils geprueften Quellstand ausweisen. Diese Hinweise ersetzen diese Belege
nicht und sind keine steuerliche Vollfreigabe.

## Explizite Solana-Anbieterwahl

Neue Historienauftraege unterscheiden **Oeffentlicher RPC (Free)** ohne Key
von **Eigener Anbieter (Free/Premium)** mit eingerichtetem Helius-, Alchemy-
oder Custom-RPC. Die Auswahl bestaetigt keinen gebuchten Tarif und erhoeht
keine lokalen Quoten. Gemeinsame IP-, Anbieter-, Methoden- und gegebenenfalls
weitere konfigurierte Budgets begrenzen den Abruf weiterhin gemeinsam.

Der Auftrag ist an seine gewaehlte Anbietereinrichtung gebunden. Fortsetzen
wechselt keinen Anbieter; eine geaenderte Key-/URL-Bindung wird nicht still
uebernommen. Anbieterwechsel erfordert einen neuen Auftrag. Ein Fehler loest
keinen automatischen Wechsel auf einen anderen RPC aus. Alte Auftraege ohne
gespeicherte explizite Bindung erhalten keinen nachtraeglichen Pin-Nachweis.

## Inventar und begrenzte Restzeitschaetzung

Zuerst werden die verfuegbaren finalisierten Signaturreferenzen inventarisiert
und private hashadressierte Originalseiten gesichert. Erst nach Abschluss
steht die eindeutige Signaturzahl fuer den anschliessenden Detailabruf fest.
Duplikate zwischen Adressen erzeugen keinen zweiten Detailabruf.

Eine Restzeitschaetzung betrifft ausschliesslich die verbleibenden verfuegbaren
RPC-Transaktionsdetails: abgeschlossenes Inventar, mindestens fuenf erfolgreich
gemessene Detailabrufe, aktuelle Messung und verfuegbare wirksame Limitdaten
sind Voraussetzungen. Die geglaettete gemessene Rate wird durch die effektiven
gemeinsamen Limits begrenzt. Discovery bleibt ohne bekannten Nenner und ETA;
pausierte, abgebrochene oder fehlerhafte Auftraege haben keinen Countdown.
Die nachfolgende Vorschauberechnung hat keine ETA. Ein beendeter Detailabruf
ist weder eine Importfreigabe noch eine Schaetzung der restlichen Vorschauzeit.

## Implementierungsgrenzen

- Detailabrufe bleiben sequenziell; ein hoeheres Parallelitaetslimit erzeugt
  keine zusaetzlichen Detailworker und garantiert keine hoehere Transaktionsrate.
- RPC-Retention, geschlossene Tokenkonten und historische Eigentuemerwechsel
  bleiben offen. Auch eine vollstaendig abgearbeitete verfuegbare Liste beweist
  keine vollstaendige Wallet-Historie. Originalexporte gegebenenfalls ergaenzen.
- Vorschau, gesonderte Import-/Neuberechnungsbestaetigung und fachliche Review-
  Grenzen bleiben bestehen. Keine automatische Aenderung der Steuer-/FIFO-Regeln.
- Der synthetische Anbieter-/ETA-Browsercheck ist mit separatem Artefaktpfad in
  die CI eingebunden. Die Einbindung allein belegt keinen erfolgreichen CI-Lauf.
- Generierte API-Dokumente und PDFs benoetigen einen gesonderten Abgleich mit
  dem freizugebenden Quellstand. Diese Hinweise ersetzen den Abgleich nicht.

## Lokaler Teilpruefstand

Am **27.10.2026** separat gemeldete lokale Ergebnisse:

- Neuer synthetischer Anbieter-/ETA-Browsercheck: **16/16 Szenarien**, dazu
  **33 Screenshots**.
- Bisheriger Historien-Browsercheck: **13/13 Szenarien**.
- Historien-E2E-Pruefung gegen das tatsaechliche isolierte Backend: bestanden.

Diese Teilnachweise sind kein Nachweis einer bestandenen Gesamtsuite und
gelten nicht als GitHub-CI-, Image- oder Deploymentbeleg. Massgeblich fuer die
technische Freigabe sind die gesonderten, quellstandgebundenen Nachweise im
Draft Release. Eine technische Freigabe ersetzt keine fachliche oder
steuerliche Vollfreigabe.

## Quellen und Bedienung

Offizielle Quellen geprueft am **27.10.2026**: [Solana: Clusters and Public RPC
Endpoints](https://solana.com/docs/references/clusters) und [Helius: Rate
Limits](https://www.helius.dev/docs/billing/rate-limits). Oeffentliche Grenzen
koennen sich aendern; Helius unterscheidet Tarif-/Produktlimits. Daraus wird
weder der tatsaechliche eigene Tarif noch eine verbleibende Herstellerquote
abgeleitet. Keine neuen Herstellerzahlen werden als lokale Vorgaben uebernommen.

- [Automatischer Quellenimport](AUTOMATISCHER_QUELLENIMPORT.md)
- [Solana-Abruflimits](SOLANA_ABRUFLIMITS.md)
- [Inbetriebnahme](INBETRIEBNAHME.md)

# Steuerreport V2 0.2.0rc29

Stand: 27.10.2026, Releasekandidat. Konkrete Pruef-, CI-, Image- und
Deploymentergebnisse werden getrennt als Nachweise im Draft Release hinterlegt.

## Historische EUR-Bewertung

Neuer normaler Bedienweg unter Portfolio & Haltefristen -> EUR-Preise ermitteln.
Preisbedarf lokal planen, externe Abfrage ausdruecklich starten, isolierte
Berechnung und Originalantworten pruefen, EUR-Preise und Neuberechnung getrennt
bestaetigen. Die neue Funktion benoetigt keine V1-Datenbank oder Altinstallation.

CoinGecko liefert direkte historische EUR-Tagesreferenzen. DefiLlama-USD-Quotes
werden mit historischen EZB-USD/EUR-Tagesreferenzen ueber Frankfurter v2
umgerechnet. Zeit-/Identitaetspruefungen, private Preiszuordnungen und
SHA256-gebundene Belege; keine heutigen oder spaeteren Ersatzkurse. Fehlende
Preise und Tarif-/Providerfehler bleiben offen. Bestehende Limiter gelten;
FX-Aufrufe und Wiederholungen zaehlen zum begrenzten HTTP-Abschnittsbudget.

Uebernahme validiert Datenstand, Software und Belege und uebernimmt die
isolierte Berechnung atomar mit menschlichem Freigabeprotokoll. Keine
automatische fachliche Quellen-, Review-, Token- oder Jahresentscheidung.
Historische Abgabesnapshots werden nicht ersetzt. Aktuelle Marktpreise bleiben
ein separater bestehender Abruf mit ausdruecklich erklaerter Schreibwirkung.

## Bestehende Historienvorschauen

Nach einem Versionswechsel kann eine fertige Vorschau aus den gespeicherten
Originalbelegen lokal neu berechnet werden. Alte Vorschau hashgebunden
archiviert, kein erneuter Anbieterabruf und kein automatischer Import.
Quellen- und Credentialbindungen bleiben geprueft; Importfreigabe bleibt offen.

## Grenzen

Keine universelle Kursverfuegbarkeit, Tarifgarantie, WORM-Zertifizierung oder
steuerliche Freigabe. Tagesreferenz ist kein Intraday-Ausfuehrungskurs. Token-
Identitaet und vollstaendige Anschaffungshistorie bleiben gesondert zu pruefen.
Legacy-Endpunkte bleiben kompatibel; nur der neue Ablauf ist V1-unabhaengig.

Details und Bedienung: [Historische EUR-Preise](HISTORISCHE_EUR_PREISE.md).

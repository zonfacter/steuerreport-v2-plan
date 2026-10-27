# Steuerreport V2 0.2.0rc30

Stand: 27.10.2026, Releasekandidat. Verbindliche Test-, Image- und
Deploymentergebnisse stehen getrennt als Nachweise im Draft Release.

Enthaelt den vollstaendigen historischen EUR-Preisworkflow aus rc29:
V1-unabhaengige Planung, CoinGecko-EUR oder DefiLlama mit historischen
EZB-USD/EUR-Tagesreferenzen ueber Frankfurter v2, private Originalbelege mit
SHA256, isolierte Berechnung und ausdrueckliche atomare Preisuebernahme.
Aktuelle Preise bleiben separat, keine automatische fachliche Freigabe.

Zusaetzlich normalisiert `create_app` uebergebene Datenbankpfade, damit
bestehende pfadbasierte Aufrufer auch mit dem neuen Preisrouter funktionieren.
Die Preis-Mocktests verwenden dieselbe kontrollierte Uhr fuer Limiter,
HTTP-Transport und Scope. Es werden keine Assertions oder Tests entfernt.

rc29 wurde nicht deployt: Main-CI hatte fuenf Mock-Uhrfehler und eine
Pfadkompatibilitaetsregression (2035 bestanden, vier uebersprungen, sechs
fehlgeschlagen). Sein Tag bleibt unveraendert, sein Publisher wurde vor dem
Image-Publish abgebrochen. Produktiv blieb bis zur geprueften Aktualisierung
rc28 erhalten. Die neue Version erfordert erneut vollstaendige CI-Pruefungen.

Nach Softwarewechsel eine alte fertige Historienvorschau ausdruecklich aus
den gespeicherten Originalen lokal erneut berechnen, dann selbst pruefen und
gegebenenfalls importieren. Kein erneuter RPC-Abruf und kein automatischer Import.

Bedienung, API, Quellen und Grenzen: [Historische EUR-Preise](HISTORISCHE_EUR_PREISE.md).
Tagesreferenzen sind keine belegten Intraday-Ausfuehrungskurse. Fehlende
Preise, Tokenidentitaet, Historienabdeckung und fachliche Freigaben bleiben offen.

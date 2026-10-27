# Steuerreport V2 0.2.0rc31

Releasekandidat vom 27.10.2026. Tatsaechliche Test-, Image- und
Deploymentnachweise werden separat am Draft Release hinterlegt.

## Bedienbarer Ablauf Ohne KI

Portfolio & Haltefristen -> EUR-Preise ermitteln -> Alle erkannten Token ->
Jahr oder Alle Jahre -> Preisbedarf planen -> externen Abruf bestaetigen ->
Vorschau pruefen -> gegebenenfalls weitere Abschnitte -> Jahresdateien
herunterladen -> Preise und Neuberechnung getrennt freigeben.

Der Modus umfasst auch Transfer-Token und ist nicht auf steuerlich bereits
angeforderte Preise beschraenkt. Die alte steuerliche Bedarfsplanung bleibt
als eigener Modus verfuegbar. Bestehende Routen und Abgabestaende bleiben.

Originale Solana-Mints, Konflikte zwischen gleichnamigen Token, Spam-Review,
fehlende Kurse und vorhandene Tagesabdeckung werden getrennt ausgewiesen.
Ein Preis aus einem Vorjahr schliesst keine aktuelle Tagesluecke.

Anfragebudgets gelten pro ausdruecklich gestarteten Abschnitt einschliesslich
Retries und FX. Die gemeinsame serverseitige Abrufsteuerung bleibt wirksam.
Fortsetzen erzeugt eine neue gebundene kumulative Vorschau, ohne produktive
Preisuebernahme. Gespeicherter Status ist nach Seiten-/Verbindungswechsel
lesend erreichbar; ein Prozessabbruch wird nicht blind automatisch wiederholt.

JSON, Markdown und deterministisches ZIP enthalten alle Zeilen und
Jahresdateien, Originalantworten und Hashmanifest, nicht nur eine UI-Seite.
Der bestehende CSV-Preisimport ist ebenfalls von seinem 50-Zeilen-
Vorschaulimit entkoppelt; vollstaendige Validierung bleibt Pflicht.

## Fachliche Grenzen

Preisvorschauen normalisieren keine Rohimporte erneut und spielen keine
Ereigniskorrekturen neu ein. Rohdaten und Canonical Events sind hashgebunden
eingefroren. Ein Preis kann dennoch Kosten, Flows, Lots und Steuerbetraege
aendern; die Vorschau weist Auswirkungen und Tax-Line-Deltas aus.

Ein Tagesreferenzpreis ist weder belegter Ausfuehrungskurs noch Einkommen.
Transfers werden nicht allein durch Bepreisung zu Rewards oder Trades.
Fehlende Historie, Identitaetsfragen und Quellen-/Token-/Review-/Jahresfreigaben
bleiben offen. Kein automatischer steuerlicher Korrekturentscheid.

Die Anwendung setzt weiterhin ein vertrauenswuerdiges LAN/VPN oder einen
vorgeschalteten TLS-/Authentifizierungsschutz voraus. Freigebender Name ist
eine dokumentierte Eigenangabe, keine neue globale Benutzeranmeldung.
Dateirechte und SHA256 sind kein zertifizierter WORM-Speicher.

Ein produktives Update uebernimmt keine Preisvorschau und startet keinen
externen Abruf. Daten, private Einstellungen und Secrets sind vor dem
Containerwechsel zu sichern und danach auf Gleichheit zu pruefen.

Details: [Historische EUR-Preise](HISTORISCHE_EUR_PREISE.md).

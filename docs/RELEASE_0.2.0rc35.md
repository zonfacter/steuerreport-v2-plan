# Steuerreport V2 0.2.0rc35

Releasekandidat vom 28.10.2026 auf Basis von rc34. Keine steuerliche
Jahresfreigabe und keine automatische Korrektur vorhandener Finanzdaten.

## Korrektur

Die reale oeffentliche GitHub-Release-Liste liefert rund 606 KiB entpackte
Metadaten, insbesondere wegen der Release-Anlagen. Das bisherige Seitenlimit
von 512 KiB hat deshalb eine erfolgreiche HTTP-Antwort verworfen. Das Limit
betraegt jetzt 1 MiB pro Seite. Das Gesamtlimit von 2 MiB, maximal fuenf
Requeststarts, der zentrale Limiter und null automatische Wiederholungen
bleiben unveraendert. Keine Zugangsdaten sind fuer diese Abfrage erforderlich.

Eine Regression prueft grosse synthetische Anlagenmetadaten durch denselben
verwalteten HTTP-Transport wie die Produktionsanwendung. Bestehende Proben
fuer Uebergroesse, Gesamtbudget, Zeitlimit und Rate-Limit bleiben verbindlich.

## Update und Grenzen

Vor dem Wechsel das gesamte dauerhafte /state-Volume konsistent sichern,
einschliesslich Originalimporte, Konfigurationen und Vault-Schluessel.
Rueckweg mit vorherigem Image und wiederhergestellter Sicherung vorhalten.
Das Update startet weder Import noch Steuerneuberechnung, akzeptiert keine
Reviews und aktiviert keine FIFO-Methode. Historische Abgabepakete bleiben
unveraendert. Fachliche Beleg- und Kostenbasisluecken bleiben offen.

Die Implementierungs- und Originalnachweise aus rc34 gelten fort. Neue
Test-, Image-, Restore- und Laufzeitnachweise werden als Release-Anlagen
bereitgestellt; implementiert und technisch getestet ist keine fachliche
Abnahme aller Steuerjahre.

Image: `ghcr.io/zonfacter/steuerreport-v2:0.2.0rc35`, linux/amd64.
Ein oeffentliches GitHub-Repository garantiert keinen anonymen GHCR-Pull.
Bei fehlender Paketberechtigung ist ein lokaler Build aus dem exakt
verifizierten Tag moeglich. Lokaler und CI-Build sind getrennt identifiziert.

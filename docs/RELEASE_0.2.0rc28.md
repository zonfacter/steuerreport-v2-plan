# Steuerreport V2 0.2.0rc28

Stand: **27.10.2026, Releasekandidat**. Verbindliche Test-, CI-, Image- und
Deploymentnachweise stehen getrennt im Draft Release.

## Anbieterlimits Direkt Einstellen

Unter **Einrichtung -> Abrufsteuerung -> Limitprofil** sind Alchemy, Helius,
eigener Solana-RPC und Solana Public RPC direkt waehlbar. Kein manuelles
Eingeben einer technischen Budgetgruppen-ID ist dafuer mehr erforderlich.

Ohne eigenes gespeichertes Profil zeigt der Editor das geerbte Standardprofil
und kennzeichnet diesen Zustand. Erst **Limitprofil speichern** legt es an.
Auswahl oder Anzeigen starten keinen Request und speichern keine Konfiguration.
Sekunden-, 10-Sekunden-, Minutenwerte, Burst, Parallelitaet und Timeout bleiben
getrennt editierbar. Untergeordnete und gemeinsame Budgets gelten weiterhin.
**Gemeinsames IP-Limit bearbeiten** fuehrt zum passenden vorhandenen oder
geerbten Profil. Bestehende Startbuchungen und Quoten werden nicht zurueckgesetzt.

## Alchemy: CU/s Sind Keine Requests/s

Alchemy dokumentiert den Durchsatz in Compute Units pro Sekunde. Die
Methodenkosten unterscheiden sich; aus 500 CU/s werden nicht 500 Requests/s.
Die Anwendung erhoeht deshalb aus einer Key-Eingabe keine Requestquote.
Dieses Release verbessert die bestehenden Requestprofile; es implementiert
keinen neuen herstellerspezifischen CU/s-Limiter. Das lokale Kostenbudget pro
Minute ist kein Ersatz fuer dessen rollierende Durchsatzsemantik.

Bei Helius RPC-, DAS-/Enhanced-API- und methodenspezifische Grenzen unterscheiden.
Nur belegte, zum eigenen Dienst und Tarif passende Requestwerte uebertragen.
Ein engeres IP- oder Methodenbudget kann beide Anbieter weiterhin begrenzen.
Der Detailabruf bleibt sequenziell; ein hoher Grenzwert ist kein garantierter
Durchsatz. Keine realen Anbieterabfragen als Test oder automatische Finanzimporte.

## Nachweise Und Grenzen

Neue Browserfaelle verwenden einen echten isolierten Limits-Router und
Dateikoordinator mit synthetischen Daten. 500 Requests/s sind dort ein
ausdruecklicher Testwert, keine Herstellerempfehlung oder Tarifverifikation.
Steuer-, FIFO-, Import-, Freigabe- und Quellenregeln bleiben unveraendert.

- [Alchemy-Durchsatz](https://www.alchemy.com/docs/reference/throughput)
- [Alchemy-Methodenkosten](https://www.alchemy.com/docs/reference/compute-unit-costs)
- [Helius-Limits](https://www.helius.dev/docs/billing/rate-limits)
- [Bedienung und Grenzen](SOLANA_ABRUFLIMITS.md)

Offizielle Referenzen geprueft am 27.10.2026; kein Nachweis des individuellen
Kundenvertrags. Keine steuerliche Vollstaendigkeitsfreigabe.

# Referenzmatrix G01-G25 Nach Blocker-Nacharbeit

Implementiert, technisch getestet und fachlich abgenommen sind verschiedene
Zustaende. Original-Testresultate stehen in `evidence/manifest.json` und den
unveraenderten JUnit-Dateien. **Keine Zeile hat eine fachliche Jahresfreigabe.**
PASS gilt nur fuer die beschriebenen synthetischen Faelle, nicht fuer den
produktiven Datenbestand. Fruehere engere Beweisgrenzen werden nicht geloescht.
Alle unten referenzierten Original-/Zusatzproben sind bestanden; die
maschinenlesbare CSV/JSON-Matrix bindet pro G-ID die tatsaechlichen Testnamen
und kennzeichnet den Status ausschliesslich als `passed_scoped`.

| ID | Implementierung / technische Sollprobe | Nacharbeit | Weiterhin offen |
| --- | --- | --- | --- |
| G01 | EUR-Kauf, Teilverkauf, Restbasis, Jahreswerte | Unveraenderte Originalprobe | Separater PDF-Fachzahlenabgleich aller Faelle |
| G02 | EUR-Erwerbs- und Verkaufskosten einmalig | Originalprobe und neue Fee-Proben beider Engines | Individuelle steuerliche Kostenrolle |
| G03 | Erwerbsassetgebuehr reduziert Nettomenge, keine zweite Verwertung | Originalprobe plus neue Fee-Proben | Nicht jeder Connector-/Nettoexportvertrag |
| G04 | Drittasset-FIFO-Verbrauch, historischer EUR-Wert, Kostenrolle und eigene Verwertung | Originalprobe plus neue feste Zahlen-/Pool-/Mehrlot-/Alt-DB-/Stale-Proben | Swapkostenrolle bleibt gesperrt; keine individuelle Kostenbasisherkunft freigegeben |
| G05 | Verknuepfter Token-Swap ohne fiktive EUR-Einzahlung | Unveraenderte Originalprobe | Slippage-/Sonderprotokoll-/Gebuehrenmethoden nicht allgemein abgenommen |
| G06 | Historischer Stablecoin-EUR-PricePoint konsumiert | Originalprobe; FX-Consumer separat erweitert | Nicht jeder Stablecoin-/Originalbelegbeschaffungsweg |
| G07 | Depegwert statt pauschaler USD-Paritaet | Unveraenderte Originalprobe | Echtheit/Abdeckung aller produktiven Depegkurse |
| G08 | USD/EUR direkt und EUR/USD invers, 100USD ergeben90EUR | Neue unabhaengige echte FX-Consumer | Keine Ausfuehrungskursbehauptung fuer Tagesreferenzen |
| G09 | Juengster belegter Vortag bis sieben Kalendertage; Wochenende/Feiertag, missing/stale/future | Neue unabhaengige echte FX-Consumer | Technische Policy, keine universelle steuerliche Freigabe |
| G10 | Lookup/Coverage/Tax/Review/Derived/Export ohne stillen Altpreis; keine Zukunftsrueckdatierung | Originalproben und zusaetzliche FX-/Pipeline-Regression | Nicht jede Altprovenienz und Preisquelle geheilt |
| G11 | Globale Methode und Wallet-Vorschau getrennt | Unveraenderte Originalprobe | Keine produktive Depotmethodenaktivierung |
| G12 | Eigenuebertrag fuehrt Anschaffungsdatum und Basis fort | Unveraenderte Teilprobe | Alle Netzwerkgebuehren und Fremdbelege |
| G13 | Rewardzugang und Verwertung getrennt; Konvertierung verdoppelt Income nicht | Originalprobe plus neue unabhaengige Income-Regression | Privat-/Betriebsherkunft bleibt Sachverhaltsentscheidung |
| G14 | Unklares Income bleibt Review | Unveraenderte Teilprobe | Vollstaendige Reward-/Sphaerenklassifikation |
| G15 | Kalenderjahrestag/Folgetag/Schaltjahr im Jahres-/CSV-/Planungsconsumer | Unveraenderte Originalproben | Reale Quellzeit und Einzelfallscope |
| G16 | Berlin-Jahr, UTC-/DST-Grenzen konsistent | Unveraenderte Originalproben | Kein exhaustiver Zeitzonenbeweis |
| G17 | Fehlender Preis/Kauf/Anfangsbestand und Nullbasis nicht final | Unveraenderte Originalproben | Positive unbelegte Basis und vollstaendige Gaptaxonomie |
| G18 | Original-Chain/Contract/Mint/Dezimalstellen, Symbolkollision blockiert; explizit gebundene Preiszuordnung | Neue unabhaengige positive und negative Identitaetsproben plus Solana-Regression | Kein allgemein positiver getrennter FIFO fuer gleichnamige Multichain-Assets |
| G19 | Belegte 100:1-Umstellung im selben Pool/UTC-Zeitpunkt, Basis/Datum, Teilverkauf; keine unbelegte Paritaet1 | Neue unabhaengige Global-/Wallet-/Beleg-/Income-/Stale-Proben | Keine generische steuerneutrale Bridge/LP, zeitversetzte Umstellung oder Gebuehrenumstellung |
| G20 | Identischer CSV-Import idempotent; begrenzte Konto-/API-Proben vorhanden | Unveraenderte Originalprobe | Nicht jeder Anbieter-/Formatwechsel |
| G21 | Vorschau bei geaenderten Daten/Preisen/Methodenmarkern gesperrt; jetzt auch TXT-Konvertierungsbeleg | Originalproben plus neue unabhaengige Belegbyte-Regression | Nicht alle sonstigen privaten Quelldateien universell bewertet |
| G22 | Offline-FIFO und CSV semantisch reproduzierbar | Unveraenderte Originalprobe | Separater Prozess-/PDF-Bytevergleich und jede neue Herkunftskette |
| G23 | Technische Exportmoeglichkeit ist keine finale Jahresfreigabe; Vorschauinhalt gebunden | Originalproben und Browserregression | Fachzahlengleichheit PDF/CSV/JSON fuer alle Spezialfaelle |
| G24 | Jahresabhaengige Freigrenze, strikter Vergleich, Zusatzkontext keine implizite0 | Unveraenderte echte Route-Proben | Keine persoenliche Einkommensteuerrechnung oder alle moeglichen Jahre |
| G25 | Archiv unveraendert, Revision und synthetischer Restore; voriger isolierter Docker-Restore bleibt historischer Nachweis | Originalprobe plus aktuelle RO-Stabilitaetspruefung | Kein neuer Image-/Restore-/Rollback-/Engineparitaetsnachweis fuer diese Revision |

## Pakete A-F

| Paket | Implementiert / untersucht | Technischer Nachweis | Fachlich abgenommen |
| --- | --- | --- | --- |
| A Betrieb | Laufzeit-/Dateizuordnung, voller semantischer RO-Vergleich, unveraenderte Produktion | `LEGACY_PARITAET.md`, `parity-summary.json`,11Helfertests; alter Restore nur fuer alten Commit | Nein:8010-Zuordnung und neues Release-/Restorepaket offen |
| B Bewertung | FX-Richtungen, Quellenbindung, Referenztage, keine Zukunftsrueckdatierung, Identitaetsguard | Agentenlaeufe277/139; integrierte Units/Referenzen/Browser im Manifest | Nein: reale Quellenabdeckung und persoenliche Methodenkonstanz offen |
| C Steuerlogik | Fee-Lotverbrauch/Kostenrollen, Kalenderfrist erhalten, belegte Konvertierung und Income-Korrektur | Original52, neue Zahlenfaelle und unabhaengige P1-Proben | Nein: ungeklaerte Scope-/Swap-/Belegfragen bleiben gesperrt |
| D Import/Konten | Vorhandene Idempotenz/Konten-/Limitlogik erhalten, keine Referenzimporte angefuegt | Bestehende Tests erneut; keine neue produktive Importvollstaendigkeit behauptet | Nein: keine persoenliche Providerhistorie komplett nachimportiert |
| E Reports/UX | Keine neue finale Freigabe; Eingabebindungen, konfigurierbare Preisidentitaet | Exportreferenzen, OpenAPI, vier Browserbreiten | Nein: kein kompletter Fachzahlenabgleich aller Reports |
| F Unabhaengige Abnahme | Urspruengliche52unveraendert; neue eigene Zahlenproben als Pflicht-CI | Originale XML plus Vorher-/Nachher-P1-Belege im Manifest | Nein als Gesamtpaket; technische Proben ersetzen keine offenen Belege |

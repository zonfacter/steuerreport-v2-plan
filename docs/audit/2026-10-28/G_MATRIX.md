# Referenzfaelle Und Unabhaengige Abnahme

Ausgangsauftrag: Nutzer vom 28.10.2026. Keine Freigabe allein aufgrund der CI.
Status vor integrierter Abnahme: **offen** fuer alle Zeilen. Unabhaengige
Sollwerte nicht aus den zu pruefenden Produktivfunktionen erzeugen. Eigene
synthetische Datenbanken; keine produktiven Review-/Methodenentscheidungen.

| ID | Anforderung | Unabhaengiger Sollansatz / Abgrenzung |
| --- | --- | --- |
| G01 | EUR-Kauf und Teilverkauf | 10 Stueck fuer100, Verkauf4 fuer60: Kosten40, Gewinn20, Rest6/Basis60 |
| G02 | EUR-Erwerbs-/Verkaufskosten | Kauf100+2, Verkauf4/10 fuer60 minus1: Kosten40.8, Gewinn18.2, Restbasis61.2; Annahme gesondert dokumentieren |
| G03 | Gebuehr aus erworbenem Token | Brutto/netto und tatsaechliche Lots konsistent; Behandlung nicht aus bestehendem Test ableiten |
| G04 | Drittassetgebuehr | EUR-Bewertung, Token-Lotverbrauch und Zuordnung ohne Doppelabzug; offener fachlicher Umfang explizit |
| G05 | Token-Token-Swap | Beide Beine verknuepft, keine fiktive EUR-Einzahlung; belegte konsistente Kurse, Slippage gesondert |
| G06 | Stablecoin-Gegenleistung | Historischer echter Tokenkurs plus FX, keine implizite USD-Paritaet |
| G07 | Depeg | Marktwert statt1USD; z.B.100 Token a0.6EUR sind60EUR |
| G08 | FX-Richtungen | 100USD*0.9EUR/USD =90EUR =100USD/(10/9 USD/EUR), Decimal-Toleranz nur definierte Praezision |
| G09 | Wochenende/Feiertag FX | Belegte begrenzte Rueckreferenz, fehlend keinFX1 |
| G10 | Alt-/Zukunftskurs | 2025-Ereignis nur2021Preis bleibt ungeprueft/nichtfinal; Lookup+Coverage+Tax+Review+Export |
| G11 | Zwei Depots | A Basis10, B Basis20, VerkaufB30: Wallet-Vorschau10 vs global20, keine Aktivierung zur Testgruenschaltung |
| G12 | Eigenuebertrag | Teilmenge traegt Originaldatum/Basis, Netzwerkgebuehr getrennt, Belegbindung |
| G13 | Reward und Verwertung | Zugang100, Verkauf150: Einnahmen100, Anschaffung100, Veraeusserungsgewinn50, Scope getrennt |
| G14 | Unklare Reward-Sphaere | Kein pauschaler privat/betrieblich-Automatismus; Review/fehlende Belege |
| G15 | Kalenderfrist | Anschaffung01.03.2023; Jahrestag01.03.2024 trotz366Tagen innerhalb, Folgetag ausserhalb;29Feb |
| G16 | Berlin/UTC/DST | Berliner Kalenderdatum/-jahr, feste erwartete Grenzzeitpunkte statt selbst erzeugter Sollwerte |
| G17 | Fehlende Basis/Historie/Preis | Unterschiedliche Gaps; kein erfundener Kauf und keine unmarkierte finale Nullbasis |
| G18 | Gleiches Symbol/andereChain | Original-Contract/Mint/Dezimalstellen; Konflikt nicht anhand Namen loesen |
| G19 | Wrapping/Migration | Belegtes Verhaeltnis, keine pauschale wirtschaftliche Paritaet |
| G20 | Identischer Doppelimport | Gleiche Ereignisse, Mengen, Lots, Ertraege |
| G21 | Daten/Preise/Regeln nach Vorschau | Alter Stand unveraendert, Uebernahme/gebundener Download veraltet oder gesperrt |
| G22 | Offline-Neulauf | Gleiche fachliche Ergebnisse/semantische Hashes; technische UUID-/PDF-Zeitabweichungen gesondert |
| G23 | Technisch exportierbar/fachlich blockiert | Vorschau im Paketinhalt, keine finale Freigabe |
| G24 | Freigrenzen-Jahre | Bis2023:600, ab2024:1000; strikt kleiner; persoenliche andere EInkuenfte nicht als bekannt behaupten |
| G25 | Restore/Revision | Raw-/Secret-/Review-Erhalt, altes Paket unveraendert, neuer Revisionsstand erklaert |

Nicht abgedeckte Sachverhalte bleiben offen. Ein Test mit Stub, Skip, xfail
oder fehlender Kostenbasis ist kein bestandener vollstaendiger Referenzfall.

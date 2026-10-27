# Steuerreport V2 0.2.0rc21

## Quellengebundener automatischer Historienimport

**Quellen & Wallets → konkrete Quelle → Transaktionen abrufen** sammelt die
verfuegbaren Anbieterbelege, berechnet eine isolierte Vorschau und uebernimmt
erst nach ausdruecklicher Import-/Berechnungsbestaetigung. Dateiimport bleibt
zusaetzlich vorhanden, nicht der einzige Importweg.

Enthalten: Solana-RPC sowie begrenzte Spot-Historienadapter fuer Binance,
Bitget Classic, Pionex und Coinbase Advanced. Mehrere Konten derselben Boerse
verwenden eigene stabile Kontoreferenzen und Zugangsdaten, keine globale
Fallback-Wallet oder fremde Kontozugaenge. Bestehende gemeinsame Limits gelten.

Jobs haben dauerhafte Cursor, unveraenderliche Originalrecords, Pause,
Fortsetzen, Abbruch, Vorschauhash und Importprotokoll. Serverneustart fuehrt
nicht zum stillen externen Wiederanlauf. Derselbe bestaetigte Import ist
idempotent; widerspruechliche Belege und nicht eindeutig deduplizierbare
alte CEX-Dateidaten blockieren statt stille Korrektur oder Doppelbuchung.

## Grenzen

- Kein Vollstaendigkeitsbeweis aus Paging-Ende oder leerer Antwort.
- Binance/Pionex erfordern explizite Handelspaare. Bitget-Fills nur letzte
  90 Tage. Historische/geschlossene Solana-Konten und nicht unterstuetzte
  Earn-, Fiat-, Convert-, UTA-, Margin-, Derivate- oder Reward-Produkte
  mit Originalbelegen ergaenzen; siehe die anbieterspezifische Dokumentation.
- Uneindeutige erfolgreiche Auszahlungen erfordern Klassifikation anhand
  der Originaldaten. Keine automatische Quellenaktivierung/Jahresfreigabe.
- Zwei aktive Jobs, 100 gespeicherte Auftraege pro Installation; keine
  automatische Archivloeschung. Benutzername im Protokoll ist Eigenangabe.
- Die bestehende Anwendung benoetigt weiterhin Betreiber-Zugriffsschutz.
- Produktive API-Zugaenge oder steuerliche Ergebnisse sind durch Mock- und
  Browserpruefungen nicht fachlich abgenommen. Keine echten Finanzimporte
  werden im Rahmen des Softwaretests gestartet.

## Dokumentation

- [Bedienung, API und Speicher-/Sicherungsmodell](AUTOMATISCHER_QUELLENIMPORT.md)
- [Offizielle Provider-Referenzen und Abdeckung](HISTORY_CEX_PROVIDER_REFERENCES.md)
- [Inbetriebnahme](INBETRIEBNAHME.md)

Die tatsaechlich ausgefuehrten Pruefungen und verbleibenden Grenzen werden
im Uebergabebericht und den Release-Pruefartefakten dokumentiert.

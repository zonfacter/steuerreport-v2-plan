# Steuerreport V2 0.2.0rc23

Automatischer Import bleibt an die konkret ausgewaehlte Wallet oder einzelne
Boersenverbindung gebunden. Dateiimport ist weiterhin eine zusaetzliche Moeglichkeit.

Diese Version korrigiert die Vorschau fuer unterschiedliche CEX-Rohlayouts:
Zeit, Asset, Menge, Gegenmenge und Gebuehren stammen jetzt aus den in der
isolierten Kopie bereits normalisierten Ereignissen. Die Stichprobe ist auf
zehn neue Ereignisse begrenzt und wird mit dem Vorschauhash gebunden. Alte
Datei-/API-Originalbelege werden nicht umgeschrieben. Reine Dubletten ergeben
keine neuen Ereignisse in der Stichprobe.

Die eigentliche Steuer-, FIFO- und Preisberechnung ist unveraendert. Der
synthetische Kauf-/Verkaufstest belegt 20.000 EUR Anschaffung, 25.000 EUR Erloes
und 5.000 EUR Gewinn, erhaltene Originalpreise, korrekt uebernommene abgeleitete
Preise sowie denselben Stand nach Neuberechnung. Er prueft nun auch die
sichtbaren BTC-Mengen der Freigabevorschau. Keine echten Anbieterabfragen oder
Finanzimporte wurden fuer die Softwaretests ausgefuehrt.

Bedienung: **Quellen & Wallets → Quelle → Transaktionen abrufen → Zeitraum/
Handelspaare und Anbieterabruf bestaetigen → Vorschau pruefen → Import und
Neuberechnung bestaetigen**. Importfreigabe ist keine Quellen-/Jahresfreigabe.
Abdeckung bleibt abhaengig von den dokumentierten Anbietergrenzen.

- [Bedienung, API und Grenzen](AUTOMATISCHER_QUELLENIMPORT.md)
- [Offizielle Provider-Referenzen](HISTORY_CEX_PROVIDER_REFERENCES.md)
- [Feature- und Zusatzpruefungen](QUELLENIMPORT_PRUEFUNG_2026-10-27.md)

Die tatsaechlichen CI-, Image-, Datenschutz- und Deploymentpruefungen stehen
mit dem geprueften Commit in den Release-Pruefartefakten.

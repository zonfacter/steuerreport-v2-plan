# Steuerreport V2 0.2.0rc33

Releasekandidat vom 28.10.2026, auf Basis der unabhaengig geprueften
rc33.dev0-Arbeit. Kein amtliches Guetesiegel, keine steuerliche Jahresfreigabe.

## Aenderungen

- Historische Preis-/FX-Zuordnung mit einheitlichen Zeitgrenzen und
  Quellenbindung; keine stille Altpreis- oder FX-1-Ersetzung.
- Gemeinsame Kalenderjahresfrist in Europe/Berlin; Reporting konsumiert
  dieselbe Klassifikation statt einer abweichenden 365-Tage-Regel.
- Gebuehren-, Erwerbskosten- und Lot-Herkunftsnachweise mit Review-Sperren;
  Transfers und Umstellungen erhalten ihre belegte Herkunft.
- Bitget-Date-CSV, signierte Futures-Gebuehren/Rabatte, Funding, neutrale
  Margin-Aktionen und generisches derivative korrigiert. Explizite
  Nettoexporte werden nicht erneut um bereits enthaltene Gebuehren vermindert.
- Versionsanzeige und Einrichtung fuer stabile/RC-Releases, gespeichertes
  Opt-in und begrenzte Abfragen ueber den zentralen HTTP-Limiter.
  Releasegebundener KI-Updateauftrag mit TXT/JSON und Clipboardfallback;
  kein automatischer Docker- oder KI-Aufruf.

## Update und Daten

Vor jedem Wechsel das gesamte dauerhafte /state-Volume konsistent sichern,
einschliesslich Originalimporte, Konfigurationen und Vault-Schluessel.
Eine laufend beschriebene DuckDB-Datei nicht unkoordiniert kopieren.
Das alte Image zusammen mit seiner Datensicherung fuer den Rueckweg erhalten.

Das Starten von rc33 importiert keine Historie, akzeptiert keine Reviews und
startet keine fachliche Neuberechnung. Alte Abgabepakete bleiben unveraendert.
Alte fehlerhafte Normalisierungen werden nicht still repariert. Neue
Bewertungsregeln koennen bisher unerkannte Luecken als Review ausweisen;
eine Softwareaktualisierung schliesst diese fachlich nicht.

Der finanzielle Eingabe-Fingerprint v3 nimmt nur die beiden nichtfinanziellen
Update-Schluessel zusaetzlich aus. Alte gebundene v2-Vorschauen benoetigen
vor einer Uebernahme einen neuen ausdruecklichen Prueflauf.

## Pruefnachweise und Grenzen

Der vorbereitende Stand besteht lokal 2722 Unit-Tests mit vier dokumentierten
privaten Belegskips, 52 urspruengliche und 104 erweiterte Pflichtreferenzen,
alle 15 Original-Bitget-Faelle sowie Browser-/Secret-Pruefungen. Der separate
Release-Commit wird erneut in CI validiert und das Image mit leerem Volume
geprueft. Version, Quellcommit und Imageidentitaet muessen zusammenpassen.

Originale: [Issuebericht](audit/2026-10-28/issues/BERICHT.md),
[Manifest und Testausgaben](audit/2026-10-28/issues/evidence/manifest.json),
[Lot-Herkunft](audit/2026-10-28/LOT_HERKUNFT_REFERENCE_HANDOFF.md).

Legacy-Datenparitaet, fehlende Anschaffungsbelege, unbekannte private/betriebliche
Einordnungen und ungepruefte Sonderfaelle bleiben offene Fachfragen. Keine
Aktivierung einer FIFO-Methode allein zum Schliessen eines Gates.

Image: `ghcr.io/zonfacter/steuerreport-v2:0.2.0rc33`, Plattform linux/amd64.
Ein GitHub-Latest-Label ist keine Garantie fuer anonymen Registry-Zugriff.
Quellcommit-/Digest- und Pull-Nachweise stehen bei den Release-Artefakten;
bei fehlendem GHCR-Zugriff ist ein Build aus dem exakt verifizierten Tag moeglich.

# Vertrag: Lesende Lot-Herkunft

Basis87b231b5a40716f41468e56a68048f3abd79f4cc. Keine Produktion,
Methodenaktivierung, Neuberechnung produktiver Daten, Freigabe oder Deployment.
Keine neue steuerliche Regel. Bestehende Klassifikationen bleiben konservative
Pruefhinweise, keine automatische Betriebs-/Privatentscheidung.

## Schnittstelle

Neue reine Hilfsklasse `domain/lot_origin.py`:

`LotOriginIndex(lots, events)` nimmt vorhandene Global-/Wallet-Lotobjekte
und CanonicalEvents (Iterable) entgegen. `resolve(line)` liefert ein
unveraenderliches `LotOriginTrace` mit:

- `status`: direct, carried oder unresolved;
- `lot_ids`: Tupel von aktuellem Lot bis zum Ursprung, hoechstens64Eintraege;
- `direct_event_id`: unmittelbar am aktuellen Lot gespeicherte Herkunft;
- `origin_event_id`: bestaetigtes Ursprungsereignis, sonstNone;
- `origin_asset`: Asset des bestaetigten Ursprungslots, sonstNone;
- `reason`: stabiler Fehlercode, sonstNone.

Keine Namen-/Symbol-/Zeitnaehe-Heuristik, kein Netzwerk, keine Writes und
keine Neuberechnung. Lot- und Event-IDs sind die Verbindung. Fehlender Lot,
verwaister Link, doppelte Identitaet, Zyklus, Tiefenlimit, widersprechende
Line-/Lot-Herkunft oder Erwerbsdaten ergeben unresolved. Originaldatum und
Kostenbasis werden weder umgeschrieben noch aus einer Kette erfunden.
Ein Herkunftslink beweist allein keine steuerliche Sphaere oder angemessene
Kostenbasis. Herkunft bei Swap-/Bridge-Sonderfaellen nicht ohne Link ableiten.

## Integration

BusinessRewardInventoryReviewService verwendet den gleichen Trace fuer
gespeicherte Zeilen. Sowohl veraeussertes Asset als auch bestaetigtes
Ursprungsasset koennen den expliziten Assetfilter treffen. Ein umgestellter
HNT-Zugang verschwindet also nicht nur wegen eines neuen Symbols aus dem
Pruefumfang. Keine allgemeine positive Multichain-/Swapklassifikation.

Additive Rowfelder (Koordinator integriert zentral):
`lineage_status` (direct/carried/unresolved, Defaultdirect),
`lineage_reason` (str/None), `sample_lot_path` (list[str], max64),
`sample_direct_event_id` (str/None). Bestehende Ursprungsfelder beziehen
sich auf den bestaetigten Root, nicht auf ein beliebiges Zwischenereignis.
Fehler bleiben export-/pruefpflichtig. Gruppierung darf Mengen und Summen
weder verlieren noch vervielfachen. Preview und gespeicherte Sicht muessen
dieselbe Herkunftsauflösung konsumieren; Berechnungsergebnisse bleiben gleich.

## Eigentum Und Speicherbudget

- Implementierungsagent: neuer Resolver, business_inventory.py und eigene
  fokussierte Unit-Tests. Keine Contracts/API/Frontend/Version/FIFO-Formeln.
- Unabhaengiger Agent: eigene neue Referenzdatei unter tests/acceptance,
  feste Zahlen und isolierte eigene Inputs, keine Produktfunktion als Oracle.
- Koordinator: Contracts, BMF-Preview-/Belegconsumer, UI, OpenAPI, Integration.
- Existierende saubere Worktrees wiederverwenden, keine DB-/Repositorykopien.
- Synthetische Testbasen nur /tmp/sr-origin-20261028-ROLE, jeweils unter
  500MiB; nach Erfolg DBs inklusive .prepared entfernen, Original-XML/JSON
  und Belegarchive behalten. Kein paralleler Vollsuitelauf pro Agent.

## Abnahme

Direkter EUR-Kauf; Reward -> Eigenuebertrag -> Verkauf; belegte100:1-
Umstellung -> Teilverkauf mit erhaltener Basis; Herkunft ausserhalb des
urspruenglichen Symbols; missing/cycle/conflicting links; grosse Mengen;
Gleichheit gespeicherter Mengen/Erloese/Kosten/Gewinne vor/nach lesender
Auswertung. Keine neue Einkommensverdopplung und keine automatische Freigabe.

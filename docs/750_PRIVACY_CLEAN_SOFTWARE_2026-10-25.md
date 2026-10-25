# Datenschutzbereinigte Softwarefassung 0.2.0rc3

Die Settingsseite und der leere Docker-Erststart sind in
[Installation und Docker](751_INSTALLATION_SETTINGS_DOCKER_RC3_2026-10-25.md)
beschrieben. Die Neupruefung schliesst zusaetzlich Exchange-UIDs in alten
Importpfaden ein.

Persoenliche Wallets, Exchange-Einzahlungsadressen und Bankkennungen sind
private Betriebsdaten. Sie gehoeren weder als Defaults noch als Testdaten
oder Beispiele in das Software-Repository. Dies gilt auch fuer reale
Transaktionssignaturen, ueber die Konten wieder zugeordnet werden koennen.

## Konfiguration

STEUERREPORT_PRIVATE_PROFILE bezeichnet eine JSON-Datei ausserhalb des
Repositorys. Die Vorlage configs/private_profile.example.json enthaelt
ausschliesslich leere Werte. Einzelwerte lassen sich mit entsprechenden
STEUERREPORT_... Umgebungsvariablen setzen. Ohne Konfiguration werden keine
persoenlichen Wallets als Default angenommen.

STEUERREPORT_PRIVATE_CONFIG_DIR bezeichnet einen externen Ordner fuer
kontobezogene Quellenregistry-, Reconciliation- und Ownership-Dateien.
Im Repository bleibt nur eine leere Quellenregistry-Vorlage. Existierende
private Konfigurationen werden vor einem Wechsel getrennt gesichert.

Die Frontend-Abfragen verwenden den serverseitigen Kontenumfang. Im
JavaScript-Build stehen keine personenbezogenen Wallet-Pool-Filter.

## Tests und Historie

Tests verwenden ein kuenstlich erzeugtes Profil. Die Kennungen wurden aus
festen Testlabels erzeugt und nicht aus echten Konten abgeleitet. Der
Teststart waehlt dieses Profil ausdruecklich; das private Betreiberprofil
wird nicht uebernommen. Oeffentliche Token-Mints und Protokolladressen sind
von persoenlichen Wallets zu unterscheiden und bleiben bei Bedarf erhalten.

scripts/check_private_data_v2.py prueft auf erneut fest eingebaute
Kontodefaults. Der externe, private Inventarabgleich prueft zusaetzlich die
konkreten entfernten Kennungen in allen erreichbaren Git-Objekten und
verschachtelten Release-Artefakten. Die private Vergleichsliste wird nicht
in dieses Repository aufgenommen.

Die lokale Repository-Kopie hat eine bereinigte Historie. Das ersetzt die
Historie eines vorhandenen GitHub-Repositorys erst nach ausdruecklich
freigegebenem Austausch der Branches und Tags. Alte Klone, Release-Caches
oder andere bereits vorhandene Kopien verschwinden dadurch nicht automatisch.

Die bisherige Installation wird durch den Bau dieser Softwarefassung nicht
neu gestartet. Datenbanken und unveraenderte Originalquellen bleiben getrennt.

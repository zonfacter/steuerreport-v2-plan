# Docker-Build und Speicher

Fruehere Builds kopierten den Anwendungscode vor der Installation der
Python-Abhaengigkeiten. Aenderte sich der Code, entstand deshalb ein neuer
grosser Installations-Layer; lokal behaltene alte Release-Images hielten ihre
jeweiligen Layer weiter fest. Das Entfernen gestoppter Container allein gibt
solche Images oder gemeinsam verwendete Layer nicht automatisch frei.

Der Build installiert die explizit gepinnten Runtime-Eintraege jetzt vor dem
Kopieren des Anwendungscodes mit `--no-deps`. Der Projektinstall erfolgt
anschliessend ebenfalls ohne automatische Dependency-Aufloesung. `pip check`
prueft die Paketabhaengigkeiten. Die Runtime-Versionspins sind keine
Artefakt-Hashes; isolierte PEP-517-Buildabhaengigkeiten sind separat zu
betrachten. Ein Lockfile-Wechsel invalidiert den Dependency-Layer weiterhin.

Der CI-Job `Docker dependency layer reuse` baut zwei isolierte Kontexte. Der
zweite unterscheidet sich nur durch einen synthetischen Quellcodekommentar. Ein
Logtest verlangt den Cache-Treffer fuer die konkrete Dependency-Step-ID sowie
einen erneut ausgefuehrten Projektinstall mit erfolgreichem `pip check`. Beide
Images werden mit frischem Volume und ohne Netzwerk auf ihren synthetischen
Anwendungs- und Neustartpfad geprueft; Zugangsdaten sind ausschliesslich
synthetische Testwerte. Der Job belegt Wiederverwendung auf seinem Runner, nicht
den Umfang des beim Betreiber freigebbaren Speichers. Der Publish-Workflow
laeuft fuer getrennte Releases auf frischen Runnern und importiert derzeit
keinen nachgewiesenen dauerhaften BuildKit-Cache. Die Wiederverwendung zwischen
unabhaengigen Releases ist daher noch nicht belegt.

Diese Aenderung entfernt weder vorhandene Images noch Daten. Docker meldet
`reclaimable` als Schaetzung und nicht als Freigabe. Vor einer Bereinigung
muessen aktive und gestoppte Container, Rueckfall-Images, Volumes, Backups und
Beweisunterlagen einzeln geprueft werden. Siehe [Speicherdiagnose](STORAGE_DIAGNOSE.md).

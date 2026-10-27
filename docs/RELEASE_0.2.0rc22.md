# Steuerreport V2 0.2.0rc22

Enthaelt den [quellengebundenen automatischen Historienimport](RELEASE_0.2.0rc21.md)
mit unveraenderter Fachlogik und korrigierter Portabilitaet des Browser-Testskripts.

Der rc21-Kandidat wurde nicht produktiv ausgerollt: GitHubs unprivilegierter
Runner konnte auf den im neuen Testskript hinterlegten lokalen Browserpfad
unter `/root` nicht zugreifen. Der Test verwendet jetzt standardmaessig
Playwrights eigenen installierten Browser; ein anderer Pfad wird nur explizit
uebergeben. Ein unprivilegierter CLI-Start prueft diese konkrete Regression.
Der alte Tag wird nicht verschoben. Produktionsstand war zuvor rc20.

Bedienung: **Quellen & Wallets → konkrete Quelle → Transaktionen abrufen →
Vorschau abrufen → pruefen → Importieren und neu berechnen**.
Dateiimport bleibt zusaetzlich moeglich. Anbietergrenzen, Originalbelege,
Dublettenpruefung und getrennte Import-/Berechnungsfreigaben bleiben erhalten.
Keine echte Transaktionshistorie wurde im Rahmen des Updates importiert.

- [Bedienung und Grenzen](AUTOMATISCHER_QUELLENIMPORT.md)
- [Provider-Referenzen](HISTORY_CEX_PROVIDER_REFERENCES.md)
- [Lokale Pruefungen des Featurestands](QUELLENIMPORT_PRUEFUNG_2026-10-27.md)

Die erneuten CI-, Image- und Deploymentpruefungen werden in den
Release-Pruefartefakten mit dem tatsaechlichen Commit dokumentiert.

# Interne OpenWebUI-Websuche

SearXNG laeuft ausschliesslich im Docker-Netz von OpenWebUI. Der Dienst darf
keinen `ports`-Eintrag erhalten. OpenWebUI greift intern auf
`http://searxng:8080/search` zu.

## Installation

1. `settings.example.yml` nach `/opt/searxng/settings.yml` uebertragen.
2. `server.secret_key` durch 32 kryptografisch zufaellige Bytes in Hex ersetzen.
3. Das Live-Verzeichnis an die UID/GID des SearXNG-Containerbenutzers
   uebergeben und `settings.yml` auf Modus `600` setzen.
4. Das offizielle Image abrufen und den aufgeloesten Repo-Digest in
   `/opt/openclaw/stack/compose.yml` festschreiben.
5. Erst SearXNG starten und eine JSON-Suche pruefen.
6. Danach `scripts/configure_openwebui_web_search.py` und
   `scripts/configure_openwebui_steuerreport_agents.py` ausfuehren.

Die fallbezogenen Steuerreport-Agenten behalten Websuche deaktiviert. Nur
`steuerreport-bmf-web-recherche` nutzt den oeffentlichen Suchpfad und besitzt
keinen Zugriff auf die lokale Steuerreport-API oder deren Wissenssammlung.

## Pruefung

```bash
docker exec open-webui python -c \
  "import json,urllib.parse,urllib.request; u='http://searxng:8080/search?'+urllib.parse.urlencode({'q':'site:bundesfinanzministerium.de Kryptowerte BMF Schreiben','format':'json','language':'de-DE'}); print(len(json.load(urllib.request.urlopen(u, timeout=30))['results']))"
```

`docker port searxng` muss leer bleiben. Eine funktionierende interne HTTP-
Verbindung allein reicht nicht: Vor Freigabe muss mindestens ein echter
Primaerquellen-Treffer ueber den OpenWebUI-Endpunkt
`/api/v1/retrieval/process/web/search` geladen werden.

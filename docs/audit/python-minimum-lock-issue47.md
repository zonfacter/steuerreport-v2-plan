# Python-Untergrenze und Runtime-Lockfile (Issue 47)

Stand: 2026-11-02. Ausgangspunkt: Commit `08d247f`.

## Entscheidung

Die deklarierte Untergrenze bleibt Python 3.11.0. Der einzige geaenderte
Runtime-Pin ist `soupsieve`: 3.0.4 wird durch 2.10 ersetzt. Die
[PyPI-Metadaten von 3.0.4](https://pypi.org/pypi/soupsieve/3.0.4/json)
verlangen mindestens 3.11.5; [2.10](https://pypi.org/pypi/soupsieve/2.10/json)
verlangt mindestens 3.10. Die Metadaten von
[beautifulsoup4 4.15.0](https://pypi.org/pypi/beautifulsoup4/4.15.0/json)
akzeptieren `soupsieve>=1.6.1`.

Eine Anhebung auf 3.11.5 haette den bisherigen Pin erhalten, aber bestehende
Installationen auf 3.11.0 bis 3.11.4 ausgeschlossen. Der aeltere Pin erhaelt
diese Unterstuetzung, verzichtet aber auf spaetere Soup-Sieve-Aenderungen.
Sicherheits- und Funktionsfolgen eines Downgrades sind damit nicht umfassend
ausgeschlossen; bei kuenftigen Updates muessen Version, Sicherheitslage und
Untergrenze erneut geprueft werden. Python-3.11-Patchupdates bleiben empfohlen.

## Metadatenabgleich

Fuer alle 52 Pins des Ausgangs-Lockfiles wurden auf PyPI die versionierten
JSON-Endpunkte `https://pypi.org/pypi/<name>/<version>/json` abgerufen;
`info.requires_python` und die `requires_python`-Angaben der publizierten
Dateien wurden gegen 3.11.0, 3.11.1, 3.11.2, 3.11.3 und 3.11.4 geprueft.
Nur `soupsieve==3.0.4` schliesst diese Versionen explizit aus. Kein Pin war
laut `info.yanked` zurueckgezogen. `compressed-rtf`, `easygui`, `oletools`,
`pcodedmp`, `pytz` und `red-black-tree-mod` geben keine Untergrenze an;
das ist kein positiver Kompatibilitaetsnachweis. Der Ersatzpin 2.10 wurde
gesondert geprueft; sowohl Release- als auch Dateimetadaten erlauben Python
ab 3.10 und das Release ist nicht zurueckgezogen.

## Sicherheitskorrektur

Der zuerst vorgeschlagene Pin 2.8.3 wurde verworfen: Dessen
[PyPI-JSON](https://pypi.org/pypi/soupsieve/2.8.3/json) meldet
GHSA-836r-79rf-4m37 und GHSA-2wc2-fm75-p42x (jeweils behoben ab 2.8.4)
sowie GHSA-j934-xhv5-fg8f und GHSA-gjv8-xp57-g29c (jeweils behoben ab
2.9.0). PyPI fuehrt zusaetzlich PYSEC-Aliasse derselben Luecken. Die erste
Auswahl beruecksichtigte diese Sicherheitsmeldungen nicht ausreichend.

Das [PyPI-JSON fuer 2.10](https://pypi.org/pypi/soupsieve/2.10/json) enthielt
bei der Nachpruefung `vulnerabilities: []`. Das ist eine zeitgebundene
Quellenangabe, kein Nachweis allgemeiner Sicherheit. Die uebrigen Runtime-Pins
wurden im Rahmen dieses Issues nicht vollstaendig auf Sicherheitsluecken
auditiert.

Der Metadatenabgleich garantiert weder verfuegbare Wheels fuer jede Plattform
noch korrekte Laufzeitfunktion. Dev- und Build-Abhaengigkeiten sind nicht
Teil des Runtime-Lockfiles und koennen sich unabhaengig davon aendern.

## Reproduktion und Grenzen

Die CI installiert auf Ubuntu 22.04 unter exakt Python 3.11.0 zunaechst alle
Runtime-Pins und anschliessend das Projekt mit Dev-Abhaengigkeiten; `pip check`
und gezielte Dependency-Smokes folgen. Die uebrigen CI-Jobs verwenden weiterhin
den jeweils bereitgestellten Python-3.11-Patchstand.

Das Dockerfile referenziert `python:3.11-slim-bookworm` per Digest
`sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf`;
das lokal fuer amd64 inspizierte Basisimage enthaelt Python 3.11.17. Die
Docker-Installation verwendet `--no-deps` fuer alle Pins und das Projekt und
anschliessend `pip check`. Bei einem neuen Digest ist der Patchstand erneut
zu pruefen. Frische Tests in separaten, kurzlebigen Testumgebungen ersetzen
keinen vollstaendigen Funktionstest auf allen Betriebssystemen und Architekturen.

Nach der Korrektur auf `soupsieve==2.10` erneut frisch lokal ausgefuehrt,
jeweils ohne produktive Daten oder Datenvolumes. Die installierte
Soup-Sieve-Version wurde jeweils explizit als 2.10 verifiziert:

- Python 3.11.0 auf amd64 im Testimage `python:3.11.0-slim-bullseye` mit
  Digest `sha256:b5ee5360b357dcd0ab2e1cc5e22fa589b6734bbd55776df6b1700994febf1527`:
  alle Pins, Projekt mit Dev-Extra, `pip check` und 4 gezielte Tests erfolgreich.
- Python 3.11.17 im oben genannten Docker-Basisimage: Installation wie im
  Dockerfile, `pip check` und Import-/Parser-Smoke erfolgreich. Dies ist kein
  vollstaendiger Build oder Funktionstest des gesamten Anwendungsimages.
- Python 3.11.2 in einem frischen lokalen venv: dokumentierte Installation mit
  Constraints und Dev-Extra, `pip check` und 8 gezielte Tests erfolgreich;
  eine Starlette-/httpx-Deprecation-Warnung wurde ausgegeben.

Beispiel fuer den 3.11.0-Test aus dem Worktree, ohne Host-Schreibzugriff aus
dem Container (das alte Testimage ist nicht als Produktionsimage gedacht):

```sh
docker run --rm --entrypoint sh \
  --mount "type=bind,source=$PWD,destination=/source,readonly" \
  python:3.11.0-slim-bullseye@sha256:b5ee5360b357dcd0ab2e1cc5e22fa589b6734bbd55776df6b1700994febf1527 \
  -ec 'mkdir /work; cp -a /source/. /work/; cd /work
    python --version
    python -m pip install --no-cache-dir --no-deps -r requirements-runtime.lock
    python -m pip install --no-cache-dir -c requirements-runtime.lock -e ".[dev]"
    python -m pip check
    python -c "import soupsieve; assert soupsieve.__version__ == \"2.10\""
    python -m pytest tests/unit/test_python_dependency_compatibility.py tests/unit/test_dockerfile_dependency_cache.py -q'
```

Fuer das Docker-Basisimage denselben isolierten Aufruf mit dessen Digest
verwenden und in `/work` die Installationsschritte aus dem Dockerfile ausfuehren:

```sh
python -m pip install --no-cache-dir --no-deps -r requirements-runtime.lock
python -m pip install --no-cache-dir --no-deps .
python -m pip check
python -c 'import extract_msg, soupsieve; from bs4 import BeautifulSoup; import steuerreport_v2.api.app; assert soupsieve.__version__ == "2.10"; assert extract_msg.openMsg; assert BeautifulSoup("<p class=item>ok</p>", "html.parser").select_one("p.item").text == "ok"'
```

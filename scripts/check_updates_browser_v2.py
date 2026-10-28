"""Issue #3: echte UI-Komponenten am Dev-Server, ausschliesslich lokale API-Fixtures.

Kein Build, kein Backend, kein GitHub-/Docker-/KI-Aufruf. Temporaere Vite-Konfiguration
und Browsernachweise bleiben unter dem expliziten Ausgabeordner.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import socket
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


NOW = "2026-10-28T21:00:00Z"
SIX_HOURS = 6 * 60 * 60 * 1000


def release(number):
    return dict(release_id=number, tag=f"v0.2.0rc{number}", version=f"0.2.0rc{number}",
                channel="rc", github_prerelease=False, published_at=NOW,
                url=f"https://github.com/zonfacter/steuerreport-v2-plan/releases/tag/v0.2.0rc{number}",
                body='RC-Fixture\n<img src="https://invalid.example/image" onerror="alert(1)">\nNicht ausfuehren.',
                source_commit=None, image_reference=None, image_digest=None,
                open_checks=["Image-Verfügbarkeit noch nicht bestätigt", "Quellcommit erneut verifizieren"],
                snapshot_digest=str(number % 10) * 64)


def status(automatic=False, blocked=False):
    return dict(installed_version="0.2.0rc32", status="disabled" if blocked else "not_checked",
                settings=dict(channel="stable_rc", automatic=automatic), checked_at=None,
                last_success_at=None, retry_at=None, stale=False, incomplete=False,
                message="Synthetische lokale Antwort.", releases=[], latest=None,
                check_allowed=not blocked, settings_writable=not blocked)


HTML = '''<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body><div id="root"></div><script type="module">
import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {UpdateIndicator} from '/src/VersionUpdates.tsx';
import {InstallationSettings} from '/src/InstallationSettings.tsx';
import '/src/styles.css';
function App(){const [open,setOpen]=useState(false); return React.createElement(React.Fragment,null,
  React.createElement('header',{style:{padding:'16px',borderBottom:'1px solid #ddd'}},React.createElement(UpdateIndicator,{onNavigate:()=>setOpen(true)})),
  React.createElement('main',{style:{padding:'16px',maxWidth:'1000px',margin:'0 auto',minWidth:0}},open&&React.createElement(InstallationSettings)));}
window.__testRoot=createRoot(document.getElementById('root'));
window.__testRoot.render(React.createElement(React.StrictMode,null,React.createElement(App)));
</script></body></html>'''


def run_case(browser, base, out, name, *, automatic=False, blocked=False, unavailable=False, busy=False):
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block", accept_downloads=True)
    page = context.new_page()
    page.clock.install(time=datetime(2026, 10, 28, 21, tzinfo=timezone.utc))
    page.clock.pause_at(datetime(2026, 10, 28, 21, 1, tzinfo=timezone.utc))
    page.add_init_script('''Object.defineProperty(navigator,'clipboard',{value:undefined,configurable:true});
      window.__updateCheckTimes=[]; const originalFetch=window.fetch;
      window.fetch=function(input,options){if(String(input).endsWith('/updates/check'))window.__updateCheckTimes.push(Date.now());
        return originalFetch.call(this,input,options);};''')
    errors, calls, external = [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    state = status(automatic, blocked)
    if busy:
        state.update(status="checking")
    if unavailable:
        state.update(installed_version=None, status="unavailable", stale=True, incomplete=True,
                     releases=[release(33)], latest=release(33), last_success_at=NOW,
                     message="Letzter Stand erhalten; Anbieter derzeit nicht erreichbar.")
    checks = []

    def route(request):
        incoming = request.request
        parsed = urlparse(incoming.url)
        if parsed.netloc != urlparse(base).netloc:
            external.append(incoming.url)
            return request.abort()
        if not parsed.path.startswith("/api/"):
            return request.continue_()
        path, method = parsed.path, incoming.method
        body = incoming.post_data_json if incoming.post_data else None
        calls.append((method, path, body))
        if path == "/api/v1/updates" and method == "GET":
            if busy and sum(path == "/api/v1/updates" for _, path, _ in calls) > 1:
                state.update(status="up_to_date", checked_at=NOW, last_success_at=NOW)
            data = state
        elif path == "/api/v1/updates/check" and method == "POST":
            assert not blocked and body["mode"] in {"manual", "automatic"}
            checks.append(body["mode"])
            if unavailable:
                return request.fulfill(status=503, json={"detail": "updates_unavailable"})
            number = 33 if len(checks) == 1 else 34
            state.update(status="update_available", releases=[release(33)] + ([release(34)] if number == 34 else []),
                         latest=release(number), checked_at=NOW, last_success_at=NOW)
            data = state
        elif path == "/api/v1/updates/settings" and method == "PUT":
            assert not blocked and set(body) == {"channel", "automatic"}
            state["settings"] = body
            data = state
        elif path == "/api/v1/updates/handoff" and method == "POST":
            assert set(body) == {"release_id", "snapshot_digest"}
            if body["release_id"] == 34:
                return request.fulfill(status=409, json={"status": "error", "detail": "update_snapshot_conflict"})
            assert body == {"release_id": 33, "snapshot_digest": "3" * 64}
            data = dict(handoff_schema_version=1, installed_version="0.2.0rc32", target=release(33),
                        text="Bitte bestehende Installation exakt auf v0.2.0rc33 aktualisieren.\nCommit und Digest unbekannt; pruefen. Kein anderes latest installieren.", created_at=NOW)
        elif path == "/api/v1/workspace/environment" and method == "GET":
            data = dict(synthetic_preview=blocked, read_only=blocked)
        elif path == "/api/v1/admin/installation" and method == "GET":
            data = dict(fields=[], revision="fixture", restart_required=False, profile_writable=False,
                        encrypted_secrets_available=False, providers={}, demo_mode=blocked)
        else:
            raise AssertionError(f"Unerwarteter API-Aufruf: {method} {path}")
        request.fulfill(json={"status": "ok", "data": data})

    context.route("**/*", route)
    page.goto(base + "/updates-test", wait_until="networkidle")
    indicator = page.get_by_role("button", name=re.compile("Version & Updates öffnen"))
    expect(indicator).to_contain_text("Version unbekannt" if unavailable else "0.2.0rc32")
    indicator.click()
    panel = page.get_by_role("region", name="Version & Updates", exact=True)
    expect(panel.get_by_role("heading", name="Version & Updates", exact=True)).to_be_visible()
    expect(panel.get_by_label("Release-Kanal", exact=True)).to_have_value("stable_rc")

    def wait_checks(count):
        for _ in range(100):
            if len(checks) >= count:
                return
            page.clock.run_for(10)
            page.wait_for_timeout(20)
        raise AssertionError((name, "check count", count, checks))

    if busy:
        expect(panel.get_by_text("Prüfung läuft", exact=True)).to_be_visible()
        page.clock.fast_forward(2000)
        expect(panel.get_by_text("Keine neuere Version gefunden", exact=True)).to_be_visible()
        assert not checks
    elif unavailable:
        expect(panel.get_by_text("Prüfung derzeit nicht möglich", exact=True)).to_be_visible()
        expect(panel.get_by_text("Keine neuere Version gefunden", exact=True)).to_have_count(0)
        expect(panel.get_by_text("Der letzte erfolgreiche Stand ist veraltet und kein Nachweis für Aktualität.", exact=True)).to_be_visible()
        expect(panel.get_by_text("Nicht alle Releases wurden bewertet. Kein vollständiger Aktualitätsnachweis.", exact=True)).to_be_visible()
        panel.get_by_role("button", name="Jetzt prüfen", exact=True).click()
        expect(panel.get_by_text(re.compile("Anfrage nicht bestätigt .HTTP 503"))).to_be_visible()
        expect(panel.get_by_role("heading", name="v0.2.0rc33 RC", exact=True)).to_be_visible()
        assert checks == ["manual"]
    elif blocked:
        expect(panel.get_by_role("button", name="Jetzt prüfen", exact=True)).to_be_disabled()
        expect(panel.get_by_label("Automatisch auf neue Versionen prüfen", exact=True)).to_be_disabled()
        page.clock.fast_forward(24 * 60 * 60 * 1000)
        page.wait_for_timeout(100)
        assert not checks and not any(method != "GET" for method, _, _ in calls)
    elif automatic:
        wait_checks(1)
        assert checks == ["automatic"]
        elapsed = page.evaluate("Date.now()-window.__updateCheckTimes.at(-1)")
        page.clock.fast_forward(SIX_HOURS - elapsed - 1)
        page.wait_for_timeout(100)
        assert len(checks) == 1
        page.clock.fast_forward(1)
        wait_checks(2)
        assert checks == ["automatic", "automatic"]
        page.evaluate("window.__testRoot.unmount()")
        page.clock.fast_forward(2 * SIX_HOURS)
        page.wait_for_timeout(100)
        assert len(checks) == 2, "Timer nach Unmount nicht entfernt"
    else:
        expect(panel.get_by_label("Automatisch auf neue Versionen prüfen", exact=True)).not_to_be_checked()
        panel.get_by_label("Automatisch auf neue Versionen prüfen", exact=True).check()
        page.wait_for_timeout(100)
        assert not checks and not any(method == "PUT" for method, _, _ in calls)
        panel.get_by_label("Automatisch auf neue Versionen prüfen", exact=True).uncheck()
        panel.get_by_role("button", name="Jetzt prüfen", exact=True).click()
        wait_checks(1)
        expect(panel.get_by_role("heading", name="v0.2.0rc33 RC", exact=True)).to_be_visible()
        expect(indicator).to_contain_text("v0.2.0rc33")
        assert panel.locator("img").count() == 0
        expect(panel.get_by_text("Unbekannt / nicht verifiziert", exact=True)).to_have_count(2)
        for width in (380, 768, 1280, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            panel.screenshot(path=str(out / f"updates-{width}.png"))
        panel.get_by_role("button", name="Updateauftrag für KI kopieren", exact=True).click()
        expect(panel.get_by_text(re.compile("Zwischenablage nicht verfügbar"))).to_be_visible()
        expect(panel.get_by_text("Auftrag in die Zwischenablage kopiert.", exact=True)).to_have_count(0)
        text = panel.get_by_label("Vollständiger Updateauftrag", exact=True).input_value()
        assert "v0.2.0rc33" in text and "latest" in text
        panel.screenshot(path=str(out / "updates-copy-fallback.png"))
        panel.get_by_role("button", name="Jetzt prüfen", exact=True).click()
        wait_checks(2)
        expect(indicator).to_contain_text("v0.2.0rc34")
        expect(panel.get_by_label("Veröffentlichtes Zielrelease", exact=True)).to_have_value("33:" + "3" * 64)
        for extension in ("TXT", "JSON"):
            with page.expect_download() as captured:
                panel.get_by_role("button", name=extension + " herunterladen", exact=True).click()
            download = captured.value
            target = out / download.suggested_filename
            download.save_as(target)
            exported = target.read_text()
            if extension == "TXT":
                assert exported == text
            else:
                document = json.loads(exported)
                assert document["text"] == text and document["target"]["release_id"] == 33
                assert document["target"]["snapshot_digest"] == "3" * 64
        page.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.__copied=text}},configurable:true})")
        panel.get_by_role("button", name="Updateauftrag für KI kopieren", exact=True).click()
        expect(panel.get_by_text("Auftrag in die Zwischenablage kopiert.", exact=True)).to_be_visible()
        assert page.evaluate("window.__copied") == text
        assert sum(path.endswith("/handoff") for _, path, _ in calls) == 1
        panel.get_by_label("Veröffentlichtes Zielrelease", exact=True).select_option("34:" + "4" * 64)
        panel.get_by_role("button", name="Updateauftrag für KI kopieren", exact=True).click()
        expect(panel.get_by_text(re.compile("Release-Snapshot geändert"))).to_be_visible()
        expect(panel.get_by_label("Vollständiger Updateauftrag", exact=True)).to_have_count(0)
        panel.get_by_label("Release-Kanal", exact=True).select_option("stable")
        assert not any(method == "PUT" for method, _, _ in calls)
        panel.get_by_role("button", name="Einstellungen speichern", exact=True).click()
        expect(panel.get_by_text("Update-Einstellungen gespeichert.", exact=True)).to_be_visible()
        assert [body for method, path, body in calls if method == "PUT"] == [{"channel": "stable", "automatic": False}]
        assert checks == ["manual", "manual"]
    assert sum(method == "GET" and path == "/api/v1/updates" for method, path, _ in calls) == (2 if busy else 1), calls
    assert not errors and not external, (errors, external)
    result = dict(passed=True, case=name, checks=checks, calls=calls, errors=errors, external_requests=external)
    context.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/sr-issues-20261028-ui"))
    parser.add_argument("--browser-executable", default="/root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    config = args.output / "vite-fixture.config.mjs"
    options = json.dumps(dict(root=str(root / "frontend"),
        cacheDir=str(args.output / "vite-cache"), esbuild=dict(jsx="automatic"),
        resolve=dict(dedupe=["react", "react-dom"]), server=dict(host="127.0.0.1", port=port, strictPort=True)))
    config.write_text("const options=" + options + "; const fixtureHtml=" + json.dumps(HTML) + ";\n" + '''
options.plugins=[{name:'updates-browser-fixture',configureServer(server){
  server.middlewares.use((req,res,next)=>{
    if(req.url!=='/updates-test')return next();
    server.transformIndexHtml('/updates-test',fixtureHtml).then(html=>{
      res.statusCode=200;res.setHeader('Content-Type','text/html');res.end(html);
    }).catch(next);
  });
}}]; export default options;
''')
    with ExitStack() as stack:
        log = stack.enter_context((args.output / "vite.log").open("w"))
        server = subprocess.Popen(["node", "node_modules/vite/bin/vite.js", "--config", str(config)],
                                  cwd=root / "frontend", stdout=log, stderr=subprocess.STDOUT)
        def stop():
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        stack.callback(stop)
        for _ in range(100):
            try:
                with urlopen(base, timeout=1):
                    break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError("Dev-Server beendet; vite.log pruefen")
                time.sleep(.1)
        with sync_playwright() as playwright:
            with playwright.chromium.launch(headless=True, executable_path=args.browser_executable) as browser:
                expect.set_options(timeout=15000)
                results = [run_case(browser, base, args.output, "manual"),
                           run_case(browser, base, args.output, "automatic", automatic=True),
                           run_case(browser, base, args.output, "blocked", automatic=True, blocked=True),
                           run_case(browser, base, args.output, "unavailable", unavailable=True),
                           run_case(browser, base, args.output, "checking", busy=True)]
        evidence = dict(passed=True, results=results, viewports=[380, 768, 1280, 1440],
                        mode="dev_server_real_components_synthetic_api", production_build=False,
                        github_docker_ai_calls=0)
        (args.output / "result.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()

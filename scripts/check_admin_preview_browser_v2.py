"""Lesender Browsernachweis der echten synthetischen Admin-Vorschau, ohne API-Mocks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--browser-executable', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser_executable, headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
        page = context.new_page()
        errors, calls, images, blocked = [], [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        origin = urlparse(args.base_url).netloc

        def readonly(route):
            request = route.request
            parsed = urlparse(request.url)
            if request.method != 'GET' or parsed.netloc != origin:
                blocked.append({'method': request.method, 'path': parsed.path})
                route.abort()
                return
            if parsed.path.startswith('/api/'):
                calls.append({'method': request.method, 'path': parsed.path})
            route.continue_()

        context.route('**/*', readonly)
        # Keine beliebige Liveinstallation als synthetische Vorschau ausgeben.
        response = context.request.get(args.base_url.rstrip('/') + '/api/v1/workspace/environment')
        assert response.headers.get('x-steuerreport-ux-sandbox') == 'synthetic-read-only'
        assert response.json()['data']['synthetic_preview'] is True
        page.goto(args.base_url.rstrip('/') + '/#admin')
        for name in ('Installation', 'Datenanbieter', 'Eigene Verbindungen', 'Abrufsteuerung', 'KI-Einrichtung'):
            expect(page.get_by_role('heading', name=name, exact=True)).to_be_visible()
        expect(page.get_by_text('Backend erreichbar', exact=True)).to_be_visible()
        connections = page.get_by_role('region', name='Eigene Verbindungen', exact=True)
        expect(connections.get_by_text('Noch keine eigene Verbindung angelegt.', exact=False)).to_be_visible()
        expect(connections.get_by_role('button', name='Verbindung hinzufügen')).to_be_disabled()
        limits = page.get_by_role('region', name='Abrufsteuerung', exact=True)
        expect(limits.get_by_text('Herstellergrenze (Betreiberdeklaration)', exact=True).first).to_be_visible()
        for width, height in ((1440, 1000), (390, 844), (768, 1000), (1280, 1000)):
            page.set_viewport_size({'width': width, 'height': height})
            page.wait_for_function("""() => innerWidth > 820 || (() => {
                const nav = document.querySelector('.sidebar');
                return nav && nav.getBoundingClientRect().right <= 0 &&
                    getComputedStyle(nav).visibility === 'hidden';
            })()""")
            page.evaluate('window.scrollTo(0,0)')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            filename = f'admin-{width}.png'
            page.screenshot(path=str(args.output / filename), full_page=True)
            images.append({'file': filename, 'viewport': {'width': width, 'height': height}, 'route': '#admin', 'data': 'synthetic'})
        assert not errors, errors
        assert not blocked, blocked
        assert all(item['method'] == 'GET' for item in calls)
        result = {'only_get_requests': True, 'javascript_errors': errors, 'external_provider_calls': 0,
                  'synthetic': True, 'screenshots': images, 'api_calls': calls, 'blocked_requests': blocked}
        (args.output / 'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        context.close()
        browser.close()
        print(json.dumps({'result': 'passed', 'viewports': len(images), 'api_gets': len(calls), 'external_requests': 0}))


if __name__ == '__main__':
    main()

"""Admin-UI am echten Frontend mit isolierten, kontrollierten API-Antworten.

Alle API-Aufrufe werden abgefangen; keine externen Anbieter werden kontaktiert.
Dies prueft UI-Vertraege, nicht Secret-Persistenz oder reale Anbieterquoten.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from ux_workspace_fixtures import WorkspaceFixture

NOW = '2026-10-26T12:00:00Z'
PROFILE = dict(origin='local_conservative', manufacturer_limit_verified=False, cost_unit='local_units', requests_per_second=2, requests_per_minute=60, weighted_cost_per_minute=100, burst=1, max_concurrency=1, timeout_seconds=30.0, max_retries=2, backoff_base_seconds=1.0, backoff_max_seconds=30.0, jitter_ratio=0.2, job_deadline_seconds=300.0)
CONFIG = dict(schema_version=1, revision=1, default_profile=PROFILE, group_profiles={'provider:binance': PROFILE, 'ip:global': PROFILE}, provider_groups={}, scheduler_enabled=False)
CREDS = dict(status='configured', has_api_key=True, has_api_secret=True, has_passphrase=False, encrypted=True, updated_at=NOW)
def connection(i):
    return dict(id=f'00000000-0000-4000-8000-00000000000{i}',provider='binance',label=f'Demo-Konto {i}',account=f'demo-{i}',subaccount='',origin='manual',budget_group='ip:global',credentials=CREDS,last_test_at=None,last_sync_at=None,last_error_code=None,tax_source_activated=False)

def show_section(section):
    section.evaluate("element => { element.scrollIntoView({block:'start'}); const header=document.querySelector('.topbar'); const offset=header && getComputedStyle(header).position==='sticky' ? header.getBoundingClientRect().height : 0; window.scrollBy(0,-offset-16); }")

def run(browser, base_url: str, out: Path, demo=False, vault=True):
    context = browser.new_context(viewport={'width':1440,'height':1000}, service_workers='block')
    fixture = WorkspaceFixture()
    page = context.new_page()
    failures=[]
    page.on('pageerror', lambda error: (failures.append(str(error)), print('PAGEERROR',error.stack,flush=True)))
    state = dict(config=copy.deepcopy(CONFIG),connections=[connection(1),connection(2)],jobs=[],writes=[],calls=[])
    def route(request):
        r=request.request
        path=urlparse(r.url).path.split('/api/v1/')[-1]
        state['calls'].append((r.method,path))
        body=r.post_data_json if r.post_data else None
        if r.method!='GET':
            state['writes'].append((r.method,path,body))
        if path=='workspace/environment':
            data=dict(synthetic_preview=demo,read_only=demo)
        elif path=='admin/installation':
            data=dict(fields=[dict(key='import_root',label='Importverzeichnis',group='Dateien',kind='path',value='/tmp/demo-imports',source='profile',editable=True),dict(key='primary_solana_wallet',label='Solana-Hauptwallet',group='Wallets',kind='account',value='',source='empty',editable=True),dict(key='solana_rpc_url',label='Solana-RPC-Endpunkt',group='Dienste',kind='url',value='',source='empty',editable=True)],revision='profile-demo',restart_required=False,profile_writable=not demo,encrypted_secrets_available=vault,providers={'solscan':True})
        elif path.startswith('admin/installation/configs/'):
            data=dict(filename='source_registry.json',revision='demo',content='{}')
        elif path.startswith('admin/installation/providers/'):
            data={}
        elif path=='admin/connections/jobs':
            data=dict(jobs=state['jobs'],max_active=4,max_retained=100)
        elif path=='admin/connections' and r.method=='GET':
            data=dict(connections=state['connections'],legacy_connections=[],vault_ready=vault,automatic_migration=False)
        elif path=='admin/connections' and r.method=='POST':
            data={**connection(3),**{k:v for k,v in body.items() if k not in ('api_key','api_secret','passphrase')}}
            state['connections'].append(data)
        elif path.startswith('admin/connections/jobs/') and path.endswith('/cancel'):
            data={**state['jobs'][0],'status':'cancelled','cancel_requested':True,'slot_reserved':False}
            state['jobs']=[data]
        elif path.endswith('/credentials'):
            data=state['connections'][0].copy()
            data['credentials']={**CREDS,'status':'missing'}
            state['connections'][0]=data
        elif path.startswith('admin/connections/') and path.endswith(('/test','/sync')):
            action=path.rsplit('/',1)[-1]
            data=dict(id='00000000-0000-4000-8000-000000000099',connection_id=state['connections'][0]['id'],provider='binance',action=action,status='queued',created_at=NOW,updated_at=NOW,deadline_at=NOW,cancel_requested=False,error_code=None,snapshot_count=0,effect='read_only_connection_test')
            state['jobs']=[data]
        elif path.startswith('admin/connections/') and r.method=='PUT':
            data=state['connections'][0].copy()
            data.update({k:v for k,v in body.items() if k not in ('api_key','api_secret','passphrase')})
            state['connections'][0]=data
        elif path=='admin/request-limits' and r.method=='PUT':
            state['config']={**body['config'],'revision':state['config']['revision']+1}
            data=state['config']
        elif path=='admin/request-limits':
            data=state['config']
        elif path=='admin/request-limits/status':
            groups=[dict(group='ip:global',profile=PROFILE,requests_last_second=1,requests_last_minute=10,cost_last_minute=12,in_flight=1,queued=2,paused_until=1793016005,next_start_at=1793016005,blocking_reasons=['max_concurrency'])]
            for provider_name, ceiling in state['config'].get('provider_ceilings',{}).items():
                effective=copy.deepcopy(PROFILE)
                for key in ('requests_per_second','requests_per_minute','weighted_cost_per_minute'):
                    if ceiling[key] is not None:
                        effective[key]=min(effective[key],ceiling[key])
                groups.append({**groups[0],'group':'budget:ceiling:'+provider_name,'profile':effective,'provider_ceiling':ceiling})
            data=dict(schema_version=1,config_revision=state['config']['revision'],observed_at=1793016000,clock_rollback=False,manufacturer_telemetry_available=True,provider_observations={'jupiter':dict(last_observed_at=1793016000,last_rate_limit_at=1793016000,used_weight_1m=None,remaining_requests=-3,reset_at=None)},coordination_scope='host_local_flock_shared_volume',concurrency_recovery='explicit_release_only',groups=groups)
        elif path=='admin/provider-references':
            data=dict(checked_at='2026-10-26',providers=[dict(provider='binance',source_url='https://developers.binance.com/',scope='IP und Endpunktgewicht',limitation='Herstellerobergrenze nicht bestätigt')])
        else:
            if fixture.handle(request):
                return
            if r.method != 'GET':
                raise AssertionError(f'Unexpected API action {r.method} {path}')
            if path == 'health':
                data = {'app_version': 'synthetic', 'status': 'ok'}
            elif path == 'product/readiness':
                data = {'overall_status': 'blocked', 'next_action': 'Synthetischer Teststand.'}
            elif path in {'admin/settings', 'ai/tasks', 'ai/changes'}:
                data = []
            elif path == 'ai/provider':
                data = {'config': {'provider': 'local', 'base_url': 'http://127.0.0.1:11434', 'model': 'synthetic', 'max_tokens': 512, 'probe_max_tokens': 32, 'timeout_seconds': 30, 'token_parameter': 'max_tokens', 'thinking': 'server_default'}, 'revision': 'test', 'local_enabled': False, 'external_enabled': False, 'api_key_present': False, 'api_key_readable': False, 'encrypted_secrets_available': vault, 'configured': False, 'source': 'test'}
            elif path == 'ai/agents':
                data = {'revision': 'test', 'knowledge': {'version': 'test'}, 'knowledge_sha256': 'a' * 64, 'profiles': []}
            else:
                data = {}
        request.fulfill(json={'status':'ok','data':data})
    def dispatch(request):
        parsed = urlparse(request.request.url)
        if parsed.path.startswith('/api/'):
            route(request)
        elif parsed.netloc == urlparse(base_url).netloc:
            request.continue_()
        else:
            raise AssertionError('Nicht-lokaler Browserrequest wurde blockiert')
    context.route('**/*', dispatch)
    page.goto(base_url.rstrip('/') + '/#admin')
    expect(page.get_by_role('heading',name='Eigene Verbindungen',exact=True)).to_be_visible()
    sources=page.get_by_role('region',name='Eigene Verbindungen',exact=True)
    limits=page.get_by_role('region',name='Abrufsteuerung',exact=True)
    providers=page.get_by_role('region',name='Datenanbieter',exact=True)
    expect(sources.get_by_role('heading',name='Demo-Konto 1')).to_be_visible()
    expect(sources.get_by_role('heading',name='Demo-Konto 2')).to_be_visible()
    expect(limits.get_by_role('cell',name='Unbekannt / nicht bestätigt').first).to_be_visible()
    assert not state['writes'],state['writes']
    assert all(not path.endswith(('/test','/sync')) for method,path in state['calls'])
    if demo:
        expect(sources.get_by_role('button',name='Verbindung hinzufügen')).to_be_disabled()
        expect(providers.get_by_role('button',name='API-Key speichern')).to_be_disabled()
        limits.get_by_text('Lokales Betreiberprofil bearbeiten',exact=True).first.click()
        expect(limits.get_by_role('button',name='Limitprofil speichern')).to_be_disabled()
        expect(page.get_by_text('Demo-/Testmodus mit synthetischen Daten.').first).to_be_visible()
    else:
        sources.get_by_role('button',name='Demo-Konto 1 bearbeiten').click()
        expect(sources.get_by_role('heading',name='Verbindung bearbeiten')).to_be_focused()
        for name in ('API-Key','API-Secret','Passphrase (falls vom Anbieter benötigt)'):
            field=sources.get_by_label(name,exact=True)
            assert field.get_attribute('type')=='password'
            assert field.input_value()==''
        expect(sources.get_by_label('API-Key',exact=True)).to_be_disabled() if not vault else None
        if vault:
            sources.get_by_label('Anzeigename',exact=True).fill('Demo-Konto 1 geändert')
            sources.get_by_role('button',name='Verbindung speichern').click()
            expect(sources.get_by_role('heading',name='Demo-Konto 1 geändert')).to_be_visible()
            body=state['writes'][-1][2]
            assert not any(k in body for k in ('api_key','api_secret','passphrase')),body
            sources.get_by_role('button',name='Verbindung hinzufügen').click()
            expect(sources.get_by_role('heading',name='Neue Verbindung',exact=True)).to_be_visible()
            sources.get_by_label('Anbieter',exact=True).select_option('coinbase')
            secret=sources.get_by_label('API-Secret',exact=True)
            secret.evaluate("element => { const transfer=new DataTransfer(); transfer.setData('text/plain','mock-line-1\\nmock-line-2'); element.dispatchEvent(new ClipboardEvent('paste',{clipboardData:transfer,bubbles:true,cancelable:true})); }")
            expect(secret).to_have_value('mock-line-1\\nmock-line-2')
            sources.get_by_label('Anbieter',exact=True).select_option('binance')
            sources.get_by_label('Anzeigename',exact=True).fill('Demo-Neu')
            sources.get_by_label('API-Key',exact=True).fill('mock-only-value')
            sources.get_by_label('API-Secret',exact=True).fill('mock-only-value')
            sources.get_by_role('button',name='Verbindung speichern').click()
            expect(sources.get_by_role('heading',name='Demo-Neu')).to_be_visible()
            expect(sources.get_by_role('heading',name='Verbindung bearbeiten')).to_have_count(0)
            first=sources.get_by_role('article',name='Demo-Konto 1 geändert',exact=True)
            writes=len(state['writes'])
            page.once('dialog',lambda dialog:dialog.dismiss())
            first.get_by_role('button',name='Verbindung testen',exact=True).click()
            assert len(state['writes'])==writes
            page.once('dialog',lambda dialog:dialog.accept())
            first.get_by_role('button',name='Verbindung testen',exact=True).click()
            expect(sources.get_by_text('Verbindungstest angenommen.',exact=False)).to_be_visible()
            expect(first.get_by_role('button',name='Verbindung testen',exact=True)).to_be_disabled()
            assert state['writes'][-1][2]['confirm_external_request'] is True
            state['jobs'][0].update(status='failed',error_code='connection_job_deadline_exceeded',slot_reserved=True)
            sources.get_by_role('button',name='Verbindungen und lokale Aufträge neu laden',exact=True).click()
            expect(sources.get_by_text('Das Zeitlimit oder ein Fehler hat den Auftrag beendet;',exact=False)).to_be_visible()
            expect(first.get_by_role('button',name='Verbindung testen',exact=True)).to_be_disabled()
            expect(sources.get_by_role('button',name='Auftrag abbrechen')).to_be_enabled()
            sources.get_by_role('button',name='Auftrag abbrechen').click()
            expect(first.get_by_role('button',name='Bestand abrufen',exact=True)).to_be_enabled()
            page.once('dialog',lambda dialog:dialog.accept())
            first.get_by_role('button',name='Bestand abrufen',exact=True).click()
            expect(sources.get_by_text('Bestandsabfrage angenommen.',exact=False)).to_be_visible()
            assert state['writes'][-1][2]['confirm_balance_snapshot'] is True
            state['jobs'][0]['status']='succeeded'
            sources.get_by_role('button',name='Verbindungen und lokale Aufträge neu laden',exact=True).click()
            expect(first.get_by_role('button',name='Demo-Konto 1 geändert bearbeiten')).to_be_enabled()
            sources.get_by_role('button',name='Demo-Konto 1 geändert bearbeiten').click()
            page.once('dialog',lambda dialog:dialog.accept())
            sources.get_by_role('button',name='Zugangsdaten entfernen',exact=True).click()
            expect(sources.get_by_text('Zugangsdaten entfernt. Verbindung und vorhandene Quelldaten bleiben erhalten.')).to_be_visible()
            limits.get_by_text('Lokales Betreiberprofil bearbeiten',exact=True).first.click()
            limits.get_by_label('Requests pro Sekunde',exact=True).fill('3')
            limits.get_by_role('button',name='Limitprofil speichern').click()
            expect(limits.get_by_text('Lokales Limitprofil gespeichert.',exact=False)).to_be_visible()
            saved=[item for item in state['writes'] if item[1]=='admin/request-limits'][-1][2]
            assert saved['expected_revision']==1
            assert saved['config']['default_profile']['requests_per_second']==3
            assert saved['config']['default_profile']['requests_per_minute']==60
            assert saved['config']['scheduler_enabled'] is False
            limits.get_by_text('Lokale Endpunktkosten',exact=True).click()
            limits.get_by_label('Anbieterkennung',exact=True).fill('binance')
            limits.get_by_label('Endpunktkennung',exact=True).fill('account')
            limits.get_by_label('Lokale Einheiten je Requestversuch',exact=True).fill('7')
            limits.get_by_role('button',name='Endpunktkosten speichern',exact=True).click()
            expect(limits.get_by_text('Lokaler Endpunktkostenwert gespeichert.',exact=False)).to_be_visible()
            assert state['config']['endpoint_costs']['binance']['account']==7
            limits.get_by_text('Herstellergrenzen aus eigenem Tarif deklarieren',exact=True).click()
            limits.get_by_label('Nicht vertraulicher Tarifname',exact=True).fill('SyntheticPlan')
            limits.get_by_label('Tarifgrenze Requests pro Sekunde',exact=True).fill('1')
            limits.get_by_label('Tarifgrenze Requests pro Minute',exact=True).fill('50')
            limits.get_by_label('Geltungsbereich der Tarifgrenze',exact=True).select_option('api_key')
            limits.get_by_label('Öffentliche Referenz zur Tarifgrenze',exact=True).fill('https://docs.example.org/limits')
            limits.get_by_label('Prüfdatum der Tarifdeklaration',exact=True).fill('2026-10-26')
            limits.get_by_role('checkbox',name='Ich habe diese Angaben',exact=False).check()
            limits.get_by_role('button',name='Tarifdeklaration speichern',exact=True).click()
            expect(limits.get_by_text('Tarifgrenze als Betreiberdeklaration gespeichert,',exact=False)).to_be_visible()
            ceiling=state['config']['provider_ceilings']['binance']
            assert ceiling['declared_by_operator'] is True
            assert ceiling['independently_verified'] is False
            assert ceiling['weighted_cost_per_minute'] is None
            limits.get_by_label('Limitprofil',exact=True).select_option('provider:binance')
            expect(limits.get_by_role('cell',name='1 · vom Betreiber deklariert, nicht unabhängig verifiziert',exact=True)).to_be_visible()
            limits.get_by_text('Tatsächlich gemeldete Anbieterwerte',exact=True).click()
            expect(limits.get_by_role('cell',name='-3',exact=True)).to_be_visible()
        else:
            expect(sources.get_by_text('Der verschlüsselte Secret-Vault ist nicht bereit.',exact=False)).to_be_visible()
            sources.get_by_role('button',name='Abbrechen',exact=True).click()
    # No credential is ever in URL or returned as a readable field.
    assert 'mock-only-value' not in page.url
    assert not page.locator('textarea[type=password]').count()
    for width in (390,768,1280,1440):
        page.set_viewport_size({'width':width,'height':1000})
        page.wait_for_function("""() => {
            const nav = document.querySelector('.sidebar');
            if (!nav) return false;
            return innerWidth > 820 || (!nav.classList.contains('open') &&
                nav.getBoundingClientRect().right <= 0 && getComputedStyle(nav).visibility === 'hidden');
        }""")
        show_section(limits)
        measurements=page.evaluate('({width:innerWidth,scroll:document.documentElement.scrollWidth})')
        assert measurements['scroll']<=measurements['width'],measurements
        page.screenshot(path=str(out/f'{"demo" if demo else "writable" if vault else "no-vault"}-limits-{width}.png'))
        if width in (390,1440):
            show_section(sources)
            page.screenshot(path=str(out/f'{"demo" if demo else "writable" if vault else "no-vault"}-connections-{width}.png'))
            primary=sources.get_by_role('button',name='Verbindung hinzufügen')
            action=primary.bounding_box()
            assert action and action['x']>=0 and action['x']+action['width']<=width,action
            assert primary.evaluate('element=> {const r=element.getBoundingClientRect(); const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2); return element===hit || element.contains(hit); }')
            if not demo:
                primary.click(trial=True)
    page.set_viewport_size({'width':1440,'height':1000})
    show_section(sources)
    page.screenshot(path=str(out/f'{"demo" if demo else "writable" if vault else "no-vault"}-connections.png'))
    assert not failures,failures
    result=dict(demo=demo,vault=vault,writes=len(state['writes']),api_calls=len(state['calls']),console_errors=failures)
    context.close()
    return result


def check_admin(browser, base_url: str, output: Path):
    """Von bestehenden Browserpruefungen aufrufbar; keine produktiven Writes."""
    output.mkdir(parents=True, exist_ok=True)
    results = [
        run(browser, base_url, output, demo=True, vault=False),
        run(browser, base_url, output),
        run(browser, base_url, output, vault=False),
    ]
    (output / 'result.json').write_text(json.dumps({
        'scope': 'Echtes Main-Frontend mit kontrollierter Mock-API; kein Secret-Persistenz- oder realer Provider-Nachweis',
        'results': results,
    }, indent=2), encoding='utf-8')
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url')
    parser.add_argument('--browser-executable')
    parser.add_argument('--output', type=Path, default=Path('artifacts/admin-browser'))
    args = parser.parse_args()
    with ExitStack() as stack:
        base_url = args.base_url
        if not base_url:
            root = Path(__file__).resolve().parents[1] / 'frontend/dist'
            if not (root / 'index.html').is_file():
                parser.error('Zuerst im Frontend npm run build ausfuehren.')
            class QuietHandler(SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            stack.callback(server.server_close)
            stack.callback(worker.join)
            stack.callback(server.shutdown)
            base_url = f'http://127.0.0.1:{server.server_port}'
        playwright = stack.enter_context(sync_playwright())
        browser = playwright.chromium.launch(executable_path=args.browser_executable, headless=True)
        stack.callback(browser.close)
        print(json.dumps(check_admin(browser, base_url, args.output)))


if __name__ == '__main__':
    main()

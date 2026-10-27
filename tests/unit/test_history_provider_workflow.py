from copy import deepcopy
import json
import time

import httpx

from steuerreport_v2.contracts.history import HistoryStart
from steuerreport_v2.domain import portfolio
from steuerreport_v2.domain.external_http import managed_client
from steuerreport_v2.domain.history import HistoryService
from steuerreport_v2.domain.request_limits import RequestLimiter
from steuerreport_v2.contracts.request_limits import RequestLimitProfile, RequestLimitsConfig
from test_history_jobs import setup as setup, request, approve, financial_state
from test_history_solana import signature, signature_info, transaction


class Clock:
    def __init__(self):
        self.value = time.monotonic()
        self.epoch_offset = time.time() - self.value

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds

    def wall(self):
        return self.epoch_offset + self.value


def test_explicit_free_provider_inventory_transport_preview_and_approval(setup, monkeypatch):
    store, service, ref, wallet = setup
    clock = Clock()
    limiter = RequestLimiter(clock=clock.wall, monotonic=clock, sleep=clock.sleep, random=lambda: 0)
    limiter.write_config(RequestLimitsConfig(default_profile=RequestLimitProfile(
        requests_per_second=1000, requests_per_minute=10000, burst=1)), expected_revision=0)
    calls = []
    rpc_errors = []
    original_rpc = portfolio.PortfolioService._solana_rpc

    def observed_rpc(self, *args, **kwargs):
        try:
            return original_rpc(self, *args, **kwargs)
        except Exception as exc:
            rpc_errors.append(str(exc))
            raise

    monkeypatch.setattr(portfolio.PortfolioService, '_solana_rpc', observed_rpc)

    def provider(http_request):
        assert http_request.url.host == 'api.mainnet.solana.com'
        payload = json.loads(http_request.content)
        method, params = payload['method'], payload['params']
        calls.append(method)
        if method == 'getTokenAccountsByOwner':
            result = {'value': []}
        elif method == 'getSignaturesForAddress':
            assert params[0] == wallet
            result = [] if params[1].get('before') else [signature_info(i) for i in range(1, 7)]
        else:
            assert method == 'getTransaction'
            number = next(i for i in range(1, 7) if signature(i) == params[0])
            result = transaction(number, payer=wallet, owner=wallet)
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 1, 'result': result})

    monkeypatch.setattr(portfolio, 'managed_client', lambda **kwargs: managed_client(
        **kwargs, transport=httpx.MockTransport(provider), limiter=limiter, clock=clock.wall, monotonic=clock))
    before = deepcopy(financial_state(store))
    initial = service.start(ref, request(rpc_provider='public'))
    assert initial.transport.id == 'public' and initial.transport.provider_id == 'solana_rpc'
    assert initial.progress.signatures_total is None
    assert not calls and financial_state(store) == before
    service._run(str(initial.id))
    ready = service.get(ref, str(initial.id))
    assert ready.status == 'ready', (ready.error_code, rpc_errors, calls)
    assert ready.progress.inventory_complete and ready.progress.signatures_total == 6
    assert ready.progress.signatures_completed == 6 and ready.progress.estimate_status == 'fetch_complete'
    assert ready.progress.estimated_fetch_remaining_seconds == 0
    assert ready.transport.pinned and ready.transport.id == 'public'
    assert calls[:4] == ['getTokenAccountsByOwner', 'getTokenAccountsByOwner',
                         'getSignaturesForAddress', 'getSignaturesForAddress']
    assert calls.count('getTransaction') == 6
    assert not ready.complete_history_proven and financial_state(store) == before
    assert service.approve(ref, str(ready.id), approve(ready)).imported_events == 6
    events = store.list_canonical_events()
    assert len(events) == 6 and all(row.event_type == 'fee' and row.account == wallet for row in events)
    saved = deepcopy(financial_state(store))
    assert service.approve(ref, str(ready.id), approve(ready)).status == 'succeeded'
    assert financial_state(store) == saved
    repeated = service.start(ref, request(rpc_provider='public'))
    service._run(str(repeated.id))
    second = service.get(ref, str(repeated.id))
    assert second.status == 'ready' and second.new_records == 0 and second.duplicate_records == 6
    assert financial_state(store) == saved


def test_changed_selected_custom_endpoint_fails_before_network_and_keeps_saved_label(setup, monkeypatch):
    store, service, ref, _wallet = setup
    monkeypatch.setenv('SOLANA_RPC_URL', 'https://rpc.synthetic.invalid/first')
    initial = service.start(ref, request(public_rpc_only=False, rpc_provider='custom'))
    assert initial.transport.id == 'custom' and initial.transport.provider_id == 'solana_custom_rpc'
    before = financial_state(store)
    monkeypatch.setenv('SOLANA_RPC_URL', 'https://different.synthetic.invalid/second')
    monkeypatch.setattr(HistoryService, '_collector', lambda *_args: (_ for _ in ()).throw(AssertionError('network forbidden')))
    service._run(str(initial.id))
    result = service.get(ref, str(initial.id))
    assert result.status == 'failed' and result.error_code == 'history_rpc_configuration_changed'
    assert not result.can_resume and result.transport.id == 'custom'
    encoded = result.model_dump_json()
    assert 'synthetic.invalid' not in encoded and '/first' not in encoded and '/second' not in encoded
    assert financial_state(store) == before


def test_explicit_free_flag_mismatch_rejected_before_source_lookup():
    try:
        HistoryStart(request_id='00000000-0000-4000-8000-000000000002', confirm_external_request=True,
                     rpc_provider='helius', public_rpc_only=True)
    except ValueError:
        return
    raise AssertionError('a free-only request cannot use the Helius credential')


def test_legacy_request_id_remains_idempotent_after_optional_provider_field(setup):
    _store, service, ref, _wallet = setup
    original = request()
    created = service.start(ref, original)
    saved = service.storage.jobs()[0]
    saved['_request'].pop('rpc_provider', None)
    service.storage.save(saved)
    assert service.start(ref, original).id == created.id

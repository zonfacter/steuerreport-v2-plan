"""Independent real-DuckDB review probes; no provider, Docker, or production DB."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore


KINDS = ['current_portfolio', 'historical']
PIPELINE = dict(normalized_events=0, balance_entries=0, flow_entries=0,
                tax_lines=0, review_issues_open=0, allow_export=False)


@pytest.fixture
def case(tmp_path, kind):
    store = DuckDbStore(tmp_path / 'synthetic-review.duckdb')
    identifier = str(uuid4())
    identity = {'request_id': identifier}
    if kind == 'historical':
        identity['operation_kind'] = kind
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    reserve = store.reserve_current_price_backfill if kind == 'current_portfolio' else store.reserve_historical_price_backfill
    assert reserve(key)
    return store, identifier, key


def result(kind, identifiers, phase='completed'):
    value = dict(operation_kind=kind, configured_assets=['SYNTHETIC'], asset_filter=[],
                 planned_jobs=len(identifiers), attempted=len(identifiers), imported_prices=len(identifiers),
                 skipped=0, failed=0, dry_run=False, jobs=[], stored_price_ids=identifiers,
                 pipeline=PIPELINE if phase == 'completed' else None,
                 pipeline_status=phase,
                 pipeline_effects={'completed': 'completed', 'failed': 'unknown_or_partial',
                                   'not_started': 'not_started'}[phase], result_journal_status='recorded')
    value.update(portfolio_assets_count=1, priced_at=datetime.now(timezone.utc).isoformat()) if kind == 'current_portfolio' else value.update(requirements_count=1)
    return value


def create_prices(store, key, kind, empty=False):
    return store.prepare_price_backfill(key, kind, [] if empty else [PricePointCreate(
        asset='SYNTHETIC', source='synthetic', priced_at=datetime.now(timezone.utc), price_eur=Decimal('2'))])


def status(store, identifier, kind):
    client = TestClient(create_app(DuckDbStore(store.path)))
    path = '/api/v1/prices/backfill/' + ('external' if kind == 'historical' else 'current-portfolio') + '/status'
    return client.post(path, json={'request_id': identifier})


class CommitAckFault:
    def __init__(self, real, after, events):
        self.real, self.after, self.events = real, after, events
    def __enter__(self):
        self.real.__enter__()
        return self
    def __exit__(self, *args):
        return self.real.__exit__(*args)
    def __getattr__(self, name):
        return getattr(self.real, name)
    def execute(self, sql, *args, **kwargs):
        if sql.strip().upper() == 'COMMIT':
            self.events.append('commit')
            if self.after:
                self.real.execute(sql, *args, **kwargs)
            raise OSError('SYNTHETIC_PRIVATE_COMMIT_ACK /private/review')
        return self.real.execute(sql, *args, **kwargs)


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('boundary', ['marker', 'final'])
@pytest.mark.parametrize('after', [False, True])
def test_actual_marker_and_final_commit_ack_loss_is_resolved_without_false_completion(
    case, kind, boundary, after, monkeypatch, caplog,
):
    store, identifier, key = case
    ids = [point.price_id for point in create_prices(store, key, kind)]
    if boundary == 'final':
        store.mark_price_backfill_pipeline_started(key, kind)
    connect, events = store.connect, []
    with monkeypatch.context() as patch:
        patch.setattr(store, 'connect', lambda: CommitAckFault(connect(), after, events))
        with pytest.raises(OSError):
            if boundary == 'marker':
                store.mark_price_backfill_pipeline_started(key, kind)
            else:
                record = store.record_current_price_backfill if kind == 'current_portfolio' else store.record_historical_price_backfill
                record(key, json.dumps(result(kind, ids)))
    assert events == ['commit']
    raw_result, raw_checkpoint = store.price_backfill_operation_record(key, kind)
    response = status(store, identifier, kind)
    assert response.status_code == 200, response.text
    body = response.json()['data']
    expected_phase = ('completed' if after else 'running_or_interrupted') if boundary == 'final' else ('running_or_interrupted' if after else 'not_started')
    assert body['checkpoint']['pipeline_status'] == expected_phase
    assert body['checkpoint']['stored_price_ids'] == ids
    assert body['checkpoint_sha256'] == hashlib.sha256(raw_checkpoint.encode()).hexdigest()
    if boundary == 'final' and after:
        assert body['status'] == 'recorded' and raw_result is not None
        assert body['result']['result_journal_status'] == 'recorded'
        assert body['result']['pipeline_status'] == 'completed'
    else:
        assert body['status'] == 'checkpointed' and body.get('result') is None and raw_result is None
    assert 'SYNTHETIC_PRIVATE_COMMIT_ACK' not in response.text + caplog.text
    assert '/private/review' not in response.text + caplog.text
    assert store.price_backfill_operation_record(key, kind) == (raw_result, raw_checkpoint)
    assert [p.price_id for p in store.list_price_points()] == ids


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('phase', ['failed', 'not_started'])
def test_reader_rejects_pipeline_result_when_checkpoint_phase_has_no_pipeline_result(case, kind, phase):
    store, identifier, key = case
    ids = [point.price_id for point in create_prices(store, key, kind, empty=phase == 'not_started')]
    if ids:
        store.mark_price_backfill_pipeline_started(key, kind)
    record = store.record_current_price_backfill if kind == 'current_portfolio' else store.record_historical_price_backfill
    record(key, json.dumps(result(kind, ids, phase)))
    valid_result, raw_checkpoint = store.price_backfill_operation_record(key, kind)
    malformed = json.loads(valid_result)
    malformed['pipeline'] = {**PIPELINE, 'allow_export': True}
    # Simulate an inconsistent restored journal, not a provider or pipeline call.
    with store.connect() as con:
        con.execute('update current_price_backfill_requests set result_json=? where request_hash=?',
                    [json.dumps(malformed), key])
    response = status(store, identifier, kind)
    print('READ_INCONSISTENCY', kind, phase, response.status_code, response.json()['data'])
    assert response.status_code == 500, 'Contradictory embedded pipeline result must not be positively readable'
    assert response.json()['data']['status'] == 'unknown'
    assert store.price_backfill_operation_record(key, kind)[1] == raw_checkpoint

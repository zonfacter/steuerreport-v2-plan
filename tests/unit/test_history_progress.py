from datetime import datetime, timedelta, timezone

import pytest

from steuerreport_v2.contracts.history import HistoryRateState, HistoryRpcOption, HistoryStart
from steuerreport_v2.domain.history_progress import public_progress, record_progress
from steuerreport_v2.domain.history_types import HistoryPage


NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


def transport(**limits):
    return HistoryRpcOption(id='public', label='Synthetic RPC', kind='public', provider_id='solana_rpc',
        limits=HistoryRateState(available=True, effective_max_requests_per_second=3.0, **limits))


def job(**changes):
    return {'status': 'running', 'updated_at': NOW.isoformat(), '_options': {'inventory_job_id': 'synthetic'},
        '_progress': {'phase': 'fetch', 'inventory_complete': True, 'signatures_total': 100,
                      'signatures_completed': 20}, '_fetch_elapsed_seconds': 10.0,
        '_detail_rate_ema': 2.0, '_detail_samples': 20, '_detail_measured_at': NOW.isoformat(), **changes}


def test_eta_uses_known_remainder_measured_rate_and_known_wait():
    result = public_progress(job(), transport(wait_seconds=7.0), at=NOW)
    assert result.estimate_status == 'estimated'
    assert result.estimated_fetch_remaining_seconds == 47
    assert result.observed_details_per_second == 2.0
    assert result.estimate_scope == 'available_rpc_transaction_details'


def test_current_operator_cap_bounds_old_faster_measurement():
    limits = HistoryRpcOption(id='helius', label='Synthetic configured', kind='configured', provider_id='helius',
        limits=HistoryRateState(available=True, effective_max_requests_per_second=0.5))
    result = public_progress(job(), limits, at=NOW)
    assert result.estimated_fetch_remaining_seconds == 160
    assert result.observed_details_per_second == 0.5


def test_unknown_total_and_record_limit_never_become_an_eta_denominator():
    state = job(max_records=100000, records_fetched=20, _progress={'phase': 'discovery', 'references_discovered': 800})
    result = public_progress(state, transport(), at=NOW)
    assert result.signatures_total is None and result.signatures_completed is None
    assert result.estimated_fetch_remaining_seconds is None and result.estimate_status == 'unknown_total'


@pytest.mark.parametrize('status', ['paused', 'failed', 'cancelled'])
def test_stopped_job_does_not_count_down_or_show_zero(status):
    result = public_progress(job(status=status), transport(), at=NOW)
    assert result.estimated_fetch_remaining_seconds is None
    assert result.observed_details_per_second is None


@pytest.mark.parametrize('status', ['ready', 'succeeded', 'importing'])
def test_fetch_completion_is_not_financial_release(status):
    result = public_progress(job(status=status), transport(), at=NOW)
    assert result.estimate_status == 'fetch_complete' and result.estimated_fetch_remaining_seconds == 0
    assert 'released' not in result.model_dump()


def test_preparation_time_remains_separate_from_finished_fetch():
    result = public_progress(job(_done=True), transport(), at=NOW)
    assert result.phase == 'preparing' and result.estimate_status == 'fetch_complete'


@pytest.mark.parametrize('changes', [
    {'_detail_samples': 4}, {'_detail_rate_ema': 0}, {'_detail_rate_ema': float('nan')},
    {'_detail_measured_at': (NOW - timedelta(minutes=3)).isoformat()},
    {'_detail_measured_at': (NOW + timedelta(minutes=3)).isoformat()},
])
def test_insufficient_invalid_or_stale_samples_do_not_invent_a_speed(changes):
    result = public_progress(job(**changes), transport(), at=NOW)
    assert result.estimated_fetch_remaining_seconds is None and result.estimate_status == 'warming_up'


def test_missing_or_failed_limit_readout_never_means_unlimited():
    for limits in (None, HistoryRpcOption(id='public', label='Synthetic', kind='public', limits=HistoryRateState())):
        result = public_progress(job(), limits, at=NOW)
        assert result.estimated_fetch_remaining_seconds is None and result.estimate_status == 'unavailable'


def test_old_cex_and_rpc_jobs_have_no_fabricated_total():
    result = public_progress(job(_progress={}, _options={}), None, at=NOW)
    assert result.estimate_status == 'not_supported' and result.signatures_total is None


def test_page_metrics_measure_successful_detail_work_and_smooth_recent_rate():
    state = job(_detail_samples=0, _detail_rate_ema=None)
    page = HistoryPage([], {}, False, extra={'progress': {'phase': 'fetch', 'inventory_complete': True,
        'signatures_total': 100, 'signatures_completed': 25}})
    record_progress(state, page, 5.0)
    assert state['_detail_samples'] == 5 and state['_detail_rate_ema'] == 1.0
    assert state['_fetch_elapsed_seconds'] == 15.0
    second = HistoryPage([], {}, False, extra={'progress': {'phase': 'fetch', 'inventory_complete': True,
        'signatures_total': 100, 'signatures_completed': 30}})
    record_progress(state, second, 10.0)
    assert state['_detail_samples'] == 10 and state['_detail_rate_ema'] == pytest.approx(0.825)


def test_discovery_does_not_measure_signature_pagination_as_transaction_speed():
    state = job(_detail_samples=0, _detail_rate_ema=None)
    record_progress(state, HistoryPage([], {}, False, extra={'progress': {'phase': 'discovery'}}), 20.0)
    assert state['_detail_samples'] == 0 and state['_detail_rate_ema'] is None
    assert state['_fetch_elapsed_seconds'] == 10.0


@pytest.mark.parametrize('choice,public', [('public', False), ('helius', True), ('alchemy', True), ('custom', True)])
def test_explicit_rpc_choice_cannot_silently_disagree_with_free_only(choice, public):
    with pytest.raises(ValueError):
        HistoryStart(request_id='00000000-0000-4000-8000-000000000001', confirm_external_request=True,
                     rpc_provider=choice, public_rpc_only=public)

"""Lesende Abrufschaetzung: unbekannter Nenner bleibt unbekannt."""
from __future__ import annotations

from datetime import datetime, timezone
import math

from steuerreport_v2.contracts.history import HistoryProgress, HistoryRpcOption


def public_progress(job: dict, transport: HistoryRpcOption | None, *, at: datetime | None = None) -> HistoryProgress:
    values = dict(job.get('_progress') or {})
    accepted = set(HistoryProgress.model_fields)
    progress = HistoryProgress.model_validate({key: value for key, value in values.items() if key in accepted})
    progress.updated_at = datetime.fromisoformat(job['updated_at'])
    elapsed = job.get('_fetch_elapsed_seconds')
    progress.fetch_elapsed_seconds = elapsed if isinstance(elapsed, (int, float)) and math.isfinite(elapsed) and elapsed >= 0 else None
    status = job['status']
    progress.estimated_fetch_remaining_seconds = None
    progress.observed_details_per_second = None
    if status in {'paused', 'failed', 'cancelled'}:
        progress.phase = {'paused': 'paused', 'failed': 'error', 'cancelled': 'cancelled'}[status]
        progress.estimate_status = 'paused' if status == 'paused' else 'unavailable'
        return progress
    if status in {'ready', 'succeeded', 'importing'}:
        progress.phase = 'complete'
        progress.estimate_status = 'fetch_complete'
        progress.estimated_fetch_remaining_seconds = 0
        return progress
    if job.get('_done'):
        progress.phase = 'preparing'
        progress.estimate_status = 'fetch_complete'
        progress.estimated_fetch_remaining_seconds = 0
        return progress
    total, completed = progress.signatures_total, progress.signatures_completed
    if not progress.inventory_complete or total is None:
        progress.estimate_status = 'unknown_total' if job.get('_options', {}).get('inventory_job_id') else 'not_supported'
        return progress
    if completed is None or completed > total:
        progress.estimate_status = 'unavailable'
        return progress
    limits = transport.limits if transport else None
    if limits is None or not limits.available or limits.effective_max_requests_per_second is None:
        progress.estimate_status = 'unavailable'
        return progress
    rate = job.get('_detail_rate_ema')
    samples = job.get('_detail_samples', 0)
    measured_at = job.get('_detail_measured_at')
    fresh = False
    if measured_at:
        try:
            age = ((at or datetime.now(timezone.utc)) - datetime.fromisoformat(measured_at)).total_seconds()
            fresh = 0 <= age <= 120
        except (ValueError, TypeError):
            pass
    if not (isinstance(rate, (int, float)) and math.isfinite(rate) and rate > 0 and samples >= 5 and fresh):
        progress.estimate_status = 'warming_up'
        return progress
    rate = min(rate, limits.effective_max_requests_per_second)
    if rate <= 0 or not math.isfinite(rate):
        progress.estimate_status = 'unavailable'
        return progress
    progress.observed_details_per_second = rate
    progress.estimate_status = 'estimated'
    # Bekannte aktuelle Kontingentwartezeit kommt zur gemessenen Restarbeit hinzu.
    progress.estimated_fetch_remaining_seconds = math.ceil((total - completed) / rate + (limits.wait_seconds or 0))
    return progress


def record_progress(job: dict, page, elapsed: float) -> None:
    values = page.extra.get('progress')
    if not isinstance(values, dict):
        return
    prior = (job.get('_progress') or {}).get('signatures_completed') or 0
    progress = HistoryProgress.model_validate(values)
    total, completed = progress.signatures_total, progress.signatures_completed
    if progress.inventory_complete and (total is None or completed is None or completed > total):
        raise ValueError('history_progress_invalid')
    job['_progress'] = progress.model_dump(mode='json')
    if progress.phase != 'fetch' or completed is None:
        return
    job['_fetch_elapsed_seconds'] = job.get('_fetch_elapsed_seconds', 0.0) + max(0.0, elapsed)
    delta = completed - prior
    if delta > 0 and elapsed > 0 and math.isfinite(elapsed):
        observed = delta / elapsed
        previous = job.get('_detail_rate_ema')
        job['_detail_rate_ema'] = observed if previous is None else 0.35 * observed + 0.65 * previous
        job['_detail_samples'] = job.get('_detail_samples', 0) + delta
        job['_detail_measured_at'] = datetime.now(timezone.utc).isoformat()

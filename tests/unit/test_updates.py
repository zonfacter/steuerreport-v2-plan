from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import multiprocessing
from pathlib import Path
import socket
import threading

import httpx
from pydantic import ValidationError
import pytest

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.updates import UpdateHandoffRequest, UpdateSettings
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.updates import (
    CACHE_KEY,
    MAX_PAGE_BYTES,
    MAX_PAGES,
    OPEN_CHECKS,
    PAGE_SIZE,
    RELEASE_API,
    REPOSITORY,
    SETTINGS_KEY,
    UpdateBlockedError,
    UpdateBusyError,
    UpdateSelectionError,
    UpdateService,
)


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def release(tag="v0.2.0rc33", *, release_id=33, prerelease=False, **changes):
    result = dict(
        id=release_id,
        tag_name=tag,
        draft=False,
        prerelease=prerelease,
        published_at="2026-10-27T12:00:00Z",
        html_url=f"https://github.com/{REPOSITORY}/releases/tag/{tag}",
        target_commitish="main",
        body="Aenderungen als fremde Daten.",
    )
    result.update(changes)
    return result


@pytest.fixture(scope="session", autouse=True)
def source_freeze(tmp_path_factory):
    repo = Path(__file__).resolve().parents[2]
    names = ("contracts/updates.py", "domain/updates.py")

    def hashes():
        return {
            name: hashlib.sha256(
                (repo / "src/steuerreport_v2" / name).read_bytes()
            ).hexdigest()
            for name in names
        }

    before = hashes()
    yield
    after = hashes()
    (tmp_path_factory.getbasetemp() / "updates-source-freeze.json").write_text(
        json.dumps(
            {"before": before, "after": after, "unchanged": before == after},
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    assert before == after


@pytest.fixture
def case(tmp_path, monkeypatch):
    def blocked(*args, **kwargs):
        raise OSError("Updates-Test: externe Verbindungen gesperrt")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.health()
    clock = Clock()
    clients = []
    calls = []

    def make(payload=None, *, handler=None, version="0.2.0rc32", **kwargs):
        def transport(request):
            calls.append(request)
            assert request.method == "GET"
            assert request.url.host == "api.github.com"
            assert request.url.path == f"/repos/{REPOSITORY}/releases"
            assert "authorization" not in request.headers
            assert "installed_version" not in request.url.params
            return (
                handler(request)
                if handler
                else httpx.Response(200, json=payload if payload is not None else [])
            )

        client = httpx.Client(transport=httpx.MockTransport(transport))
        clients.append(client)
        return UpdateService(
            store,
            client=client,
            clock=clock,
            state_dir=tmp_path / "state",
            installed_version=version,
            **kwargs,
        )

    yield store, clock, calls, make
    for client in clients:
        client.close()
    assert (
        sum(path.stat().st_size for path in tmp_path.rglob("*") if path.is_file())
        < 500 * 1024 * 1024
    )


@pytest.mark.parametrize(
    "version,channel",
    [
        ("0.2.0rc32", "stable_rc"),
        ("0.2.0rc33.dev0", "stable_rc"),
        ("0.2.0", "stable"),
        (None, "stable"),
        ("unbekannt", "stable"),
    ],
)
def test_cache_only_status_has_safe_defaults_and_no_writes_or_http(
    case, version, channel
):
    store, _, calls, make = case
    service = make(version=version)
    before = store.list_admin_settings()
    status = service.status()
    assert status.settings.channel == channel
    assert status.settings.automatic is False
    assert status.status == (
        "not_checked" if version not in {None, "unbekannt"} else "unavailable"
    )
    assert status.check_allowed and status.settings_writable
    assert status.checked_at is None and status.last_success_at is None
    assert not calls
    assert store.list_admin_settings() == before
    assert not service.lock_path.exists()


@pytest.mark.parametrize(
    "installed,tag,available",
    [
        ("0.2.0rc9", "v0.2.0rc10", True),
        ("0.2.0rc32", "v0.2.0rc33", True),
        ("0.2.0rc32", "v0.2.0rc32", False),
        ("0.2.0rc32", "v0.2.0rc31", False),
        ("0.2.0rc99", "v0.2.0", True),
        ("0.2.0rc32", "v0.1.0", False),
        ("0.2.0", "v0.10.0", True),
        ("0.10.0", "v0.9.0", False),
    ],
)
def test_versions_use_parser_never_string_order_or_downgrade(
    case, installed, tag, available
):
    _, _, calls, make = case
    service = make([release(tag)], version=installed)
    status = service.check("manual")
    assert len(calls) == 1
    assert status.status == ("update_available" if available else "up_to_date")
    assert bool(status.releases) is available
    assert not status.stale and not status.incomplete
    if available:
        assert status.latest.tag == tag
        assert status.latest.source_commit is None
        assert status.latest.image_digest is None
        assert status.latest.image_reference is None
        assert status.latest.open_checks == OPEN_CHECKS
        assert len(status.latest.snapshot_digest) == 64


@pytest.mark.parametrize("prerelease", [False, True])
def test_rc_is_rc_even_when_github_flag_is_false_and_saved_channel_survives(
    case, prerelease
):
    store, _, calls, make = case
    service = make([release(prerelease=prerelease)])
    status = service.check("manual")
    assert status.latest.channel == "rc"
    assert status.latest.github_prerelease is prerelease
    service.save_settings(UpdateSettings(channel="stable", automatic=True))
    restarted = make([release(prerelease=prerelease)], version="0.2.0rc34")
    assert restarted.status().settings == UpdateSettings(
        channel="stable", automatic=True
    )
    assert restarted.status().latest is None
    assert len(calls) == 1
    assert any(item.key == SETTINGS_KEY for item in store.list_admin_settings())


@pytest.mark.parametrize(
    "tag,changes,incomplete",
    [
        ("v0.3.0", {"draft": True}, False),
        ("v0.3.0.dev0", {}, False),
        ("v0.3.0a1", {}, False),
        ("v0.3.0b1", {}, False),
        ("not-a-version", {}, False),
        ("v0.3.0+unknown", {}, False),
        ("v0.3.0.post1", {}, False),
        ("v0.3.0", {"prerelease": True}, True),
        ("v0.3.0", {"draft": "false"}, True),
        ("v0.3.0", {"published_at": None}, True),
        ("v0.3.0", {"published_at": "2026-10-29T12:00:00Z"}, True),
        ("v0.3.0", {"html_url": "https://evil.invalid/release"}, True),
        ("v0.3.0", {"id": True}, True),
    ],
)
def test_nonpublished_unsupported_or_contradictory_releases_not_offered(
    case, tag, changes, incomplete
):
    _, _, _, make = case
    status = make([release(tag, **changes)]).check("manual")
    assert status.latest is None and not status.releases
    assert status.incomplete is incomplete
    assert status.status == ("unavailable" if incomplete else "up_to_date")


def test_sorting_ignores_response_order_and_publication_time(case):
    _, _, _, make = case
    status = make(
        [
            release("v0.2.0rc34", release_id=34),
            release("v0.1.0", release_id=1000, published_at="2026-10-28T11:00:00Z"),
            release("v0.2.0rc33"),
            release("v0.2.0", release_id=200),
        ]
    ).check("manual")
    assert [item.tag for item in status.releases] == [
        "v0.2.0",
        "v0.2.0rc34",
        "v0.2.0rc33",
    ]


def test_page_two_and_page_specific_etag_304_revalidate_whole_snapshot(case):
    _, clock, calls, make = case

    def handler(request):
        page = request.url.params["page"]
        etag = f'"page-{page}"'
        if "if-none-match" in request.headers:
            assert request.headers["if-none-match"] == etag
            return httpx.Response(304)
        headers = {"ETag": etag}
        if page == "1":
            # Query-Reihenfolge ist keine Identitaet des Upstreams.
            headers["Link"] = f'<{RELEASE_API}?page=2&per_page={PAGE_SIZE}>; rel="next"'
        return httpx.Response(
            200,
            json=[release("v0.1.0", release_id=1)] if page == "1" else [release()],
            headers=headers,
        )

    service = make(handler=handler)
    first = service.check("manual")
    assert first.latest.release_id == 33
    clock.advance(hours=6)
    second = service.check("manual")
    assert second.latest == first.latest
    assert second.last_success_at == clock.now
    assert second.status == "update_available" and not second.stale
    assert len(calls) == 4


def test_pagination_cap_is_explicit_and_never_falsely_up_to_date(case):
    _, _, calls, make = case

    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json=[release("v0.1.0", release_id=page)],
            headers={
                "Link": f'<{RELEASE_API}?per_page={PAGE_SIZE}&page={page + 1}>; rel="next"',
            },
        )

    status = make(handler=handler).check("manual")
    assert len(calls) == MAX_PAGES
    assert status.incomplete is True
    assert status.latest is None
    assert status.status == "unavailable"


@pytest.mark.parametrize(
    "next_url",
    [
        "https://evil.invalid/releases?page=2&per_page=100",
        "http://api.github.com/repos/zonfacter/steuerreport-v2-plan/releases?page=2&per_page=100",
        "https://api.github.com/repos/other/repo/releases?page=2&per_page=100",
        RELEASE_API + "?page=2&per_page=100&page=3",
    ],
)
def test_pagination_never_follows_untrusted_url_or_query(case, next_url):
    _, _, calls, make = case
    status = make(
        handler=lambda _: httpx.Response(
            200, json=[], headers={"Link": f'<{next_url}>; rel="next"'}
        )
    ).check()
    assert status.status == "unavailable"
    assert status.last_success_at is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "kind", ["timeout", "invalid_json", "object", "oversize", "redirect", "304", "500"]
)
def test_failures_keep_last_success_stale_without_false_current_or_exception_secrets(
    case, kind
):
    _, clock, calls, make = case
    service = make([release()])
    first = service.check()
    clock.advance(minutes=2)

    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("SECRET_SHOULD_NOT_LEAK", request=request)
        if kind == "invalid_json":
            return httpx.Response(200, content=b"{broken")
        if kind == "object":
            return httpx.Response(200, json={"message": "not-a-list"})
        if kind == "oversize":
            return httpx.Response(200, content=b" " * (MAX_PAGE_BYTES + 1))
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "https://evil.invalid"})
        return httpx.Response(int(kind))

    failed = make(handler=handler).check()
    assert failed.status == "unavailable"
    assert failed.stale
    assert failed.latest == first.latest
    assert failed.last_success_at == first.last_success_at
    assert failed.checked_at == clock.now
    assert not failed.check_allowed
    assert "SECRET_SHOULD_NOT_LEAK" not in failed.model_dump_json()
    assert len(calls) == 2


def test_304_without_cache_is_unavailable(case):
    _, _, _, make = case
    status = make(handler=lambda _: httpx.Response(304)).check()
    assert status.status == "unavailable"
    assert status.last_success_at is None


@pytest.mark.parametrize("code", [403, 429])
@pytest.mark.parametrize("date_header", [False, True])
def test_retry_after_seconds_or_http_date_persists_across_restart(
    case, code, date_header
):
    _, clock, calls, make = case
    value = "Wed, 28 Oct 2026 12:02:00 GMT" if date_header else "120"
    service = make(
        handler=lambda _: httpx.Response(code, headers={"Retry-After": value})
    )
    status = service.check()
    assert status.status == "unavailable"
    assert status.retry_at == NOW + timedelta(seconds=120)
    restarted = make([])
    clock.advance(seconds=119)
    assert restarted.check().check_allowed is False
    assert len(calls) == 1
    clock.advance(seconds=1)
    assert restarted.check().status == "up_to_date"
    assert len(calls) == 2


def test_rate_limit_reset_and_clock_rollback_do_not_trigger_request_flood(case):
    _, clock, calls, make = case
    status = make(
        handler=lambda _: httpx.Response(
            403,
            headers={
                "Retry-After": "60",
                "X-RateLimit-Reset": str(int(NOW.timestamp()) + 180),
            },
        )
    ).check()
    assert status.retry_at == NOW + timedelta(seconds=180)
    clock.advance(hours=-1)
    service = make([])
    assert not service.status().check_allowed
    assert service.check().status == "unavailable"
    assert len(calls) == 1


def test_automatic_off_by_default_six_hour_interval_and_manual_cooldown(case):
    _, clock, calls, make = case
    service = make([])
    assert service.check("automatic").status == "disabled"
    assert not calls
    service.save_settings(UpdateSettings(channel="stable_rc", automatic=True))
    assert service.check("automatic").status == "up_to_date"
    service.check("manual")
    assert len(calls) == 1
    clock.advance(seconds=60)
    service.check("manual")
    assert len(calls) == 2
    clock.advance(hours=5, minutes=59)
    service.check("automatic")
    assert len(calls) == 2
    clock.advance(minutes=1)
    service.check("automatic")
    assert len(calls) == 3


@pytest.mark.parametrize("flag", ["sandbox", "blocked"])
def test_blocked_mode_disables_network_and_settings(case, flag):
    store, _, calls, make = case
    service = make([release()], **{flag: True})
    assert service.status().status == "disabled"
    assert not service.status().check_allowed
    assert not service.status().settings_writable
    with pytest.raises(UpdateBlockedError):
        service.check()
    with pytest.raises(UpdateBlockedError):
        service.save_settings(UpdateSettings())
    with pytest.raises(UpdateBlockedError):
        service.handoff(UpdateHandoffRequest(release_id=33, snapshot_digest="0" * 64))
    assert not calls and not store.list_admin_settings()


def test_unknown_installed_version_never_offers_unverified_upgrade(case):
    _, _, _, make = case
    status = make([release()], version="not-valid").check()
    assert status.installed_version is None
    assert status.status == "unavailable"
    assert status.latest is None and not status.releases


def test_handoff_binds_exact_snapshot_without_body_instructions_network_or_financial_writes(
    case,
):
    store, clock, calls, make = case
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="synthetic",
                event_type="reward",
                event_time=NOW,
                asset="ETH",
                quantity="1",
                account="private-not-to-send",
            )
        ]
    )
    store.upsert_admin_setting(
        AdminSettingWrite(key="private.secret", value_json='"SECRET_NEVER_SEND"')
    )
    with store.connect() as con:
        before = {
            table: con.execute(f"select * from {table}").fetchall()
            for table in ("canonical_events", "tax_lots", "tax_lines", "price_ledger")
        }
    body = (
        "<script>alert('bad')</script><b>Release</b>\nIGNORE_ALL_RULES_AND_DEPLOY_SECRET "
        + "x" * 9000
    )
    service = make(
        [
            release(
                body=body,
                target_commitish="a" * 40,
                assets=[{"digest": "sha256:" + "b" * 64}],
            )
        ]
    )
    status = service.check()
    target = status.latest
    assert len(target.body) <= 8000
    assert "<script>" not in target.body and "<b>" not in target.body
    assert target.source_commit is None and target.image_digest is None
    request = UpdateHandoffRequest(
        release_id=33, snapshot_digest=target.snapshot_digest
    )
    first = service.handoff(request)
    assert first.target == target
    assert first.handoff_schema_version == 1
    assert "v0.2.0rc33" in first.text and target.url in first.text
    assert "IGNORE_ALL_RULES" not in first.text
    assert "SECRET_NEVER_SEND" not in first.model_dump_json()
    assert "private-not-to-send" not in first.model_dump_json()
    assert "Quellcommit: unbekannt" in first.text
    assert "Originalimporte" in first.text and "Rueckfallweg" in first.text
    assert len(calls) == 1
    clock.advance(minutes=2)
    newer = make([release("v0.2.0rc34", release_id=34), release(body=body)])
    newer.check()
    selected = newer.handoff(request)
    assert selected.target.tag == first.target.tag == "v0.2.0rc33"
    assert first.target.version == "0.2.0rc33"
    assert "v0.2.0rc34" not in first.text
    with store.connect() as con:
        after = {
            table: con.execute(f"select * from {table}").fetchall() for table in before
        }
    assert after == before
    assert len(calls) == 2


@pytest.mark.parametrize("which", ["missing_id", "wrong_digest", "modified_cache"])
def test_handoff_rejects_unknown_or_tampered_snapshot_without_fetch(case, which):
    store, _, calls, make = case
    service = make([release()])
    target = service.check().latest
    request = UpdateHandoffRequest(
        release_id=34 if which == "missing_id" else 33,
        snapshot_digest="0" * 64 if which == "wrong_digest" else target.snapshot_digest,
    )
    if which == "modified_cache":
        item = next(
            item for item in store.list_admin_settings() if item.key == CACHE_KEY
        )
        data = json.loads(item.value_json)
        data["pages"]["1"]["releases"][0]["tag"] = "v9.0.0"
        store.upsert_admin_setting(
            AdminSettingWrite(key=CACHE_KEY, value_json=json.dumps(data))
        )
    with pytest.raises(UpdateSelectionError):
        service.handoff(request)
    assert len(calls) == 1


def test_settings_validation_and_bad_cache_never_claim_current(case):
    store, _, calls, make = case
    with pytest.raises(ValidationError):
        UpdateSettings(channel="nightly")
    with pytest.raises(ValidationError):
        UpdateSettings(automatic="yes")
    store.upsert_admin_setting(AdminSettingWrite(key=CACHE_KEY, value_json="{broken"))
    status = make([]).status()
    assert status.status == "unavailable" and status.stale
    assert not calls


def test_no_database_connection_is_held_during_transport(case, monkeypatch):
    store, _, _, make = case
    active = 0
    original = store.connect

    @contextmanager
    def connect():
        nonlocal active
        with original() as con:
            active += 1
            try:
                yield con
            finally:
                active -= 1

    monkeypatch.setattr(store, "connect", connect)

    def handler(_):
        assert active == 0
        with store.connect() as con:
            assert (
                con.execute("select count(*) from canonical_events").fetchone()[0] == 0
            )
        return httpx.Response(200, json=[])

    assert make(handler=handler).check().status == "up_to_date"


def _hold_lock(filename, pipe):
    with open(filename, "a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        pipe.send("locked")
        pipe.recv()
        fcntl.flock(handle, fcntl.LOCK_UN)


def test_flock_is_shared_across_processes(case):
    _, _, calls, make = case
    service = make([])
    service.lock_path.parent.mkdir(parents=True)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    worker = context.Process(target=_hold_lock, args=(str(service.lock_path), child))
    worker.start()
    try:
        assert parent.poll(10) and parent.recv() == "locked"
        assert service.status().status == "checking"
        assert service.check().status == "checking"
        with pytest.raises(UpdateBusyError):
            service.save_settings(UpdateSettings())
        with pytest.raises(UpdateBusyError):
            service.handoff(
                UpdateHandoffRequest(release_id=33, snapshot_digest="0" * 64)
            )
        assert not calls
    finally:
        parent.send("release")
        worker.join(10)
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        parent.close()
        child.close()
    assert worker.exitcode == 0
    assert service.check().status == "up_to_date"
    assert len(calls) == 1


def test_two_service_instances_deduplicate_inflight_network_and_keep_status_local(case):
    _, _, calls, make = case
    entered, finish = threading.Event(), threading.Event()
    result = []

    def handler(_):
        entered.set()
        assert finish.wait(10)
        return httpx.Response(200, json=[release()])

    first, second = make(handler=handler), make([release()])
    thread = threading.Thread(target=lambda: result.append(first.check()))
    thread.start()
    try:
        assert entered.wait(10)
        assert second.status().status == "checking"
        assert second.check().status == "checking"
        assert len(calls) == 1
    finally:
        finish.set()
        thread.join(10)
    assert not thread.is_alive()
    assert len(result) == 1 and result[0].status == "update_available"
    assert second.check().status == "update_available"
    assert len(calls) == 1


def test_default_version_is_read_from_running_backend_at_construction(
    case, monkeypatch, tmp_path
):
    import steuerreport_v2

    store, clock, _, _ = case
    monkeypatch.setattr(steuerreport_v2, "__version__", "0.2.0rc33.dev1")
    service = UpdateService(store, clock=clock, state_dir=tmp_path / "state")
    assert service.status().installed_version == "0.2.0rc33.dev1"
    assert service.status().settings.channel == "stable_rc"


def test_malformed_pagination_url_becomes_unavailable_not_server_exception(case):
    _, _, calls, make = case
    status = make(
        handler=lambda _: httpx.Response(
            200,
            json=[],
            headers={"Link": '<http://[>; rel="next"'},
        )
    ).check()
    assert status.status == "unavailable"
    assert status.last_success_at is None
    assert len(calls) == 1


def test_total_response_budget_is_bounded_across_pages(case):
    _, _, calls, make = case

    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json=[release(release_id=page, body="x" * 510000)],
            headers={
                "Link": f'<{RELEASE_API}?per_page={PAGE_SIZE}&page={page + 1}>; rel="next"',
            },
        )

    status = make(handler=handler).check()
    assert status.status == "unavailable"
    assert status.last_success_at is None
    assert len(calls) <= MAX_PAGES
    assert "Abruflimit" in status.message


def test_failed_second_page_preserves_entire_old_snapshot_not_partial_new_release(case):
    _, clock, calls, make = case
    original = make([release()]).check()
    clock.advance(minutes=2)

    def handler(request):
        if request.url.params["page"] == "2":
            raise httpx.ReadTimeout("synthetic", request=request)
        return httpx.Response(
            200,
            json=[release("v0.2.0rc34", release_id=34)],
            headers={
                "Link": f'<{RELEASE_API}?per_page={PAGE_SIZE}&page=2>; rel="next"',
            },
        )

    status = make(handler=handler).check()
    assert status.status == "unavailable" and status.stale
    assert status.releases == original.releases
    assert status.last_success_at == original.last_success_at
    assert len(calls) == 3


def test_clock_rollback_after_long_check_is_also_detected(case):
    _, clock, calls, make = case

    def handler(_):
        clock.advance(seconds=30)
        return httpx.Response(200, json=[])

    service = make(handler=handler)
    assert service.check().status == "up_to_date"
    clock.advance(seconds=-15)
    status = service.status()
    assert status.status == "unavailable" and status.stale
    assert not status.check_allowed
    service.check()
    assert len(calls) == 1


def test_stale_handoff_stays_bound_and_explicitly_warns_without_network(case):
    _, clock, calls, make = case
    service = make([release()])
    target = service.check().latest
    clock.advance(hours=7)
    result = service.handoff(
        UpdateHandoffRequest(
            release_id=target.release_id,
            snapshot_digest=target.snapshot_digest,
        )
    )
    assert result.target == target
    assert "veraltet oder unvollstaendig" in result.text
    assert len(calls) == 1


def test_conflicting_release_ids_are_not_silently_selected(case):
    _, _, _, make = case
    status = make([release(), release("v0.2.0rc34")]).check()
    assert status.status == "unavailable"
    assert status.latest is None and status.last_success_at is None

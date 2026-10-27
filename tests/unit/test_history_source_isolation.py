"""Quellenisolation mit temporaerer DuckDB, privatem Testprofil und Test-Vault."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
from nacl.signing import SigningKey
from pydantic import SecretStr
import pytest

from steuerreport_v2.contracts.connections import ConnectionCreate, ConnectionUpdate
from steuerreport_v2.contracts.connectors import PublicWalletAddressRequest
from steuerreport_v2.contracts.history import HistoryApprove, HistoryStart
from steuerreport_v2.contracts.review import ReviewTask, ReviewTaskSummary
from steuerreport_v2.contracts.workspace import ActivityQuery, WorkspaceReviewQuery
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.cex_balances import CexBalanceService
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.connectors import ConnectorService
from steuerreport_v2.domain.history import HistoryService
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryPage, HistoryRecord
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.secret_vault import KEY_FILE_ENV, is_encrypted_envelope
from steuerreport_v2.domain.secrets import upsert_secret
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.domain.workspace import ActivityService, WorkspaceService, source_ref
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


AT = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
FINANCIAL_TABLES = (
    "raw_import_batches", "raw_objects", "canonical_events", "balance_ledger",
    "tax_lines", "review_decisions",
)


def _address(seed):
    value = SigningKey(seed).verify_key.encode()
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number, result = int.from_bytes(value, "big"), ""
    while number:
        number, digit = divmod(number, 58)
        result = alphabet[digit] + result
    return "1" * (len(value) - len(value.lstrip(b"\0"))) + result


def _financial_state(store):
    with store.connect() as con:
        return {table: con.execute(f"select * from {table} order by all").fetchall()
                for table in FINANCIAL_TABLES}


def _source_report(sources):
    return "\n".join(f"{item.ref}: {item.label!r}, wallet={item.wallet_address!r}, "
                     f"connection={item.connection_id!r}, events={item.events_count}, imports={item.imports_count}"
                     for item in sources)


@pytest.fixture
def isolated_sources(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="ascii")
    registry = tmp_path / "source_registry.json"
    registry.write_text(json.dumps({"registry_version": "isolation-test", "entries": [],
                                   "ledger_adjustments": [], "transfer_evidence": []}), encoding="ascii")
    key = tmp_path / "synthetic-vault.key"
    key.write_bytes(bytes(range(32)))
    key.chmod(0o600)
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv(KEY_FILE_ENV, str(key))
    monkeypatch.setenv("STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS", "1")
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", "")
    monkeypatch.setattr(PortfolioService, "KNOWN_JUP_WALLET", "")
    monkeypatch.setattr(PortfolioService, "SOURCE_REGISTRY_CONFIG_PATH", registry)
    monkeypatch.setattr(SourceRegistryService, "DEFAULT_CONFIG_PATH", registry)
    monkeypatch.setattr(HistoryService, "_launch", lambda *_args: None)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Quellenisolation darf keine externen Abrufe starten")
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(CexBalanceService, "_get_json", forbidden)
    monkeypatch.setattr(PortfolioService, "_live_solana_wallet_balances", forbidden)
    monkeypatch.setattr(ConnectionService, "_launch", forbidden)

    store = DuckDbStore(tmp_path / "isolation.duckdb")
    wallets = (_address(bytes(range(32))), _address(bytes(range(32, 64))))
    for wallet in wallets:
        ConnectorService(store).save_public_wallet(PublicWalletAddressRequest(
            wallet_address=wallet, display_label="Gleicher Wallet-Anzeigename"))
    connections = tuple(ConnectionService(store).create(ConnectionCreate(
        provider="binance", label="Gleicher CEX-Anzeigename", account="Gleicher frei editierbarer Alias",
        budget_group="budget:isolation", api_key=SecretStr(f"synthetic-key-{marker}"),
        api_secret=SecretStr(f"synthetic-secret-{marker}"),
    )) for marker in ("a", "b"))
    accounts = (*wallets, *("connection:" + str(item.id) for item in connections))
    refs = tuple(source_ref("wallet:" + account) if index < 2 else source_ref(account)
                 for index, account in enumerate(accounts))
    return SimpleNamespace(store=store, wallets=wallets, connections=connections, accounts=accounts,
                           refs=refs, history=HistoryService(store), workspace=WorkspaceService(store))


def _cex_row(account, identity, *, amount="0", kind="unknown"):
    row = {"utc time": AT.isoformat(), "coin": "EUR", "change": amount,
           "operation": kind, "account": account, "id": identity}
    if kind == "unknown":
        row["history_classification_required"] = "1"
    return row


def _seed(env, index, count=1, *, amount=None):
    account = env.accounts[index]
    source = "solana_rpc" if index < 2 else "binance"
    rows = []
    for number in range(count):
        identity = f"seed-{index}-{number}"
        if index < 2:
            rows.append({"timestamp_utc": AT.isoformat(), "asset": "EUR", "quantity": "0",
                         "event_type": "unknown", "wallet_address": account, "tx_id": identity,
                         "history_classification_required": "1"})
        else:
            rows.append(_cex_row(account, identity, amount=amount if number == 0 and amount else "0",
                                 kind="deposit" if number == 0 and amount else "unknown"))
    batch = CsvRawImporter(env.store).import_rows(source, f"seed-{index}.json",
        hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(), rows)
    events = RawNormalizer(env.store).normalize_batch(batch.batch_id)
    assert len(events) == count
    BalanceLedgerBuilder(env.store).rebuild()
    return events


def _request():
    return HistoryStart(request_id=uuid4(), confirm_external_request=True,
                        start="2025-01-01", end="2025-01-02", symbols=["BTCEUR"])


def _approval(job):
    return HistoryApprove(preview_sha256=job.preview_sha256, actor="Isolierter Testreviewer",
                          confirm_import=True, confirm_recalculation=True)


class _Collector:
    def __init__(self, store, target, observed, *, raw_only=False):
        self.store, self.target, self.observed, self.raw_only = store, target, observed, raw_only

    def fetch_page(self, cursor, check):
        check()
        assert cursor == {}
        target = self.target
        credentials = None if target.provider == "solana" else CexBalanceService(
            self.store, connection_id=target.connection_id)._credentials(target.provider)
        self.observed.append((target, credentials))
        if self.raw_only:
            source = "solana_rpc" if target.provider == "solana" else target.provider
            raw = {"transaction" if target.provider == "solana" else "payload": {"id": "shared-raw-id"}}
            records = [HistoryRecord("shared-raw-id", source, [], raw)]
        else:
            records = [HistoryRecord(identity, "binance", [_cex_row(
                target.account, identity, amount=amount, kind=kind)],
                {"payload": {"id": identity, "coin": "EUR", "amount": amount}})
                for identity, amount, kind in (("shared-deposit-id", "10", "deposit"),
                                               ("shared-withdrawal-id", "0", "unknown"))]
        return HistoryPage(records, {"page": 1}, True, requests=1,
                           notes=("Synthetische begrenzte Provider-Abdeckung.",))


def _collect(env, monkeypatch, ref, *, raw_only=False):
    observed = []
    monkeypatch.setattr(HistoryService, "_collector", lambda service, target, _options:
                        _Collector(service.store, target, observed, raw_only=raw_only))
    service = HistoryService(DuckDbStore(env.store.path))
    request = _request()
    if ref in env.refs[:2]:
        request = request.model_copy(update={"symbols": []})
    job = service.start(ref, request)
    service._run(str(job.id))
    job = service.get(ref, str(job.id))
    assert job.status == "ready", service.storage.load(str(job.id)).get("error_code")
    return service, job, observed


@pytest.mark.parametrize("with_legacy", [False, True], ids=["individual-only", "legacy-also-present"])
def test_wallets_and_cex_accounts_keep_exact_stable_refs_and_private_credentials(isolated_sources, with_legacy):
    env = isolated_sources
    if with_legacy:
        # Vorhandene globale Test-Credentials duerfen die Einzelkonten nicht ersetzen.
        upsert_secret(env.store, "secret.cex.binance.api_key", "synthetic-legacy-key")
        upsert_secret(env.store, "secret.cex.binance.api_secret", "synthetic-legacy-secret")
    financial = _financial_state(env.store)
    settings = env.store.list_admin_settings()
    sources = env.workspace.sources()
    exact = [item for item in sources.sources if item.wallet_address or item.connection_id]
    assert {item.ref for item in exact} == set(env.refs), _source_report(sources.sources)
    assert len(exact) == 4 and sources.events_count == 0
    assert all(item.events_count == item.imports_count == 0 for item in sources.sources)
    assert {item.wallet_address for item in sources.sources if item.wallet_address} == set(env.wallets)
    assert {item.connection_id for item in sources.sources if item.connection_id} == {str(c.id) for c in env.connections}
    assert all(item.connection_status == "configured" and not item.can_sync
               for item in exact if item.connection_id)
    for index, ref in enumerate(env.refs):
        target = env.history._target(ref)
        assert target.account == env.accounts[index]
        assert target.source_ref == ref and not target.legacy_credentials
        assert env.history.capability(ref).ready
        if index < 2:
            assert target.wallet_address == env.wallets[index] and target.connection_id is None
        else:
            assert target.connection_id == str(env.connections[index - 2].id)
            marker = "a" if index == 2 else "b"
            assert CexBalanceService(env.store, connection_id=target.connection_id)._credentials("binance") == (
                f"synthetic-key-{marker}", f"synthetic-secret-{marker}", "")
    assert _financial_state(env.store) == financial
    assert env.store.list_admin_settings() == settings
    encoded = sources.model_dump_json() + env.history.view(env.refs[2]).model_dump_json()
    assert "synthetic-key" not in encoded and "synthetic-secret" not in encoded
    secrets = [item for item in settings if item.key.startswith("secret.")]
    assert secrets and all(is_encrypted_envelope(item.value_json) for item in secrets)

    connection = env.connections[0]
    ConnectionService(env.store).update(connection.id, ConnectionUpdate(label="Umbenannt", account="Anderer Alias"))
    ConnectorService(env.store).save_public_wallet(PublicWalletAddressRequest(
        wallet_address=env.wallets[0], display_label="Nicht als neue Wallet anlegen"))
    restarted = WorkspaceService(DuckDbStore(env.store.path))
    assert HistoryService(restarted.store)._target(env.refs[2]).account == env.accounts[2]
    reloaded = restarted.sources().sources
    assert {item.ref for item in reloaded} == set(env.refs), _source_report(reloaded)


def test_event_import_and_activity_counts_remain_per_exact_source(isolated_sources):
    env = isolated_sources
    events = [_seed(env, index, index + 1) for index in range(4)]
    before = _financial_state(env.store)
    sources = env.workspace.sources()
    assert {item.ref for item in sources.sources} == set(env.refs), _source_report(sources.sources)
    assert sources.events_count == sum(item.events_count for item in sources.sources) == 10
    for index, ref in enumerate(env.refs):
        item = next(item for item in sources.sources if item.ref == ref)
        assert item.events_count == index + 1
        assert item.imports_count == 1
        page = ActivityService(env.store).query(ActivityQuery(source_ref=ref, page_size=100))
        assert page.total == index + 1
        assert {row.event.event_id for row in page.rows} == {event.event_id for event in events[index]}
        assert {row.event.account for row in page.rows} == {env.accounts[index]}
        detail = env.workspace.source(ref)
        for task in detail.review_tasks:
            if task.event_ids:
                assert set(task.event_ids) <= {event.event_id for event in events[index]}
                assert task.candidate_source_refs == [ref] and task.context_status == "matched"
    assert _financial_state(env.store) == before


def _task(identity, *, source="review_gate", scope="unresolved", evidence=()):
    return ReviewTask(task_id=identity, priority="high", category="evidence", title="Gleicher Anzeigename",
                      detail="Keine Zuordnung aus Freitext ableiten", source=source, scope=scope,
                      evidence_refs=list(evidence), asset="EUR", blocks_export=True, action_label="Pruefen")


def test_review_account_event_and_raw_identity_mapping_never_falls_back_to_provider(isolated_sources, monkeypatch):
    env = isolated_sources
    events = [_seed(env, index)[0] for index in range(4)]
    tasks = [
        _task("wallet-a", scope=f"account:{env.accounts[0]}:asset:EUR"),
        _task("wallet-b", scope="event:" + events[1].event_id),
        _task("cex-a", source="binance", scope=f"account:{env.accounts[2]}:asset:EUR"),
        _task("cex-b", source="binance", evidence=(events[3].raw_object_id,)),
        _task("both-cex", source="binance", scope="event:" + events[2].event_id,
              evidence=("event:" + events[3].event_id,)),
        _task("unknown-account", source="binance", scope="account:not-owned:asset:EUR"),
        _task("prose-only").model_copy(update={"detail": env.wallets[0] + " Gleicher CEX-Anzeigename"}),
    ]
    summary = ReviewTaskSummary(generated_at=AT, open_tasks=len(tasks), blocking_tasks=len(tasks),
        high_priority_tasks=len(tasks), medium_priority_tasks=0, low_priority_tasks=0,
        fifo_relevant_tasks=0, evidence_tasks=len(tasks), tasks=tasks, methodology="Synthetischer Aufgabeneingang")
    monkeypatch.setattr(ReviewService, "tasks", lambda *_args, **_kwargs: deepcopy(summary))
    before = _financial_state(env.store)
    mapped = {item.task.task_id: item for item in env.workspace._review_items(tasks, env.workspace.source_scopes())}
    for identity, ref in zip(("wallet-a", "wallet-b", "cex-a", "cex-b"), env.refs):
        assert mapped[identity].source_ref == ref
        assert mapped[identity].candidate_source_refs == [ref] and mapped[identity].context_status == "matched"
    assert mapped["both-cex"].source_ref is None
    assert mapped["both-cex"].context_status == "ambiguous"
    assert set(mapped["both-cex"].candidate_source_refs) == set(env.refs[2:])
    for identity in ("unknown-account", "prose-only"):
        assert mapped[identity].source_ref is None and mapped[identity].candidate_source_refs == []
        assert mapped[identity].context_status == "unresolved"
    sources = {item.ref: item for item in env.workspace.sources().sources}
    for index, ref in enumerate(env.refs):
        expected = {("wallet-a", "wallet-b", "cex-a", "cex-b")[index]}
        if index >= 2:
            expected.add("both-cex")
        detail = env.workspace.source(ref)
        assert {item.task.task_id for item in detail.review_tasks} == expected
        assert sources[ref].review_tasks_count == 1
        assert sources[ref].blocking_review_tasks_count == len(expected)
        assert sources[ref].ambiguous_review_tasks_count == (1 if index >= 2 else 0)
        page = env.workspace.review_page(WorkspaceReviewQuery(source_ref=ref))
        assert {item.task.task_id for item in page.items} == expected
    assert _financial_state(env.store) == before


def test_real_job_preview_approve_on_connection_a_leaves_b_and_wallets_untouched(isolated_sources, monkeypatch):
    env = isolated_sources
    for index in (0, 1):
        _seed(env, index)
    _seed(env, 3, count=2, amount="20")
    account_a, account_b = env.accounts[2:]
    before = _financial_state(env.store)
    b_connection = ConnectionService(env.store).list().connections[1]
    b_detail = env.workspace.source(env.refs[3]).model_dump()
    service, job, observed = _collect(env, monkeypatch, env.refs[2])
    assert job.new_records == job.records_fetched == 2 and job.imported_events == 0
    assert _financial_state(env.store) == before
    assert job.preview_sha256 and job.before_summary is not None and job.after_summary is not None
    assert service.storage.load(str(job.id))["_preview"]["imported_events"] == 2
    target, credentials = observed[0]
    assert target.account == account_a == "connection:" + str(env.connections[0].id)
    assert credentials == ("synthetic-key-a", "synthetic-secret-a", "")
    originals = service.storage.records(service.storage.load(str(job.id)))
    assert {row["account"] for record in originals for row in record.rows} == {account_a}
    assert not service.view(env.refs[3]).jobs
    for foreign_ref in (env.refs[0], env.refs[3]):
        for action in (
            lambda: service.get(foreign_ref, str(job.id)), lambda: service.audit(foreign_ref, str(job.id)),
            lambda: service.control(foreign_ref, str(job.id), "cancel"),
            lambda: service.approve(foreign_ref, str(job.id), _approval(job)),
        ):
            with pytest.raises(HistoryFetchError, match="history_job_not_found"):
                action()
    assert _financial_state(env.store) == before
    result = service.approve(env.refs[2], str(job.id), _approval(job))
    assert result.status == "succeeded" and result.imported_events == 2
    assert not result.complete_history_proven
    after = _financial_state(env.store)
    for table in ("raw_import_batches", "raw_objects", "canonical_events"):
        assert set(before[table]) <= set(after[table])
    events = env.store.list_canonical_events()
    own = [event for event in events if event.account == account_a]
    assert len(own) == 2 and {event.event_type for event in own} == {"transfer", "unknown"}
    with env.store.connect() as con:
        assert con.execute("select account, sum(delta_quantity) from balance_ledger where account in (?, ?) group by account order by account",
                           [account_a, account_b]).fetchall() == sorted([(account_a, 10), (account_b, 20)])
        raw_accounts = con.execute("select distinct json_extract_string(payload_json, '$.account') from raw_objects where json_extract_string(payload_json, '$.history_source_ref')=?",
                                   [env.refs[2]]).fetchall()
        assert raw_accounts == [(account_a,)]
    assert ConnectionService(env.store).list().connections[1] == b_connection
    assert env.workspace.source(env.refs[3]).model_dump() == b_detail
    assert not service.view(env.refs[3]).jobs
    sources = {item.ref: item for item in env.workspace.sources().sources}
    assert set(sources) == set(env.refs), _source_report(sources.values())
    assert sources[env.refs[2]].events_count == sources[env.refs[3]].events_count == 2
    assert sources[env.refs[2]].imports_count == sources[env.refs[3]].imports_count == 1
    unknown = next(event for event in own if event.event_type == "unknown")
    mapped = [task for task in env.workspace.source(env.refs[2]).review_tasks
              if unknown.event_id in task.event_ids]
    assert mapped and all(task.candidate_source_refs == [env.refs[2]] for task in mapped)
    assert all(unknown.event_id not in task.event_ids for task in env.workspace.source(env.refs[3]).review_tasks)


def test_identical_provider_record_ids_do_not_deduplicate_another_connection(isolated_sources, monkeypatch):
    env = isolated_sources
    for index, marker in ((2, "a"), (3, "b")):
        service, job, observed = _collect(env, monkeypatch, env.refs[index])
        assert job.new_records == 2 and job.duplicate_records == 0
        assert observed[0][1] == (f"synthetic-key-{marker}", f"synthetic-secret-{marker}", "")
        assert service.approve(env.refs[index], str(job.id), _approval(job)).imported_events == 2
    with env.store.connect() as con:
        assert con.execute("select account, count(*) from canonical_events group by account order by account").fetchall() == sorted([
            (env.accounts[2], 2), (env.accounts[3], 2)])
        assert con.execute("select count(distinct json_extract_string(payload_json, '$.history_scope_identity')) from raw_objects").fetchone()[0] == 4
    before = _financial_state(env.store)
    service, repeated, _ = _collect(env, monkeypatch, env.refs[2])
    assert repeated.new_records == 0 and repeated.duplicate_records == 2
    service.approve(env.refs[2], str(repeated.id), _approval(repeated))
    after = _financial_state(env.store)
    for table in ("raw_import_batches", "raw_objects", "canonical_events", "balance_ledger", "tax_lines"):
        assert after[table] == before[table]


@pytest.mark.parametrize("index", [0, 2], ids=["wallet", "cex-connection"])
def test_raw_only_approved_import_belongs_to_selected_source_without_broad_duplicate(isolated_sources, monkeypatch, index):
    env = isolated_sources
    service, job, _ = _collect(env, monkeypatch, env.refs[index], raw_only=True)
    assert job.new_records == 1
    assert service.approve(env.refs[index], str(job.id), _approval(job)).imported_events == 0
    assert not env.store.list_canonical_events()
    with env.store.connect() as con:
        assert con.execute("select json_extract_string(payload_json, '$.account') from raw_objects").fetchall() == [(env.accounts[index],)]
    scopes = {item.ref: item for item in env.workspace.sources().sources}
    assert scopes[env.refs[index]].imports_count == 1, {
        ref: {"imports": item.imports_count, "wallet": item.wallet_address, "connection": item.connection_id}
        for ref, item in scopes.items()
    }
    assert set(scopes) == set(env.refs), "Rohbelege duerfen keine zusaetzliche breite Provider-Quelle erzeugen"
    assert all(item.events_count == 0 for item in scopes.values())
    assert all(item.imports_count == 0 for ref, item in scopes.items() if ref != env.refs[index])

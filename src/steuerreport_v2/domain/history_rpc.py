"""Explizite RPC-Bindung und rein lokale, geheimnisfreie Abrufmetadaten.

Der Aufrufer haelt ResolvedRpc fuer den gesamten Abruf fest. Weder Aufloesung
noch Status starten Requests oder aendern Quoten, Keys oder Limiterzustand.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
import time
from typing import Literal
from urllib.parse import quote, urlencode, urlsplit

from steuerreport_v2.contracts.history import HistoryRateState, HistoryRpcOption
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.history_types import HistoryFetchError
from steuerreport_v2.domain.request_limits import LimiterUnavailable, RequestLimiter
from steuerreport_v2.domain.secret_vault import (
    ENVELOPE_TYPE, ENVELOPE_VERSION, decode_secret_setting, load_vault_key, vault_key_id,
)
from steuerreport_v2.paths import PROJECT_ROOT
from steuerreport_v2.private_settings import private_profile_path, private_state_root


PUBLIC_RPC_URL = "https://api.mainnet.solana.com"
TRANSACTION_ENDPOINT = "rpc_gettransaction"
CHOICES = ("public", "helius", "alchemy", "custom")
_LABELS = {
    "public": "Solana Public RPC (ohne Key)",
    "helius": "Helius (eigener Key, Tarif nicht verifiziert)",
    "alchemy": "Alchemy (eigener Key, Tarif nicht verifiziert)",
    "custom": "Eigener RPC (Tarif nicht verifiziert)",
}
_KEYS = {"helius": "secret.helius.api_key", "alchemy": "secret.alchemy.api_key"}


@dataclass(frozen=True)
class ResolvedRpc:
    url: str = field(repr=False)
    provider_id: str
    label: str
    kind: Literal["public", "configured"]
    binding_hash: str = field(repr=False)


def _choice(choice: str) -> None:
    if choice not in CHOICES:
        raise HistoryFetchError("history_rpc_choice_invalid", resumable=False)


def _custom_url() -> str:
    value = _profile_rpc_url().strip()
    return value or os.environ.get("SOLANA_RPC_URL", "").strip()


def _profile_rpc_url() -> str:
    # private_value cached das Profil. Eine Bindungspruefung muss Aenderungen
    # sofort sehen, ohne den globalen Cache anderer Dienste zu invalidieren.
    if "STEUERREPORT_SOLANA_RPC_URL" in os.environ:
        return os.environ["STEUERREPORT_SOLANA_RPC_URL"]
    path = private_profile_path()
    if path is None:
        return ""
    if not path.exists() and "STEUERREPORT_PRIVATE_PROFILE" not in os.environ:
        return ""
    profile = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(profile, dict) or not all(isinstance(key, str) and isinstance(value, str)
                                              for key, value in profile.items()):
        raise HistoryFetchError("history_rpc_profile_unavailable", resumable=False)
    return profile.get("solana_rpc_url", "")


def _classify_url(value: str) -> tuple[str, str, Literal["public", "configured"]]:
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"https", "http"} and parsed.hostname
            and not parsed.username and not parsed.password and not parsed.fragment
            and not any(char.isspace() or ord(char) < 32 for char in value)
            and "," not in value and "\\" not in value
        )
        port = parsed.port
        host = (parsed.hostname or "").lower()
    except ValueError:
        valid = False
    if not valid:
        raise HistoryFetchError("history_rpc_url_invalid", resumable=False) from None
    # Nur bekannte Hosts, nie Schluesselwoerter im Pfad oder eine fremde Domain.
    if host in {"api.mainnet.solana.com", "api.mainnet-beta.solana.com"} and port in {None, 443, 80}:
        return "solana_rpc", _LABELS["public"], "public"
    if host in {"solana-rpc.publicnode.com", "solana.publicnode.dev"} and port in {None, 443, 80}:
        return "solana_rpc", "Oeffentlicher Solana-RPC (Tarif nicht verifiziert)", "public"
    for suffix, provider in (
        ("helius-rpc.com", "helius"), ("helius.xyz", "helius"), ("helius.dev", "helius"),
        ("alchemy.com", "alchemy"), ("alchemyapi.io", "alchemy"),
    ):
        if host == suffix or host.endswith("." + suffix):
            return provider, _LABELS[provider], "configured"
    return "solana_custom_rpc", _LABELS["custom"], "configured"


def _secret_json(store: DuckDbStore, key: str) -> str | None:
    with store.connect() as con:
        row = con.execute("select value_json from admin_settings where key = ?", [key]).fetchone()
    return row[0] if row is not None else None


def resolve_rpc(store: DuckDbStore, choice: str) -> ResolvedRpc:
    """Genau EINEN Endpunkt aufloesen; None bleibt Sache des Legacy-Aufrufers."""
    _choice(choice)
    if choice == "public":
        url = PUBLIC_RPC_URL
    elif choice == "custom":
        try:
            url = _custom_url()
        except Exception:
            raise HistoryFetchError("history_rpc_profile_unavailable", resumable=False) from None
        if not url:
            raise HistoryFetchError("history_rpc_url_missing", resumable=False)
    else:
        try:
            setting_key = _KEYS[choice]
            value_json = _secret_json(store, setting_key)
            key = decode_secret_setting(setting_key, value_json) if value_json is not None else ""
        except Exception:
            raise HistoryFetchError("history_rpc_key_unavailable", resumable=False) from None
        if not key and choice == "alchemy":
            key = _alchemy_env_key()
        if not key:
            raise HistoryFetchError("history_rpc_key_missing", resumable=False)
        url = (
            "https://mainnet.helius-rpc.com/?" + urlencode({"api-key": key})
            if choice == "helius" else
            "https://solana-mainnet.g.alchemy.com/v2/" + quote(key, safe="")
        )
    provider_id, label, kind = _classify_url(url)
    binding = hashlib.sha256(f"{choice}\0{provider_id}\0{url}".encode("utf-8")).hexdigest()
    return ResolvedRpc(url=url, provider_id=provider_id, label=label, kind=kind, binding_hash=binding)


def _alchemy_env_key() -> str:
    return next((os.environ[name].strip() for name in ("ALCHEMY_API_KEY", "ALCHEMY_SOLANA_API_KEY")
                 if os.environ.get(name, "").strip()), "")


def _key_metadata(store: DuckDbStore, choice: str) -> tuple[bool, bool, str | None]:
    """Nur Vorhandensein/Envelope-Metadaten, kein Entschluesseln oder Probeaufruf."""
    configured = False
    try:
        value_json = _secret_json(store, _KEYS[choice])
        configured = value_json is not None and bool(value_json.strip())
        try:
            value = json.loads(value_json) if value_json is not None else None
        except json.JSONDecodeError:
            # Derselbe leere-Key-Fall wie im bestehenden Alchemy-Keypfad.
            value = None
        if isinstance(value, str):
            present = bool(value.strip())
            if not present and choice == "alchemy":
                present = bool(_alchemy_env_key())
            return present, present, None if present else "history_rpc_key_missing"
        if value is None:
            present = bool(_alchemy_env_key()) if choice == "alchemy" else False
            return present, present, None if present else "history_rpc_key_missing"
        if isinstance(value, dict) and value.get("type") == ENVELOPE_TYPE:
            key = load_vault_key()
            ready = (
                value.get("version") == ENVELOPE_VERSION and key is not None
                and value.get("key_id") == vault_key_id(key)
                and bool(value.get("nonce")) and bool(value.get("ciphertext"))
            )
            return True, ready, None if ready else "history_rpc_key_unavailable"
        return True, False, "history_rpc_key_unavailable"
    except Exception:
        return configured, False, "history_rpc_key_unavailable"


def _option(store: DuckDbStore, choice: str) -> dict:
    _choice(choice)
    option = HistoryRpcOption(
        id=choice, label=_LABELS[choice], kind="public" if choice == "public" else "configured",
        provider_id="solana_rpc" if choice == "public" else choice,
    )
    if choice == "public":
        option.configured = option.ready = True
    elif choice == "custom":
        option.provider_id = "solana_custom_rpc"
        try:
            value = _custom_url()
            option.configured = bool(value)
            if value:
                option.provider_id, option.label, option.kind = _classify_url(value)
                option.ready = True
            else:
                option.blocked_reason = "history_rpc_url_missing"
        except HistoryFetchError as exc:
            option.blocked_reason = exc.code
        except Exception:
            option.blocked_reason = "history_rpc_profile_unavailable"
    else:
        option.configured, option.ready, option.blocked_reason = _key_metadata(store, choice)
    return option.model_dump()


def rpc_options(store: DuckDbStore) -> list[dict]:
    """Metadaten fuer GET: keine Keys entschluesseln, keine Limiteranlage."""
    return [_option(store, choice) for choice in CHOICES]


class _ReadOnlyLimiter(RequestLimiter):
    """Bestehende Limiterberechnung auf einem gesperrt gelesenen Snapshot."""

    def __init__(self):
        self._clock = time.time

    def _save(self, *args, **kwargs):
        raise LimiterUnavailable("history_rpc_limits_unavailable")

    @contextmanager
    def _locked(self, **kwargs):
        yield self.document


def _limiter_snapshot() -> _ReadOnlyLimiter:
    limiter = _ReadOnlyLimiter()
    root = private_state_root().resolve()
    if root.is_relative_to(PROJECT_ROOT.resolve()):
        raise LimiterUnavailable("history_rpc_limits_unavailable")
    directory = root / "request_limits"
    limiter._check_private(directory.lstat(), directory=True)
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        lock_fd = os.open("coordinator.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
        try:
            limiter._check_private(os.fstat(lock_fd))
            fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            if (not os.fstat(lock_fd).st_size or
                os.stat("coordinator.lock", dir_fd=directory_fd, follow_symlinks=False).st_ino != os.fstat(lock_fd).st_ino):
                raise LimiterUnavailable("history_rpc_limits_unavailable")
            # _load validiert auch Buchungen und defekten Zustand. _save ist
            # gesperrt: fehlender Zustand darf hier niemals initialisiert werden.
            limiter.document = limiter._load(directory_fd, lock_fd)
        finally:
            os.close(lock_fd)
    finally:
        os.close(directory_fd)
    return limiter


def _rate_state(provider_id: str) -> dict:
    try:
        limiter = _limiter_snapshot()
        document = limiter.document
        config = document.config
        groups = limiter._groups(provider_id, None, config, endpoint=TRANSACTION_ENDPOINT)
        profile = limiter.profile(provider_id, endpoint=TRANSACTION_ENDPOINT)
        now = limiter._now(document)
        buckets = limiter._buckets(document, groups, now)
        costs = config.endpoint_costs.get(provider_id, {})
        cost = costs.get(TRANSACTION_ENDPOINT, costs.get("default", 1))
        group_rates, delays, blocking = {}, {}, set()
        impossible = set()
        for group in groups:
            local = limiter._profile(group, config)
            rates = [float(local.requests_per_second), local.requests_per_minute / 60]
            if local.requests_per_10_seconds is not None:
                rates.append(local.requests_per_10_seconds / 10)
            if local.weighted_cost_per_minute is not None:
                rates.append(local.weighted_cost_per_minute / cost / 60)
                if cost > local.weighted_cost_per_minute:
                    impossible.add(group)
            group_rates[group] = min(rates)
            active = sum(group in item.groups for item in document.active.values())
            delay, reasons = limiter._wait(buckets[group], local, active, cost, now)
            delays[group] = delay
            blocking.update(reasons)
        if impossible:
            blocking.add("request_cost_exceeds_group_capacity")
        rate = min(group_rates.values())
        delay = max(delays.values())
        bottlenecks = sorted(impossible | {group for group in groups if group_rates[group] == rate
                                          or (delay > 0 and delays[group] == delay)})
        return HistoryRateState(
            available=True, config_revision=config.revision,
            requests_per_second=profile.requests_per_second,
            requests_per_10_seconds=profile.requests_per_10_seconds,
            requests_per_minute=profile.requests_per_minute,
            max_concurrency=profile.max_concurrency,
            effective_max_requests_per_second=None if impossible else rate, budget_groups=groups,
            bottlenecks=bottlenecks, blocking_reasons=sorted(blocking),
            waiting_requests=sum(bool(set(groups).intersection(item.groups)) and item.expires_at > now
                                 for item in document.waiters.values()),
            in_flight=sum(bool(set(groups).intersection(item.groups)) for item in document.active.values()),
            wait_seconds=delay if math.isfinite(delay) and not impossible else None,
            retry_at=datetime.fromtimestamp(now + delay, timezone.utc)
            if delay > 0 and math.isfinite(delay) and not impossible else None,
        ).model_dump()
    except Exception:
        return HistoryRateState(blocking_reasons=["history_rpc_limits_unavailable"]).model_dump()


def rpc_status(store: DuckDbStore, choice: str | None = None, *, provider_id: str | None = None) -> dict:
    """RateState fuer die eingefrorene Provider-ID, unabhaengig von neuen Keys/URLs.

    Ohne Provider-ID wird nur die Auswahl klassifiziert, niemals entschluesselt.
    Legacy ohne eingefrorene Bindung hat kein ehrlich bestimmbares Einzelprofil.
    """
    if provider_id is None:
        if choice is None or choice == "legacy":
            return HistoryRateState().model_dump()
        _choice(choice)
        if choice == "custom":
            option = _option(store, choice)
            if not option["ready"]:
                return HistoryRateState(blocking_reasons=[option["blocked_reason"]]).model_dump()
            provider_id = option["provider_id"]
        else:
            provider_id = "solana_rpc" if choice == "public" else choice
    if provider_id not in {"solana_rpc", "helius", "alchemy", "solana_custom_rpc"}:
        return HistoryRateState(blocking_reasons=["history_rpc_provider_invalid"]).model_dump()
    return _rate_state(provider_id)

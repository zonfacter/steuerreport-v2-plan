"""Persistenter, host-lokaler Abruf-Limiter ohne Netzwerk-/Datenbankzugriff.

Alle Teilnehmer muessen dasselbe private Verzeichnis auf einem Dateisystem
mit verlaesslichem flock/replace/fsync verwenden. Kein verteilter/NFS-Limiter.
Konfiguration UND Reservierungen stehen in einem atomar ersetzten JSON-Dokument.
Die Sperrdatei darf im Betrieb niemals geloescht/ersetzt werden.

acquire reserviert vor dem Requeststart. Unmittelbar vor dem HTTP-Aufruf
Lease.start(prepare=signer) aufrufen: Signierung ausserhalb der Dateisperre,
danach atomare erneute Pruefung und Umbuchung auf den Dispatchzeitpunkt.
Lease fuer genau EINEN Aufruf verwenden, Timeout im HTTP-Adapter durchsetzen, erst nach dessen Ende
freigeben. Auch Retries, Folgeseiten und Metadatenaufrufe erneut acquire'n.
Ein Absturz hinterlaesst absichtlich eine blockierende aktive Lease: automatische
TTL-Freigabe koennte einen noch laufenden Request doppelt zaehlen. Administrative
Wiederherstellung erst nach gesichertem Ende aller alten Worker/HTTP-Aufrufe.

Die Deadline ist absolute monotonic()-Zeit, persistierte Fenster/Pausen nutzen
UTC-Epochensekunden. Rueckwaerts springende Wanduhr friert Fenster konservativ
ein. Eine verlaessliche Hostuhr ist erforderlich. Keine Fairness/FIFO-Garantie.
Dieses Modul startet weder Scheduler noch HTTP, erzwingt keine Transporttimeouts
und kennt keine Herstellergewichte, Auth-Fehler oder Retry-After-Headersemantik.
Provider-Ceilings sind deklarierte Betreiberangaben mit Pflichtreferenz, keine
unabhaengige Vertragspruefung. Sie zaehlen konservativ pro gesamtem Provider,
nicht separat pro Konto/Key, und nur die hier modellierten rollierenden 1s/60s-
Dimensionen. 10s-CU, Tages-/Monatsbudgets und fremde Anwendungen am selben
IP-/Providerbudget benoetigen eigene Koordination; observe ist nur Telemetrie.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import random as random_module
import stat
from threading import Event
import time
from typing import Callable, Iterator
from uuid import uuid4

from pydantic import Field, TypeAdapter

from steuerreport_v2.contracts.request_limits import (
    GroupId, LimitContract, ProviderId, ProviderObservation, RequestLimitGroupStatus,
    RequestLimitProfile, RequestLimitsConfig, RequestLimitsStatus,
)
from steuerreport_v2.paths import PROJECT_ROOT
from steuerreport_v2.private_settings import private_state_root


class RequestLimitError(RuntimeError):
    """Fehlertexte enthalten keine Eingaben, Zugangsdaten oder Dateiinhalte."""


class LimiterUnavailable(RequestLimitError):
    pass


class RevisionConflict(RequestLimitError):
    pass


class RequestCancelled(RequestLimitError):
    pass


class RequestDeadlineExceeded(RequestLimitError):
    pass


class RequestCostExceeded(RequestLimitError):
    pass


class RetryNotAllowed(RequestLimitError):
    pass


class _Start(LimitContract):
    at: float = Field(ge=0)
    cost: int = Field(ge=1)
    reservation_id: str | None = None


class _Bucket(LimitContract):
    tokens: float = Field(ge=0)
    updated_at: float = Field(ge=0)
    rate: int = Field(ge=1)
    capacity: int = Field(ge=1)
    starts: list[_Start]
    paused_until: float = Field(ge=0)


class _Active(LimitContract):
    groups: list[GroupId] = Field(min_length=2)
    started_at: float = Field(ge=0)
    timeout_seconds: float = Field(gt=0)


class _Waiter(LimitContract):
    groups: list[GroupId]
    expires_at: float = Field(ge=0)


class _Document(LimitContract):
    config: RequestLimitsConfig
    last_seen_at: float = Field(ge=0)
    buckets: dict[GroupId, _Bucket]
    active: dict[str, _Active]
    waiters: dict[str, _Waiter]
    observations: dict[ProviderId, ProviderObservation] = Field(default_factory=dict, max_length=1000)


@dataclass
class Lease:
    """Reservierte Parallelitaet; Freigabe erst nach beendetem HTTP-Aufruf.

timeout_seconds an den Transport weiterreichen. Keine automatische Freigabe
bei Timeout/Prozesstod; __exit__/release muessen nach Transportende stattfinden.
"""

    limiter: RequestLimiter
    lease_id: str
    groups: tuple[str, ...]
    timeout_seconds: float
    deadline: float
    provider: str = ""
    cost: int = 1
    cancel: Event | None = None
    acquired_at: float = 0.0
    _released: bool = False
    _entered: bool = False
    _started: bool = False
    _dispatching: bool = False

    def __enter__(self) -> Lease:
        if self._released or self._entered:
            raise RequestLimitError("lease_not_reusable")
        if self.limiter._monotonic() >= self.deadline:
            self.release()
            raise RequestDeadlineExceeded("request_deadline_exceeded")
        self._entered = True
        self.timeout_seconds = min(self.timeout_seconds, self.deadline - self.limiter._monotonic())
        return self

    def __exit__(self, *_exc) -> None:
        self.release()

    def start(self, prepare: Callable[[], None] | None = None) -> None:
        """Genau einen HTTP-Start erlauben; prepare kann bei Konkurrenz erneut laufen.

        Kein Callback und kein Warten unter flock. Nach Rueckkehr unmittelbar
        den Transport starten; keine weitere blockierende Vorbereitung einfuegen.
        Bei Fehlern bleibt release/__exit__ fuer die Parallelitaet erforderlich.
        """
        if self._released or self._started or self._dispatching:
            raise RequestLimitError("lease_not_reusable")
        self._dispatching = True
        try:
            self.limiter._dispatch(self, prepare)
            self._started = True
        finally:
            self._dispatching = False

    def release(self) -> None:
        if not self._released:
            self.limiter._release(self.lease_id)
            self._released = True


class RequestLimiter:
    def __init__(
        self, *, state_root: Path | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        random: Callable[[], float] = random_module.random,
    ):
        self._clock, self._monotonic, self._sleep, self._random = clock, monotonic, sleep, random
        root = Path(state_root) if state_root is not None else private_state_root()
        try:
            root = root.expanduser().resolve()
            if root.is_relative_to(PROJECT_ROOT.resolve()):
                raise LimiterUnavailable("limiter_state_must_be_outside_software")
            missing = []
            candidate = root / "request_limits"
            while not candidate.exists():
                missing.append(candidate)
                candidate = candidate.parent
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            root_info = root.stat()
            if root_info.st_uid != os.geteuid() or root_info.st_mode & 0o022:
                raise LimiterUnavailable("limiter_private_root_must_not_be_shared_writable")
            self.directory = root / "request_limits"
            self.directory.mkdir(mode=0o700, exist_ok=True)
            self._check_private(self.directory.lstat(), directory=True)
            # Auch neue Verzeichniseintraege muessen einen Hostneustart ueberstehen.
            for created in reversed(missing):
                parent_fd = os.open(created.parent, os.O_DIRECTORY | os.O_CLOEXEC)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
        except OSError:
            raise LimiterUnavailable("limiter_private_directory_unavailable") from None
        # Jede Instanz prueft bestehende Daten; fehlende/defekte Daten sind kein Reset.
        with self._locked():
            pass

    @staticmethod
    def _check_private(info: os.stat_result, *, directory: bool = False) -> None:
        kind_ok = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if not kind_ok or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise LimiterUnavailable("limiter_private_permissions_required")
        if not directory and info.st_nlink != 1:
            raise LimiterUnavailable("limiter_hardlinks_forbidden")

    def _check_wait(self, cancel: Event | None, deadline: float) -> None:
        if cancel is not None and cancel.is_set():
            raise RequestCancelled("request_cancelled")
        current = self._monotonic()
        if not math.isfinite(current):
            raise LimiterUnavailable("limiter_monotonic_clock_invalid")
        if current >= deadline:
            raise RequestDeadlineExceeded("request_deadline_exceeded")

    @contextmanager
    def _locked(self, *, cancel: Event | None = None, deadline: float | None = None) -> Iterator[_Document]:
        deadline = min(deadline, self._monotonic() + 5.0) if deadline is not None else self._monotonic() + 5.0
        directory_fd = lock_fd = None
        try:
            self._check_private(self.directory.lstat(), directory=True)
            directory_fd = os.open(self.directory, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            lock_fd = os.open(
                "coordinator.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=directory_fd,
            )
            self._check_private(os.fstat(lock_fd))
            while True:
                # Durable job cancellation may need a DB read. Poll only before
                # acquiring the coordinator lock, never from _check_wait inside it.
                refresh = getattr(cancel, "refresh", None)
                if refresh is not None:
                    refresh()
                self._check_wait(cancel, deadline)
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    self._sleep(min(0.05, max(0.0, deadline - self._monotonic())))
            self._check_wait(cancel, deadline)
            if os.stat("coordinator.lock", dir_fd=directory_fd, follow_symlinks=False).st_ino != os.fstat(lock_fd).st_ino:
                raise LimiterUnavailable("limiter_lock_changed")
            document = self._load(directory_fd, lock_fd)
            yield document
        except (OSError, ValueError, OverflowError):
            raise LimiterUnavailable("limiter_state_unavailable") from None
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            if directory_fd is not None:
                os.close(directory_fd)

    def _now(self, document: _Document) -> float:
        value = self._clock()
        if not math.isfinite(value) or value < 0:
            raise LimiterUnavailable("limiter_clock_invalid")
        return max(value, document.last_seen_at)

    def _load(self, directory_fd: int, lock_fd: int) -> _Document:
        try:
            fd = os.open("coordinator.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
        except FileNotFoundError:
            if os.fstat(lock_fd).st_size:
                raise LimiterUnavailable("limiter_state_missing_no_automatic_reset") from None
            now = self._clock()
            document = _Document(config=RequestLimitsConfig(), last_seen_at=now, buckets={}, active={}, waiters={})
            self._save(document, directory_fd)
        else:
            with os.fdopen(fd, "rb") as stream:
                self._check_private(os.fstat(stream.fileno()))
                if os.fstat(stream.fileno()).st_size > 64 * 1024 * 1024:
                    raise LimiterUnavailable("limiter_state_too_large")
                document = _Document.model_validate(json.loads(stream.read(), object_pairs_hook=self._unique_pairs))
            # Strukturfehler, unmoegliche Buchungen und NaN niemals als leeren Stand behandeln.
            for bucket in document.buckets.values():
                if (bucket.tokens > bucket.capacity or bucket.updated_at > document.last_seen_at
                    or any(item.at > document.last_seen_at for item in bucket.starts)
                    or any(a.at > b.at for a, b in zip(bucket.starts, bucket.starts[1:]))):
                    raise LimiterUnavailable("limiter_state_inconsistent")
            if any(group not in document.buckets for lease in document.active.values() for group in lease.groups):
                raise LimiterUnavailable("limiter_state_inconsistent")
        if not os.fstat(lock_fd).st_size:
            os.write(lock_fd, b"request-limits-v1\n")
            os.fsync(lock_fd)
            os.fsync(directory_fd)
        return document

    @staticmethod
    def _unique_pairs(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise LimiterUnavailable("limiter_duplicate_state_keys")
        return result

    def _save(self, document: _Document, directory_fd: int | None = None) -> None:
        serialized = document.model_dump_json()
        if len(serialized.encode("utf-8")) > 64 * 1024 * 1024:
            raise LimiterUnavailable("limiter_state_capacity_exceeded")
        own_fd = directory_fd is None
        if own_fd:
            directory_fd = os.open(self.directory, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        temporary = ".state-" + uuid4().hex
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, "coordinator.json", src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            os.fsync(directory_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            if own_fd:
                os.close(directory_fd)

    def _groups(self, provider: str, groups: list[str] | None, config: RequestLimitsConfig) -> list[str]:
        TypeAdapter(ProviderId).validate_python(provider)
        extra = TypeAdapter(list[GroupId]).validate_python(groups or [])
        if len(extra) > 16:
            raise ValueError("too_many_budget_groups")
        if any(group.startswith("budget:ceiling:") for group in extra):
            raise ValueError("ceiling_budget_namespace_reserved")
        # Provideridentitaet muss der serverseitige Adapter vorgeben, nicht ein freies UI-Feld.
        shared = "ip:ai" if provider.startswith("ai_") else "ip:global"
        ceiling = [f"budget:ceiling:{provider}"] if provider in config.provider_ceilings else []
        return sorted({f"provider:{provider}", shared, *ceiling, *config.provider_groups.get(provider, []), *extra})

    @staticmethod
    def _profile(group: str, config: RequestLimitsConfig) -> RequestLimitProfile:
        prefix = "budget:ceiling:"
        if group.startswith(prefix) and group[len(prefix):] in config.provider_ceilings:
            provider = group[len(prefix):]
            ceiling = config.provider_ceilings[provider]
            operator = config.group_profiles.get(f"provider:{provider}", config.default_profile)
            values = operator.model_dump()
            for name in ("requests_per_second", "requests_per_minute", "weighted_cost_per_minute"):
                cap, desired = getattr(ceiling, name), values[name]
                if cap is not None:
                    values[name] = min(cap, desired) if desired is not None else cap
            values["burst"] = min(operator.burst, values["requests_per_second"], values["requests_per_minute"])
            return RequestLimitProfile(**values)
        return config.group_profiles.get(group, config.default_profile)

    def read_config(self) -> RequestLimitsConfig:
        with self._locked() as document:
            return document.config.model_copy(deep=True)

    def profile(self, provider: str, *, groups: list[str] | None = None) -> RequestLimitProfile:
        """Konservativste gemeinsame Parameter aller wirksamen Budgetgruppen."""
        config = self.read_config()
        profiles = [self._profile(group, config) for group in self._groups(provider, groups, config)]
        fields = (
            "requests_per_second", "requests_per_minute", "burst", "max_concurrency",
            "timeout_seconds", "max_retries", "backoff_base_seconds", "backoff_max_seconds",
            "jitter_ratio", "job_deadline_seconds",
        )
        values = {name: min(getattr(profile, name) for profile in profiles) for name in fields}
        costs = [profile.weighted_cost_per_minute for profile in profiles if profile.weighted_cost_per_minute is not None]
        return RequestLimitProfile(**values, weighted_cost_per_minute=min(costs) if costs else None)

    def write_config(self, config: RequestLimitsConfig, *, expected_revision: int) -> RequestLimitsConfig:
        config = RequestLimitsConfig.model_validate(config.model_dump())
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("expected_revision_invalid")
        with self._locked() as document:
            if document.config.revision != expected_revision or config.revision != expected_revision:
                raise RevisionConflict("limiter_config_revision_conflict")
            now = self._now(document)
            # Vorhandene Token nur nach ALTER Rate auffuellen. Keine Reset-/Erhoehungsbursts.
            buckets = {group: self._refresh(bucket, self._profile(group, document.config), now)
                       for group, bucket in document.buckets.items()}
            updated = config.model_copy(update={"revision": expected_revision + 1}, deep=True)
            buckets = {group: self._refresh(bucket, self._profile(group, updated), now)
                       for group, bucket in buckets.items()}
            replacement = document.model_copy(update={"config": updated, "buckets": buckets, "last_seen_at": now})
            # Neue Obergrenze erbt auch die VOR der Konfigurationsaenderung entstandene Historie.
            ceiling_groups = [f"budget:ceiling:{provider}" for provider in updated.provider_ceilings]
            buckets = self._buckets(replacement, ceiling_groups, now)
            for provider in updated.provider_ceilings:
                canonical = buckets.get(f"provider:{provider}")
                group = f"budget:ceiling:{provider}"
                if canonical is not None:
                    # Auch Entfernen + spaeteres Wiederhinzufuegen darf keine Luecke erzeugen.
                    buckets[group] = buckets[group].model_copy(update={
                        "starts": list(canonical.starts),
                        "paused_until": max(buckets[group].paused_until, canonical.paused_until),
                    })
            self._save(replacement.model_copy(update={"buckets": buckets}))
            return updated.model_copy(deep=True)

    @staticmethod
    def _refresh(bucket: _Bucket, profile: RequestLimitProfile, now: float) -> _Bucket:
        tokens = min(float(bucket.capacity), bucket.tokens + max(0, now - bucket.updated_at) * bucket.rate)
        return bucket.model_copy(update={
            "tokens": min(float(profile.burst), tokens), "updated_at": now,
            "capacity": profile.burst, "rate": profile.requests_per_second,
            "starts": [start for start in bucket.starts if start.at > now - 60.0],
        })

    def _buckets(self, document: _Document, groups: list[str], now: float) -> dict[str, _Bucket]:
        buckets = dict(document.buckets)
        for group in groups:
            profile = self._profile(group, document.config)
            old = buckets.get(group)
            if old is None and group.startswith("budget:ceiling:"):
                old = buckets.get("provider:" + group[len("budget:ceiling:"):])
            if old is None:
                old = _Bucket(tokens=float(profile.burst), updated_at=now,
                              rate=profile.requests_per_second, capacity=profile.burst,
                              starts=[], paused_until=0.0)
            buckets[group] = self._refresh(old, profile, now)
        return buckets

    @staticmethod
    def _wait(bucket: _Bucket, profile: RequestLimitProfile, active: int, cost: int, now: float) -> tuple[float, list[str]]:
        delays: list[tuple[float, str]] = []
        if bucket.paused_until > now:
            delays.append((bucket.paused_until - now, "provider_pause"))
        if active >= profile.max_concurrency:
            delays.append((float("inf"), "concurrency"))
        second = [start for start in bucket.starts if start.at > now - 1.0]
        if len(second) >= profile.requests_per_second:
            delays.append((second[len(second) - profile.requests_per_second].at + 1.0 - now, "rolling_second"))
        if len(bucket.starts) >= profile.requests_per_minute:
            delays.append((bucket.starts[len(bucket.starts) - profile.requests_per_minute].at + 60.0 - now, "rolling_minute"))
        if profile.weighted_cost_per_minute is not None:
            excess = sum(start.cost for start in bucket.starts) + cost - profile.weighted_cost_per_minute
            if excess > 0:
                for start in bucket.starts:
                    excess -= start.cost
                    if excess <= 0:
                        delays.append((start.at + 60.0 - now, "weighted_minute"))
                        break
        if bucket.tokens < 1:
            delays.append(((1.0 - bucket.tokens) / profile.requests_per_second, "burst"))
        return max((delay for delay, _ in delays), default=0.0), [reason for _, reason in delays]

    def acquire(
        self, provider: str, *, cost: int = 1, groups: list[str] | None = None,
        cancel: Event | None = None, deadline: float | None = None,
    ) -> Lease:
        """Reserviert sofort; deadline ist absolute monotone Zeit, kein UTC-Wert."""
        if type(cost) is not int or cost < 1 or cost > 100_000_000:
            raise ValueError("request_cost_invalid")
        if deadline is not None and (not math.isfinite(deadline) or isinstance(deadline, bool)):
            raise ValueError("request_deadline_invalid")
        started = self._monotonic()
        effective_deadline = deadline if deadline is not None else started + 86_400.0
        waiter = uuid4().hex
        waiting = False
        try:
            while True:
                self._check_wait(cancel, effective_deadline)
                with self._locked(cancel=cancel, deadline=effective_deadline) as document:
                    names = self._groups(provider, groups, document.config)
                    profiles = [self._profile(group, document.config) for group in names]
                    effective_deadline = min(effective_deadline, started + min(p.job_deadline_seconds for p in profiles))
                    self._check_wait(cancel, effective_deadline)
                    if any(p.weighted_cost_per_minute is not None and cost > p.weighted_cost_per_minute for p in profiles):
                        raise RequestCostExceeded("request_cost_exceeds_group_capacity")
                    now = self._now(document)
                    buckets = self._buckets(document, names, now)
                    waits = [self._wait(buckets[group], profile, sum(group in item.groups for item in document.active.values()), cost, now)[0]
                             for group, profile in zip(names, profiles)]
                    delay = max(waits)
                    waiters = {key: value for key, value in document.waiters.items() if value.expires_at > now and key != waiter}
                    active = dict(document.active)
                    timeout = min(*(p.timeout_seconds for p in profiles), effective_deadline - self._monotonic())
                    if delay == 0:
                        for group in names:
                            bucket = buckets[group]
                            buckets[group] = bucket.model_copy(update={
                                "tokens": bucket.tokens - 1.0,
                                "starts": [*bucket.starts, _Start(at=now, cost=cost, reservation_id=waiter)],
                            })
                        active[waiter] = _Active(groups=names, started_at=now, timeout_seconds=timeout)
                    else:
                        waiters[waiter] = _Waiter(groups=names, expires_at=now + effective_deadline - self._monotonic())
                        waiting = True
                    self._save(document.model_copy(update={
                        "buckets": buckets, "active": active, "waiters": waiters, "last_seen_at": now,
                    }))
                if delay == 0:
                    waiting = False
                    lease = Lease(self, waiter, tuple(names), timeout, effective_deadline,
                                  provider=provider, cost=cost, cancel=cancel, acquired_at=started)
                    if cancel is not None and cancel.is_set():
                        lease.release()
                        raise RequestCancelled("request_cancelled")
                    return lease
                self._sleep(min(0.1, max(0.000001, delay), max(0.0, effective_deadline - self._monotonic())))
        finally:
            if waiting:
                self._remove_waiter(waiter)

    @staticmethod
    def _without_reservation(bucket: _Bucket, identifier: str, now: float) -> _Bucket:
        own = [start for start in bucket.starts if start.reservation_id == identifier]
        # Bereits nachgefuellte Tokens nicht nochmals erstatten. Die untere
        # Schranke der noch wirksamen eigenen Tokenlast ist konservativ, auch
        # wenn andere Reservierungen zwischenzeitlich Tokens verbraucht haben.
        refund = sum(max(0.0, 1.0 - max(0.0, now - start.at) * bucket.rate) for start in own)
        return bucket.model_copy(update={
            "tokens": min(float(bucket.capacity), bucket.tokens + refund),
            "starts": [start for start in bucket.starts if start.reservation_id != identifier],
        })

    def _dispatch(self, lease: Lease, prepare: Callable[[], None] | None) -> None:
        prepared = False
        waiting = False
        try:
            while True:
                self._check_wait(lease.cancel, lease.deadline)
                with self._locked(cancel=lease.cancel, deadline=lease.deadline) as document:
                    current = document.active.get(lease.lease_id)
                    if current is None:
                        raise RequestLimitError("lease_not_active")
                    # Eine neue Pflichtgruppe muss gelten; entfernte alte
                    # Gruppen duerfen bestehende Reservierungen nicht freigeben.
                    names = sorted(set(current.groups) | set(self._groups(lease.provider, None, document.config)))
                    profiles = [self._profile(group, document.config) for group in names]
                    lease.deadline = min(lease.deadline, lease.acquired_at + min(p.job_deadline_seconds for p in profiles))
                    self._check_wait(lease.cancel, lease.deadline)
                    if any(p.weighted_cost_per_minute is not None and lease.cost > p.weighted_cost_per_minute for p in profiles):
                        raise RequestCostExceeded("request_cost_exceeds_group_capacity")
                    now = self._now(document)
                    buckets = self._buckets(document, names, now)
                    eligible = {group: self._without_reservation(buckets[group], lease.lease_id, now) for group in names}
                    delay = max(self._wait(
                        eligible[group], profile,
                        sum(group in active.groups for key, active in document.active.items() if key != lease.lease_id),
                        lease.cost, now,
                    )[0] for group, profile in zip(names, profiles))
                    self._check_wait(lease.cancel, lease.deadline)
                    if prepared and delay == 0:
                        for group in names:
                            bucket = eligible[group]
                            buckets[group] = bucket.model_copy(update={
                                "tokens": bucket.tokens - 1.0,
                                "starts": [*bucket.starts, _Start(at=now, cost=lease.cost, reservation_id=lease.lease_id)],
                            })
                        timeout = min(lease.timeout_seconds, *(p.timeout_seconds for p in profiles),
                                      lease.deadline - self._monotonic())
                        self._check_wait(lease.cancel, lease.deadline)
                        active = {**document.active, lease.lease_id: _Active(
                            groups=names, started_at=now, timeout_seconds=timeout,
                        )}
                        waiters = {key: value for key, value in document.waiters.items() if key != lease.lease_id}
                        self._save(document.model_copy(update={
                            "buckets": buckets, "active": active, "waiters": waiters, "last_seen_at": now,
                        }))
                        lease.groups, lease.timeout_seconds = tuple(names), timeout
                        self._check_wait(lease.cancel, lease.deadline)
                        return
                    if delay > 0:
                        waiters = {**document.waiters, lease.lease_id: _Waiter(
                            groups=names, expires_at=now + lease.deadline - self._monotonic(),
                        )}
                        self._save(document.model_copy(update={
                            "buckets": buckets, "waiters": waiters, "last_seen_at": now,
                        }))
                        waiting = True
                if delay > 0:
                    prepared = False
                    self._sleep(min(0.1, max(0.000001, delay), max(0.0, lease.deadline - self._monotonic())))
                    continue
                self._check_wait(lease.cancel, lease.deadline)
                if prepare is not None:
                    prepare()
                self._check_wait(lease.cancel, lease.deadline)
                prepared = True
        finally:
            if waiting:
                self._remove_waiter(lease.lease_id)

    def _remove_waiter(self, identifier: str) -> None:
        try:
            with self._locked(deadline=self._monotonic() + 0.05) as document:
                if identifier in document.waiters:
                    waiters = dict(document.waiters)
                    del waiters[identifier]
                    self._save(document.model_copy(update={"waiters": waiters}))
        except RequestLimitError:
            # Keine Buchung wurde erlaubt; der rein informative Wartestatus laeuft ab.
            pass

    def _release(self, identifier: str) -> None:
        with self._locked() as document:
            if identifier in document.active:
                active = dict(document.active)
                del active[identifier]
                self._save(document.model_copy(update={"active": active}))

    def pause(self, provider: str, seconds: float, *, groups: list[str] | None = None) -> None:
        """Alle Gruppen pausieren; bestehende laengere Pause niemals verkuerzen."""
        if isinstance(seconds, bool) or not math.isfinite(seconds) or not 0 < seconds <= 604_800:
            raise ValueError("pause_seconds_invalid")
        with self._locked() as document:
            now = self._now(document)
            names = self._groups(provider, groups, document.config)
            buckets = self._buckets(document, names, now)
            for group in names:
                buckets[group] = buckets[group].model_copy(update={"paused_until": max(buckets[group].paused_until, now + seconds)})
            self._save(document.model_copy(update={"buckets": buckets, "last_seen_at": now}))

    def retry_delay(
        self, provider: str, attempt: int, *, retryable: bool, idempotent: bool,
        retry_after: float | None = None, groups: list[str] | None = None,
    ) -> float:
        """attempt=1 ist erster Retry; HTTP-Klassifikation macht der Adapter.

        Ergebnis via pause speichern und erneut acquire aufrufen. Auth-/dauerhafte
        Fehler mit retryable=False, unsichere Schreibaufrufe mit idempotent=False.
        """
        profile = self.profile(provider, groups=groups)
        if not retryable or not idempotent or type(attempt) is not int or not 1 <= attempt <= profile.max_retries:
            raise RetryNotAllowed("request_retry_not_allowed")
        if retry_after is not None and (isinstance(retry_after, bool) or not math.isfinite(retry_after) or not 0 <= retry_after <= 604_800):
            raise ValueError("retry_after_invalid")
        jitter = self._random()
        if not math.isfinite(jitter) or not 0 <= jitter <= 1:
            raise LimiterUnavailable("limiter_random_invalid")
        base = profile.backoff_base_seconds * 2 ** (attempt - 1)
        delay = min(profile.backoff_max_seconds, base * (1.0 + profile.jitter_ratio * jitter))
        return max(delay, retry_after or 0.0)

    def observe(
        self, provider: str, *, used_weight_1m: int | None = None,
        remaining_requests: int | None = None, reset_at: float | None = None,
        rate_limited: bool = False,
    ) -> None:
        """Headertelemetrie ohne Budgetannahmen; Retry-After separat via pause.

        Nicht mitgelieferte Messfelder bleiben unbekannt (None), nicht Null.
        Historische letzte Limitantwort bleibt mit eigenem Zeitpunkt erhalten.
        """
        TypeAdapter(ProviderId).validate_python(provider)
        if type(rate_limited) is not bool:
            raise ValueError("rate_limited_invalid")
        # Vor dem Lock validieren, ohne eventuell vertrauliche Rohheader zu speichern.
        measured = ProviderObservation(last_observed_at=0.0, used_weight_1m=used_weight_1m,
                                       remaining_requests=remaining_requests, reset_at=reset_at)
        with self._locked() as document:
            now = self._now(document)
            previous = document.observations.get(provider)
            last_limit = now if rate_limited else previous.last_rate_limit_at if previous else None
            observation = measured.model_copy(update={"last_observed_at": now, "last_rate_limit_at": last_limit})
            observations = {**document.observations, provider: observation}
            if len(observations) > 1000:
                raise LimiterUnavailable("limiter_observation_capacity_exceeded")
            self._save(document.model_copy(update={"observations": observations, "last_seen_at": now}))

    def status(self) -> RequestLimitsStatus:
        """Lokale Zaehler und separate Headerbeobachtungen, keine geschaetzte Restquote.

        next_start_at gilt fuer cost=1; bei Parallelitaetssperre unbekannt.
        """
        with self._locked() as document:
            now = self._now(document)
            names = sorted(set(document.buckets) | set(document.config.group_profiles)
                           | {f"budget:ceiling:{provider}" for provider in document.config.provider_ceilings})
            buckets = self._buckets(document, names, now)
            statuses = []
            for group in names:
                bucket, profile = buckets[group], self._profile(group, document.config)
                in_flight = sum(group in item.groups for item in document.active.values())
                delay, reasons = self._wait(bucket, profile, in_flight, 1, now)
                statuses.append(RequestLimitGroupStatus(
                    group=group, profile=profile,
                    requests_last_second=sum(start.at > now - 1.0 for start in bucket.starts),
                    requests_last_minute=len(bucket.starts), cost_last_minute=sum(start.cost for start in bucket.starts),
                    in_flight=in_flight,
                    queued=sum(group in item.groups and item.expires_at > now for item in document.waiters.values()),
                    paused_until=bucket.paused_until if bucket.paused_until > now else None,
                    next_start_at=now + delay if math.isfinite(delay) else None, blocking_reasons=reasons,
                    provider_ceiling=document.config.provider_ceilings.get(group[len("budget:ceiling:"):])
                    if group.startswith("budget:ceiling:") else None,
                ))
            observations = document.observations
            available = any(item.used_weight_1m is not None or item.remaining_requests is not None
                            or item.reset_at is not None or item.last_rate_limit_at is not None
                            for item in observations.values())
            return RequestLimitsStatus(config_revision=document.config.revision, observed_at=now,
                                       clock_rollback=self._clock() < document.last_seen_at, groups=statuses,
                                       provider_observations=observations,
                                       manufacturer_telemetry_available=available)

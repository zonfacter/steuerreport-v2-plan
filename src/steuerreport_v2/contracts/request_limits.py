"""Lokale Abrufbudgets, keine Aussage ueber vertragliche Herstellerlimits.

Sekunden-/10-Sekunden-/Minutenfenster sind rollierend: (jetzt - Fenster, jetzt].
Burst ist eine ZUSAETZLICHE Token-Bucket-Grenze mit requests_per_second
als Auffuellrate; sie hebt keines der rollierenden Fenster auf. Kosten sind
lokale Einheiten. Ihre Zuordnung zu API-Gewichten/CU obliegt dem Connector.
"""
from __future__ import annotations

from datetime import date
from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


GroupId = Annotated[str, Field(pattern=r"^(provider|ip|project|account|endpoint|budget):[a-z0-9][a-z0-9_.:-]{0,63}$")]
ProviderId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")]
EndpointId = Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_.:-]{0,63}$")]
EndpointCost = Annotated[int, Field(ge=1, le=100_000_000)]


class LimitContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False,
        hide_input_in_errors=True,
    )


class RequestLimitProfile(LimitContract):
    origin: Literal["local_conservative"] = "local_conservative"
    manufacturer_limit_verified: Literal[False] = False
    cost_unit: Literal["local_units"] = "local_units"
    requests_per_second: int = Field(default=1, ge=1, le=10_000)
    requests_per_10_seconds: int | None = Field(default=None, ge=1, le=100_000)
    requests_per_minute: int = Field(default=30, ge=1, le=100_000)
    weighted_cost_per_minute: int | None = Field(default=None, ge=1, le=100_000_000)
    burst: int = Field(default=1, ge=1, le=10_000)
    max_concurrency: int = Field(default=1, ge=1, le=1000)
    timeout_seconds: float = Field(default=30.0, gt=0, le=3600)
    max_retries: int = Field(default=2, ge=0, le=10)
    backoff_base_seconds: float = Field(default=1.0, gt=0, le=300)
    backoff_max_seconds: float = Field(default=30.0, gt=0, le=3600)
    jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    job_deadline_seconds: float = Field(default=300.0, gt=0, le=86_400)

    @model_validator(mode="after")
    def consistent_limits(self):
        windows = [self.requests_per_second, self.requests_per_minute]
        if self.requests_per_10_seconds is not None:
            windows.append(self.requests_per_10_seconds)
        if self.burst > min(windows):
            raise ValueError("burst_exceeds_request_window")
        if self.backoff_base_seconds > self.backoff_max_seconds:
            raise ValueError("backoff_range_invalid")
        if self.timeout_seconds > self.job_deadline_seconds:
            raise ValueError("request_timeout_exceeds_job_deadline")
        return self


class ProviderCeiling(LimitContract):
    """Vom Betreiber aus seinem Plan uebertragene Obergrenze, nicht verifiziert.

    Die Referenz wird NICHT aufgerufen. Eine URL beweist keine Vertragstreue;
    deshalb keine vorgebliche offizielle Domain-Allowlist/Herstellerempfehlung.
    Unbekannte Dimensionen bleiben None. Rollierende 1s/10s/60s-Grenzen sind nur
    fuer dazu passende Anbietersemantik geeignet (z.B. kein 10s-CU-Ersatz).
    """

    requests_per_second: int | None = Field(default=None, ge=1, le=10_000)
    requests_per_10_seconds: int | None = Field(default=None, ge=1, le=100_000)
    requests_per_minute: int | None = Field(default=None, ge=1, le=100_000)
    weighted_cost_per_minute: int | None = Field(default=None, ge=1, le=100_000_000)
    source_url: str = Field(min_length=12, max_length=1024)
    checked_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    scope: Literal["provider", "ip", "account", "api_key", "project", "endpoint_group", "combination"]
    plan: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9 ._:+-]{0,79}$")
    declared_by_operator: Literal[True] = True
    independently_verified: Literal[False] = False

    @field_validator("source_url")
    @classmethod
    def public_reference_without_credentials(cls, value: str) -> str:
        url = urlsplit(value)
        if (any(ord(char) <= 32 or ord(char) >= 127 for char in value) or url.scheme != "https"
            or not url.hostname or "." not in url.hostname or url.username or url.password
            or url.query or url.fragment or url.port is not None):
            raise ValueError("ceiling_reference_requires_public_https_without_credentials_or_query")
        try:
            ip_address(url.hostname)
        except ValueError:
            pass
        else:
            raise ValueError("ceiling_reference_requires_documentation_hostname")
        if url.hostname.endswith((".local", ".internal")):
            raise ValueError("ceiling_reference_requires_documentation_hostname")
        return value

    @field_validator("checked_date")
    @classmethod
    def valid_checked_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def at_least_one_ceiling(self):
        if all(value is None for value in (
            self.requests_per_second, self.requests_per_10_seconds,
            self.requests_per_minute, self.weighted_cost_per_minute,
        )):
            raise ValueError("ceiling_has_no_known_dimension")
        return self


class RequestLimitsConfig(LimitContract):
    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    default_profile: RequestLimitProfile = Field(default_factory=RequestLimitProfile)
    group_profiles: dict[GroupId, RequestLimitProfile] = Field(default_factory=dict, max_length=1000)
    # Zusaetzlich zu provider:<name> und ip:ai (ai_*) bzw. ip:global (CEX/RPC).
    provider_groups: dict[ProviderId, list[GroupId]] = Field(default_factory=dict, max_length=1000)
    endpoint_costs: dict[ProviderId, dict[EndpointId, EndpointCost]] = Field(default_factory=dict, max_length=1000)
    endpoint_profiles: dict[ProviderId, dict[EndpointId, RequestLimitProfile]] = Field(default_factory=dict, max_length=1000)
    provider_ceilings: dict[ProviderId, ProviderCeiling] = Field(default_factory=dict, max_length=1000)
    scheduler_enabled: Literal[False] = False

    @model_validator(mode="after")
    def bounded_bindings(self):
        if any(len(groups) > 16 or len(groups) != len(set(groups)) for groups in self.provider_groups.values()):
            raise ValueError("budget_bindings_invalid")
        if sum(len(costs) for costs in self.endpoint_costs.values()) > 1000:
            raise ValueError("too_many_endpoint_costs")
        if sum(len(profiles) for profiles in self.endpoint_profiles.values()) > 1000:
            raise ValueError("too_many_endpoint_profiles")
        reserved = [*self.group_profiles, *(group for groups in self.provider_groups.values() for group in groups)]
        if any(group.startswith("budget:ceiling:") for group in reserved):
            raise ValueError("ceiling_budget_namespace_reserved")
        if any(group.startswith("budget:endpoint:") for group in reserved):
            raise ValueError("endpoint_budget_namespace_reserved")
        return self


class RequestLimitGroupStatus(LimitContract):
    group: GroupId
    profile: RequestLimitProfile
    requests_last_second: int
    requests_last_10_seconds: int = 0
    requests_last_minute: int
    cost_last_minute: int
    in_flight: int
    queued: int
    paused_until: float | None
    next_start_at: float | None
    blocking_reasons: list[str]
    provider_ceiling: ProviderCeiling | None = None
    provider: ProviderId | None = None
    endpoint: EndpointId | None = None


class ProviderObservation(LimitContract):
    """Nur tatsaechlich vom Adapter gelesene Header; keine berechnete Restquote."""

    last_observed_at: float = Field(ge=0)
    last_rate_limit_at: float | None = Field(default=None, ge=0)
    used_weight_1m: int | None = Field(default=None, ge=0)
    # Anbieter koennen nach 429 einen negativen Restwert melden; unveraendert erhalten.
    remaining_requests: int | None = None
    reset_at: float | None = Field(default=None, ge=0)


class RequestLimitsStatus(LimitContract):
    schema_version: Literal[1] = 1
    config_revision: int
    observed_at: float
    clock_rollback: bool
    groups: list[RequestLimitGroupStatus]
    manufacturer_telemetry_available: bool = False
    provider_observations: dict[ProviderId, ProviderObservation] = Field(default_factory=dict)
    coordination_scope: Literal["host_local_flock_shared_volume"] = "host_local_flock_shared_volume"
    concurrency_recovery: Literal["explicit_release_only"] = "explicit_release_only"
    recovery_hint: str = (
        "Abgestuerzte Worker geben aktive Leases nicht automatisch frei. Erst alle alten "
        "Worker und HTTP-Aufrufe nachweislich beenden; Wiederherstellung administrativ "
        "unter exklusivem Zugriff pruefen. Konfiguration, Startbuchungen und Pausen erhalten; "
        "nur nachweislich verwaiste aktive Lease-IDs gezielt bereinigen. Niemals die "
        "Zustandsdatei loeschen. Kein automatischer Reset oder Ablauf."
    )

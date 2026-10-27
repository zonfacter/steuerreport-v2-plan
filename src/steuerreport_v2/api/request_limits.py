"""Geheimnisfreie lokale Abrufkonfiguration, keine automatischen Anbieteraufrufe."""
from __future__ import annotations

from datetime import datetime, timezone
import json

from fastapi import APIRouter, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from steuerreport_v2.contracts.common import ApiResponse
from steuerreport_v2.contracts.request_limits import RequestLimitsConfig, RequestLimitsStatus
from steuerreport_v2.domain.request_limits import RequestLimiter, RequestLimitError, RevisionConflict
from steuerreport_v2.domain.request_limits import (
    ActiveLeaseConflict, PresetConflict, SOLANA_PUBLIC_FREE, SOLANA_HISTORY_PROFILE,
    SOLANA_HISTORY_ENDPOINTS, endpoint_group, solana_preset_conflicts,
)
from steuerreport_v2.paths import PROJECT_ROOT
from steuerreport_v2.private_settings import private_state_root


class LimitsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    config: RequestLimitsConfig
    expected_revision: int = Field(ge=0, strict=True)


class PresetWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    expected_revision: int = Field(ge=0)
    confirmation: bool


class SafeLimitRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            if request.method != "GET" and getattr(request.app.state, "ux_sandbox", False) is True:
                return JSONResponse(status_code=403, content={"detail": "connection_demo_read_only"})
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "request_limits_invalid"})
            except RevisionConflict:
                return JSONResponse(status_code=409, content={"detail": "request_limits_revision_conflict"})
            except ActiveLeaseConflict:
                return JSONResponse(status_code=409, content={"detail": "request_limits_active_leases_conflict"})
            except PresetConflict as exc:
                return JSONResponse(status_code=409, content={"detail": "request_limits_preset_conflict", "conflicts": exc.conflicts})
            except (RequestLimitError, OSError, ValueError):
                return JSONResponse(status_code=503, content={"detail": "request_limits_unavailable"})
        return handler


def _uninitialized():
    root = private_state_root().resolve()
    if root.is_relative_to(PROJECT_ROOT.resolve()):
        raise ValueError("private_state_inside_software")
    return not (root / "request_limits").exists()


def build_request_limits_router():
    router = APIRouter(prefix="/api/v1/admin", tags=["request-limits"], route_class=SafeLimitRoute)

    @router.get("/request-limits")
    def read_limits() -> ApiResponse[RequestLimitsConfig]:
        return ApiResponse(data=RequestLimitsConfig() if _uninitialized() else RequestLimiter().read_config())

    @router.put("/request-limits")
    def write_limits(payload: LimitsWrite) -> ApiResponse[RequestLimitsConfig]:
        from steuerreport_v2.domain.external_http import HTTP_ENDPOINTS, RPC_READS
        known = {"default", *HTTP_ENDPOINTS.values(), *("rpc_" + method.lower() for method in RPC_READS)}
        if any(set(values) - known for mapping in (payload.config.endpoint_costs, payload.config.endpoint_profiles)
               for values in mapping.values()):
            raise HTTPException(status_code=422, detail="request_limits_unknown_endpoint")
        return ApiResponse(data=RequestLimiter().write_config(payload.config, expected_revision=payload.expected_revision))

    @router.get("/request-limits/status")
    def status() -> ApiResponse[RequestLimitsStatus]:
        if _uninitialized():
            return ApiResponse(data=RequestLimitsStatus(config_revision=0, observed_at=datetime.now(timezone.utc).timestamp(), clock_rollback=False, groups=[]))
        return ApiResponse(data=RequestLimiter().status())

    @router.get("/request-limits/endpoints")
    def endpoints() -> ApiResponse[dict]:
        from steuerreport_v2.domain.external_http import HTTP_ENDPOINTS, RPC_READS
        return ApiResponse(data={"fallback": "default", "unit": "local_units",
            "http": [{"id": identifier, "path": path} for path, identifier in sorted(HTTP_ENDPOINTS.items())],
            "rpc": [{"id": "rpc_" + method.lower(), "method": method} for method in sorted(RPC_READS)]})

    @router.get("/request-limits/presets")
    def presets() -> ApiResponse[dict]:
        config = RequestLimitsConfig() if _uninitialized() else RequestLimiter().read_config()
        return ApiResponse(data={"presets": [{
            "id": "solana_public_free", "label": "Solana Public RPC - Free",
            "source_url": "https://solana.com/docs/references/clusters", "checked_date": "2026-10-27",
            "description": (
                "Konservatives lokales Profil fuer oeffentliche Solana-RPCs: 3/s, 180/min, 30/10s. "
                "Dokumentiert pro IP: 100 Requests/10s gesamt, 40/10s je RPC-Methode, "
                "40 parallele und 40 neue Verbindungen/10s. Jeder RPC kann einen neuen Client erzeugen. "
                "100 MB/30s werden NICHT als gemessenes Budget durchgesetzt. Keine Restquote oder "
                "Durchsatzgarantie; Limits koennen sich aendern. Fremde Anwendungen derselben IP "
                "werden nicht erfasst. Keine Umgehung durch IP-/Key-Wechsel. Private RPCs und "
                "andere Anbieter haben eigene Vertraege; keine automatische Tarifpruefung."
            ),
            "profile": SOLANA_PUBLIC_FREE.model_dump(),
            "endpoint_profiles": {"solana_rpc": dict.fromkeys(SOLANA_HISTORY_ENDPOINTS, SOLANA_HISTORY_PROFILE.model_dump())},
            "affected_groups": ["provider:solana_rpc", "ip:global",
                                *(endpoint_group("solana_rpc", endpoint) for endpoint in SOLANA_HISTORY_ENDPOINTS)],
            "conflicts": solana_preset_conflicts(config), "current_revision": config.revision,
            "documented_limits": {"requests_per_10_seconds_per_ip": 100,
                                  "requests_per_10_seconds_per_method_per_ip": 40,
                                  "max_concurrent_connections_per_ip": 40,
                                  "new_connections_per_10_seconds_per_ip": 40,
                                  "data_mb_per_30_seconds": 100},
            "data_budget_enforced": False, "throughput_guaranteed": False,
        }], "current_revision": config.revision})

    @router.post("/request-limits/presets/solana_public_free")
    def apply_preset(payload: PresetWrite) -> ApiResponse[RequestLimitsConfig]:
        if payload.confirmation is not True:
            raise HTTPException(status_code=422, detail="request_limits_confirmation_required")
        # Konflikte auch vor der ersten Anlage pruefen; insbesondere stale CAS
        # darf nicht allein durch einen fehlgeschlagenen POST Zustand anlegen.
        if _uninitialized() and payload.expected_revision != 0:
            raise RevisionConflict("limiter_config_revision_conflict")
        return ApiResponse(data=RequestLimiter().apply_solana_public_free(expected_revision=payload.expected_revision))

    @router.get("/provider-references")
    def references() -> ApiResponse[dict]:
        return ApiResponse(data=json.loads((PROJECT_ROOT / "configs/provider_request_references.json").read_text()))

    return router

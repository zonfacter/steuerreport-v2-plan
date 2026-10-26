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
from steuerreport_v2.paths import PROJECT_ROOT
from steuerreport_v2.private_settings import private_state_root


class LimitsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    config: RequestLimitsConfig
    expected_revision: int = Field(ge=0, strict=True)


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
        if any(set(costs) - known for costs in payload.config.endpoint_costs.values()):
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

    @router.get("/provider-references")
    def references() -> ApiResponse[dict]:
        return ApiResponse(data=json.loads((PROJECT_ROOT / "configs/provider_request_references.json").read_text()))

    return router

"""Routerfactory; Einbindung und bestehende Auth-Middleware bleiben beim Host."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from steuerreport_v2.contracts.common import ApiMessage, ApiResponse
from steuerreport_v2.contracts.connections import (
    Connection, ConnectionAction, ConnectionCreate, ConnectionJob, ConnectionJobs,
    ConnectionList, ConnectionSnapshots, ConnectionUpdate,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connections import ConnectionError, ConnectionService


def _error(code: str, status_code: int) -> JSONResponse:
    response = ApiResponse(status="error", errors=[ApiMessage(code=code, message=code)])
    return JSONResponse(status_code=status_code, content=response.model_dump(mode="json"))


class _SafeConnectionRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            if request.method != "GET" and getattr(request.app.state, "ux_sandbox", False) is True:
                return _error("connection_demo_read_only", 403)
            try:
                return await original(request)
            except RequestValidationError:
                # Pydantic/FastAPI koennten sonst Secret-Eingaben in input ausgeben.
                return _error("connection_payload_invalid", 422)
            except ConnectionError as exc:
                return _error(exc.code, exc.http_status)
            except Exception:
                return _error("connection_service_unavailable", 503)

        return handler


def build_connections_router(store: DuckDbStore) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin/connections", tags=["connections"],
                       route_class=_SafeConnectionRoute)
    service = ConnectionService(store)

    @router.get("")
    def connections() -> ApiResponse[ConnectionList]:
        return ApiResponse(data=service.list())

    @router.post("", status_code=201)
    def create(payload: ConnectionCreate) -> ApiResponse[Connection]:
        return ApiResponse(data=service.create(payload))

    @router.get("/jobs")
    def jobs() -> ApiResponse[ConnectionJobs]:
        return ApiResponse(data=service.jobs())

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: UUID) -> ApiResponse[ConnectionJob]:
        return ApiResponse(data=service.cancel(job_id))

    @router.put("/{connection_id}")
    def update(connection_id: UUID, payload: ConnectionUpdate) -> ApiResponse[Connection]:
        return ApiResponse(data=service.update(connection_id, payload))

    @router.delete("/{connection_id}/credentials")
    def delete_credentials(connection_id: UUID) -> ApiResponse[Connection]:
        return ApiResponse(data=service.delete_credentials(connection_id))

    @router.get("/{connection_id}/snapshots")
    def snapshots(connection_id: UUID) -> ApiResponse[ConnectionSnapshots]:
        return ApiResponse(data=service.snapshots(connection_id))

    @router.post("/{connection_id}/test", status_code=202)
    def test(connection_id: UUID, payload: ConnectionAction) -> ApiResponse[ConnectionJob]:
        return ApiResponse(data=service.start(connection_id, "test", payload))

    @router.post("/{connection_id}/sync", status_code=202)
    def sync(connection_id: UUID, payload: ConnectionAction) -> ApiResponse[ConnectionJob]:
        return ApiResponse(data=service.start(connection_id, "sync", payload))

    return router

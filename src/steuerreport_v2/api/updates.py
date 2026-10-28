"""Lokaler Update-Status, begrenzte Metadatenpruefung, kein Deployment."""
from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from steuerreport_v2.contracts.common import ApiMessage, ApiResponse
from steuerreport_v2.contracts.updates import (
    UpdateCheckRequest, UpdateHandoff, UpdateHandoffRequest, UpdateSettings, UpdateStatus,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.updates import (
    UpdateBlockedError, UpdateBusyError, UpdateSelectionError, UpdateService,
)


def _error(code: str, message: str, status: int) -> JSONResponse:
    response = ApiResponse(status="error", errors=[ApiMessage(code=code, message=message)])
    return JSONResponse(status_code=status, content=response.model_dump(mode="json"))


class _SafeUpdateRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError:
                return _error("updates_payload_invalid", "Update-Anfrage ist ungueltig.", 422)
            except UpdateBlockedError:
                return _error("updates_blocked", "Update-Pruefung und Einstellungen sind in diesem Betrieb gesperrt.", 403)
            except UpdateBusyError:
                return _error("updates_check_in_progress", "Eine Pruefung laeuft bereits. Anschliessend erneut versuchen.", 409)
            except UpdateSelectionError:
                return _error("updates_snapshot_not_available", "Die ausgewaehlte Release-Version ist nicht mehr in diesem Metadatenstand. Liste neu laden und Ziel erneut pruefen.", 409)
            except Exception:
                return _error("updates_unavailable", "Update-Status derzeit nicht verfuegbar. Finanzdaten wurden nicht veraendert.", 503)
        return handler


def build_updates_router(store: DuckDbStore, *, service_factory=None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/updates", tags=["administration"], route_class=_SafeUpdateRoute)

    def service(request: Request) -> UpdateService:
        sandbox = getattr(request.app.state, "ux_sandbox", False) is True
        return service_factory(sandbox) if service_factory else UpdateService(store, sandbox=sandbox)

    @router.get("")
    def status(request: Request) -> ApiResponse[UpdateStatus]:
        return ApiResponse(data=service(request).status())

    @router.put("/settings")
    def settings(payload: UpdateSettings, request: Request) -> ApiResponse[UpdateStatus]:
        return ApiResponse(data=service(request).save_settings(payload))

    @router.post("/check")
    def check(payload: UpdateCheckRequest, request: Request) -> ApiResponse[UpdateStatus]:
        return ApiResponse(data=service(request).check(payload.mode))

    @router.post("/handoff")
    def handoff(payload: UpdateHandoffRequest, request: Request) -> ApiResponse[UpdateHandoff]:
        return ApiResponse(data=service(request).handoff(payload))

    return router

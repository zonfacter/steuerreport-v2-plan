"""Automatischer Historienimport, an die ausgewaehlte Quelle gebunden."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from steuerreport_v2.contracts.common import ApiMessage, ApiResponse
from steuerreport_v2.contracts.history import HistoryApprove, HistoryJob, HistoryResume, HistoryStart, HistoryView
from steuerreport_v2.domain.history import HistoryService
from steuerreport_v2.domain.history_types import HistoryFetchError
from steuerreport_v2.importers.solana_history_identity import SolanaHistoryConflict


class _HistoryRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe(request: Request):
            def error(code, status):
                return JSONResponse(status_code=status, content=ApiResponse(
                    status="error", errors=[ApiMessage(code=code, message=code)],
                ).model_dump(mode="json"))
            if request.method != "GET" and getattr(request.app.state, "ux_sandbox", False) is True:
                return error("history_demo_read_only", 403)
            try:
                return await handler(request)
            except RequestValidationError:
                return error("history_request_invalid", 422)
            except HistoryFetchError as exc:
                return error(exc.code, 404 if exc.code.endswith("not_found") else 409)
            except SolanaHistoryConflict:
                return error("history_existing_evidence_conflict", 409)
            except Exception:
                return error("history_service_unavailable", 503)
        return safe


def build_history_router(store, on_import):
    router = APIRouter(prefix="/api/v1/workspace/sources/{ref}/history", tags=["source-history"], route_class=_HistoryRoute)
    service = HistoryService(store)

    @router.get("")
    def history(ref: str) -> ApiResponse[HistoryView]:
        return ApiResponse(data=service.view(ref))

    @router.post("/jobs", status_code=202)
    def start(ref: str, request: HistoryStart) -> ApiResponse[HistoryJob]:
        return ApiResponse(data=service.start(ref, request))

    @router.get("/jobs/{job_id}")
    def job(ref: str, job_id: UUID) -> ApiResponse[HistoryJob]:
        return ApiResponse(data=service.get(ref, str(job_id)))

    @router.post("/jobs/{job_id}/pause")
    def pause(ref: str, job_id: UUID) -> ApiResponse[HistoryJob]:
        return ApiResponse(data=service.control(ref, str(job_id), "pause"))

    @router.post("/jobs/{job_id}/cancel")
    def cancel(ref: str, job_id: UUID) -> ApiResponse[HistoryJob]:
        return ApiResponse(data=service.control(ref, str(job_id), "cancel"))

    @router.post("/jobs/{job_id}/resume", status_code=202)
    def resume(ref: str, job_id: UUID, request: HistoryResume) -> ApiResponse[HistoryJob]:
        return ApiResponse(data=service.control(ref, str(job_id), "resume", request))

    @router.post("/jobs/{job_id}/import")
    def apply(ref: str, job_id: UUID, request: HistoryApprove) -> ApiResponse[HistoryJob]:
        result = service.approve(ref, str(job_id), request)
        on_import()
        return ApiResponse(data=result)

    @router.post("/jobs/{job_id}/repreview", status_code=202)
    def repreview(ref: str, job_id: UUID) -> ApiResponse[HistoryJob]:
        return ApiResponse(data=service.repreview(ref, str(job_id)))

    @router.get("/jobs/{job_id}/audit.json")
    def audit(ref: str, job_id: UUID) -> ApiResponse[dict]:
        return ApiResponse(data=service.audit(ref, str(job_id)))

    return router

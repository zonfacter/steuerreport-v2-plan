"""Versionierter, geheimnisfreier Preisworkflow; keine Fachlogik im Router."""
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from steuerreport_v2.contracts.common import ApiResponse
from steuerreport_v2.contracts.historical_prices import HistoricalPriceApply, HistoricalPriceFetch, HistoricalPriceQuery, PriceMapping
from steuerreport_v2.domain.historical_prices import HistoricalPriceError, HistoricalPriceService


class _PriceRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe(request: Request):
            def error(code, status):
                return JSONResponse(status_code=status, content={"status": "error", "errors": [{"code": code, "message": code}], "data": None})
            read_only = request.method == "GET" or request.url.path.endswith("/plan")
            if not read_only and getattr(request.app.state, "ux_sandbox", False) is True:
                return error("historical_price_demo_read_only", 403)
            try:
                return await handler(request)
            except RequestValidationError:
                return error("historical_price_request_invalid", 422)
            except HistoricalPriceError as exc:
                return error(str(exc), 404 if str(exc).endswith("not_found") else 409)
            except Exception:
                return error("historical_price_service_unavailable", 503)
        return safe


def build_historical_prices_router(store, on_apply):
    router = APIRouter(prefix="/api/v1/prices/historical", tags=["Prices"], route_class=_PriceRoute)
    service = HistoricalPriceService(store)

    @router.post("/plan")
    def plan(request: HistoricalPriceQuery) -> ApiResponse[dict]:
        return ApiResponse(data=service.plan(request))

    @router.get("/mappings")
    def mappings() -> ApiResponse[dict]:
        return ApiResponse(data=service.mappings())

    @router.put("/mappings")
    def save_mapping(request: PriceMapping) -> ApiResponse[dict]:
        return ApiResponse(data=service.save_mapping(request))

    @router.get("/previews")
    def recent() -> ApiResponse[list[dict]]:
        return ApiResponse(data=service.recent())

    @router.get("/previews/{request_id}")
    def get(request_id: UUID) -> ApiResponse[dict]:
        return ApiResponse(data=service.get(request_id))

    @router.get("/previews/{request_id}/evidence/{sha}")
    def evidence(request_id: UUID, sha: str) -> Response:
        content = service.evidence(request_id, sha)
        return Response(content=content, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="historical-price-{sha}.json"'})

    @router.post("/previews")
    def fetch(request: HistoricalPriceFetch) -> ApiResponse[dict]:
        return ApiResponse(data=service.fetch(request))

    @router.post("/previews/{request_id}/apply")
    def apply(request_id: UUID, request: HistoricalPriceApply) -> ApiResponse[dict]:
        result = service.apply(request_id, request)
        on_apply()
        return ApiResponse(data=result)

    return router

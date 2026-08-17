from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.models.search import (
    RouteDetailResponse,
    SearchRequest,
    SearchResponse,
    SelectedRouteRequest,
)
from backend.app.services.agent_service import (
    AgentService,
    AgentServiceError,
    get_agent_service,
)

router = APIRouter()


@router.post("/chat", response_model=SearchResponse, tags=["chat"])
async def chat(
    request: SearchRequest,
    service: AgentService = Depends(get_agent_service),
) -> SearchResponse:
    try:
        return await service.send_message(request.message, request.conversationId)
    except AgentServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Rental agent is temporarily unavailable.",
        ) from exc


@router.post("/route", response_model=RouteDetailResponse, tags=["maps"])
async def selected_route(
    request: SelectedRouteRequest,
    service: AgentService = Depends(get_agent_service),
) -> RouteDetailResponse:
    try:
        return await service.get_selected_route(
            request.listingId,
            request.conversationId,
            destination=request.destination or "",
            mode=request.mode or "",
        )
    except AgentServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Route service is temporarily unavailable.",
        ) from exc

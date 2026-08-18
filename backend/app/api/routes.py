from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.auth import AuthenticatedUser, get_current_user
from backend.app.models.search import (
    RouteDetailResponse,
    SearchRequest,
    SearchResponse,
    SelectedRouteRequest,
)
from backend.app.services.agent_service import (
    AgentService,
    AgentServiceError,
    ConversationAccessError,
    get_agent_service,
)

router = APIRouter()


@router.post("/chat", response_model=SearchResponse, tags=["chat"])
async def chat(
    request: SearchRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> SearchResponse:
    try:
        return await service.send_message(
            request.message,
            request.conversationId,
            user_id=user.uid,
        )
    except ConversationAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This conversation belongs to a different user.",
        ) from exc
    except AgentServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Rental agent is temporarily unavailable.",
        ) from exc


@router.post("/route", response_model=RouteDetailResponse, tags=["maps"])
async def selected_route(
    request: SelectedRouteRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: AgentService = Depends(get_agent_service),
) -> RouteDetailResponse:
    try:
        return await service.get_selected_route(
            request.listingId,
            request.conversationId,
            destination=request.destination or "",
            mode=request.mode or "",
            user_id=user.uid,
        )
    except ConversationAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This conversation belongs to a different user.",
        ) from exc
    except AgentServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Route service is temporarily unavailable.",
        ) from exc

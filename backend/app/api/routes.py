from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.models.search import SearchRequest, SearchResponse
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

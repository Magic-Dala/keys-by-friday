from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from backend.app.auth import AuthenticatedUser, get_current_user
from backend.app.models.search import (
    RouteDetailResponse,
    SaveShortlistRequest,
    SearchRequest,
    SearchResponse,
    SelectedRouteRequest,
    ShortlistItemResponse,
    ShortlistResponse,
)
from backend.app.services.agent_service import (
    AgentService,
    AgentServiceError,
    ConversationAccessError,
    PersistenceUnavailableError,
    get_agent_service,
)
from backend.app.services.shortlist_service import (
    ShortlistConversationAccessError,
    ShortlistConversationNotFoundError,
    ShortlistListingNotFoundError,
    ShortlistPersistenceUnavailableError,
    ShortlistService,
    get_shortlist_service,
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
    except PersistenceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation storage is temporarily unavailable.",
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
    except PersistenceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation storage is temporarily unavailable.",
        ) from exc
    except AgentServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Route service is temporarily unavailable.",
        ) from exc


@router.get("/shortlist", response_model=ShortlistResponse, tags=["shortlist"])
async def list_shortlist(
    user: AuthenticatedUser = Depends(get_current_user),
    service: ShortlistService = Depends(get_shortlist_service),
) -> ShortlistResponse:
    try:
        return await service.list_for_user(user.uid)
    except ShortlistPersistenceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shortlist storage is temporarily unavailable.",
        ) from exc


@router.post(
    "/shortlist",
    response_model=ShortlistItemResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["shortlist"],
)
async def save_shortlist_item(
    request: SaveShortlistRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    service: ShortlistService = Depends(get_shortlist_service),
) -> ShortlistItemResponse:
    try:
        return await service.save(
            user.uid,
            conversation_id=request.conversationId,
            listing_id=request.listingId,
        )
    except ShortlistConversationAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This conversation belongs to a different user.",
        ) from exc
    except ShortlistConversationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The source conversation was not found.",
        ) from exc
    except ShortlistListingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The listing was not found in the conversation's latest results.",
        ) from exc
    except ShortlistPersistenceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shortlist storage is temporarily unavailable.",
        ) from exc


@router.delete(
    "/shortlist/{listing_id:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["shortlist"],
)
async def remove_shortlist_item(
    listing_id: Annotated[str, Path(min_length=1, max_length=256)],
    user: AuthenticatedUser = Depends(get_current_user),
    service: ShortlistService = Depends(get_shortlist_service),
) -> Response:
    try:
        await service.remove(user.uid, listing_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except ShortlistPersistenceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shortlist storage is temporarily unavailable.",
        ) from exc

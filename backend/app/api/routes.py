import math
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status

from backend.app.auth import AuthenticatedUser, get_current_user
from backend.app.models.search import (
    ComparisonRequest,
    RouteDetailResponse,
    SaveShortlistRequest,
    SearchRequest,
    SearchResponse,
    SelectedRouteRequest,
    ShortlistItemResponse,
    ShortlistResponse,
    UpdateShortlistRequest,
)
from backend.app.repositories.base import RateLimitUsage
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
    ShortlistItemMissingError,
    ShortlistPersistenceUnavailableError,
    ShortlistService,
    get_shortlist_service,
)
from backend.app.services.rate_limit_service import (
    AnonymousSearchRateLimitService,
    RateLimitStorageUnavailableError,
    get_anonymous_search_rate_limit_service,
)

router = APIRouter()


async def enforce_anonymous_agent_request_limit(
    response: Response,
    user: AuthenticatedUser,
    service: AnonymousSearchRateLimitService,
) -> RateLimitUsage | None:
    try:
        usage = await service.consume_if_anonymous(user)
    except RateLimitStorageUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Anonymous request limits are temporarily unavailable.",
        ) from exc
    if usage is None:
        return None

    reset_epoch = str(int(usage.reset_at.timestamp()))
    headers = {
        "X-RateLimit-Limit": str(usage.limit),
        "X-RateLimit-Remaining": str(usage.remaining),
        "X-RateLimit-Reset": reset_epoch,
    }
    if not usage.allowed:
        retry_after = max(
            math.ceil(
                (usage.reset_at - datetime.now(timezone.utc)).total_seconds()
            ),
            1,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Anonymous search limit reached. Try again after the "
                "current rate-limit window resets."
            ),
            headers={**headers, "Retry-After": str(retry_after)},
        )

    for name, value in headers.items():
        response.headers[name] = value
    return usage


@router.post("/chat", response_model=SearchResponse, tags=["chat"])
async def chat(
    request: SearchRequest,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    rate_limit_service: AnonymousSearchRateLimitService = Depends(
        get_anonymous_search_rate_limit_service
    ),
    service: AgentService = Depends(get_agent_service),
) -> SearchResponse:
    await enforce_anonymous_agent_request_limit(
        response, user, rate_limit_service
    )
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


@router.post("/compare", response_model=SearchResponse, tags=["comparison"])
async def compare_listings(
    request: ComparisonRequest,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
    rate_limit_service: AnonymousSearchRateLimitService = Depends(
        get_anonymous_search_rate_limit_service
    ),
    service: AgentService = Depends(get_agent_service),
) -> SearchResponse:
    await enforce_anonymous_agent_request_limit(
        response, user, rate_limit_service
    )
    try:
        return await service.compare_listings(
            request.listingIds,
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
            detail="Rental comparison is temporarily unavailable.",
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


@router.patch(
    "/shortlist/{listing_id:path}",
    response_model=ShortlistItemResponse,
    tags=["shortlist"],
)
async def update_shortlist_item(
    request: UpdateShortlistRequest,
    listing_id: Annotated[str, Path(min_length=1, max_length=256)],
    user: AuthenticatedUser = Depends(get_current_user),
    service: ShortlistService = Depends(get_shortlist_service),
) -> ShortlistItemResponse:
    try:
        return await service.update_note(user.uid, listing_id, request.note)
    except ShortlistItemMissingError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The shortlist item was not found.",
        ) from exc
    except ShortlistPersistenceUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Shortlist storage is temporarily unavailable.",
        ) from exc

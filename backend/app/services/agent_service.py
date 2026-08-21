from __future__ import annotations

import asyncio
from functools import lru_cache
import logging
import math
import re
import time
from typing import Any, cast
from uuid import uuid4

from backend.app.config import AdkSessionMode, get_settings
from backend.app.models.search import (
    ComparisonResponse,
    CommuteEvaluationResponse,
    CommuteResponse,
    ListingResponse,
    RouteDetailResponse,
    SearchResponse,
    SourcePostingResponse,
)
from backend.app.repositories.base import (
    ConversationNotFoundError,
    ConversationOwnershipError,
    ConversationRepository,
    RepositoryError,
)
from backend.app.repositories.dependencies import get_conversation_repository
from backend.app.services.conversation_turns import ConversationTurnCoordinator


_CANONICAL_LISTING_SCHEMA = "kbf.canonical-listing.v1"
_CANONICAL_COMPARISON_SCHEMA = "kbf.canonical-comparison.v1"


logger = logging.getLogger("keys_by_friday.agent")


class AgentServiceError(RuntimeError):
    """Stable backend boundary for failures from the ADK execution path."""


class ConversationAccessError(AgentServiceError):
    """A user attempted to continue a conversation owned by another user."""


class PersistenceUnavailableError(AgentServiceError):
    """Conversation metadata persistence could not complete safely."""


_LOG_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_REALTYAPI_MULTI_SOURCES = ("apartments", "zillow", "realtor")


def _safe_log_token(value: object) -> str | None:
    """Keep dependency metadata useful without allowing arbitrary log content."""

    token = str(value).strip() if value is not None else ""
    return token if _LOG_TOKEN_PATTERN.fullmatch(token) else None


def _provider_log_fields(
    search_payload: dict[str, Any] | None,
    *,
    provider_latency_ms: float | None,
) -> dict[str, object]:
    """Build sanitized, non-secret fields for one listing-search tool result."""

    if search_payload is None:
        return {
            "tool": "search_listings",
            "provider": "not_called",
            "provider_status": "not_called",
            "provider_search_performed": False,
            "sources": [],
            "source_statuses": {},
            "failed_sources": [],
            "data_source": "not_applicable",
            "cache_status": "not_applicable",
        }

    provider = _safe_log_token(search_payload.get("provider")) or "unknown"
    data_source = _safe_log_token(search_payload.get("data_source")) or "unknown"
    network_call = search_payload.get("provider_search_performed") is True

    failed_value = search_payload.get("failed_sources", [])
    failed_sources = (
        [
            token
            for item in failed_value
            if (token := _safe_log_token(item)) is not None
        ]
        if isinstance(failed_value, (list, tuple))
        else []
    )

    if provider == "realtyapi-multi":
        sources = list(_REALTYAPI_MULTI_SOURCES)
    elif provider.startswith("realtyapi-"):
        source = _safe_log_token(provider.removeprefix("realtyapi-"))
        sources = [source] if source else []
    elif provider == "mock":
        sources = ["mock"]
    else:
        sources = []

    if not network_call:
        provider_status = "cache_hit"
        source_statuses = {source: "cache" for source in sources}
    else:
        provider_status = (
            "success"
            if search_payload.get("search_complete") is not False
            else "partial_failure"
        )
        failed = set(failed_sources)
        source_statuses = {
            source: "failed" if source in failed else "success"
            for source in sources
        }

    fields: dict[str, object] = {
        "tool": "search_listings",
        "provider": provider,
        "provider_status": provider_status,
        "provider_search_performed": network_call,
        "sources": sources,
        "source_statuses": source_statuses,
        "failed_sources": failed_sources,
        "data_source": data_source,
        "cache_status": "network" if network_call else "cache",
    }
    if provider_latency_ms is not None:
        fields["provider_latency_ms"] = round(provider_latency_ms, 2)
    return fields


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _canonical_listing(container: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(container, dict):
        return None
    payload = container.get("backend_listing")
    if not isinstance(payload, dict):
        return None
    if payload.get("schemaVersion") != _CANONICAL_LISTING_SCHEMA:
        return None
    return payload


def _canonical_section(
    listing: dict[str, Any], section: str
) -> dict[str, Any]:
    value = listing.get(section)
    return value if isinstance(value, dict) else {}


def _canonical_listing_id(container: dict[str, Any] | None) -> str | None:
    canonical = _canonical_listing(container)
    if canonical is None:
        return None
    listing_id = _canonical_section(canonical, "identity").get("id")
    normalized = str(listing_id).strip() if listing_id is not None else ""
    return normalized or None


def _commute_from_tool_payload(
    value: object, *, allow_empty_destination: bool = False
) -> CommuteResponse | None:
    if not isinstance(value, dict) or "destination" not in value:
        return None
    if not allow_empty_destination and not value.get("destination"):
        return None
    status = value.get("status")
    if status not in {"available", "unavailable", "unknown"}:
        return None
    duration = value.get("duration_minutes")
    distance = value.get("distance_meters")
    return CommuteResponse(
        destination=str(value["destination"]),
        destinationPlaceId=(
            str(value["destination_place_id"])
            if value.get("destination_place_id")
            else None
        ),
        mode=str(value["mode"]) if value.get("mode") else None,
        durationMinutes=int(duration) if isinstance(duration, (int, float)) else None,
        distanceMeters=int(distance) if isinstance(distance, (int, float)) else None,
        status=status,
        routingPreference=(
            str(value["routing_preference"]) if value.get("routing_preference") else None
        ),
    )


def _commute_evaluation_from_tool_payload(
    value: object,
) -> CommuteEvaluationResponse | None:
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if status not in {
        "not_requested",
        "requires_input",
        "available",
        "partial",
        "unavailable",
        "unknown",
    }:
        return None

    def count(name: str) -> int:
        raw = value.get(name, 0)
        return int(raw) if isinstance(raw, (int, float)) and raw >= 0 else 0

    return CommuteEvaluationResponse(
        status=status,
        evaluatedCount=count("evaluated_count"),
        availableCount=count("available_count"),
        unavailableCount=count("unavailable_count"),
        unknownCount=count("unknown_count"),
        withinLimitCount=count("within_limit_count"),
        overLimitCount=count("over_limit_count"),
    )


def _comparison_from_tool_payload(value: object) -> ComparisonResponse | None:
    if not isinstance(value, dict):
        return None
    if value.get("schemaVersion") != _CANONICAL_COMPARISON_SCHEMA:
        return None
    try:
        return ComparisonResponse.model_validate(value)
    except ValueError:
        return None


def _route_from_tool_payload(value: object) -> RouteDetailResponse | None:
    if not isinstance(value, dict) or value.get("listing_id") is None:
        return None
    commute = _commute_from_tool_payload(value, allow_empty_destination=True)
    if commute is None:
        return None
    return RouteDetailResponse(
        **commute.model_dump(),
        listingId=str(value["listing_id"]),
        encodedPolyline=(
            str(value["encoded_polyline"]) if value.get("encoded_polyline") else None
        ),
    )


def _listing_from_tool_payload(
    listing: dict[str, Any],
    ranked: dict[str, Any] | None = None,
    *,
    canonical: dict[str, Any] | None = None,
    rank: int | None = None,
    source_postings: list[SourcePostingResponse] | None = None,
) -> ListingResponse | None:
    if canonical is not None:
        identity = _canonical_section(canonical, "identity")
        location = _canonical_section(canonical, "location")
        pricing = _canonical_section(canonical, "pricing")
        property_data = _canonical_section(canonical, "property")
        source = _canonical_section(canonical, "source")
        listing_id = identity.get("id")
        if listing_id is None or not str(listing_id).strip():
            return None
        reasons = ranked.get("reasons", []) if ranked else []
        reason = (
            "; ".join(str(item) for item in reasons if item)
            if isinstance(reasons, list)
            else None
        )
        address = location.get("address")
        property_name = identity.get("propertyName")
        commute = _commute_from_tool_payload(ranked.get("commute")) if ranked else None
        return ListingResponse(
            id=str(listing_id),
            title=str(property_name or address) if property_name or address else None,
            address=str(address) if address else None,
            price=_optional_float(pricing.get("rent")),
            priceMin=_optional_float(pricing.get("rentMin")),
            priceMax=_optional_float(pricing.get("rentMax")),
            bedrooms=_optional_float(property_data.get("bedrooms")),
            bedroomsMin=_optional_float(property_data.get("bedroomsMin")),
            bedroomsMax=_optional_float(property_data.get("bedroomsMax")),
            bathrooms=_optional_float(property_data.get("bathrooms")),
            bathroomsMinEvidence=_optional_float(
                property_data.get("bathroomsMinEvidence")
            ),
            latitude=_optional_float(location.get("latitude")),
            longitude=_optional_float(location.get("longitude")),
            url=str(source.get("url")) if source.get("url") else None,
            score=_optional_float(ranked.get("score")) if ranked else None,
            reason=reason or None,
            rank=rank,
            sourcePostings=source_postings or [],
            commute=commute,
        )

    listing_id = listing.get("id")
    if listing_id is None:
        return None

    reasons = ranked.get("reasons", []) if ranked else []
    reason = "; ".join(str(item) for item in reasons if item) if isinstance(reasons, list) else None
    address = listing.get("address")
    property_name = listing.get("property_name")
    commute = _commute_from_tool_payload(ranked.get("commute")) if ranked else None

    return ListingResponse(
        id=str(listing_id),
        title=str(property_name or address) if property_name or address else None,
        address=str(address) if address else None,
        price=_optional_float(listing.get("rent")),
        priceMin=_optional_float(listing.get("rent_min")),
        priceMax=_optional_float(listing.get("rent_max")),
        bedrooms=_optional_float(listing.get("bedrooms")),
        bedroomsMin=_optional_float(listing.get("bedrooms_min")),
        bedroomsMax=_optional_float(listing.get("bedrooms_max")),
        bathrooms=_optional_float(listing.get("bathrooms")),
        bathroomsMinEvidence=_optional_float(listing.get("bathrooms_min_evidence")),
        latitude=_optional_float(listing.get("latitude")),
        longitude=_optional_float(listing.get("longitude")),
        url=str(listing.get("source_url")) if listing.get("source_url") else None,
        score=_optional_float(ranked.get("score")) if ranked else None,
        reason=reason or None,
        rank=rank,
        sourcePostings=source_postings or [],
        commute=commute,
    )


def _source_posting_from_tool_payload(
    posting: dict[str, Any],
) -> SourcePostingResponse | None:
    canonical = _canonical_listing(posting)
    if canonical is not None:
        identity = _canonical_section(canonical, "identity")
        pricing = _canonical_section(canonical, "pricing")
        property_data = _canonical_section(canonical, "property")
        source = _canonical_section(canonical, "source")
        listing_id = identity.get("id")
        if listing_id is None or not str(listing_id).strip():
            return None
        return SourcePostingResponse(
            id=str(listing_id),
            source=str(source.get("provider")) if source.get("provider") else None,
            label=str(posting.get("source_label")) if posting.get("source_label") else None,
            url=str(source.get("url")) if source.get("url") else None,
            price=_optional_float(pricing.get("rent")),
            priceMin=_optional_float(pricing.get("rentMin")),
            priceMax=_optional_float(pricing.get("rentMax")),
            bedrooms=_optional_float(property_data.get("bedrooms")),
            bedroomsMin=_optional_float(property_data.get("bedroomsMin")),
            bedroomsMax=_optional_float(property_data.get("bedroomsMax")),
            bathrooms=_optional_float(property_data.get("bathrooms")),
            bathroomsMinEvidence=_optional_float(
                property_data.get("bathroomsMinEvidence")
            ),
        )

    listing = posting.get("listing")
    if (
        not isinstance(listing, dict)
        or listing.get("id") is None
        or not str(listing.get("id")).strip()
    ):
        return None
    return SourcePostingResponse(
        id=str(listing["id"]),
        source=str(listing.get("source")) if listing.get("source") else None,
        label=str(posting.get("source_label")) if posting.get("source_label") else None,
        url=str(listing.get("source_url")) if listing.get("source_url") else None,
        price=_optional_float(listing.get("rent")),
        priceMin=_optional_float(listing.get("rent_min")),
        priceMax=_optional_float(listing.get("rent_max")),
        bedrooms=_optional_float(listing.get("bedrooms")),
        bedroomsMin=_optional_float(listing.get("bedrooms_min")),
        bedroomsMax=_optional_float(listing.get("bedrooms_max")),
        bathrooms=_optional_float(listing.get("bathrooms")),
        bathroomsMinEvidence=_optional_float(listing.get("bathrooms_min_evidence")),
    )


def _normalize_tool_listings(
    search_payload: dict[str, Any] | None,
    detail_payloads: list[dict[str, Any]],
) -> list[ListingResponse]:
    detail_by_id: dict[str, dict[str, Any]] = {}
    rejected_ids: set[str] = set()
    for payload in detail_payloads:
        listing = payload.get("listing")
        canonical_id = _canonical_listing_id(payload)
        legacy_id = (
            str(listing["id"])
            if isinstance(listing, dict) and listing.get("id") is not None
            else None
        )
        listing_id = canonical_id or legacy_id
        if listing_id is not None:
            detail_by_id[listing_id] = payload
            verification = payload.get("verification")
            if (
                isinstance(verification, dict)
                and verification.get("passes_current_hard_filters") is False
            ):
                rejected_ids.add(listing_id)

    results: list[ListingResponse] = []
    seen: set[str] = set()

    groups = search_payload.get("property_groups", []) if search_payload else []
    if isinstance(groups, list):
        for group in groups[:5]:
            if not isinstance(group, dict):
                continue
            representative = group.get("representative")
            if not isinstance(representative, dict):
                continue
            listing = representative.get("listing")
            if not isinstance(listing, dict) or listing.get("id") is None:
                continue
            listing_id = str(listing["id"])
            if listing_id in rejected_ids:
                continue

            postings_payload = group.get("postings", [])
            source_postings: list[SourcePostingResponse] = []
            if isinstance(postings_payload, list):
                for posting in postings_payload:
                    if not isinstance(posting, dict):
                        continue
                    normalized_posting = _source_posting_from_tool_payload(posting)
                    if normalized_posting is not None:
                        source_postings.append(normalized_posting)

            rank_value = group.get("rank")
            rank = int(rank_value) if isinstance(rank_value, (int, float)) else None
            normalized = _listing_from_tool_payload(
                (
                    detail_by_id[listing_id].get("listing", listing)
                    if listing_id in detail_by_id
                    else listing
                ),
                representative,
                canonical=(
                    _canonical_listing(detail_by_id[listing_id])
                    if listing_id in detail_by_id
                    else _canonical_listing(representative)
                ),
                rank=rank,
                source_postings=source_postings,
            )
            if normalized is not None and normalized.id not in seen:
                results.append(normalized)
                seen.add(normalized.id)

    if results:
        return results

    ranked_items = search_payload.get("top_5", []) if search_payload else []

    if isinstance(ranked_items, list):
        for ranked in ranked_items:
            if not isinstance(ranked, dict):
                continue
            listing = ranked.get("listing")
            if not isinstance(listing, dict) or listing.get("id") is None:
                continue
            listing_id = str(listing["id"])
            if listing_id in rejected_ids:
                continue
            normalized = _listing_from_tool_payload(
                (
                    detail_by_id[listing_id].get("listing", listing)
                    if listing_id in detail_by_id
                    else listing
                ),
                ranked,
                canonical=(
                    _canonical_listing(detail_by_id[listing_id])
                    if listing_id in detail_by_id
                    else _canonical_listing(ranked)
                ),
            )
            if normalized is not None and normalized.id not in seen:
                results.append(normalized)
                seen.add(normalized.id)

    if not results:
        for payload in detail_payloads:
            listing = payload.get("listing")
            if not isinstance(listing, dict):
                continue
            normalized = _listing_from_tool_payload(
                listing, canonical=_canonical_listing(payload)
            )
            if (
                normalized is not None
                and normalized.id not in rejected_ids
                and normalized.id not in seen
            ):
                results.append(normalized)
                seen.add(normalized.id)

    return results


class AgentService:
    def __init__(
        self,
        mode: str | None = None,
        timeout_seconds: float | None = None,
        conversation_repository: ConversationRepository | None = None,
        session_mode: str | None = None,
        session_database_url: str | None = None,
        runner: Any | None = None,
    ) -> None:
        settings = get_settings()
        self.mode = (mode or settings.agent_mode).strip().lower()
        if self.mode not in {"adk", "stub"}:
            raise ValueError("AGENT_MODE must be 'adk' or 'stub'.")
        self.timeout_seconds = (
            settings.agent_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError(
                "Agent timeout must be a finite number greater than zero."
            )
        configured_session_mode = (
            session_mode or settings.adk_session_mode
        ).strip().lower()
        if configured_session_mode not in {"memory", "database"}:
            raise ValueError("ADK_SESSION_MODE must be 'memory' or 'database'.")
        self.session_mode = cast(AdkSessionMode, configured_session_mode)
        self._session_database_url = (
            settings.adk_session_database_url
            if session_database_url is None
            else session_database_url
        )
        self._runner = runner
        self._turns = ConversationTurnCoordinator()
        if conversation_repository is None:
            from backend.app.repositories.memory import (
                MemoryConversationRepository,
            )

            conversation_repository = MemoryConversationRepository()
        self._conversations = conversation_repository

    def _get_runner(self):
        if self._runner is None:
            from backend.app.adk_runtime import (
                AdkRuntimeConfigurationError,
                create_adk_runner,
            )

            try:
                self._runner = create_adk_runner(
                    mode=self.session_mode,
                    database_url=self._session_database_url,
                )
            except AdkRuntimeConfigurationError:
                raise AgentServiceError(
                    "ADK session storage could not be initialized"
                ) from None
        return self._runner

    async def _claim_conversation(
        self, conversation_id: str, user_id: str
    ) -> None:
        try:
            await self._conversations.claim(conversation_id, user_id)
        except ConversationOwnershipError as exc:
            raise ConversationAccessError(
                "Conversation is owned by a different user."
            ) from exc
        except RepositoryError as exc:
            raise PersistenceUnavailableError(
                "Conversation metadata could not be stored."
            ) from exc

    async def _record_conversation_response(
        self,
        response: SearchResponse,
        *,
        user_id: str,
    ) -> None:
        try:
            await self._conversations.record_response(
                response.conversationId,
                user_id,
                listings=[
                    listing.model_dump(mode="json")
                    for listing in response.listings
                ],
                commute_status=(
                    response.commuteEvaluation.status
                    if response.commuteEvaluation is not None
                    else None
                ),
                route_listing_id=(
                    response.route.listingId
                    if response.route is not None
                    else None
                ),
            )
        except ConversationOwnershipError as exc:
            raise ConversationAccessError(
                "Conversation is owned by a different user."
            ) from exc
        except (ConversationNotFoundError, RepositoryError) as exc:
            raise PersistenceUnavailableError(
                "Conversation metadata could not be updated."
            ) from exc

    async def send_message(
        self,
        message: str,
        conversation_id: str | None = None,
        *,
        user_id: str,
    ) -> SearchResponse:
        conversation_id = conversation_id or str(uuid4())
        await self._claim_conversation(conversation_id, user_id)
        async with self._turns.hold(user_id, conversation_id):
            return await self._send_message_locked(
                message, conversation_id, user_id=user_id
            )

    async def _send_message_locked(
        self,
        message: str,
        conversation_id: str,
        *,
        user_id: str,
    ) -> SearchResponse:
        if self.mode == "stub":
            response = SearchResponse(
                conversationId=conversation_id,
                message=f"Development stub is active. received: {message}",
                listings=[],
                mode="stub",
            )
            await self._record_conversation_response(response, user_id=user_id)
            return response

        started = time.perf_counter()
        logger.info(
            "agent request started",
            extra={"conversation_id": conversation_id, "mode": self.mode},
        )
        try:
            response = await asyncio.wait_for(
                self._send_adk_message(message, conversation_id, user_id),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            logger.warning(
                "agent request timed out",
                extra={
                    "conversation_id": conversation_id,
                    "mode": self.mode,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000, 2
                    ),
                },
            )
            raise AgentServiceError("ADK execution timed out") from exc

        await self._record_conversation_response(response, user_id=user_id)
        logger.info(
            "agent request completed",
            extra={
                "conversation_id": conversation_id,
                "mode": self.mode,
                "listing_count": len(response.listings),
                "duration_ms": round(
                    (time.perf_counter() - started) * 1000, 2
                ),
            },
        )
        return response

    async def _send_adk_message(
        self, message: str, conversation_id: str, user_id: str
    ) -> SearchResponse:

        from google.genai import types

        try:
            runner = self._get_runner()
            session = await runner.session_service.get_session(
                app_name=runner.app_name, user_id=user_id, session_id=conversation_id
            )
            if session is None:
                await runner.session_service.create_session(
                    app_name=runner.app_name, user_id=user_id, session_id=conversation_id
                )

            content = types.Content(role="user", parts=[types.Part(text=message)])
            final_text = ""
            search_payload: dict[str, Any] | None = None
            detail_payloads: list[dict[str, Any]] = []
            route_payload: dict[str, Any] | None = None
            comparison_payload: dict[str, Any] | None = None
            models: list[str] = []
            search_started_at: float | None = None
            provider_latency_ms: float | None = None

            async for event in runner.run_async(
                user_id=user_id, session_id=conversation_id, new_message=content
            ):
                model = _safe_log_token(getattr(event, "model_version", None))
                if model and model not in models:
                    models.append(model)

                for function_call in event.get_function_calls():
                    if function_call.name == "search_listings":
                        search_started_at = time.perf_counter()

                for function_response in event.get_function_responses():
                    payload = function_response.response
                    if not isinstance(payload, dict):
                        continue
                    if function_response.name == "search_listings":
                        search_payload = payload
                        if search_started_at is not None:
                            provider_latency_ms = (
                                time.perf_counter() - search_started_at
                            ) * 1000
                    elif function_response.name == "get_listing_details":
                        detail_payloads.append(payload)
                    elif function_response.name == "get_route_details":
                        route_payload = payload
                    elif function_response.name == "compare_candidates":
                        comparison_payload = payload

                if event.is_final_response() and event.content:
                    final_text = "".join(
                        part.text or "" for part in event.content.parts if part.text
                    ).strip()
        except Exception as exc:
            logger.exception(
                "agent execution failed",
                extra={"conversation_id": conversation_id, "mode": self.mode},
            )
            raise AgentServiceError("ADK execution failed") from exc

        if not final_text:
            raise AgentServiceError("ADK agent completed without a final response")

        logger.info(
            "agent dependency telemetry",
            extra={
                "conversation_id": conversation_id,
                "mode": self.mode,
                "models": models,
                **_provider_log_fields(
                    search_payload,
                    provider_latency_ms=provider_latency_ms,
                ),
            },
        )

        return SearchResponse(
            conversationId=conversation_id,
            message=final_text,
            listings=_normalize_tool_listings(search_payload, detail_payloads),
            commuteEvaluation=_commute_evaluation_from_tool_payload(
                search_payload.get("commute_summary") if search_payload else None
            ),
            route=_route_from_tool_payload(route_payload),
            comparison=_comparison_from_tool_payload(comparison_payload),
            mode="adk",
        )

    async def get_selected_route(
        self,
        listing_id: str,
        conversation_id: str,
        *,
        destination: str = "",
        mode: str = "",
        user_id: str,
    ) -> RouteDetailResponse:
        from rental_agent.agent import _route_details_from_state

        await self._claim_conversation(conversation_id, user_id)
        async with self._turns.hold(user_id, conversation_id):
            state: object = {}
            if self.mode == "adk":
                runner = self._get_runner()
                try:
                    session = await runner.session_service.get_session(
                        app_name=runner.app_name,
                        user_id=user_id,
                        session_id=conversation_id,
                    )
                except Exception as exc:
                    raise AgentServiceError("ADK session lookup failed") from exc
                if session is not None:
                    state = session.state

            payload = _route_details_from_state(
                listing_id, destination, mode, state
            )
            route = _route_from_tool_payload(payload)
            if route is None:
                raise AgentServiceError("Route detail normalization failed")
            return route


@lru_cache(maxsize=1)
def get_agent_service() -> AgentService:
    return AgentService(
        conversation_repository=get_conversation_repository()
    )

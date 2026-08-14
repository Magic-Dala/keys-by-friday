from __future__ import annotations

from functools import lru_cache
from typing import Any
from uuid import uuid4

from backend.app.config import get_settings
from backend.app.models.search import ListingResponse, SearchResponse, SourcePostingResponse


class AgentServiceError(RuntimeError):
    """Stable backend boundary for failures from the ADK execution path."""


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _listing_from_tool_payload(
    listing: dict[str, Any],
    ranked: dict[str, Any] | None = None,
    *,
    rank: int | None = None,
    source_postings: list[SourcePostingResponse] | None = None,
) -> ListingResponse | None:
    listing_id = listing.get("id")
    if listing_id is None:
        return None

    reasons = ranked.get("reasons", []) if ranked else []
    reason = "; ".join(str(item) for item in reasons if item) if isinstance(reasons, list) else None
    address = listing.get("address")
    property_name = listing.get("property_name")

    return ListingResponse(
        id=str(listing_id),
        title=str(property_name or address) if property_name or address else None,
        address=str(address) if address else None,
        price=_optional_float(listing.get("rent")),
        bedrooms=_optional_float(listing.get("bedrooms")),
        bathrooms=_optional_float(listing.get("bathrooms")),
        url=str(listing.get("source_url")) if listing.get("source_url") else None,
        score=_optional_float(ranked.get("score")) if ranked else None,
        reason=reason or None,
        rank=rank,
        sourcePostings=source_postings or [],
    )


def _source_posting_from_tool_payload(
    posting: dict[str, Any],
) -> SourcePostingResponse | None:
    listing = posting.get("listing")
    if not isinstance(listing, dict) or listing.get("id") is None:
        return None
    return SourcePostingResponse(
        id=str(listing["id"]),
        source=str(listing.get("source")) if listing.get("source") else None,
        label=str(posting.get("source_label")) if posting.get("source_label") else None,
        url=str(listing.get("source_url")) if listing.get("source_url") else None,
        price=_optional_float(listing.get("rent")),
        bedrooms=_optional_float(listing.get("bedrooms")),
        bathrooms=_optional_float(listing.get("bathrooms")),
    )


def _normalize_tool_listings(
    search_payload: dict[str, Any] | None,
    detail_payloads: list[dict[str, Any]],
) -> list[ListingResponse]:
    detail_by_id: dict[str, dict[str, Any]] = {}
    rejected_ids: set[str] = set()
    for payload in detail_payloads:
        listing = payload.get("listing")
        if isinstance(listing, dict) and listing.get("id") is not None:
            listing_id = str(listing["id"])
            detail_by_id[listing_id] = listing
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
                detail_by_id.get(listing_id, listing),
                representative,
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
                detail_by_id.get(listing_id, listing), ranked
            )
            if normalized is not None and normalized.id not in seen:
                results.append(normalized)
                seen.add(normalized.id)

    if not results:
        for payload in detail_payloads:
            listing = payload.get("listing")
            if not isinstance(listing, dict):
                continue
            normalized = _listing_from_tool_payload(listing)
            if (
                normalized is not None
                and normalized.id not in rejected_ids
                and normalized.id not in seen
            ):
                results.append(normalized)
                seen.add(normalized.id)

    return results


class AgentService:
    def __init__(self, mode: str | None = None) -> None:
        self.mode = (mode or get_settings().agent_mode).strip().lower()
        if self.mode not in {"adk", "stub"}:
            raise ValueError("AGENT_MODE must be 'adk' or 'stub'.")
        self._runner = None

    def _get_runner(self):
        if self._runner is None:
            from google.adk.runners import InMemoryRunner
            from rental_agent.agent import root_agent

            self._runner = InMemoryRunner(agent=root_agent, app_name="keys_by_friday_web")
        return self._runner

    async def send_message(self, message: str, conversation_id: str | None = None) -> SearchResponse:
        conversation_id = conversation_id or str(uuid4())
        if self.mode == "stub":
            return SearchResponse(
                conversationId=conversation_id,
                message=f"Development stub is active. received: {message}",
                listings=[],
                mode="stub",
            )

        from google.genai import types

        runner = self._get_runner()
        user_id = "web-user"
        try:
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

            async for event in runner.run_async(
                user_id=user_id, session_id=conversation_id, new_message=content
            ):
                for function_response in event.get_function_responses():
                    payload = function_response.response
                    if not isinstance(payload, dict):
                        continue
                    if function_response.name == "search_listings":
                        search_payload = payload
                    elif function_response.name == "get_listing_details":
                        detail_payloads.append(payload)

                if event.is_final_response() and event.content:
                    final_text = "".join(
                        part.text or "" for part in event.content.parts if part.text
                    ).strip()
        except Exception as exc:
            raise AgentServiceError("ADK execution failed") from exc

        if not final_text:
            raise AgentServiceError("ADK agent completed without a final response")

        return SearchResponse(
            conversationId=conversation_id,
            message=final_text,
            listings=_normalize_tool_listings(search_payload, detail_payloads),
            mode="adk",
        )


@lru_cache(maxsize=1)
def get_agent_service() -> AgentService:
    return AgentService()

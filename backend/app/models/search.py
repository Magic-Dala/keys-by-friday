from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SourcePostingResponse(BaseModel):
    id: str
    source: str | None = None
    label: str | None = None
    url: str | None = None
    price: float | None = None
    priceMin: float | None = None
    priceMax: float | None = None
    bedrooms: float | None = None
    bedroomsMin: float | None = None
    bedroomsMax: float | None = None
    bathrooms: float | None = None
    bathroomsMinEvidence: float | None = None


class CommuteResponse(BaseModel):
    destination: str
    destinationPlaceId: str | None = None
    mode: str | None = None
    durationMinutes: int | None = None
    distanceMeters: int | None = None
    status: Literal["available", "unavailable", "unknown"]
    routingPreference: str | None = None


class CommuteEvaluationResponse(BaseModel):
    status: Literal[
        "not_requested", "requires_input", "available", "partial", "unavailable", "unknown"
    ]
    evaluatedCount: int = 0
    availableCount: int = 0
    unavailableCount: int = 0
    unknownCount: int = 0
    withinLimitCount: int = 0
    overLimitCount: int = 0


class RouteDetailResponse(CommuteResponse):
    listingId: str
    encodedPolyline: str | None = None


class SelectedRouteRequest(BaseModel):
    listingId: str = Field(min_length=1, max_length=256)
    conversationId: str = Field(min_length=1, max_length=128)
    destination: str | None = Field(default=None, max_length=512)
    mode: str | None = Field(default=None, max_length=32)

    @field_validator("listingId", "conversationId")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("destination", "mode")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ListingResponse(BaseModel):
    id: str
    title: str | None = None
    address: str | None = None
    price: float | None = None
    priceMin: float | None = None
    priceMax: float | None = None
    bedrooms: float | None = None
    bedroomsMin: float | None = None
    bedroomsMax: float | None = None
    bathrooms: float | None = None
    bathroomsMinEvidence: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    url: str | None = None
    score: float | None = None
    reason: str | None = None
    rank: int | None = None
    sourcePostings: list[SourcePostingResponse] = Field(default_factory=list)
    commute: CommuteResponse | None = None


class SearchRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversationId: str | None = Field(default=None, max_length=128)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized

    @field_validator("conversationId")
    @classmethod
    def normalize_conversation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SearchResponse(BaseModel):
    conversationId: str
    message: str
    listings: list[ListingResponse] = Field(default_factory=list)
    commuteEvaluation: CommuteEvaluationResponse | None = None
    route: RouteDetailResponse | None = None
    mode: Literal["adk", "stub"]


class RecentSearchResponse(BaseModel):
    conversationId: str
    createdAt: datetime
    updatedAt: datetime
    turnCount: int = Field(ge=1)
    listings: list[ListingResponse] = Field(default_factory=list)
    lastCommuteStatus: str | None = None


class RecentSearchesResponse(BaseModel):
    items: list[RecentSearchResponse] = Field(default_factory=list)


class SaveShortlistRequest(BaseModel):
    listingId: str = Field(min_length=1, max_length=256)
    conversationId: str = Field(min_length=1, max_length=128)

    @field_validator("listingId", "conversationId")
    @classmethod
    def normalize_shortlist_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class ShortlistItemResponse(BaseModel):
    listing: ListingResponse
    sourceConversationId: str
    savedAt: datetime
    updatedAt: datetime


class ShortlistResponse(BaseModel):
    items: list[ShortlistItemResponse] = Field(default_factory=list)

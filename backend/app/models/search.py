from datetime import datetime
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AdditiveContractModel(BaseModel):
    """A versioned contract that keeps future additive fields intact."""

    model_config = ConfigDict(extra="allow")


class CanonicalIdentityResponse(AdditiveContractModel):
    id: str
    sourceListingId: str | None = None
    propertyName: str | None = None


class CanonicalLocationResponse(AdditiveContractModel):
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zipCode: str | None = None
    countryCode: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class CanonicalPricingResponse(AdditiveContractModel):
    rent: float | None = None
    rentMin: float | None = None
    rentMax: float | None = None


class CanonicalPropertyResponse(AdditiveContractModel):
    bedrooms: float | None = None
    bedroomsMin: float | None = None
    bedroomsMax: float | None = None
    bathrooms: float | None = None
    bathroomsMinEvidence: float | None = None
    propertyType: str | None = None


class CanonicalListingResponse(AdditiveContractModel):
    """The frozen Agent -> Backend listing contract."""

    schemaVersion: Literal["kbf.canonical-listing.v1"]
    identity: CanonicalIdentityResponse
    location: CanonicalLocationResponse
    pricing: CanonicalPricingResponse
    property: CanonicalPropertyResponse
    availability: dict[str, Any]
    policies: dict[str, Any]
    features: dict[str, Any]
    media: dict[str, Any]
    contact: dict[str, Any]
    source: dict[str, Any]
    evidence: dict[str, Any]
    completeness: dict[str, Any]


class CanonicalComparisonResultResponse(AdditiveContractModel):
    listingId: str
    hardConstraintStatus: Literal["pass", "fail", "evidence_only", "unknown"]
    satisfiesCurrentRequirements: bool | None = None
    softPreferenceEvidence: list[dict[str, Any]] = Field(default_factory=list)
    tradeoffs: list[str | dict[str, Any]] = Field(default_factory=list)
    comparisonUnknowns: list[str] = Field(default_factory=list)
    decisionUnknowns: list[str] = Field(default_factory=list)
    decisionReady: bool
    score: float | None = None
    rank: int | None = None


class CanonicalComparisonResponse(AdditiveContractModel):
    """Deterministic facts produced by the Agent comparison tool."""

    schemaVersion: Literal["kbf.canonical-comparison.v1"]
    listingIds: list[str]
    results: list[CanonicalComparisonResultResponse]


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


class ComparisonResultResponse(BaseModel):
    listingId: str
    hardConstraintStatus: Literal["pass", "fail", "evidence_only", "unknown"]
    satisfiesCurrentRequirements: bool | None = None
    softPreferenceEvidence: list[dict[str, Any]] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    comparisonUnknowns: list[str] = Field(default_factory=list)
    decisionUnknowns: list[str] = Field(default_factory=list)
    decisionReady: bool = False
    score: float | None = None
    rank: int | None = None


class ComparisonResponse(BaseModel):
    schemaVersion: Literal["kbf.canonical-comparison.v1"]
    listingIds: list[str] = Field(default_factory=list)
    results: list[ComparisonResultResponse] = Field(default_factory=list)


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
    canonicalListing: CanonicalListingResponse | None = None


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


class SearchRequirementsResponse(BaseModel):
    city: str | None = None
    state: str | None = None
    maxRent: float | None = None
    minBedrooms: float | None = None
    maxBedrooms: float | None = None
    minBathrooms: float | None = None
    maxBathrooms: float | None = None
    petsRequired: bool | None = None
    parkingRequired: bool | None = None
    commuteDestination: str | None = None
    maxCommuteMinutes: float | None = None
    commuteTravelMode: str | None = None
    softPreferences: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    conversationId: str
    message: str
    listings: list[ListingResponse] = Field(default_factory=list)
    requirements: SearchRequirementsResponse | None = None
    missingRequirements: list[str] = Field(default_factory=list)
    commuteEvaluation: CommuteEvaluationResponse | None = None
    route: RouteDetailResponse | None = None
    comparison: CanonicalComparisonResponse | None = None
    searchPerformed: bool = False
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


class ComparisonRequest(BaseModel):
    listingIds: list[str] = Field(min_length=2, max_length=4)
    conversationId: str = Field(min_length=1, max_length=128)

    @field_validator("listingIds")
    @classmethod
    def normalize_listing_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item or len(item) > 256 for item in normalized):
            raise ValueError("listing IDs must contain 1 to 256 characters")
        if any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", item) is None
            for item in normalized
        ):
            raise ValueError("listing IDs contain unsupported characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("listing IDs must be unique")
        return normalized

    @field_validator("conversationId")
    @classmethod
    def normalize_comparison_conversation_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


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


class UpdateShortlistRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ShortlistItemResponse(BaseModel):
    listing: ListingResponse
    sourceConversationId: str
    note: str | None = None
    savedAt: datetime
    updatedAt: datetime


class ShortlistResponse(BaseModel):
    items: list[ShortlistItemResponse] = Field(default_factory=list)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SearchRequirements:
    city: str
    state: str = "CA"
    max_rent: float | None = None
    min_bedrooms: float | None = None
    max_bedrooms: float | None = None
    min_bathrooms: float | None = None
    max_bathrooms: float | None = None
    pets_required: bool = False
    parking_required: bool = False
    soft_preferences: tuple[str, ...] = ()
    limit: int = 50


@dataclass(frozen=True)
class Listing:
    id: str
    address: str
    city: str
    state: str
    zip_code: str | None
    rent: float | None
    bedrooms: float | None
    bathrooms: float | None
    property_type: str | None = None
    square_footage: float | None = None
    status: str | None = None
    listed_date: datetime | None = None
    last_seen_date: datetime | None = None
    pets_allowed: bool | None = None
    parking_available: bool | None = None
    source_url: str | None = None
    source: str = "unknown"
    property_name: str | None = None
    availability: str | None = None
    year_built: int | None = None
    amenities: tuple[str, ...] = ()
    pet_policy: str | None = None
    parking_policy: str | None = None
    detail_verified: bool = False
    bathrooms_min_evidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("listed_date", "last_seen_date"):
            value = data[key]
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data


@dataclass(frozen=True)
class RankedListing:
    listing: Listing
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    tradeoffs: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing": self.listing.to_dict(),
            "score": round(self.score, 2),
            "reasons": list(self.reasons),
            "tradeoffs": list(self.tradeoffs),
        }

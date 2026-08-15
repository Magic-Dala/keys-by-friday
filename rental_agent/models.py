from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from rental_agent.commute import CommuteResult


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
    commute_destination: str | None = None
    max_commute_minutes: float | None = None
    commute_travel_mode: str | None = None
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
    rent_is_exact: bool | None = None
    bedrooms_is_exact: bool | None = None
    source_listing_id: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    primary_image_url: str | None = None
    rent_min: float | None = None
    rent_max: float | None = None
    bedrooms_min: float | None = None
    bedrooms_max: float | None = None
    days_on_market: int | None = None
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
    phone: str | None = None
    rating: float | None = None
    multimedia_url: str | None = None
    virtual_tour_url: str | None = None
    has_availability: bool | None = None
    is_multifamily: bool | None = None
    attachment_count: int | None = None
    specialties: tuple[str, ...] = ()
    property_manager_name: str | None = None
    property_manager_company_id: str | None = None
    has_lead_email: bool | None = None
    description: str | None = None
    rent_deals_count: int | None = None
    query_backed_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("listed_date", "last_seen_date"):
            value = data[key]
            if isinstance(value, datetime):
                data[key] = value.isoformat()
        return data

    def to_backend_dict(self) -> dict[str, Any]:
        """Stable, provider-agnostic handoff for backend persistence/API mapping."""

        def iso(value: datetime | None) -> str | None:
            return value.isoformat() if isinstance(value, datetime) else None

        def canonical_bounds(
            minimum: float | None, maximum: float | None
        ) -> tuple[float | None, float | None]:
            if minimum is not None and maximum is not None and minimum > maximum:
                return None, None
            return minimum, maximum

        def canonical_exact(
            value: float | None,
            minimum: float | None,
            maximum: float | None,
            is_exact: bool | None,
            bounds_invalid: bool,
        ) -> float | None:
            if is_exact is True:
                return value
            if bounds_invalid:
                return None
            if minimum is not None or maximum is not None:
                if minimum is not None and maximum is not None and minimum == maximum:
                    return minimum
                return None
            return value

        rent_bounds_invalid = (
            self.rent_min is not None
            and self.rent_max is not None
            and self.rent_min > self.rent_max
        )
        bedrooms_bounds_invalid = (
            self.bedrooms_min is not None
            and self.bedrooms_max is not None
            and self.bedrooms_min > self.bedrooms_max
        )
        rent_min, rent_max = canonical_bounds(self.rent_min, self.rent_max)
        bedrooms_min, bedrooms_max = canonical_bounds(
            self.bedrooms_min, self.bedrooms_max
        )
        exact_rent = canonical_exact(
            self.rent,
            rent_min,
            rent_max,
            self.rent_is_exact,
            rent_bounds_invalid,
        )
        exact_bedrooms = canonical_exact(
            self.bedrooms,
            bedrooms_min,
            bedrooms_max,
            self.bedrooms_is_exact,
            bedrooms_bounds_invalid,
        )

        sections: dict[str, dict[str, Any]] = {
            "identity": {
                "id": self.id,
                "sourceListingId": self.source_listing_id,
                "propertyName": self.property_name,
            },
            "location": {
                "address": self.address,
                "city": self.city,
                "state": self.state,
                "zipCode": self.zip_code,
                "countryCode": self.country_code,
                "latitude": self.latitude,
                "longitude": self.longitude,
            },
            "pricing": {
                "rent": exact_rent,
                "rentMin": rent_min,
                "rentMax": rent_max,
            },
            "property": {
                "bedrooms": exact_bedrooms,
                "bedroomsMin": bedrooms_min,
                "bedroomsMax": bedrooms_max,
                "bathrooms": self.bathrooms,
                "bathroomsMinEvidence": self.bathrooms_min_evidence,
                "propertyType": self.property_type,
                "squareFootage": self.square_footage,
                "yearBuilt": self.year_built,
                "isMultifamily": self.is_multifamily,
                "rating": self.rating,
                "description": self.description,
            },
            "availability": {
                "status": self.status,
                "availabilityText": self.availability,
                "hasAvailability": self.has_availability,
                "listedAt": iso(self.listed_date),
                "lastSeenAt": iso(self.last_seen_date),
                "daysOnMarket": self.days_on_market,
            },
            "policies": {
                "petsAllowed": self.pets_allowed,
                "petPolicy": self.pet_policy,
                "parkingAvailable": self.parking_available,
                "parkingPolicy": self.parking_policy,
            },
            "features": {
                "amenities": list(self.amenities),
                "specialties": list(self.specialties),
                "rentDealsCount": self.rent_deals_count,
            },
            "media": {
                "primaryImageUrl": self.primary_image_url,
                "multimediaUrl": self.multimedia_url,
                "virtualTourUrl": self.virtual_tour_url,
                "attachmentCount": self.attachment_count,
            },
            "contact": {
                "phone": self.phone,
                "propertyManagerName": self.property_manager_name,
                "propertyManagerCompanyId": self.property_manager_company_id,
                "hasLeadEmail": self.has_lead_email,
            },
            "source": {
                "provider": self.source,
                "url": self.source_url,
            },
        }

        def known(value: Any) -> bool:
            if value is None:
                return False
            if isinstance(value, str):
                return bool(value.strip())
            if isinstance(value, (list, tuple, dict, set)):
                return bool(value)
            return True

        known_fields: list[str] = []
        unknown_fields: list[str] = []
        section_coverage: dict[str, dict[str, int | float]] = {}
        for section_name, values in sections.items():
            section_known = 0
            for field_name, value in values.items():
                path = f"{section_name}.{field_name}"
                if known(value):
                    known_fields.append(path)
                    section_known += 1
                else:
                    unknown_fields.append(path)
            total = len(values)
            section_coverage[section_name] = {
                "known": section_known,
                "total": total,
                "ratio": round(section_known / total, 3) if total else 1.0,
            }

        critical_paths = {
            "identity.id": self.id,
            "location.address": self.address,
            "location.latitude": self.latitude,
            "location.longitude": self.longitude,
            "pricing.rentOrRange": (
                exact_rent
                if exact_rent is not None
                else rent_min
                if rent_min is not None
                else rent_max
            ),
            "property.bedroomsOrRange": (
                exact_bedrooms
                if exact_bedrooms is not None
                else bedrooms_min
                if bedrooms_min is not None
                else bedrooms_max
            ),
            "property.bathrooms": self.bathrooms
            if self.bathrooms is not None
            else self.bathrooms_min_evidence,
            "policies.petsAllowed": self.pets_allowed,
            "policies.parkingAvailable": self.parking_available,
            "media.primaryImageUrl": self.primary_image_url,
            "source.url": self.source_url,
        }
        critical_unknown = [path for path, value in critical_paths.items() if not known(value)]

        evidence_field_map = {
            "bathrooms": "property.bathrooms",
            "bathrooms_min_evidence": "property.bathroomsMinEvidence",
            "pets_allowed": "policies.petsAllowed",
            "parking_available": "policies.parkingAvailable",
        }
        query_backed = [
            evidence_field_map.get(field_name, field_name)
            for field_name in self.query_backed_fields
        ]
        critical_query_backed = [
            path
            for path in query_backed
            if path
            in {
                "property.bathrooms",
                "property.bathroomsMinEvidence",
                "policies.petsAllowed",
                "policies.parkingAvailable",
            }
        ]

        total_fields = len(known_fields) + len(unknown_fields)
        return {
            "schemaVersion": "kbf.canonical-listing.v1",
            **sections,
            "evidence": {
                "detailVerified": self.detail_verified,
                "queryBackedFields": query_backed,
                "criticalQueryBackedFields": critical_query_backed,
            },
            "completeness": {
                "knownFields": known_fields,
                "unknownFields": unknown_fields,
                "knownCount": len(known_fields),
                "totalCount": total_fields,
                "ratio": round(len(known_fields) / total_fields, 3) if total_fields else 1.0,
                "criticalUnknownFields": critical_unknown,
                "sectionCoverage": section_coverage,
                "mapReady": self.latitude is not None and self.longitude is not None,
                "cardReady": all(
                    known(value)
                    for value in (
                        self.id,
                        self.address,
                        exact_rent
                        if exact_rent is not None
                        else rent_min
                        if rent_min is not None
                        else rent_max,
                        exact_bedrooms
                        if exact_bedrooms is not None
                        else bedrooms_min
                        if bedrooms_min is not None
                        else bedrooms_max,
                        self.source_url,
                    )
                ),
                "comparisonReady": not any(
                    path
                    in {
                        "pricing.rentOrRange",
                        "property.bedroomsOrRange",
                        "property.bathrooms",
                        "policies.petsAllowed",
                        "policies.parkingAvailable",
                    }
                    for path in critical_unknown
                ),
                "decisionReady": (
                    self.detail_verified
                    and not critical_unknown
                    and not critical_query_backed
                ),
                "verificationRequired": (
                    not self.detail_verified
                    or bool(critical_unknown)
                    or bool(critical_query_backed)
                ),
            },
        }


@dataclass(frozen=True)
class RankedListing:
    listing: Listing
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    tradeoffs: tuple[str, ...] = field(default_factory=tuple)
    commute: CommuteResult | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "listing": self.listing.to_dict(),
            "backend_listing": self.listing.to_backend_dict(),
            "score": round(self.score, 2),
            "reasons": list(self.reasons),
            "tradeoffs": list(self.tradeoffs),
        }
        if self.commute is not None:
            result["commute"] = self.commute.to_dict()
        return result

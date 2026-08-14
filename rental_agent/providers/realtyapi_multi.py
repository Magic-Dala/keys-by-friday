from __future__ import annotations

from dataclasses import replace
from itertools import zip_longest
import time
from typing import Any, Callable, Iterable, TypeVar

import httpx

from rental_agent.models import Listing, SearchRequirements
from rental_agent.providers.base import ListingProvider
from rental_agent.providers.realtyapi import (
    RealtyApiProvider,
    _number,
    _numeric_range,
    _parse_datetime,
)


ZILLOW_BASE_URL = "https://zillow.realtyapi.io"
REALTOR_BASE_URL = "https://realtor.realtyapi.io"


def _nested(raw: dict[str, Any], path: str) -> object:
    value: object = raw
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first(raw: dict[str, Any], *paths: str) -> object:
    for path in paths:
        value = _nested(raw, path)
        if value is not None and value != "":
            return value
    return None


def _first_number(raw: dict[str, Any], *paths: str) -> float | None:
    for path in paths:
        value = _number(_nested(raw, path))
        if value is not None:
            return value
    return None


def _first_text(raw: dict[str, Any], *paths: str) -> str | None:
    for path in paths:
        value = _nested(raw, path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_rows(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected RealtyAPI response shape")

    for key in (
        "searchResults",
        "results",
        "props",
        "properties",
        "listings",
        "items",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    data = payload.get("data")
    if isinstance(data, (list, dict)):
        return _extract_rows(data)

    raise RuntimeError("Unexpected RealtyAPI response shape: listing collection not found")


def _unwrap_detail(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected RealtyAPI listing-details response shape")

    current = payload
    for _ in range(3):
        nested = None
        for key in (
            "detail",
            "data",
            "result",
            "property",
            "listing",
            "home",
            "propertyDetails",
        ):
            value = current.get(key)
            if isinstance(value, dict):
                nested = value
                break
        if nested is None:
            break
        current = nested
    return current


def _address_parts(
    raw: dict[str, Any], requirements: SearchRequirements | None
) -> tuple[str, str, str, str | None]:
    address_value = raw.get("address")
    address_obj = address_value if isinstance(address_value, dict) else {}

    address = _first_text(
        raw,
        "formattedAddress",
        "oneLineAddress",
        "streetAddress",
        "location.address.line",
        "location.address.streetAddress",
        "address.streetAddress",
        "address.line",
    )
    if address is None and isinstance(address_value, str) and address_value.strip():
        address = address_value.strip()
    if address is None:
        address = ""

    city = _first_text(raw, "city", "location.address.city", "address.city")
    state = _first_text(
        raw,
        "state",
        "state_code",
        "location.address.state_code",
        "location.address.state",
        "address.state",
        "address.state_code",
    )
    zip_code = _first_text(
        raw,
        "zipcode",
        "zipCode",
        "postalCode",
        "location.address.postal_code",
        "location.address.postalCode",
        "address.zipcode",
        "address.zipCode",
        "address.postalCode",
    )

    if requirements is not None:
        city = city or requirements.city
        state = state or requirements.state

    if state and state.casefold().strip() == "california":
        state = "CA"

    return address, city or "", state or "", zip_code


def _range(minimum: float | None, maximum: float | None) -> str | None:
    parts: list[str] = []
    if minimum is not None:
        parts.append(f"min:{minimum:g}")
    if maximum is not None:
        parts.append(f"max:{maximum:g}")
    return ",".join(parts) or None


def _zillow_bathrooms(minimum: float | None) -> str | None:
    if minimum is None:
        return None
    mapping = {
        1.0: "OnePlus",
        1.5: "OneHalfPlus",
        2.0: "TwoPlus",
        3.0: "ThreePlus",
        4.0: "FourPlus",
    }
    return mapping.get(float(minimum))


def _amenities(raw: dict[str, Any]) -> tuple[str, ...]:
    values: list[str] = []
    for path in (
        "amenities",
        "amenityNames",
        "features",
        "tags",
        "description.tags",
        "resoFacts.associationAmenities",
        "resoFacts.parkingFeatures",
        "parking.features",
    ):
        value = _nested(raw, path)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    values.append(item.strip())
                elif isinstance(item, dict):
                    label = item.get("name") or item.get("text") or item.get("description")
                    if isinstance(label, str) and label.strip():
                        values.append(label.strip())
        elif isinstance(value, str) and value.strip():
            values.append(value.strip())
    return tuple(dict.fromkeys(values))


def _policy_bool(text: str | None, positive_terms: tuple[str, ...]) -> bool | None:
    if not text:
        return None
    lowered = text.casefold()
    if any(term in lowered for term in ("no pets", "pets not allowed", "no parking")):
        return False
    if any(term in lowered for term in positive_terms):
        return True
    return None


def _structured_parking(raw: dict[str, Any], amenities: tuple[str, ...]) -> bool | None:
    for path in ("hasGarage", "resoFacts.hasGarage", "parking.hasGarage"):
        value = _nested(raw, path)
        if isinstance(value, bool):
            return value
    capacity = _first_number(
        raw,
        "parkingCapacity",
        "garageSpaces",
        "resoFacts.garageParkingCapacity",
        "parking.totalSpaces",
    )
    if capacity is not None:
        return capacity > 0
    if any(
        any(term in amenity.casefold() for term in ("parking", "garage", "carport"))
        for amenity in amenities
    ):
        return True
    return None


def _structured_pets(raw: dict[str, Any], amenities: tuple[str, ...]) -> bool | None:
    for path in ("petsAllowed", "allowsPets", "resoFacts.petsAllowed"):
        value = _nested(raw, path)
        if isinstance(value, bool):
            return value
    pet_policy = _first_text(raw, "petPolicy", "pet_policy", "resoFacts.petPolicy")
    parsed = _policy_bool(pet_policy, ("pet", "dog", "cat"))
    if parsed is not None:
        return parsed
    if any(any(term in item.casefold() for term in ("pet friendly", "dogs allowed", "cats allowed")) for item in amenities):
        return True
    return None


def _source_url(raw: dict[str, Any], *, provider: str) -> str | None:
    value = _first_text(
        raw,
        "detailUrl",
        "propertyUrl",
        "listingUrl",
        "sourceUrl",
        "href",
        "url",
    )
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if not value.startswith("/"):
        value = f"/{value}"
    if provider == "zillow":
        return f"https://www.zillow.com{value}"
    return f"https://www.realtor.com{value}"


def normalize_zillow_listing(
    raw: dict[str, Any],
    *,
    requirements: SearchRequirements | None = None,
    detail_verified: bool = False,
    listing_id: str | None = None,
) -> Listing:
    raw_id = listing_id or str(_first(raw, "zpid", "id", "propertyId") or "")
    if not raw_id:
        raise RuntimeError("Zillow result is missing zpid")
    address, city, state, zip_code = _address_parts(raw, requirements)
    amenities = _amenities(raw)

    rent = _first_number(
        raw, "price", "rent", "listPrice", "unformattedPrice", "minPrice"
    )
    if rent is None:
        _, rent = _numeric_range(_first(raw, "priceRange", "rentRange"))

    bedrooms = _first_number(raw, "bedrooms", "beds", "resoFacts.bedrooms")
    units_group = raw.get("unitsGroup")
    if bedrooms is None and isinstance(units_group, list):
        qualifying_units = [
            unit
            for unit in units_group
            if isinstance(unit, dict)
            and _number(unit.get("bedrooms")) is not None
            and (
                requirements is None
                or requirements.min_bedrooms is None
                or float(_number(unit.get("bedrooms"))) >= requirements.min_bedrooms
            )
            and (
                requirements is None
                or requirements.max_bedrooms is None
                or float(_number(unit.get("bedrooms"))) <= requirements.max_bedrooms
            )
        ]
        if qualifying_units:
            selected_unit = min(
                qualifying_units,
                key=lambda unit: (
                    _number(unit.get("minPrice"))
                    if _number(unit.get("minPrice")) is not None
                    else float("inf"),
                    _number(unit.get("bedrooms")) or float("inf"),
                ),
            )
            bedrooms = _number(selected_unit.get("bedrooms"))
            unit_rent = _number(selected_unit.get("minPrice"))
            if unit_rent is not None:
                rent = unit_rent

    pets_allowed = _structured_pets(raw, amenities)
    parking_available = _structured_parking(raw, amenities)
    if requirements is not None and requirements.pets_required:
        pets_allowed = True
    if requirements is not None and requirements.parking_required:
        parking_available = True

    year_built = _first_number(raw, "yearBuilt", "resoFacts.yearBuilt")
    return Listing(
        id=f"zillow:{raw_id}",
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        rent=rent,
        bedrooms=bedrooms,
        bathrooms=_first_number(raw, "bathrooms", "baths", "resoFacts.bathrooms"),
        property_type=_first_text(raw, "homeType", "propertyType", "resoFacts.homeType"),
        square_footage=_first_number(raw, "livingArea", "livingAreaValue", "sqft", "resoFacts.livingArea"),
        listed_date=_parse_datetime(_first(raw, "datePosted", "listingDate", "listedDate")),
        last_seen_date=_parse_datetime(_first(raw, "lastUpdated", "updatedAt")),
        pets_allowed=pets_allowed,
        parking_available=parking_available,
        source_url=_source_url(raw, provider="zillow"),
        source="realtyapi-zillow",
        property_name=_first_text(raw, "buildingName", "propertyName", "name"),
        year_built=int(year_built) if year_built is not None else None,
        amenities=amenities,
        pet_policy=_first_text(raw, "petPolicy", "pet_policy", "resoFacts.petPolicy"),
        parking_policy=_first_text(raw, "parkingDescription", "parking.text", "resoFacts.parkingFeatures"),
        detail_verified=detail_verified,
    )


def normalize_realtor_listing(
    raw: dict[str, Any],
    *,
    requirements: SearchRequirements | None = None,
    detail_verified: bool = False,
    listing_id: str | None = None,
) -> Listing:
    raw_id = listing_id or str(_first(raw, "property_id", "propertyId", "id") or "")
    if not raw_id:
        raise RuntimeError("Realtor result is missing property_id")
    address, city, state, zip_code = _address_parts(raw, requirements)
    amenities = _amenities(raw)

    rent = _first_number(raw, "price", "list_price", "listPrice", "rent")
    if rent is None:
        _, rent = _numeric_range(_first(raw, "priceRange", "rentRange"))

    pets_allowed = _structured_pets(raw, amenities)
    if requirements is not None and requirements.pets_required:
        # Realtor petsAllowed is an explicit rental filter, so this is query-backed evidence.
        pets_allowed = True

    year_built = _first_number(raw, "year_built", "yearBuilt", "description.year_built")
    return Listing(
        id=f"realtor:{raw_id}",
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        rent=rent,
        bedrooms=_first_number(raw, "beds", "bedrooms", "description.beds"),
        bathrooms=_first_number(raw, "baths", "bathrooms", "description.baths"),
        property_type=_first_text(raw, "property_type", "propertyType", "description.type"),
        square_footage=_first_number(raw, "sqft", "squareFeet", "description.sqft"),
        listed_date=_parse_datetime(_first(raw, "list_date", "listingDate", "listedDate")),
        last_seen_date=_parse_datetime(_first(raw, "last_update_date", "updatedAt")),
        pets_allowed=pets_allowed,
        # keywords=parking is only a text search. Do not treat it as parking evidence.
        parking_available=_structured_parking(raw, amenities),
        source_url=_source_url(raw, provider="realtor"),
        source="realtyapi-realtor",
        property_name=_first_text(raw, "property_name", "propertyName", "name"),
        year_built=int(year_built) if year_built is not None else None,
        amenities=amenities,
        pet_policy=_first_text(raw, "petPolicy", "pet_policy"),
        parking_policy=_first_text(raw, "parkingDescription", "parking.text"),
        detail_verified=detail_verified,
    )


def _interleave(groups: Iterable[list[Listing]]) -> Iterable[Listing]:
    for row in zip_longest(*groups):
        for listing in row:
            if listing is not None:
                yield listing


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return type(exc).__name__
    return type(exc).__name__


_T = TypeVar("_T")


def _is_transient_credit_race(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    response = exc.response
    if response.status_code not in (401, 402):
        return False
    remaining = response.headers.get("X-Credits-Remaining")
    try:
        remaining_credits = int(remaining) if remaining is not None else 0
    except ValueError:
        return False
    if remaining_credits <= 0:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("error") == "Not enough credits remaining"
    )


def _call_with_credit_race_retry(call: Callable[[], _T]) -> _T:
    for attempt in range(3):
        try:
            return call()
        except Exception as exc:
            if attempt >= 2 or not _is_transient_credit_race(exc):
                raise
            time.sleep((2.0, 5.0)[attempt])
    raise AssertionError("unreachable")


class RealtyApiMultiProvider(ListingProvider):
    def __init__(
        self,
        api_key: str,
        *,
        apartments_provider: RealtyApiProvider | None = None,
        zillow_client: httpx.Client | None = None,
        realtor_client: httpx.Client | None = None,
    ):
        if not api_key.strip():
            raise RuntimeError(
                "RealtyAPI real-data mode requires REALTYAPI_API_KEY. "
                "Set it in .env or the process environment."
            )
        self._apartments = apartments_provider or RealtyApiProvider(api_key=api_key)
        self._zillow = zillow_client or httpx.Client(base_url=ZILLOW_BASE_URL, timeout=30.0)
        self._realtor = realtor_client or httpx.Client(base_url=REALTOR_BASE_URL, timeout=30.0)
        headers = {"Accept": "application/json", "x-realtyapi-key": api_key.strip()}
        self._zillow.headers.update(headers)
        self._realtor.headers.update(headers)

    def _search_zillow(self, requirements: SearchRequirements) -> list[Listing]:
        params: dict[str, str] = {
            "location": f"{requirements.city}, {requirements.state}",
            "listingStatus": "For_Rent",
        }
        if requirements.max_rent is not None:
            params["listPriceRange"] = f"max:{requirements.max_rent:g}"
        if requirements.min_bedrooms is not None and float(requirements.min_bedrooms).is_integer():
            params["bed_min"] = f"{requirements.min_bedrooms:g}"
        if requirements.max_bedrooms is not None and float(requirements.max_bedrooms).is_integer():
            params["bed_max"] = f"{requirements.max_bedrooms:g}"
        bathrooms = _zillow_bathrooms(requirements.min_bathrooms)
        if bathrooms:
            params["bathrooms"] = bathrooms
        if requirements.pets_required:
            params["pets"] = "Allow large dogs,Allow small dogs,Allow cats"
        if requirements.parking_required:
            params["otherAmenities"] = "On-site Parking"

        response = self._zillow.get("/search/byaddress", params=params)
        response.raise_for_status()
        rows = _extract_rows(response.json())[: max(1, requirements.limit)]
        normalized_rows: list[Listing] = []
        for row in rows:
            property_row = row.get("property")
            raw = property_row if isinstance(property_row, dict) else row
            normalized_rows.append(
                normalize_zillow_listing(raw, requirements=requirements)
            )
        return normalized_rows

    def _search_realtor(self, requirements: SearchRequirements) -> list[Listing]:
        params: dict[str, str | int] = {
            "location": f"{requirements.city}, {requirements.state}",
            "searchType": "For_Rent",
            "resultCount": max(1, min(requirements.limit, 200)),
        }
        if requirements.max_rent is not None:
            params["priceRange"] = f"max:{requirements.max_rent:g}"
        beds = _range(requirements.min_bedrooms, requirements.max_bedrooms)
        if beds:
            params["bedsRange"] = beds
        baths = _range(requirements.min_bathrooms, requirements.max_bathrooms)
        if baths:
            params["bathsRange"] = baths
        if requirements.pets_required:
            params["petsAllowed"] = "dog,cat"
        if requirements.parking_required:
            params["keywords"] = "parking"

        response = self._realtor.get("/search/bylocation", params=params)
        response.raise_for_status()
        rows = _extract_rows(response.json())[: max(1, requirements.limit)]
        return [normalize_realtor_listing(row, requirements=requirements) for row in rows]

    def search(self, requirements: SearchRequirements) -> list[Listing]:
        per_source_requirements = replace(
            requirements, limit=max(1, requirements.limit)
        )
        results: list[list[Listing]] = []
        failures: list[tuple[str, Exception]] = []

        for source, search in (
            ("apartments", lambda: self._apartments.search(per_source_requirements)),
            ("zillow", lambda: self._search_zillow(per_source_requirements)),
            ("realtor", lambda: self._search_realtor(per_source_requirements)),
        ):
            try:
                results.append(_call_with_credit_race_retry(search))
            except Exception as exc:
                failures.append((source, exc))
                results.append([])

        if len(failures) == 3:
            summary = ", ".join(
                f"{source}: {_safe_error(exc)}" for source, exc in failures
            )
            raise RuntimeError(f"All RealtyAPI sources failed ({summary})")

        # Preserve source-specific postings. The agent groups the same physical
        # property across Zillow/Realtor/Apartments so source evidence is not lost.
        return list(_interleave(results))

    def get_listing(self, listing_id: str) -> Listing:
        if listing_id.startswith("zillow:"):
            zpid = listing_id.removeprefix("zillow:")
            response = self._zillow.get("/pro/byzpid", params={"zpid": zpid})
            response.raise_for_status()
            return normalize_zillow_listing(
                _unwrap_detail(response.json()),
                detail_verified=True,
                listing_id=zpid,
            )
        if listing_id.startswith("realtor:"):
            property_id = listing_id.removeprefix("realtor:")
            response = self._realtor.get(
                "/details/byid", params={"property_id": property_id}
            )
            response.raise_for_status()
            return normalize_realtor_listing(
                _unwrap_detail(response.json()),
                detail_verified=True,
                listing_id=property_id,
            )
        return self._apartments.get_listing(listing_id)

    def health(self) -> dict[str, object]:
        return {
            "ok": True,
            "provider": "realtyapi-multi",
            "sources": ["apartments", "zillow", "realtor"],
        }

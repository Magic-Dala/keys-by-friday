from __future__ import annotations

from datetime import datetime
import re
from typing import Any

import httpx

from rental_agent.models import Listing, SearchRequirements
from rental_agent.providers.base import ListingProvider


REALTYAPI_BASE_URL = "https://apartments.realtyapi.io"


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _numeric_range(value: object) -> tuple[float | None, float | None]:
    if isinstance(value, dict):
        low = _number(value.get("min") or value.get("minimum") or value.get("low"))
        high = _number(value.get("max") or value.get("maximum") or value.get("high"))
        if low is None and high is None:
            single = _number(value.get("value"))
            return single, single
        return low, high
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return number, number
    if not isinstance(value, str):
        return None, None

    numbers = [
        float(token.replace(",", ""))
        for token in re.findall(r"\d[\d,]*(?:\.\d+)?", value)
    ]
    if "studio" in value.casefold():
        numbers.append(0.0)
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def _first_number(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in raw:
            value = _number(raw[key])
            if value is not None:
                return value
    return None


def _address_parts(raw: dict[str, Any]) -> tuple[str, str, str, str | None]:
    address_value = raw.get("address")
    address_obj = address_value if isinstance(address_value, dict) else {}

    address = ""
    if isinstance(raw.get("oneLineAddress"), str):
        address = str(raw["oneLineAddress"]).strip()
    elif isinstance(address_value, str):
        address = address_value.strip()
    else:
        for key in (
            "formattedAddress",
            "fullAddress",
            "streetAddress",
            "street",
            "lineOne",
        ):
            value = raw.get(key) or address_obj.get(key)
            if isinstance(value, str) and value.strip():
                address = value.strip()
                break

    city = str(raw.get("city") or address_obj.get("city") or "")
    state = str(raw.get("state") or address_obj.get("state") or "")
    zip_value = (
        raw.get("zip")
        or raw.get("zipCode")
        or raw.get("postalCode")
        or address_obj.get("zip")
        or address_obj.get("zipCode")
        or address_obj.get("postalCode")
    )
    zip_code = str(zip_value) if zip_value is not None else None
    return address, city, state, zip_code


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _apartments_listing_url(
    raw: dict[str, Any], listing_id: str, address: str, city: str, state: str
) -> str | None:
    for key in ("listingUrl", "propertyUrl", "sourceUrl", "url"):
        value = raw.get(key)
        if isinstance(value, str) and value.startswith("https://www.apartments.com/"):
            return value

    if not listing_id:
        return None

    name = raw.get("name")
    label = name.strip() if isinstance(name, str) and name.strip() else address
    if not label:
        return None
    if city and city.casefold() not in label.casefold():
        location_suffix = " ".join(part for part in (city, state) if part)
        label = f"{label} {location_suffix}"
    slug = _slugify(label)
    if not slug:
        return None
    return f"https://www.apartments.com/{slug}/{listing_id}/"


def _policy_text(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if not isinstance(value, list):
        return None
    descriptions: list[str] = []
    for item in value:
        if isinstance(item, dict):
            desc = item.get("desc") or item.get("description") or item.get("name")
            if isinstance(desc, str) and desc.strip():
                descriptions.append(desc.strip())
        elif isinstance(item, str) and item.strip():
            descriptions.append(item.strip())
    if not descriptions:
        return None
    return "; ".join(dict.fromkeys(descriptions))


def _policy_boolean(policy: str | None, *, negative_terms: tuple[str, ...]) -> bool | None:
    if not policy:
        return None
    lowered = policy.casefold()
    if any(term in lowered for term in negative_terms):
        return False
    return True


def _amenities(raw: dict[str, Any]) -> tuple[str, ...]:
    value = raw.get("amenityNames") or raw.get("amenities")
    if not isinstance(value, list):
        return ()
    names = [str(item).strip() for item in value if str(item).strip()]
    return tuple(dict.fromkeys(names))


def _extract_listing_rows(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected RealtyAPI response shape")

    for key in ("searchResults", "listings", "results", "properties", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    data = payload.get("data")
    if isinstance(data, (list, dict)):
        return _extract_listing_rows(data)

    raise RuntimeError("Unexpected RealtyAPI response shape: listing collection not found")


def normalize_realtyapi_listing(
    raw: dict[str, Any],
    *,
    requirements: SearchRequirements | None = None,
    detail_verified: bool = False,
) -> Listing:
    address, city, state, zip_code = _address_parts(raw)
    listing_id = str(raw.get("listingKey") or raw.get("listing_id") or raw.get("id") or "")

    rent = _first_number(raw, "rent", "minRent", "rentMin", "rent_min", "price")
    if rent is None:
        _, rent_high = _numeric_range(raw.get("rentRange") or raw.get("priceRange"))
        rent = rent_high

    bedrooms = _first_number(raw, "beds", "bedrooms", "minBeds", "bedsMin")
    if bedrooms is None:
        _, bedrooms_high = _numeric_range(raw.get("bedRange"))
        bedrooms = bedrooms_high

    bathrooms = _first_number(raw, "baths", "bathrooms", "minBaths", "bathsMin")
    if bathrooms is None and requirements is not None:
        bathrooms = (
            requirements.min_bathrooms
            if requirements.min_bathrooms is not None
            else requirements.max_bathrooms
        )

    square_footage = _first_number(
        raw, "sqft", "squareFeet", "squareFootage", "minSqft", "sqftMin"
    )
    if square_footage is None:
        _, square_footage = _numeric_range(
            raw.get("squareFeetRange") or raw.get("sqftRange")
        )

    amenities = _amenities(raw)
    pet_policy = _policy_text(raw, "petPolicies")
    parking_policy = _policy_text(raw, "parkingPolicies")
    pets_allowed = _policy_boolean(
        pet_policy, negative_terms=("no pets", "not allowed", "prohibited")
    )
    parking_available = _policy_boolean(
        parking_policy, negative_terms=("no parking", "not available")
    )
    if parking_available is None and any(
        "parking" in amenity.casefold() or "garage" in amenity.casefold()
        for amenity in amenities
    ):
        parking_available = True
    if pets_allowed is None and requirements is not None and requirements.pets_required:
        pets_allowed = True
    if (
        parking_available is None
        and requirements is not None
        and requirements.parking_required
    ):
        parking_available = True

    year_built_number = _number(raw.get("yearBuilt"))

    return Listing(
        id=listing_id,
        address=address,
        city=city,
        state=state,
        zip_code=zip_code,
        rent=rent,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        property_type=(
            str(raw.get("propertyType")) if raw.get("propertyType") is not None else None
        ),
        square_footage=square_footage,
        status=None,
        listed_date=_parse_datetime(raw.get("listedDate") or raw.get("listingDate")),
        last_seen_date=_parse_datetime(
            raw.get("lastModifiedDate") or raw.get("updatedAt") or raw.get("updated_at")
        ),
        pets_allowed=pets_allowed,
        parking_available=parking_available,
        source_url=_apartments_listing_url(raw, listing_id, address, city, state),
        source="realtyapi-apartments",
        property_name=(
            str(raw.get("name")).strip()
            if isinstance(raw.get("name"), str) and str(raw.get("name")).strip()
            else None
        ),
        availability=(
            str(raw.get("availabilityText")).strip()
            if isinstance(raw.get("availabilityText"), str)
            and str(raw.get("availabilityText")).strip()
            else None
        ),
        year_built=int(year_built_number) if year_built_number is not None else None,
        amenities=amenities,
        pet_policy=pet_policy,
        parking_policy=parking_policy,
        detail_verified=detail_verified,
    )


class RealtyApiProvider(ListingProvider):
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key.strip():
            raise RuntimeError(
                "RealtyAPI real-data mode requires REALTYAPI_API_KEY. "
                "Set it in .env or the process environment."
            )
        if client is None:
            client = httpx.Client(base_url=REALTYAPI_BASE_URL, timeout=30.0)
        client.headers.update(
            {"Accept": "application/json", "x-realtyapi-key": api_key.strip()}
        )
        self._client = client

    @staticmethod
    def _range(minimum: float | None, maximum: float | None) -> str | None:
        parts: list[str] = []
        if minimum is not None:
            parts.append(f"min:{minimum:g}")
        if maximum is not None:
            parts.append(f"max:{maximum:g}")
        return ",".join(parts) or None

    def search(self, requirements: SearchRequirements) -> list[Listing]:
        params: dict[str, str | int] = {
            "location": f"{requirements.city}, {requirements.state}",
            "resultCount": max(1, min(requirements.limit, 500)),
        }
        if requirements.max_rent is not None:
            params["priceRange"] = f"max:{requirements.max_rent:g}"

        bed_range = self._range(requirements.min_bedrooms, requirements.max_bedrooms)
        if bed_range:
            params["bedRange"] = bed_range

        bath_values = (requirements.min_bathrooms, requirements.max_bathrooms)
        if all(value is None or float(value).is_integer() for value in bath_values):
            bath_range = self._range(*bath_values)
            if bath_range:
                params["bathRange"] = bath_range

        if requirements.pets_required:
            params["petPolicy"] = "Dog_and_Cat"
        if requirements.parking_required:
            params["amenities"] = "parking"

        response = self._client.get("/search/bylocation", params=params)
        response.raise_for_status()
        rows = _extract_listing_rows(response.json())
        return [
            normalize_realtyapi_listing(row, requirements=requirements) for row in rows
        ]

    def get_listing(self, listing_id: str) -> Listing:
        response = self._client.get("/details/byid", params={"listingKey": listing_id})
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            for key in ("detail", "data", "result", "property", "listing"):
                nested = payload.get(key)
                if isinstance(nested, dict):
                    payload = nested
                    break
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected RealtyAPI listing-details response shape")
        return normalize_realtyapi_listing(payload, detail_verified=True)

    def health(self) -> dict[str, object]:
        return {"ok": True, "provider": "realtyapi-apartments", "configured": True}

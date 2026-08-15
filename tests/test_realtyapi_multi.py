import httpx

from rental_agent.models import SearchRequirements
from rental_agent.pipeline import passes_hard_filters
from rental_agent.providers.realtyapi import REALTYAPI_BASE_URL, RealtyApiProvider
from rental_agent.providers.realtyapi_multi import (
    REALTOR_BASE_URL,
    ZILLOW_BASE_URL,
    RealtyApiMultiProvider,
)


def _client(base_url: str, handler) -> httpx.Client:
    return httpx.Client(base_url=base_url, transport=httpx.MockTransport(handler))


def _apartments_row(
    listing_id: str = "apt-1",
    address: str = "100 Castro St, Mountain View, CA 94041",
    rent: str = "$3,800",
) -> dict[str, object]:
    return {
        "listingKey": listing_id,
        "oneLineAddress": address,
        "address": {
            "city": "Mountain View",
            "state": "CA",
            "postalCode": "94041",
            "countryCode": "US",
        },
        "rentRange": rent,
        "bedRange": "2 Beds",
        "baths": 2,
        "latitude": 37.3861,
        "longitude": -122.0839,
        "primaryImage": "https://img.example.test/apartment.jpg",
    }


def _zillow_row(
    zpid: str = "2001",
    address: str = "200 Hope St",
    rent: int = 3700,
) -> dict[str, object]:
    return {
        "zpid": zpid,
        "address": address,
        "city": "Mountain View",
        "state": "CA",
        "zipcode": "94041",
        "price": rent,
        "bedrooms": 2,
        "bathrooms": 2,
        "livingArea": 980,
        "latitude": 37.3901,
        "longitude": -122.0812,
        "imgSrc": "https://img.example.test/zillow.jpg",
        "detailUrl": f"/homedetails/{zpid}_zpid/",
    }


def _realtor_row(
    property_id: str = "3001",
    address: str = "300 Mercy St",
    rent: int = 3600,
) -> dict[str, object]:
    return {
        "property_id": property_id,
        "location": {
            "address": {
                "line": address,
                "city": "Mountain View",
                "state_code": "CA",
                "postal_code": "94041",
            }
        },
        "price": rent,
        "listing_id": f"listing-{property_id}",
        "description": {"beds": 2, "baths": 2, "sqft": 950},
        "primary_photo": {"href": "https://img.example.test/realtor.jpg"},
        "location": {
            "address": {
                "line": address,
                "city": "Mountain View",
                "state_code": "CA",
                "postal_code": "94041",
                "coordinate": {"lat": 37.3942, "lon": -122.0781},
            }
        },
        "href": f"https://www.realtor.com/realestateandhomes-detail/{property_id}",
    }


def _provider(
    apartments_handler,
    zillow_handler,
    realtor_handler,
) -> RealtyApiMultiProvider:
    apartments = RealtyApiProvider(
        api_key="dummy-key",
        client=_client(REALTYAPI_BASE_URL, apartments_handler),
    )
    return RealtyApiMultiProvider(
        api_key="dummy-key",
        apartments_provider=apartments,
        zillow_client=_client(ZILLOW_BASE_URL, zillow_handler),
        realtor_client=_client(REALTOR_BASE_URL, realtor_handler),
    )


def test_search_calls_all_three_sources_and_normalizes_each_source():
    calls: list[tuple[str, str, dict[str, str]]] = []

    def apartments_handler(request: httpx.Request) -> httpx.Response:
        calls.append(("apartments", request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"searchResults": [_apartments_row()]})

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        calls.append(("zillow", request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"results": [_zillow_row()]})

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        calls.append(("realtor", request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"searchResults": [_realtor_row()]})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    results = provider.search(
        SearchRequirements(
            city="Mountain View",
            state="CA",
            max_rent=4000,
            min_bedrooms=2,
            min_bathrooms=2,
            pets_required=True,
            parking_required=True,
            limit=9,
        )
    )

    assert [call[0] for call in calls] == ["apartments", "zillow", "realtor"]
    assert calls[0][1] == "/search/bylocation"
    assert calls[1][1] == "/search/byaddress"
    assert calls[2][1] == "/search/bylocation"
    assert calls[1][2]["listingStatus"] == "For_Rent"
    assert calls[1][2]["otherAmenities"] == "On-site Parking"
    assert calls[2][2]["searchType"] == "For_Rent"
    assert calls[2][2]["keywords"] == "parking"

    assert {listing.source for listing in results} == {
        "realtyapi-apartments",
        "realtyapi-zillow",
        "realtyapi-realtor",
    }
    zillow = next(item for item in results if item.source == "realtyapi-zillow")
    realtor = next(item for item in results if item.source == "realtyapi-realtor")
    assert zillow.id == "zillow:2001"
    assert zillow.source_listing_id == "2001"
    assert zillow.latitude == 37.3901
    assert zillow.longitude == -122.0812
    assert zillow.primary_image_url == "https://img.example.test/zillow.jpg"
    assert zillow.pets_allowed is True
    assert zillow.parking_available is True
    assert realtor.id == "realtor:3001"
    assert realtor.source_listing_id == "listing-3001"
    assert realtor.latitude == 37.3942
    assert realtor.longitude == -122.0781
    assert realtor.primary_image_url == "https://img.example.test/realtor.jpg"
    assert realtor.pets_allowed is True
    assert realtor.parking_available is None

    apartments = next(item for item in results if item.source == "realtyapi-apartments")
    assert apartments.source_listing_id == "apt-1"
    assert apartments.country_code == "US"
    assert apartments.latitude == 37.3861
    assert apartments.longitude == -122.0839
    assert apartments.primary_image_url == "https://img.example.test/apartment.jpg"
    assert apartments.bedrooms_min == 2
    assert apartments.bedrooms_max == 2

    # These booleans were not reported in the row; they are guaranteed by the
    # search filters and must be marked as query-backed rather than detail facts.
    assert "pets_allowed" in apartments.query_backed_fields
    assert "parking_available" in apartments.query_backed_fields



def test_zillow_search_unwraps_live_property_envelope_and_uses_unit_evidence():
    def apartments_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": []})

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "searchResults": [
                    {
                        "resultType": "building",
                        "property": {
                            "zpid": 461662543,
                            "address": {
                                "streetAddress": "191 E El Camino Real",
                                "city": "Mountain View",
                                "state": "CA",
                                "zipcode": "94040",
                            },
                            "minPrice": 3795,
                            "maxPrice": 3995,
                            "unitsGroup": [
                                {"bedrooms": 2, "minPrice": 3795},
                                {"bedrooms": 3, "minPrice": 3995},
                            ],
                        },
                    }
                ]
            },
        )

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": []})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    requirements = SearchRequirements(
        city="Mountain View",
        state="CA",
        max_rent=4000,
        min_bedrooms=2,
        min_bathrooms=2,
        limit=5,
    )
    results = provider.search(requirements)

    assert len(results) == 1
    listing = results[0]
    assert listing.id == "zillow:461662543"
    assert listing.source == "realtyapi-zillow"
    assert listing.address == "191 E El Camino Real"
    assert listing.city == "Mountain View"
    assert listing.state == "CA"
    assert listing.rent == 3795
    assert listing.bedrooms == 2
    assert listing.bathrooms is None
    assert listing.bathrooms_min_evidence == 2
    assert listing.source_url == "https://www.zillow.com/homedetails/461662543_zpid/"
    assert passes_hard_filters(listing, requirements) is True
    assert "bathrooms_min_evidence" in listing.query_backed_fields


def test_explicit_provider_policy_is_not_overwritten_by_query_evidence():
    def apartments_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": []})

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        row = _zillow_row("explicit-no-pets")
        row["petsAllowed"] = False
        row["hasGarage"] = False
        return httpx.Response(200, json={"results": [row]})

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        row = _realtor_row("explicit-no-pets")
        row["petsAllowed"] = False
        return httpx.Response(200, json={"searchResults": [row]})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    results = provider.search(
        SearchRequirements(
            city="Mountain View",
            state="CA",
            pets_required=True,
            parking_required=True,
            limit=5,
        )
    )

    zillow = next(item for item in results if item.source == "realtyapi-zillow")
    realtor = next(item for item in results if item.source == "realtyapi-realtor")
    assert zillow.pets_allowed is False
    assert zillow.parking_available is False
    assert "pets_allowed" not in zillow.query_backed_fields
    assert "parking_available" not in zillow.query_backed_fields
    assert realtor.pets_allowed is False
    assert "pets_allowed" not in realtor.query_backed_fields

def test_one_source_failure_does_not_fail_search():
    def apartments_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": [_apartments_row()]})

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "upstream unavailable"})

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": [_realtor_row()]})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    results = provider.search(
        SearchRequirements(city="Mountain View", state="CA", limit=6)
    )

    assert {listing.source for listing in results} == {
        "realtyapi-apartments",
        "realtyapi-realtor",
    }
    health = provider.health()
    assert health["search_complete"] is False
    assert health["failed_sources"] == ["zillow"]


def test_get_listing_routes_ids_to_correct_detail_endpoint():
    calls: list[tuple[str, str, dict[str, str]]] = []

    def apartments_handler(request: httpx.Request) -> httpx.Response:
        calls.append(("apartments", request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"detail": _apartments_row("apt-detail")})

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        calls.append(("zillow", request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"property": _zillow_row("2002")})

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        calls.append(("realtor", request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={"data": _realtor_row("3002")})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)

    apartments = provider.get_listing("apt-detail")
    zillow = provider.get_listing("zillow:2002")
    realtor = provider.get_listing("realtor:3002")

    assert calls == [
        ("apartments", "/details/byid", {"listingKey": "apt-detail"}),
        ("zillow", "/pro/byzpid", {"zpid": "2002"}),
        ("realtor", "/details/byid", {"property_id": "3002"}),
    ]
    assert apartments.id == "apt-detail"
    assert zillow.id == "zillow:2002"
    assert zillow.detail_verified is True
    assert realtor.id == "realtor:3002"
    assert realtor.detail_verified is True


def test_cross_source_postings_are_preserved_for_agent_grouping():
    def apartments_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "searchResults": [
                    _apartments_row(
                        "apt-same",
                        "100 Castro Street, Mountain View, CA 94041",
                        "$3,800",
                    ),
                    _apartments_row(
                        "apt-unit-2",
                        "100 Castro St Apt 2, Mountain View, CA 94041",
                        "$3,800",
                    ),
                ]
            },
        )

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        row = _zillow_row("z-same", "100 Castro St", 3800)
        return httpx.Response(200, json={"results": [row]})

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": []})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    results = provider.search(
        SearchRequirements(city="Mountain View", state="CA", limit=9)
    )

    ids = {listing.id for listing in results}
    assert "apt-same" in ids
    assert "zillow:z-same" in ids
    assert "apt-unit-2" in ids
    assert len(results) == 3


def test_interleaving_prevents_first_source_from_consuming_limit():
    def apartments_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "searchResults": [
                    _apartments_row(f"apt-{index}", f"{index} A St", f"${3500 + index}")
                    for index in range(10)
                ]
            },
        )

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [_zillow_row("z-1")]})

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": [_realtor_row("r-1")]})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    results = provider.search(
        SearchRequirements(city="Mountain View", state="CA", limit=3)
    )

    assert [listing.source for listing in results[:3]] == [
        "realtyapi-apartments",
        "realtyapi-zillow",
        "realtyapi-realtor",
    ]
    assert len(results) == 12
    assert sum(item.source == "realtyapi-apartments" for item in results) == 10
    assert sum(item.source == "realtyapi-zillow" for item in results) == 1
    assert sum(item.source == "realtyapi-realtor" for item in results) == 1


def test_realtor_full_state_name_normalizes_for_hard_filters():
    row = _realtor_row("state-name")
    address = row["location"]["address"]
    address.pop("state_code")
    address["state"] = "California"

    def apartments_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": []})

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "not available"})

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": [row]})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    requirements = SearchRequirements(
        city="Mountain View",
        state="CA",
        max_rent=4000,
        min_bedrooms=2,
        max_bedrooms=2,
        limit=5,
    )

    result = provider.search(requirements)[0]

    assert result.source == "realtyapi-realtor"
    assert result.state == "CA"
    assert passes_hard_filters(result, requirements) is True


def test_zillow_retries_bounded_credit_race_until_success(monkeypatch):
    zillow_calls = 0
    sleeps: list[float] = []
    monkeypatch.setattr("rental_agent.providers.realtyapi_multi.time.sleep", sleeps.append)

    def apartments_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": []})

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        nonlocal zillow_calls
        zillow_calls += 1
        if zillow_calls < 3:
            return httpx.Response(
                402,
                headers={"X-Credits-Remaining": "10"},
                json={"error": "Not enough credits remaining"},
            )
        return httpx.Response(200, json={"results": [_zillow_row("retry-ok")]})

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": []})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    results = provider.search(
        SearchRequirements(city="Mountain View", state="CA", limit=3)
    )

    assert zillow_calls == 3
    assert sleeps == [2.0, 5.0]
    assert [listing.id for listing in results] == ["zillow:retry-ok"]


def test_zillow_does_not_retry_when_credits_are_actually_exhausted():
    zillow_calls = 0

    def apartments_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": [_apartments_row()]})

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        nonlocal zillow_calls
        zillow_calls += 1
        return httpx.Response(
            402,
            headers={"X-Credits-Remaining": "0"},
            json={"error": "Not enough credits remaining"},
        )

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": []})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    results = provider.search(
        SearchRequirements(city="Mountain View", state="CA", limit=3)
    )

    assert zillow_calls == 1
    assert [listing.source for listing in results] == ["realtyapi-apartments"]


def test_credit_race_retry_applies_to_apartments_source(monkeypatch):
    apartment_calls = 0
    sleeps: list[float] = []
    monkeypatch.setattr("rental_agent.providers.realtyapi_multi.time.sleep", sleeps.append)

    def apartments_handler(request: httpx.Request) -> httpx.Response:
        nonlocal apartment_calls
        apartment_calls += 1
        if apartment_calls < 3:
            return httpx.Response(
                401,
                headers={"X-Credits-Remaining": "9"},
                json={"error": "Not enough credits remaining"},
            )
        return httpx.Response(200, json={"searchResults": [_apartments_row()]})

    def zillow_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": []})

    def realtor_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"searchResults": []})

    provider = _provider(apartments_handler, zillow_handler, realtor_handler)
    results = provider.search(
        SearchRequirements(city="Mountain View", state="CA", limit=3)
    )

    assert apartment_calls == 3
    assert sleeps == [2.0, 5.0]
    assert [listing.source for listing in results] == ["realtyapi-apartments"]

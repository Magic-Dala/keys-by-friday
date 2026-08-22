import httpx

from rental_agent.models import SearchRequirements
from rental_agent.providers.realtyapi import (
    REALTYAPI_BASE_URL,
    RealtyApiProvider,
    normalize_realtyapi_listing,
)


def test_realtyapi_search_request_construction_auth_and_live_shape_normalization():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["api_key"] = request.headers.get("x-realtyapi-key")
        return httpx.Response(
            200,
            json={
                "message": "success",
                "source": "apartments",
                "total": 1,
                "resultCount": 1,
                "nextPage": False,
                "searchResults": [
                    {
                        "listingKey": "mv1234",
                        "name": "Castro Place",
                        "oneLineAddress": "100 Castro St, Mountain View, CA 94041",
                        "address": {
                            "lineOne": "100 Castro St",
                            "lineTwo": "Mountain View, CA 94041",
                            "city": "Mountain View",
                            "state": "CA",
                            "postalCode": "94041",
                            "countryCode": "US",
                        },
                        "rentRange": "$2,750 - 3,650",
                        "priceRange": "$2,750 - 3,650",
                        "bedRange": "1 - 2 Beds",
                        "propertyType": "Apartment",
                        "listingStatus": "For_Rent",
                        "availabilityText": "Available Now",
                        "amenityNames": ["Parking", "Gym"],
                    }
                ],
            },
        )

    client = httpx.Client(
        base_url=REALTYAPI_BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    provider = RealtyApiProvider(api_key="test-secret", client=client)
    results = provider.search(
        SearchRequirements(
            city="Mountain View",
            state="CA",
            max_rent=4000,
            min_bedrooms=2,
            min_bathrooms=2,
            pets_required=True,
            parking_required=True,
            limit=50,
        )
    )

    assert captured["path"] == "/search/bylocation"
    assert captured["api_key"] == "test-secret"
    assert captured["params"] == {
        "location": "Mountain View, CA",
        "resultCount": "50",
        "priceRange": "max:4000",
        "bedRange": "min:2",
        "bathRange": "min:2",
        "petPolicy": "Dog_and_Cat",
        "amenities": "parking",
    }
    assert len(results) == 1
    assert results[0].id == "mv1234"
    assert results[0].source == "realtyapi-apartments"
    assert results[0].address == "100 Castro St, Mountain View, CA 94041"
    assert results[0].city == "Mountain View"
    assert results[0].rent == 3650
    assert results[0].bedrooms == 2
    assert results[0].bathrooms is None
    assert results[0].bathrooms_min_evidence == 2
    assert results[0].status == "active"
    assert "bathrooms_min_evidence" in results[0].query_backed_fields
    assert results[0].pets_allowed is True
    assert results[0].parking_available is True
    assert results[0].source_url == (
        "https://www.apartments.com/castro-place-mountain-view-ca/mv1234/"
    )


def test_realtyapi_get_listing_uses_documented_detail_endpoint_and_detail_envelope():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "message": "success",
                "source": "apartments",
                "detail": {
                    "listingKey": "mv1234",
                    "oneLineAddress": "100 Castro St, Mountain View, CA 94041",
                    "address": {
                        "city": "Mountain View",
                        "state": "CA",
                        "postalCode": "94041",
                    },
                    "rentRange": "$3,850 - 3,995",
                    "bedRange": "2 Beds",
                },
            },
        )

    client = httpx.Client(
        base_url=REALTYAPI_BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    provider = RealtyApiProvider(api_key="test-secret", client=client)

    listing = provider.get_listing("mv1234")

    assert captured["path"] == "/details/byid"
    assert captured["params"] == {"listingKey": "mv1234"}
    assert listing.id == "mv1234"
    assert listing.rent == 3995
    assert listing.bedrooms == 2
    assert listing.city == "Mountain View"
    assert listing.source_url == (
        "https://www.apartments.com/100-castro-st-mountain-view-ca-94041/mv1234/"
    )


def test_explicit_apartments_url_is_preserved():
    client = httpx.Client(
        base_url=REALTYAPI_BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "searchResults": [
                        {
                            "listingKey": "abc123",
                            "listingUrl": "https://www.apartments.com/example/abc123/",
                            "oneLineAddress": "1 Main St, Mountain View, CA 94040",
                            "address": {
                                "city": "Mountain View",
                                "state": "CA",
                                "postalCode": "94040",
                            },
                            "rentRange": "$3,000",
                            "bedRange": "2 Beds",
                        }
                    ]
                },
            )
        ),
    )
    provider = RealtyApiProvider(api_key="test-secret", client=client)

    result = provider.search(SearchRequirements(city="Mountain View", state="CA"))[0]

    assert result.source_url == "https://www.apartments.com/example/abc123/"


def test_dict_bed_range_preserves_zero_lower_bound():
    listing = normalize_realtyapi_listing(
        {
            "listingKey": "studio-range",
            "oneLineAddress": "1 Main St, Mountain View, CA 94040",
            "address": {
                "city": "Mountain View",
                "state": "CA",
                "postalCode": "94040",
            },
            "bedRange": {"min": 0, "max": 2},
        }
    )

    assert listing.bedrooms == 2
    assert listing.bedrooms_min == 0
    assert listing.bedrooms_max == 2


def test_non_integer_bath_constraint_stays_deterministic_locally():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"searchResults": []})

    client = httpx.Client(
        base_url=REALTYAPI_BASE_URL,
        transport=httpx.MockTransport(handler),
    )
    provider = RealtyApiProvider(api_key="test-secret", client=client)
    provider.search(
        SearchRequirements(
            city="Mountain View",
            state="CA",
            min_bathrooms=1.5,
        )
    )

    assert "bathRange" not in captured["params"]

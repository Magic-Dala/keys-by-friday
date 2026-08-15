from __future__ import annotations

import json
import httpx

from rental_agent import agent as agent_module
from rental_agent.agent import search_listings
from rental_agent.commute import (
    CommuteOrigin,
    CommuteResult,
    GoogleRoutesService,
    normalize_route_matrix_response,
)
from rental_agent.models import Listing, SearchRequirements
from rental_agent.pipeline import filter_and_rank
from rental_agent.providers import get_provider


def _listing(identifier: str) -> Listing:
    return Listing(
        id=identifier,
        address=f"{identifier} Test St",
        city="Mountain View",
        state="CA",
        zip_code="94040",
        latitude=37.4,
        longitude=-122.1,
        rent=3500,
        bedrooms=2,
        bathrooms=2,
        status="active",
    )


def test_route_matrix_response_normalizes_duration_distance_and_status() -> None:
    origins = [
        CommuteOrigin("a", 37.4, -122.1),
        CommuteOrigin("b", 37.41, -122.11),
    ]
    result = normalize_route_matrix_response(
        [
            {
                "originIndex": 0,
                "destinationIndex": 0,
                "status": {},
                "condition": "ROUTE_EXISTS",
                "distanceMeters": 12400,
                "duration": "1080s",
            },
            {
                "originIndex": 1,
                "destinationIndex": 0,
                "status": {"code": 5},
                "condition": "ROUTE_MATRIX_ELEMENT_CONDITION_UNSPECIFIED",
            },
        ],
        origins,
        destination="Google Mountain View",
        mode="DRIVE",
    )

    assert result["a"] == CommuteResult(
        destination="Google Mountain View",
        mode="DRIVE",
        duration_minutes=18,
        distance_meters=12400,
        status="available",
    )
    assert result["b"].status == "unavailable"
    assert result["b"].duration_minutes is None
    assert result["b"].distance_meters is None


def test_google_routes_uses_one_route_matrix_call_for_multiple_listings() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "originIndex": 0,
                    "destinationIndex": 0,
                    "status": {},
                    "condition": "ROUTE_EXISTS",
                    "distanceMeters": 1000,
                    "duration": "600s",
                },
                {
                    "originIndex": 1,
                    "destinationIndex": 0,
                    "status": {},
                    "condition": "ROUTE_EXISTS",
                    "distanceMeters": 2000,
                    "duration": "900s",
                },
            ],
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = GoogleRoutesService("test-key", client=client)
    result = service.compute_commutes(
        [
            CommuteOrigin("a", 37.4, -122.1),
            CommuteOrigin("b", 37.41, -122.11),
        ],
        destination="Google Mountain View",
        mode="DRIVE",
    )

    assert len(calls) == 1
    assert calls[0].url.path == "/distanceMatrix/v2:computeRouteMatrix"
    assert json.loads(calls[0].content)["routingPreference"] == "TRAFFIC_AWARE"
    assert result["a"].duration_minutes == 10
    assert result["b"].duration_minutes == 15
    assert result["a"].routing_preference == "TRAFFIC_AWARE"


def test_google_routes_selected_route_uses_traffic_aware_drive() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "routes": [
                    {
                        "distanceMeters": 12400,
                        "duration": "1080s",
                        "polyline": {"encodedPolyline": "abc123"},
                    }
                ]
            },
        )

    service = GoogleRoutesService(
        "test-key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    route = service.compute_route(
        CommuteOrigin("listing-1", 37.4, -122.1),
        destination="Google Mountain View",
        mode="DRIVE",
    )

    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert body["routingPreference"] == "TRAFFIC_AWARE"
    assert route.status == "available"
    assert route.routing_preference == "TRAFFIC_AWARE"
    assert route.encoded_polyline == "abc123"


def test_route_matrix_chunks_at_100_origins_for_transit() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        assert body["travelMode"] == "TRANSIT"
        assert "routingPreference" not in body
        return httpx.Response(
            200,
            json=[
                {
                    "originIndex": index,
                    "destinationIndex": 0,
                    "status": {},
                    "condition": "ROUTE_EXISTS",
                    "distanceMeters": 1000 + index,
                    "duration": "600s",
                }
                for index in range(len(body["origins"]))
            ],
        )

    service = GoogleRoutesService(
        "test-key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    origins = [CommuteOrigin(f"listing-{index}", 37.4, -122.1) for index in range(101)]

    result = service.compute_commutes(
        origins,
        destination="Google Mountain View",
        mode="TRANSIT",
    )

    assert len(calls) == 2
    assert len(json.loads(calls[0].content)["origins"]) == 100
    assert len(json.loads(calls[1].content)["origins"]) == 1
    assert len(result) == 101
    assert all(item.status == "available" for item in result.values())


def test_hard_commute_requirement_is_deterministic_for_known_and_unknown_times() -> None:
    req = SearchRequirements(
        city="Mountain View",
        commute_destination="Google Mountain View",
        max_commute_minutes=20,
        commute_travel_mode="DRIVE",
    )
    listings = [_listing("within"), _listing("over"), _listing("unknown")]
    commutes = {
        "within": CommuteResult(
            "Google Mountain View", "DRIVE", 18, 12000, "available"
        ),
        "over": CommuteResult(
            "Google Mountain View", "DRIVE", 27, 18000, "available"
        ),
        "unknown": CommuteResult(
            "Google Mountain View", "DRIVE", status="unknown"
        ),
    }

    ranked = filter_and_rank(listings, req, top_n=10, commutes=commutes)

    assert [item.listing.id for item in ranked] == ["within"]


def test_non_commute_search_does_not_touch_maps_and_still_works(monkeypatch) -> None:
    class ExplodingService:
        def compute_commutes(self, *args, **kwargs):
            raise AssertionError("Maps must not run for ordinary rental search")

    monkeypatch.setattr(agent_module, "get_commute_service", lambda: ExplodingService())
    monkeypatch.setenv("LISTING_PROVIDER", "mock")
    get_provider.cache_clear()
    try:
        result = search_listings(
            city="Mountain View",
            max_rent=4000,
            min_bedrooms=2,
        )
    finally:
        get_provider.cache_clear()

    assert result["matched_count"] > 0
    assert result["commute_evaluations"] == {}


def test_maps_failure_is_explicit_and_does_not_false_pass_hard_commute(monkeypatch) -> None:
    class CoordinateProvider:
        def search(self, requirements):
            return [_listing("candidate")]

        def get_listing(self, listing_id):
            raise AssertionError("detail lookup should not be needed")

        def health(self):
            return {"ok": True, "provider": "coordinate-test"}

    class UnavailableService:
        def compute_commutes(
            self,
            origins,
            *,
            destination,
            mode,
            destination_place_id=None,
        ):
            return {
                origin.listing_id: CommuteResult(
                    destination=destination,
                    mode=mode,
                    status="unavailable",
                )
                for origin in origins
            }

    monkeypatch.setattr(agent_module, "get_provider", lambda: CoordinateProvider())
    monkeypatch.setattr(agent_module, "get_commute_service", lambda: UnavailableService())

    result = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        commute_destination="Google Mountain View",
        max_commute_minutes=30,
        commute_travel_mode="DRIVE",
    )

    assert result["matched_count"] == 0
    assert result["commute_evaluations"]["candidate"]["status"] == "unavailable"
    assert result["commute_evaluations"]["candidate"]["duration_minutes"] is None
    assert result["commute_summary"] == {
        "status": "unavailable",
        "evaluated_count": 1,
        "available_count": 0,
        "unavailable_count": 1,
        "unknown_count": 0,
        "within_limit_count": 0,
        "over_limit_count": 0,
    }


def test_incomplete_hard_commute_requirement_does_not_call_rental_provider(monkeypatch) -> None:
    class ExplodingProvider:
        def search(self, requirements):
            raise AssertionError("rental provider must not run before commute input is complete")

    monkeypatch.setattr(agent_module, "get_provider", lambda: ExplodingProvider())

    result = search_listings(
        city="Mountain View",
        commute_destination="Google Mountain View",
        max_commute_minutes=30,
    )

    assert result["status"] == "requires_input"
    assert result["missing_requirements"] == ["commute_travel_mode"]
    assert result["provider_search_performed"] is False
    assert result["commute_summary"]["status"] == "requires_input"


def test_clear_commute_preserves_other_requirements() -> None:
    previous = SearchRequirements(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        commute_destination="Google Mountain View",
        max_commute_minutes=30,
        commute_travel_mode="DRIVE",
    )

    merged = agent_module._merge_requirements(
        previous=previous,
        city="",
        state="",
        max_rent=None,
        min_bedrooms=None,
        max_bedrooms=None,
        min_bathrooms=None,
        max_bathrooms=None,
        pets_required=None,
        parking_required=None,
        commute_destination=None,
        max_commute_minutes=None,
        commute_travel_mode=None,
        clear_commute=True,
        soft_preferences="",
        reset_search=False,
    )

    assert merged.max_rent == 4000
    assert merged.min_bedrooms == 2
    assert merged.commute_destination is None
    assert merged.max_commute_minutes is None
    assert merged.commute_travel_mode is None

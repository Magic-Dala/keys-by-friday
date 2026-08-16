from __future__ import annotations

import json
import httpx

from backend.app.services.agent_service import (
    _commute_evaluation_from_tool_payload,
    _normalize_tool_listings,
)
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


def test_google_routes_rejects_invalid_coordinates_without_http_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("invalid coordinates must not reach Google Routes")

    service = GoogleRoutesService(
        "test-key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    for latitude, longitude in [
        (float("nan"), -122.1),
        (float("inf"), -122.1),
        (999, -122.1),
        (37.4, -999),
    ]:
        route = service.compute_route(
            CommuteOrigin("invalid", latitude, longitude),
            destination="Google Mountain View",
            mode="DRIVE",
        )
        assert route.status == "unknown"

    assert calls == []


def test_listing_coordinate_normalization_keeps_canonical_map_ready_false() -> None:
    cases = [
        ("NaN", -122.1),
        ("inf", -122.1),
        (999, -122.1),
        (37.4, -999),
        (None, -122.1),
        (37.4, None),
        (True, -122.1),
    ]
    for latitude, longitude in cases:
        listing = Listing(
            id="invalid",
            address="100 Test St",
            city="Mountain View",
            state="CA",
            zip_code="94040",
            latitude=latitude,  # type: ignore[arg-type]
            longitude=longitude,  # type: ignore[arg-type]
            rent=3500,
            bedrooms=2,
            bathrooms=2,
        )
        assert listing.to_backend_dict()["completeness"]["mapReady"] is False


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


def test_fake_commute_data_flows_from_agent_search_into_backend_contract(monkeypatch) -> None:
    class FakeProvider:
        def search(self, requirements):
            return [
                Listing(
                    id="within",
                    address="100 Castro St",
                    city="Mountain View",
                    state="CA",
                    zip_code="94041",
                    latitude=37.3947,
                    longitude=-122.0780,
                    rent=3600,
                    bedrooms=2,
                    bathrooms=2,
                    status="active",
                ),
                Listing(
                    id="over",
                    address="200 Test Ave",
                    city="Mountain View",
                    state="CA",
                    zip_code="94040",
                    latitude=37.4050,
                    longitude=-122.1150,
                    rent=3400,
                    bedrooms=2,
                    bathrooms=2,
                    status="active",
                ),
                Listing(
                    id="unknown",
                    address="300 Test Blvd",
                    city="Mountain View",
                    state="CA",
                    zip_code="94043",
                    latitude=37.4200,
                    longitude=-122.0900,
                    rent=3200,
                    bedrooms=2,
                    bathrooms=2,
                    status="active",
                ),
            ]

        def get_listing(self, listing_id):
            raise AssertionError("detail lookup is not part of this fake search flow")

        def health(self):
            return {"ok": True, "provider": "fake-provider"}

    class FakeCommuteService:
        def compute_commutes(
            self,
            origins,
            *,
            destination,
            mode,
            destination_place_id=None,
        ):
            fake = {
                "within": CommuteResult(
                    destination=destination,
                    mode=mode,
                    duration_minutes=18,
                    distance_meters=12400,
                    status="available",
                    routing_preference="TRAFFIC_AWARE",
                ),
                "over": CommuteResult(
                    destination=destination,
                    mode=mode,
                    duration_minutes=42,
                    distance_meters=28600,
                    status="available",
                    routing_preference="TRAFFIC_AWARE",
                ),
                "unknown": CommuteResult(
                    destination=destination,
                    mode=mode,
                    status="unknown",
                    routing_preference="TRAFFIC_AWARE",
                ),
            }
            return {origin.listing_id: fake[origin.listing_id] for origin in origins}

    monkeypatch.setattr(agent_module, "get_provider", lambda: FakeProvider())
    monkeypatch.setattr(agent_module, "get_commute_service", lambda: FakeCommuteService())

    agent_payload = search_listings(
        city="Mountain View",
        max_rent=4000,
        min_bedrooms=2,
        commute_destination="Google Mountain View",
        max_commute_minutes=30,
        commute_travel_mode="DRIVE",
    )

    assert agent_payload["matched_count"] == 1
    assert agent_payload["top_5"][0]["listing"]["id"] == "within"
    assert agent_payload["top_5"][0]["commute"]["duration_minutes"] == 18
    assert agent_payload["commute_summary"] == {
        "status": "partial",
        "evaluated_count": 3,
        "available_count": 2,
        "unavailable_count": 0,
        "unknown_count": 1,
        "within_limit_count": 1,
        "over_limit_count": 1,
    }

    backend_listings = _normalize_tool_listings(agent_payload, [])
    backend_evaluation = _commute_evaluation_from_tool_payload(
        agent_payload["commute_summary"]
    )

    assert len(backend_listings) == 1
    assert backend_listings[0].id == "within"
    assert backend_listings[0].latitude == 37.3947
    assert backend_listings[0].longitude == -122.0780
    assert backend_listings[0].commute is not None
    assert backend_listings[0].commute.durationMinutes == 18
    assert backend_listings[0].commute.routingPreference == "TRAFFIC_AWARE"
    assert backend_evaluation is not None
    assert backend_evaluation.status == "partial"
    assert backend_evaluation.evaluatedCount == 3
    assert backend_evaluation.withinLimitCount == 1
    assert backend_evaluation.overLimitCount == 1

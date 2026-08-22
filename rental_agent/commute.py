from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import math
import os
from typing import Protocol

import httpx

from rental_agent.coordinates import valid_coordinates


SUPPORTED_TRAVEL_MODES = {"DRIVE", "BICYCLE", "WALK", "TRANSIT"}
_MAX_MATRIX_ORIGINS_PER_REQUEST = 100


def normalize_travel_mode(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    normalized = {
        "DRIVING": "DRIVE",
        "BICYCLING": "BICYCLE",
        "WALKING": "WALK",
    }.get(normalized, normalized)
    return normalized if normalized in SUPPORTED_TRAVEL_MODES else None


@dataclass(frozen=True)
class CommuteOrigin:
    listing_id: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class CommuteResult:
    destination: str
    mode: str | None
    duration_minutes: int | None = None
    distance_meters: int | None = None
    status: str = "unknown"
    destination_place_id: str | None = None
    routing_preference: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RouteDetail:
    listing_id: str
    destination: str
    mode: str | None
    duration_minutes: int | None = None
    distance_meters: int | None = None
    encoded_polyline: str | None = None
    status: str = "unknown"
    destination_place_id: str | None = None
    routing_preference: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CommuteService(Protocol):
    def compute_commutes(
        self,
        origins: list[CommuteOrigin],
        *,
        destination: str,
        mode: str,
        destination_place_id: str | None = None,
    ) -> dict[str, CommuteResult]: ...

    def compute_route(
        self,
        origin: CommuteOrigin,
        *,
        destination: str,
        mode: str,
        destination_place_id: str | None = None,
    ) -> RouteDetail: ...


def _duration_minutes(value: object) -> int | None:
    if not isinstance(value, str) or not value.endswith("s"):
        return None
    try:
        seconds = float(value[:-1])
    except ValueError:
        return None
    if seconds < 0:
        return None
    return int(math.ceil(seconds / 60.0))


def normalize_route_matrix_response(
    payload: object,
    origins: list[CommuteOrigin],
    *,
    destination: str,
    mode: str,
    destination_place_id: str | None = None,
    routing_preference: str | None = None,
) -> dict[str, CommuteResult]:
    results = {
        origin.listing_id: CommuteResult(
            destination=destination,
            destination_place_id=destination_place_id,
            mode=mode,
            status="unknown",
            routing_preference=routing_preference,
        )
        for origin in origins
    }
    if not isinstance(payload, list):
        return results

    for element in payload:
        if not isinstance(element, dict):
            continue
        origin_index = element.get("originIndex")
        if not isinstance(origin_index, int) or not 0 <= origin_index < len(origins):
            continue
        origin = origins[origin_index]
        status_payload = element.get("status")
        status_code = status_payload.get("code", 0) if isinstance(status_payload, dict) else 0
        if status_code != 0 or element.get("condition") != "ROUTE_EXISTS":
            results[origin.listing_id] = CommuteResult(
                destination=destination,
                destination_place_id=destination_place_id,
                mode=mode,
                status="unavailable",
                routing_preference=routing_preference,
            )
            continue
        duration = _duration_minutes(element.get("duration"))
        distance = element.get("distanceMeters")
        distance_meters = distance if isinstance(distance, int) and distance >= 0 else None
        if duration is None or distance_meters is None:
            continue
        results[origin.listing_id] = CommuteResult(
            destination=destination,
            destination_place_id=destination_place_id,
            mode=mode,
            duration_minutes=duration,
            distance_meters=distance_meters,
            status="available",
            routing_preference=routing_preference,
        )
    return results


def _waypoint(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    address: str | None = None,
    place_id: str | None = None,
) -> dict[str, object]:
    if place_id:
        return {"placeId": place_id}
    if address:
        return {"address": address}
    return {
        "location": {
            "latLng": {"latitude": latitude, "longitude": longitude}
        }
    }


class GoogleRoutesService:
    MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
    ROUTE_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=15.0)

    def _headers(self, field_mask: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": field_mask,
        }

    def compute_commutes(
        self,
        origins: list[CommuteOrigin],
        *,
        destination: str,
        mode: str,
        destination_place_id: str | None = None,
    ) -> dict[str, CommuteResult]:
        if not origins:
            return {}
        normalized_mode = normalize_travel_mode(mode)
        if normalized_mode is None:
            return {
                origin.listing_id: CommuteResult(destination=destination, mode=None)
                for origin in origins
            }
        routing_preference = "TRAFFIC_AWARE" if normalized_mode == "DRIVE" else None
        valid_origins = [
            origin for origin in origins if valid_coordinates(origin.latitude, origin.longitude)
        ]
        results: dict[str, CommuteResult] = {
            origin.listing_id: CommuteResult(
                destination=destination,
                destination_place_id=destination_place_id,
                mode=normalized_mode,
                status="unknown",
                routing_preference=routing_preference,
            )
            for origin in origins
            if not valid_coordinates(origin.latitude, origin.longitude)
        }
        for start in range(0, len(valid_origins), _MAX_MATRIX_ORIGINS_PER_REQUEST):
            chunk = valid_origins[start : start + _MAX_MATRIX_ORIGINS_PER_REQUEST]
            body = {
                "origins": [
                    {"waypoint": _waypoint(latitude=item.latitude, longitude=item.longitude)}
                    for item in chunk
                ],
                "destinations": [
                    {
                        "waypoint": _waypoint(
                            address=destination if not destination_place_id else None,
                            place_id=destination_place_id,
                        )
                    }
                ],
                "travelMode": normalized_mode,
                "regionCode": "us",
            }
            if routing_preference:
                body["routingPreference"] = routing_preference
            try:
                response = self._client.post(
                    self.MATRIX_URL,
                    headers=self._headers(
                        "originIndex,destinationIndex,status,condition,distanceMeters,duration"
                    ),
                    json=body,
                )
                response.raise_for_status()
                chunk_results = normalize_route_matrix_response(
                    response.json(),
                    chunk,
                    destination=destination,
                    destination_place_id=destination_place_id,
                    mode=normalized_mode,
                    routing_preference=routing_preference,
                )
            except (httpx.HTTPError, ValueError):
                chunk_results = {
                    origin.listing_id: CommuteResult(
                        destination=destination,
                        destination_place_id=destination_place_id,
                        mode=normalized_mode,
                        status="unavailable",
                        routing_preference=routing_preference,
                    )
                    for origin in chunk
                }
            results.update(chunk_results)
        return results

    def compute_route(
        self,
        origin: CommuteOrigin,
        *,
        destination: str,
        mode: str,
        destination_place_id: str | None = None,
    ) -> RouteDetail:
        normalized_mode = normalize_travel_mode(mode)
        if normalized_mode is None:
            return RouteDetail(origin.listing_id, destination, None)
        routing_preference = "TRAFFIC_AWARE" if normalized_mode == "DRIVE" else None
        if not valid_coordinates(origin.latitude, origin.longitude):
            return RouteDetail(
                listing_id=origin.listing_id,
                destination=destination,
                mode=normalized_mode,
                status="unknown",
                routing_preference=routing_preference,
            )
        body = {
            "origin": _waypoint(latitude=origin.latitude, longitude=origin.longitude),
            "destination": _waypoint(
                address=destination if not destination_place_id else None,
                place_id=destination_place_id,
            ),
            "travelMode": normalized_mode,
            "regionCode": "us",
        }
        if routing_preference:
            body["routingPreference"] = routing_preference
        try:
            response = self._client.post(
                self.ROUTE_URL,
                headers=self._headers(
                    "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"
                ),
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return RouteDetail(
                listing_id=origin.listing_id,
                destination=destination,
                destination_place_id=destination_place_id,
                mode=normalized_mode,
                status="unavailable",
                routing_preference=routing_preference,
            )
        routes = payload.get("routes", []) if isinstance(payload, dict) else []
        route = routes[0] if isinstance(routes, list) and routes and isinstance(routes[0], dict) else None
        if route is None:
            return RouteDetail(
                origin.listing_id,
                destination,
                normalized_mode,
                status="unavailable",
                destination_place_id=destination_place_id,
                routing_preference=routing_preference,
            )
        duration = _duration_minutes(route.get("duration"))
        distance = route.get("distanceMeters")
        polyline = route.get("polyline")
        encoded = polyline.get("encodedPolyline") if isinstance(polyline, dict) else None
        if duration is None or not isinstance(distance, int):
            return RouteDetail(
                origin.listing_id,
                destination,
                normalized_mode,
                destination_place_id=destination_place_id,
                routing_preference=routing_preference,
            )
        return RouteDetail(
            listing_id=origin.listing_id,
            destination=destination,
            destination_place_id=destination_place_id,
            mode=normalized_mode,
            duration_minutes=duration,
            distance_meters=distance,
            encoded_polyline=str(encoded) if encoded else None,
            status="available",
            routing_preference=routing_preference,
        )


class UnavailableCommuteService:
    def compute_commutes(
        self,
        origins: list[CommuteOrigin],
        *,
        destination: str,
        mode: str,
        destination_place_id: str | None = None,
    ) -> dict[str, CommuteResult]:
        normalized_mode = normalize_travel_mode(mode)
        return {
            origin.listing_id: CommuteResult(
                destination=destination,
                destination_place_id=destination_place_id,
                mode=normalized_mode,
                status="unavailable",
            )
            for origin in origins
        }

    def compute_route(
        self,
        origin: CommuteOrigin,
        *,
        destination: str,
        mode: str,
        destination_place_id: str | None = None,
    ) -> RouteDetail:
        return RouteDetail(
            listing_id=origin.listing_id,
            destination=destination,
            destination_place_id=destination_place_id,
            mode=normalize_travel_mode(mode),
            status="unavailable",
        )


@lru_cache(maxsize=1)
def get_commute_service() -> CommuteService:
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        return UnavailableCommuteService()
    return GoogleRoutesService(api_key)

import { describe, expect, it } from "vitest";

import {
  commutePresentation,
  initialRouteSelectionState,
  mapReadyListings,
  routeRequestMessage,
  routeSelectionReducer,
} from "@/lib/map-model";
import type { Listing, RouteDetail } from "@/types/search";

const listing: Listing = {
  id: "home-1",
  title: "Heatherstone Apartments",
  address: "877 Heatherstone Way",
  latitude: 37.4,
  longitude: -122.1,
  commute: {
    destination: "Google Mountain View",
    mode: "DRIVE",
    durationMinutes: 18,
    distanceMeters: 12400,
    status: "available",
    routingPreference: "TRAFFIC_AWARE",
  },
};

const route: RouteDetail = {
  listingId: "home-1",
  destination: "Google Mountain View",
  mode: "DRIVE",
  durationMinutes: 18,
  distanceMeters: 12400,
  status: "available",
  encodedPolyline: "abc123",
};

describe("mapReadyListings", () => {
  it("keeps only finite coordinates without removing list-only homes", () => {
    expect(mapReadyListings([
      listing,
      { id: "missing" },
      { id: "invalid", latitude: Number.NaN, longitude: -122 },
    ])).toEqual([listing]);
  });

  it("accepts coordinate boundaries and rejects values outside the globe", () => {
    const validSouthWest = { id: "south-west", latitude: -90, longitude: -180 };
    const validNorthEast = { id: "north-east", latitude: 90, longitude: 180 };

    expect(mapReadyListings([
      validSouthWest,
      validNorthEast,
      { id: "south", latitude: -90.0001, longitude: 0 },
      { id: "north", latitude: 90.0001, longitude: 0 },
      { id: "west", latitude: 0, longitude: -180.0001 },
      { id: "east", latitude: 0, longitude: 180.0001 },
    ])).toEqual([validSouthWest, validNorthEast]);
  });
});

describe("commutePresentation", () => {
  it("distinguishes available, unavailable, and unknown commute facts", () => {
    expect(commutePresentation(listing.commute)).toMatchObject({ label: "18 min drive", tone: "available" });
    expect(commutePresentation({ destination: "Work", status: "unavailable" })).toMatchObject({ label: "Route unavailable", tone: "unavailable" });
    expect(commutePresentation(undefined)).toMatchObject({ label: "Commute unknown", tone: "unknown" });
  });
});

it("builds a deterministic route request using the existing chat contract", () => {
  expect(routeRequestMessage(listing)).toBe(
    'Show the commute route for "Heatherstone Apartments" (listing ID: home-1) to Google Mountain View by DRIVE.',
  );
});

it("ignores a stale success after a newer selection", () => {
  const loadingOne = routeSelectionReducer(initialRouteSelectionState, { type: "select", listingId: "home-1", requestId: 1 });
  const loadingTwo = routeSelectionReducer(loadingOne, { type: "select", listingId: "home-2", requestId: 2 });
  expect(routeSelectionReducer(loadingTwo, { type: "resolved", listingId: "home-1", requestId: 1, route })).toBe(loadingTwo);
});

it("clears old geometry as soon as a new home is selected", () => {
  const available = routeSelectionReducer(
    { ...initialRouteSelectionState, selectedListingId: "home-1", route, status: "available", requestId: 1 },
    { type: "select", listingId: "home-2", requestId: 2 },
  );
  expect(available).toMatchObject({ selectedListingId: "home-2", route: undefined, status: "loading", requestId: 2 });
});

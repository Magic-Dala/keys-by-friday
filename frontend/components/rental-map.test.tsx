import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

const { loadGoogleMapsMock } = vi.hoisted(() => ({ loadGoogleMapsMock: vi.fn() }));

vi.mock("@/lib/google-maps", () => ({ loadGoogleMaps: loadGoogleMapsMock }));

import { RentalMap } from "@/components/rental-map";
import { initialRouteSelectionState } from "@/lib/map-model";

const listings = [
  { id: "one", title: "Heatherstone", address: "877 Heatherstone Way", latitude: 37.4, longitude: -122.1, commute: { destination: "Google", mode: "DRIVE", durationMinutes: 18, status: "available" as const } },
  { id: "two", title: "No coordinates", commute: { destination: "Google", status: "unknown" as const } },
];

beforeEach(() => {
  loadGoogleMapsMock.mockReset();
  loadGoogleMapsMock.mockReturnValue(new Promise(() => {}));
});

it("shows an honest configuration fallback and real commute facts without a public key", () => {
  render(<RentalMap listings={listings} routeState={initialRouteSelectionState} onSelectListing={vi.fn()} apiKey="" mapId="DEMO_MAP_ID" />);
  expect(screen.getByText("Map needs a browser key")).toBeVisible();
  expect(screen.getByText("Heatherstone")).toBeVisible();
  expect(screen.getByText("877 Heatherstone Way")).toBeVisible();
  expect(screen.getByText("18 min drive")).toBeVisible();
});

it("lets fallback rows select the same listing route", async () => {
  const select = vi.fn();
  render(<RentalMap listings={listings} routeState={initialRouteSelectionState} onSelectListing={select} apiKey="" mapId="DEMO_MAP_ID" />);
  await userEvent.click(screen.getByRole("button", { name: /Select Heatherstone/ }));
  expect(select).toHaveBeenCalledWith(listings[0]);
});

it("does not load Google Maps when no home has valid coordinates", () => {
  const noCoordinates = [{ id: "missing", title: "Location pending", address: "Address under review" }];
  render(<RentalMap listings={noCoordinates} routeState={initialRouteSelectionState} onSelectListing={vi.fn()} apiKey="browser-key" mapId="DEMO_MAP_ID" />);

  expect(screen.getByText("Map needs home locations")).toBeVisible();
  expect(screen.getByText("Location pending")).toBeVisible();
  expect(loadGoogleMapsMock).not.toHaveBeenCalled();
});

it("keeps the map and route facts when the route line cannot be decoded", async () => {
  class TestMap {
    setCenter() {}
    setZoom() {}
    fitBounds() {}
  }
  class TestMarker extends EventTarget {
    map: unknown;

    constructor(options: { map?: unknown }) {
      super();
      this.map = options.map;
    }
  }
  class TestPin {}

  loadGoogleMapsMock.mockResolvedValue({
    Map: TestMap,
    AdvancedMarkerElement: TestMarker,
    PinElement: TestPin,
    encoding: { decodePath: () => { throw new Error("Invalid route geometry"); } },
  });

  render(
    <RentalMap
      listings={[listings[0]]}
      routeState={{
        selectedListingId: "one",
        status: "available",
        requestId: 1,
        route: {
          listingId: "one",
          destination: "Google",
          mode: "DRIVE",
          durationMinutes: 18,
          status: "available",
          encodedPolyline: "invalid",
        },
      }}
      onSelectListing={vi.fn()}
      apiKey="browser-key"
      mapId="DEMO_MAP_ID"
    />,
  );

  expect(await screen.findByText("Route line unavailable")).toBeVisible();
  expect(screen.queryByText("Map unavailable")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Map of recommended rental homes and the selected commute route")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("18 min drive");
  expect(screen.getByText("Invalid route geometry")).toBeVisible();
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const { loadGoogleMapsMock } = vi.hoisted(() => ({ loadGoogleMapsMock: vi.fn() }));

vi.mock("@/lib/google-maps", () => ({ loadGoogleMaps: loadGoogleMapsMock }));

import { RentalMap } from "@/components/rental-map";
import { initialRouteSelectionState } from "@/lib/map-model";

const listings = [
  { id: "one", title: "Heatherstone", address: "877 Heatherstone Way", latitude: 37.4, longitude: -122.1, commute: { destination: "Google", mode: "DRIVE", durationMinutes: 18, status: "available" as const } },
  { id: "two", title: "No coordinates", commute: { destination: "Google", status: "unknown" as const } },
];

const mapInstances: TestMap[] = [];
const markerInstances: TestMarker[] = [];
const pinInstances: TestPin[] = [];
const boundsInstances: TestBounds[] = [];
const polylineInstances: TestPolyline[] = [];

class TestMap {
  setCenter = vi.fn();
  setZoom = vi.fn();
  fitBounds = vi.fn();

  constructor() {
    mapInstances.push(this);
  }
}

class TestMarker extends EventTarget {
  map: unknown;
  title?: string;
  zIndex?: number;

  constructor(options: { map?: unknown; title?: string; zIndex?: number }) {
    super();
    this.map = options.map;
    this.title = options.title;
    this.zIndex = options.zIndex;
    markerInstances.push(this);
  }
}

class TestPin {
  background?: string | null;
  borderColor?: string | null;
  glyphColor?: string | null;
  glyphText?: string | null;
  scale?: number | null;

  constructor(options: Partial<TestPin> = {}) {
    Object.assign(this, options);
    pinInstances.push(this);
  }
}

class TestBounds {
  extend = vi.fn(() => this);

  constructor() {
    boundsInstances.push(this);
  }
}

class TestPolyline {
  map: unknown;
  options: Record<string, unknown>;
  setMap = vi.fn((map: unknown) => {
    this.map = map;
  });

  constructor(options: Record<string, unknown>) {
    this.options = options;
    this.map = options.map;
    polylineInstances.push(this);
  }
}

function installGoogleMaps(decodePath = vi.fn(() => [{ lat: 37.3, lng: -122.2 }])) {
  vi.stubGlobal("google", {
    maps: {
      LatLngBounds: TestBounds,
      Polyline: TestPolyline,
    },
  });
  loadGoogleMapsMock.mockResolvedValue({
    Map: TestMap,
    AdvancedMarkerElement: TestMarker,
    PinElement: TestPin,
    encoding: { decodePath },
  });
}

beforeEach(() => {
  loadGoogleMapsMock.mockReset();
  loadGoogleMapsMock.mockReturnValue(new Promise(() => {}));
  mapInstances.length = 0;
  markerInstances.length = 0;
  pinInstances.length = 0;
  boundsInstances.length = 0;
  polylineInstances.length = 0;
});

afterEach(() => vi.unstubAllGlobals());

it("shows an honest configuration fallback and real commute facts without a public key", () => {
  render(<RentalMap listings={listings} routeState={initialRouteSelectionState} onSelectListing={vi.fn()} apiKey="" mapId="DEMO_MAP_ID" />);
  expect(screen.getByText("Map needs browser configuration")).toBeVisible();
  expect(screen.getByText("Heatherstone")).toBeVisible();
  expect(screen.getByText("877 Heatherstone Way")).toBeVisible();
  expect(screen.getByText("18 min drive")).toBeVisible();
});

it("shows the configuration fallback and skips Maps loading when the Map ID is missing", () => {
  render(<RentalMap listings={listings} routeState={initialRouteSelectionState} onSelectListing={vi.fn()} apiKey="browser-key" />);

  expect(screen.getByText("Map needs browser configuration")).toBeVisible();
  expect(screen.getByText(/browser key and Map ID/i)).toBeVisible();
  expect(loadGoogleMapsMock).not.toHaveBeenCalled();
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

it("synchronizes selected and highlighted marker presentation by listing ID", async () => {
  installGoogleMaps();
  const mapListings = [
    listings[0],
    { ...listings[0], id: "two", title: "Birchwood", latitude: 37.5, rank: 2 },
  ];

  render(
    <RentalMap
      listings={mapListings}
      routeState={{ selectedListingId: "one", status: "loading", requestId: 1 }}
      highlightedListingId="two"
      onSelectListing={vi.fn()}
      onHighlightListing={vi.fn()}
      apiKey="browser-key"
      mapId="DEMO_MAP_ID"
    />,
  );

  await waitFor(() => expect(markerInstances).toHaveLength(2));
  expect(pinInstances[0]).toMatchObject({
    background: "#c13f35",
    borderColor: "#ffffff",
    glyphColor: "#ffffff",
    scale: 1.12,
  });
  expect(pinInstances[1]).toMatchObject({
    background: "#1d1d1f",
    borderColor: "#ffffff",
    glyphColor: "#ffffff",
    scale: 1.18,
  });
  expect(markerInstances[0]).toMatchObject({
    title: "Rank 1: Heatherstone. 18 min drive. Selected.",
    zIndex: 3,
  });
  expect(markerInstances[1]).toMatchObject({
    title: "Rank 2: Birchwood. 18 min drive.",
    zIndex: 2,
  });
});

it("shares marker hover and focus highlights without selecting a route", async () => {
  installGoogleMaps();
  const select = vi.fn();
  const highlight = vi.fn();

  render(
    <RentalMap
      listings={[listings[0]]}
      routeState={initialRouteSelectionState}
      onSelectListing={select}
      onHighlightListing={highlight}
      apiKey="browser-key"
      mapId="DEMO_MAP_ID"
    />,
  );
  await waitFor(() => expect(markerInstances).toHaveLength(1));

  markerInstances[0].dispatchEvent(new Event("pointerenter"));
  markerInstances[0].dispatchEvent(new Event("pointerleave"));
  markerInstances[0].dispatchEvent(new Event("focus"));
  markerInstances[0].dispatchEvent(new Event("blur"));

  expect(highlight.mock.calls).toEqual([["one"], [undefined], ["one"], [undefined]]);
  expect(select).not.toHaveBeenCalled();
});

it("keeps keyed marker instances alive when parent callbacks change", async () => {
  installGoogleMaps();
  const stableListings = [listings[0]];
  const highlight = vi.fn();
  const { rerender } = render(
    <RentalMap
      listings={stableListings}
      routeState={initialRouteSelectionState}
      onSelectListing={vi.fn()}
      onHighlightListing={highlight}
      apiKey="browser-key"
      mapId="DEMO_MAP_ID"
    />,
  );
  await waitFor(() => expect(markerInstances).toHaveLength(1));
  const firstMarker = markerInstances[0];

  rerender(
    <RentalMap
      listings={stableListings}
      routeState={initialRouteSelectionState}
      onSelectListing={vi.fn()}
      onHighlightListing={highlight}
      apiKey="browser-key"
      mapId="DEMO_MAP_ID"
    />,
  );

  await waitFor(() => expect(markerInstances).toHaveLength(1));
  expect(firstMarker.map).toBe(mapInstances[0]);
});

it("draws a brand route over contrasting casing and fits beneath the overlay", async () => {
  installGoogleMaps();

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
          encodedPolyline: "encoded",
        },
      }}
      onSelectListing={vi.fn()}
      onHighlightListing={vi.fn()}
      apiKey="browser-key"
      mapId="DEMO_MAP_ID"
    />,
  );

  await waitFor(() => expect(polylineInstances).toHaveLength(2));
  expect(polylineInstances[0].options).toMatchObject({
    strokeColor: "#ffffff",
    strokeOpacity: 0.9,
    strokeWeight: 9,
    zIndex: 1,
  });
  expect(polylineInstances[1].options).toMatchObject({
    strokeColor: "#c13f35",
    strokeOpacity: 1,
    strokeWeight: 5,
    zIndex: 2,
  });
  expect(boundsInstances.at(-1)?.extend).toHaveBeenCalledWith({ lat: 37.4, lng: -122.1 });
  expect(mapInstances[0].fitBounds).toHaveBeenLastCalledWith(
    boundsInstances.at(-1),
    { top: 220, right: 64, bottom: 64, left: 64 },
  );
});

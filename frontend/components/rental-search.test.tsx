import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { RentalSearch } from "@/components/rental-search";
import { getSelectedRoute, sendChat } from "@/lib/api";
import type { SearchResponse } from "@/types/search";

const { loadGoogleMapsMock } = vi.hoisted(() => ({ loadGoogleMapsMock: vi.fn() }));

vi.mock("@/lib/api", () => ({ getSelectedRoute: vi.fn(), sendChat: vi.fn() }));
vi.mock("@/lib/google-maps", () => ({ loadGoogleMaps: loadGoogleMapsMock }));

const mapInstances: TestMap[] = [];

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

  constructor(options: { map?: unknown }) {
    super();
    this.map = options.map;
  }
}

class TestPin {}

class TestBounds {
  extend = vi.fn(() => this);
}

function installGoogleMaps() {
  vi.stubGlobal("google", {
    maps: {
      LatLngBounds: TestBounds,
      Polyline: class {},
    },
  });
  loadGoogleMapsMock.mockResolvedValue({
    Map: TestMap,
    AdvancedMarkerElement: TestMarker,
    PinElement: TestPin,
    encoding: { decodePath: vi.fn() },
  });
}

const searchResponse: SearchResponse = {
  conversationId: "conversation-1",
  message: "I found one strong match.",
  listings: [
    {
      id: "one",
      title: "Heatherstone",
      latitude: 37.4,
      longitude: -122.1,
      commute: {
        destination: "Google",
        mode: "DRIVE",
        durationMinutes: 18,
        status: "available",
      },
    },
  ],
  mode: "adk",
};

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(getSelectedRoute).mockReset();
  vi.mocked(sendChat).mockReset();
  loadGoogleMapsMock.mockReset();
  mapInstances.length = 0;
  vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("aborts and clears an active route as soon as a refinement starts", async () => {
  let routeSignal: AbortSignal | undefined;
  vi.mocked(sendChat)
    .mockResolvedValueOnce(searchResponse)
    .mockImplementationOnce(() => new Promise(() => {}));
  vi.mocked(getSelectedRoute)
    .mockImplementationOnce((_request, options) => {
      routeSignal = options?.signal;
      return new Promise(() => {});
    });

  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.type(screen.getByLabelText("Describe your ideal rental"), "Find one home");
  await user.click(screen.getByRole("button", { name: "Ask rental agent" }));
  const selectHome = await screen.findByRole("button", {
    name: "Select Heatherstone on the map and load its route",
  });

  await user.click(selectHome);
  expect(await screen.findByText("Selected on map")).toBeVisible();
  expect(routeSignal?.aborted).toBe(false);

  await user.type(screen.getByLabelText("Refine your request"), "Add parking");
  await user.click(screen.getByRole("button", { name: "Refine search" }));

  await waitFor(() => expect(routeSignal?.aborted).toBe(true));
  expect(screen.getByRole("status")).toHaveTextContent("Select a home to see its commute route.");
});

it("waits to initialize and fit Google Maps until the mobile Map view is selected", async () => {
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "browser-key");
  vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID", "map-id");
  installGoogleMaps();
  vi.mocked(sendChat).mockResolvedValue({
    ...searchResponse,
    listings: [
      ...searchResponse.listings,
      {
        id: "two",
        title: "Birchwood",
        latitude: 37.5,
        longitude: -122.2,
        commute: { destination: "Google", mode: "DRIVE", durationMinutes: 22, status: "available" },
      },
    ],
  });

  render(<RentalSearch />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Describe your ideal rental"), "Find two homes");
  await user.click(screen.getByRole("button", { name: "Ask rental agent" }));
  await screen.findByText("The strongest matches");

  expect(loadGoogleMapsMock).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "Map" }));

  await waitFor(() => expect(loadGoogleMapsMock).toHaveBeenCalledWith("browser-key"));
  expect(mapInstances[0].fitBounds).toHaveBeenCalled();
});

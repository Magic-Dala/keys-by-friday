import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { RentalSearch } from "@/components/rental-search";
import { compareListings, getSelectedRoute, getShortlist, sendChat } from "@/lib/api";
import type { CanonicalListing, SearchResponse } from "@/types/search";

const { loadGoogleMapsMock } = vi.hoisted(() => ({ loadGoogleMapsMock: vi.fn() }));

vi.mock("@/lib/api", () => ({
  compareListings: vi.fn(),
  getSelectedRoute: vi.fn(),
  getShortlist: vi.fn(),
  removeShortlistItem: vi.fn(),
  saveShortlistItem: vi.fn(),
  sendChat: vi.fn(),
}));
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
  searchPerformed: true,
  mode: "adk",
};

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(getSelectedRoute).mockReset();
  vi.mocked(compareListings).mockReset();
  vi.mocked(getShortlist).mockReset();
  vi.mocked(getShortlist).mockResolvedValue({ items: [] });
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

it("loads deterministic comparison facts and the Agent explanation", async () => {
  const listings = [
    {
      id: "one",
      title: "Heatherstone",
      price: 3180,
      bedrooms: 2,
      bathrooms: 2,
    },
    {
      id: "two",
      title: "Birchwood",
      price: 3450,
      bedrooms: 2,
      bathrooms: 2,
    },
  ];
  vi.mocked(sendChat).mockResolvedValue({
    ...searchResponse,
    listings,
  });
  const verifiedHeatherstone: CanonicalListing = {
    schemaVersion: "kbf.canonical-listing.v1",
    identity: { id: "one", sourceListingId: "one", propertyName: null },
    location: {
      address: null,
      city: null,
      state: null,
      zipCode: null,
      countryCode: null,
      latitude: null,
      longitude: null,
    },
    pricing: { rent: 3180, rentMin: null, rentMax: null },
    property: {
      bedrooms: 2,
      bedroomsMin: null,
      bedroomsMax: null,
      bathrooms: 2,
      bathroomsMinEvidence: null,
      propertyType: null,
    },
    availability: {},
    policies: { petsAllowed: true, parkingAvailable: true },
    features: {},
    media: {},
    contact: {},
    source: {},
    evidence: { detailVerified: true, queryBackedFields: [] },
    completeness: {},
  };
  vi.mocked(compareListings).mockResolvedValue({
    conversationId: "conversation-1",
    message: "Gemini prose says Heatherstone pets are not allowed.",
    listings: [
      {
        ...listings[0],
        canonicalListing: verifiedHeatherstone,
      },
      {
        ...listings[1],
        canonicalListing: {
          ...verifiedHeatherstone,
          identity: { id: "two", sourceListingId: "two", propertyName: null },
          policies: { petsAllowed: null, parkingAvailable: true },
          evidence: {
            detailVerified: true,
            queryBackedFields: ["policies.parkingAvailable"],
          },
        },
      },
    ],
    comparison: {
      schemaVersion: "kbf.canonical-comparison.v1",
      listingIds: ["one", "two"],
      results: [
        {
          listingId: "one",
          hardConstraintStatus: "pass",
          satisfiesCurrentRequirements: true,
          softPreferenceEvidence: [{ preference: "quiet", status: "supported" }],
          tradeoffs: ["Older building"],
          comparisonUnknowns: [],
          decisionUnknowns: [],
          decisionReady: true,
          score: 90,
          rank: 1,
        },
        {
          listingId: "two",
          hardConstraintStatus: "evidence_only",
          satisfiesCurrentRequirements: null,
          softPreferenceEvidence: [],
          tradeoffs: [],
          comparisonUnknowns: [
            "policies.parkingAvailable",
            "media.primaryImageUrl",
            "availability.moveInDate",
          ],
          decisionUnknowns: [
            "policies.parkingAvailable",
            "media.primaryImageUrl",
            "availability.moveInDate",
          ],
          decisionReady: false,
          score: 85,
          rank: 2,
        },
      ],
    },
    searchPerformed: false,
    mode: "adk",
  });

  render(<RentalSearch />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Describe your ideal rental"), "Find two homes");
  await user.click(screen.getByRole("button", { name: "Ask rental agent" }));
  await screen.findByText("The strongest matches");

  const compareButtons = screen.getAllByRole("button", { name: "Compare" });
  await user.click(compareButtons[0]);
  await user.click(compareButtons[1]);
  await user.click(screen.getByRole("button", { name: "Compare homes" }));

  expect(compareListings).toHaveBeenCalledWith(
    ["one", "two"],
    "conversation-1",
    expect.objectContaining({ signal: expect.any(AbortSignal) }),
  );
  expect(await screen.findByText("Passes confirmed requirements")).toBeVisible();
  expect(screen.getByText("Needs stronger verification")).toBeVisible();
  expect(screen.getByText("Parking availability")).toBeVisible();
  expect(screen.getByText("Listing photo")).toBeVisible();
  expect(screen.getByText("Move in date")).toBeVisible();
  expect(screen.queryByText("policies.parkingAvailable")).not.toBeInTheDocument();
  expect(screen.queryByText("media.primaryImageUrl")).not.toBeInTheDocument();
  expect(screen.queryByText("availability.moveInDate")).not.toBeInTheDocument();
  expect(screen.getByText(/Gemini prose says Heatherstone pets are not allowed/)).toBeVisible();
  const comparisonPanel = screen.getByRole("region", {
    name: "Compare the details that matter",
  });
  const heatherstoneCard = within(comparisonPanel)
    .getByRole("heading", { name: "Heatherstone" })
    .closest("article");
  expect(heatherstoneCard).not.toBeNull();
  const petsRow = within(heatherstoneCard as HTMLElement)
    .getByText("Pets allowed")
    .closest("div");
  expect(petsRow).toHaveTextContent("Yes");
  const birchwoodCard = within(comparisonPanel)
    .getByRole("heading", { name: "Birchwood" })
    .closest("article");
  expect(birchwoodCard).not.toBeNull();
  const parkingRow = within(birchwoodCard as HTMLElement)
    .getByText("Parking available")
    .closest("div");
  expect(parkingRow).toHaveTextContent("Needs verification");
});

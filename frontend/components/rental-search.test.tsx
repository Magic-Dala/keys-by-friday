import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { RentalSearch } from "@/components/rental-search";
import { compareListings, getRecentSearches, getSelectedRoute, getShortlist, sendChat } from "@/lib/api";
import {
  createAccountWithEmail,
  observeFirebaseUser,
  signInWithEmail,
  signInWithGoogle,
  signOutToAnonymous,
} from "@/lib/firebase-auth";
import type { CanonicalListing, RecentSearch, SearchResponse } from "@/types/search";

const { loadGoogleMapsMock } = vi.hoisted(() => ({ loadGoogleMapsMock: vi.fn() }));

vi.mock("@/lib/api", () => ({
  getRecentSearches: vi.fn(),
  compareListings: vi.fn(),
  getSelectedRoute: vi.fn(),
  getShortlist: vi.fn(),
  removeShortlistItem: vi.fn(),
  saveShortlistItem: vi.fn(),
  sendChat: vi.fn(),
}));
vi.mock("@/lib/firebase-auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/firebase-auth")>();
  return {
    ...actual,
    createAccountWithEmail: vi.fn(),
    observeFirebaseUser: vi.fn(),
    signInWithEmail: vi.fn(),
    signInWithGoogle: vi.fn(),
    signOutToAnonymous: vi.fn(),
  };
});
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
  vi.mocked(getRecentSearches).mockReset();
  vi.mocked(getRecentSearches).mockResolvedValue({ items: [] });
  vi.mocked(getSelectedRoute).mockReset();
  vi.mocked(compareListings).mockReset();
  vi.mocked(getShortlist).mockReset();
  vi.mocked(getShortlist).mockResolvedValue({ items: [] });
  vi.mocked(sendChat).mockReset();
  vi.mocked(observeFirebaseUser).mockReset();
  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    listener({
      uid: "anon-1",
      isAnonymous: true,
      displayName: null,
      email: null,
    } as never);
    return vi.fn();
  });
  vi.mocked(signInWithGoogle).mockReset();
  vi.mocked(signInWithEmail).mockReset();
  vi.mocked(createAccountWithEmail).mockReset();
  vi.mocked(signOutToAnonymous).mockReset();
  loadGoogleMapsMock.mockReset();
  mapInstances.length = 0;
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "firebase");
  vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "");
});

it("shows remembered requirements and sends a guided choice in the same conversation", async () => {
  vi.mocked(sendChat)
    .mockResolvedValueOnce({
      ...searchResponse,
      message: "I need your commute destination before I search.",
      listings: [],
      requirements: {
        city: "Mountain View",
        state: "CA",
        maxRent: 4000,
        minBedrooms: 2,
        maxCommuteMinutes: 30,
        softPreferences: ["quiet"],
      },
      missingRequirements: ["commute_destination", "commute_travel_mode"],
    })
    .mockResolvedValueOnce({
      ...searchResponse,
      message: "Got it. How do you usually commute?",
      listings: [],
      requirements: {
        city: "Mountain View",
        state: "CA",
        maxRent: 4000,
        minBedrooms: 2,
        maxCommuteMinutes: 30,
        commuteDestination: "Google Mountain View",
        softPreferences: ["quiet"],
      },
      missingRequirements: ["commute_travel_mode"],
    });

  render(<RentalSearch />);
  const user = userEvent.setup();
  await user.type(
    screen.getByLabelText("Describe your ideal rental"),
    "Quiet 2 bed under $4,000 in Mountain View, commute under 30 minutes",
  );
  await user.click(screen.getByRole("button", { name: "Ask rental agent" }));

  expect(await screen.findByText("Agent remembers")).toBeVisible();
  expect(screen.getByText("Mountain View, CA")).toBeVisible();
  expect(screen.getByText("≤ $4,000/mo")).toBeVisible();
  expect(screen.getByText("Where do you commute to?")).toBeVisible();

  await user.click(screen.getByRole("button", { name: "Google Mountain View" }));

  await waitFor(() => {
    expect(sendChat).toHaveBeenNthCalledWith(
      2,
      {
        message: "My commute destination is Google Mountain View.",
        conversationId: "conversation-1",
      },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });
  expect(await screen.findByText("How do you usually commute?")).toBeVisible();
  expect(screen.getByText("to Google Mountain View")).toBeVisible();
});

function recentSearch(overrides: Partial<RecentSearch> = {}): RecentSearch {
  return {
    conversationId: "historical-conversation",
    createdAt: "2026-08-20T18:00:00Z",
    updatedAt: "2026-08-20T18:15:00Z",
    turnCount: 4,
    listings: [
      {
        id: "historical-listing",
        title: "Saved Heatherstone",
        address: "877 Heatherstone Way",
        priceMin: 3450,
        priceMax: 3950,
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
    lastCommuteStatus: "available",
    ...overrides,
  };
}

function displayedRecentSearchDate(timestamp = "2026-08-20T18:15:00Z") {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(timestamp));
}

it("does not show another account's Recent Searches to an anonymous user", () => {
  render(<RentalSearch />);

  expect(screen.queryByRole("heading", { name: "Recent Searches" })).not.toBeInTheDocument();
  expect(getRecentSearches).not.toHaveBeenCalled();
});

it("shows authenticated Recent Searches in the order returned by the backend", async () => {
  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    listener({
      uid: "email-2",
      isAnonymous: false,
      displayName: "Ada Lovelace",
      email: "ada@example.com",
    } as never);
    return vi.fn();
  });
  vi.mocked(getRecentSearches).mockResolvedValue({
    items: [
      recentSearch({ conversationId: "newest", updatedAt: "2026-08-20T18:15:00Z" }),
      recentSearch({ conversationId: "older", updatedAt: "2026-08-19T18:15:00Z" }),
    ],
  });

  render(<RentalSearch />);

  const panel = await screen.findByRole("region", { name: "Recent Searches" });
  await waitFor(() => expect(getRecentSearches).toHaveBeenCalledTimes(1));
  expect(getRecentSearches).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) });
  const panelText = panel.textContent ?? "";
  expect(panelText.indexOf(`Updated ${displayedRecentSearchDate("2026-08-20T18:15:00Z")}`)).toBeLessThan(
    panelText.indexOf(`Updated ${displayedRecentSearchDate("2026-08-19T18:15:00Z")}`),
  );
  expect(within(panel).getAllByRole("heading", { name: "Rental search" })).toHaveLength(2);
});

it("clears the previous account's Recent Searches when Firebase UID changes", async () => {
  let notifyAuthChange: ((user: unknown) => void) | undefined;
  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    notifyAuthChange = listener as (user: unknown) => void;
    listener({ uid: "email-1", isAnonymous: false, displayName: "Ada", email: "ada@example.com" } as never);
    return vi.fn();
  });
  vi.mocked(getRecentSearches)
    .mockResolvedValueOnce({ items: [recentSearch({ conversationId: "old-account" })] })
    .mockImplementationOnce(() => new Promise(() => undefined));

  render(<RentalSearch />);
  const updatedLabel = `Updated ${displayedRecentSearchDate()} · 4 turns`;
  expect(await screen.findByText(updatedLabel)).toBeVisible();

  await act(async () => {
    notifyAuthChange?.({ uid: "email-2", isAnonymous: false, displayName: "Grace", email: "grace@example.com" });
  });

  await waitFor(() => expect(getRecentSearches).toHaveBeenCalledTimes(2));
  expect(screen.queryByText(updatedLabel)).not.toBeInTheDocument();
});

it("restores saved listings without fabricating transcript turns and continues with its conversation ID", async () => {
  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    listener({ uid: "email-2", isAnonymous: false, displayName: "Ada", email: "ada@example.com" } as never);
    return vi.fn();
  });
  vi.mocked(getRecentSearches).mockResolvedValue({ items: [recentSearch()] });
  vi.mocked(sendChat).mockResolvedValue(searchResponse);

  render(<RentalSearch />);
  const user = userEvent.setup();
  const panel = await screen.findByRole("region", { name: "Recent Searches" });

  await user.click(within(panel).getByRole("button", { name: "View Results" }));

  expect(await screen.findByText("The strongest matches")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Saved Heatherstone" })).toBeVisible();
  expect(
    screen.getByText(`Showing the latest saved results from ${displayedRecentSearchDate()}.`),
  ).toBeVisible();
  expect(screen.getByText("Verify").closest("li")).toHaveClass("isCurrent");
  expect(screen.queryByText("I found one strong match.")).not.toBeInTheDocument();

  await user.type(screen.getByLabelText("Refine your request"), "Add parking");
  await user.click(screen.getByRole("button", { name: "Refine search" }));

  await waitFor(() => expect(sendChat).toHaveBeenCalledWith(
    { message: "Add parking", conversationId: "historical-conversation" },
    { signal: expect.any(AbortSignal) },
  ));
});

it("focuses the composer and indicates continuation from Continue Search", async () => {
  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    listener({ uid: "email-2", isAnonymous: false, displayName: "Ada", email: "ada@example.com" } as never);
    return vi.fn();
  });
  vi.mocked(getRecentSearches).mockResolvedValue({ items: [recentSearch()] });
  vi.mocked(sendChat).mockResolvedValue(searchResponse);

  render(<RentalSearch />);
  const user = userEvent.setup();
  const panel = await screen.findByRole("region", { name: "Recent Searches" });

  await user.click(within(panel).getByRole("button", { name: "Continue Search" }));

  await waitFor(() => expect(screen.getByLabelText("Refine your request")).toHaveFocus());
  expect(screen.getByText(`Continuing your search from ${displayedRecentSearchDate()}.`)).toBeVisible();
});

it("does not turn a successful chat result into an error when history refresh fails", async () => {
  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    listener({ uid: "email-2", isAnonymous: false, displayName: "Ada", email: "ada@example.com" } as never);
    return vi.fn();
  });
  vi.mocked(getRecentSearches)
    .mockResolvedValueOnce({ items: [] })
    .mockRejectedValueOnce(new Error("Recent searches are unavailable."));
  vi.mocked(sendChat).mockResolvedValue(searchResponse);

  render(<RentalSearch />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Describe your ideal rental"), "Find one home");
  await user.click(screen.getByRole("button", { name: "Ask rental agent" }));

  expect(await screen.findByRole("heading", { name: "Heatherstone" })).toBeVisible();
  await waitFor(() => expect(getRecentSearches).toHaveBeenCalledTimes(2));
  expect(screen.queryByText("The search could not be completed.")).not.toBeInTheDocument();
  expect(screen.getByText("Recent searches are unavailable.")).toBeVisible();
});
it("opens one sign-in dialog that contains Google and email options", async () => {
  render(<RentalSearch />);
  const user = userEvent.setup();

  const signIn = await screen.findByRole("button", { name: "Sign in" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

  await user.click(signIn);

  const dialog = screen.getByRole("dialog", { name: "Sign in to Keys by Friday" });
  const email = within(dialog).getByLabelText("Email address");
  const google = within(dialog).getByRole("button", { name: "Continue with Google" });
  expect(dialog).toBeVisible();
  expect(email).toBeVisible();
  expect(within(dialog).getByLabelText("Password")).toBeVisible();
  expect(within(dialog).getByRole("button", { name: "Forgot password?" })).toBeVisible();
  expect(within(dialog).getByRole("button", { name: "Create account" })).toBeVisible();
  expect(google).toBeVisible();
  expect(email.compareDocumentPosition(google) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("toggles the email/password visibility control", async () => {
  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Sign in" }));
  const dialog = screen.getByRole("dialog");
  const password = within(dialog).getByLabelText("Password");
  const toggle = within(dialog).getByRole("button", { name: "Show password" });

  expect(password).toHaveAttribute("type", "password");
  await user.click(toggle);
  expect(password).toHaveAttribute("type", "text");
  expect(within(dialog).getByRole("button", { name: "Hide password" })).toBeVisible();

  await user.click(within(dialog).getByRole("button", { name: "Hide password" }));
  expect(password).toHaveAttribute("type", "password");
});

it("signs in with Google from the sign-in dialog", async () => {
  vi.mocked(signInWithGoogle).mockResolvedValue({
    uid: "anon-1",
    isAnonymous: false,
    displayName: "Ada Lovelace",
    email: "ada@example.com",
  } as never);

  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Sign in" }));
  const dialog = screen.getByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Continue with Google" }));

  expect(signInWithGoogle).toHaveBeenCalledTimes(1);
});

it("switches to account creation and creates an email/password account", async () => {
  vi.mocked(createAccountWithEmail).mockResolvedValue({
    uid: "anon-1",
    isAnonymous: false,
    displayName: null,
    email: "ada@example.com",
  } as never);

  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Sign in" }));
  let dialog = screen.getByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Create account" }));

  expect(screen.getByRole("dialog", { name: "Create your account" })).toBeVisible();
  dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText("Email address"), "ada@example.com");
  await user.type(within(dialog).getByLabelText("Password"), "secret123");
  await user.click(within(dialog).getByRole("button", { name: "Create account" }));

  expect(createAccountWithEmail).toHaveBeenCalledWith("ada@example.com", "secret123");
});

it("signs in to an existing email/password account from the dialog", async () => {
  vi.mocked(signInWithEmail).mockResolvedValue({
    uid: "email-2",
    isAnonymous: false,
    displayName: null,
    email: "ada@example.com",
  } as never);

  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Sign in" }));
  const dialog = screen.getByRole("dialog");
  await user.type(within(dialog).getByLabelText("Email address"), "ada@example.com");
  await user.type(within(dialog).getByLabelText("Password"), "secret123");
  await user.click(within(dialog).getByRole("button", { name: "Sign in" }));

  expect(signInWithEmail).toHaveBeenCalledWith("ada@example.com", "secret123");
});

it("shows inline validation instead of silently disabling account creation", async () => {
  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Sign in" }));
  const dialog = screen.getByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Create account" }));
  await user.type(within(dialog).getByLabelText("Email address"), "ada@example.com");
  await user.type(within(dialog).getByLabelText("Password"), "123");
  await user.click(within(dialog).getByRole("button", { name: "Create account" }));

  expect(screen.getByRole("alert")).toHaveTextContent("Use at least 6 characters for your password.");
  expect(createAccountWithEmail).not.toHaveBeenCalled();
});

it("keeps forgot-password as a clear placeholder action", async () => {
  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Sign in" }));
  const dialog = screen.getByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Forgot password?" }));

  expect(within(dialog).getByRole("status")).toHaveTextContent("Password reset is coming soon.");
});

it("shows the Google account identity and signs out to a fresh anonymous session", async () => {
  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    listener({
      uid: "google-2",
      isAnonymous: false,
      displayName: "Ada Lovelace",
      email: "ada@example.com",
    } as never);
    return vi.fn();
  });
  vi.mocked(signOutToAnonymous).mockResolvedValue({
    uid: "anon-3",
    isAnonymous: true,
    displayName: null,
    email: null,
  } as never);

  render(<RentalSearch />);
  const user = userEvent.setup();

  expect(await screen.findByText("Ada Lovelace")).toBeVisible();
  expect(screen.getByText("ada@example.com")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Sign Out" }));

  expect(signOutToAnonymous).toHaveBeenCalledTimes(1);
});

it("preserves rental state when an anonymous user is linked without changing UID", async () => {
  let notifyAuthChange: ((user: unknown) => void) | undefined;
  const linkedUser = {
    uid: "anon-1",
    isAnonymous: false,
    displayName: "Ada Lovelace",
    email: "ada@example.com",
  };
  const secondListing = {
    id: "two",
    title: "Birchwood",
    latitude: 37.5,
    longitude: -122.2,
    commute: { destination: "Google", mode: "DRIVE" as const, durationMinutes: 22, status: "available" as const },
  };

  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    notifyAuthChange = listener as (user: unknown) => void;
    listener({ uid: "anon-1", isAnonymous: true, displayName: null, email: null } as never);
    return vi.fn();
  });
  vi.mocked(getShortlist).mockResolvedValue({
    items: [{ listing: searchResponse.listings[0], sourceConversationId: "conversation-anon", savedAt: "", updatedAt: "" }],
  });
  vi.mocked(sendChat).mockResolvedValue({
    ...searchResponse,
    conversationId: "conversation-anon",
    listings: [searchResponse.listings[0], secondListing],
  });

  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.type(screen.getByLabelText("Describe your ideal rental"), "Find two homes");
  await user.click(screen.getByRole("button", { name: "Ask rental agent" }));
  expect(await screen.findByRole("heading", { name: "Heatherstone" })).toBeVisible();
  expect(screen.getByText("1 saved")).toBeVisible();

  await user.click(screen.getAllByRole("button", { name: "Compare" })[0]);
  await user.click(screen.getAllByRole("button", { name: "Compare" })[0]);
  await user.click(screen.getByRole("button", { name: "Compare homes" }));
  expect(screen.getByRole("heading", { name: "Compare the details that matter" })).toBeVisible();

  await act(async () => notifyAuthChange?.(linkedUser));

  expect(screen.getByText("I found one strong match.")).toBeVisible();
  expect(screen.getAllByRole("heading", { name: "Heatherstone" })).toHaveLength(2);
  expect(screen.getByRole("heading", { name: "Compare the details that matter" })).toBeVisible();
  expect(getShortlist).toHaveBeenCalledTimes(1);
});

it("resets rental state and refetches the shortlist when UID changes", async () => {
  let notifyAuthChange: ((user: unknown) => void) | undefined;
  const secondListing = {
    id: "two",
    title: "Birchwood",
    latitude: 37.5,
    longitude: -122.2,
    commute: { destination: "Google", mode: "DRIVE" as const, durationMinutes: 22, status: "available" as const },
  };

  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    notifyAuthChange = listener as (user: unknown) => void;
    listener({ uid: "anon-1", isAnonymous: true, displayName: null, email: null } as never);
    return vi.fn();
  });
  vi.mocked(getShortlist)
    .mockResolvedValueOnce({
      items: [{ listing: searchResponse.listings[0], sourceConversationId: "conversation-anon", savedAt: "", updatedAt: "" }],
    })
    .mockResolvedValueOnce({ items: [] });
  vi.mocked(sendChat).mockResolvedValue({
    ...searchResponse,
    conversationId: "conversation-anon",
    listings: [searchResponse.listings[0], secondListing],
  });

  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.type(screen.getByLabelText("Describe your ideal rental"), "Find two homes");
  await user.click(screen.getByRole("button", { name: "Ask rental agent" }));
  expect(await screen.findByRole("heading", { name: "Heatherstone" })).toBeVisible();
  expect(screen.getByText("1 saved")).toBeVisible();

  await user.click(screen.getAllByRole("button", { name: "Compare" })[0]);
  await user.click(screen.getAllByRole("button", { name: "Compare" })[0]);
  await user.click(screen.getByRole("button", { name: "Compare homes" }));
  expect(screen.getByRole("heading", { name: "Compare the details that matter" })).toBeVisible();

  await act(async () => notifyAuthChange?.({ uid: "email-2", isAnonymous: false, displayName: "Grace Hopper", email: "grace@example.com" }));

  await waitFor(() => expect(getShortlist).toHaveBeenCalledTimes(2));
  expect(screen.queryByText("I found one strong match.")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Heatherstone" })).not.toBeInTheDocument();
  expect(screen.getByText("Nothing saved yet")).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Compare the details that matter" })).not.toBeInTheDocument();
});

it("loads the shortlist when auth is disabled and no Firebase user is observed", async () => {
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "disabled");
  vi.mocked(observeFirebaseUser).mockImplementation((listener) => {
    listener(null);
    return vi.fn();
  });
  vi.mocked(getShortlist).mockResolvedValue({
    items: [{ listing: searchResponse.listings[0], sourceConversationId: "local-conversation", savedAt: "", updatedAt: "" }],
  });

  render(<RentalSearch />);

  expect(await screen.findByText("1 saved")).toBeVisible();
  expect(screen.getByText("Heatherstone")).toBeVisible();
  expect(getShortlist).toHaveBeenCalledTimes(1);
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
            "property.bathrooms",
            "policies.parkingAvailable",
            "media.primaryImageUrl",
            "availability.moveInDate",
          ],
          decisionUnknowns: [
            "property.bathrooms",
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
  const decisionOutcome = screen.getByLabelText("Decision outcome");
  expect(within(decisionOutcome).getByRole("heading", { name: "Decision pending" })).toBeVisible();
  expect(decisionOutcome).toHaveTextContent("Bathroom count");
  expect(decisionOutcome).toHaveTextContent("before making a final recommendation");
});

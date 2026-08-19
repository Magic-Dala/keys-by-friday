import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { RentalSearch } from "@/components/rental-search";
import { getSelectedRoute, getShortlist, sendChat } from "@/lib/api";
import {
  createAccountWithEmail,
  observeFirebaseUser,
  signInWithEmail,
  signInWithGoogle,
  signOutToAnonymous,
} from "@/lib/firebase-auth";
import type { SearchResponse } from "@/types/search";

const { loadGoogleMapsMock } = vi.hoisted(() => ({ loadGoogleMapsMock: vi.fn() }));

vi.mock("@/lib/api", () => ({
  getSelectedRoute: vi.fn(),
  getShortlist: vi.fn(),
  removeShortlistItem: vi.fn(),
  saveShortlistItem: vi.fn(),
  sendChat: vi.fn(),
}));
vi.mock("@/lib/firebase-auth", () => ({
  createAccountWithEmail: vi.fn(),
  observeFirebaseUser: vi.fn(),
  signInWithEmail: vi.fn(),
  signInWithGoogle: vi.fn(),
  signOutToAnonymous: vi.fn(),
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
  mode: "adk",
};

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(getSelectedRoute).mockReset();
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
  vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "");
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

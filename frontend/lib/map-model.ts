import type { Commute, Listing, RouteDetail } from "@/types/search";

export type MapReadyListing = Listing & { latitude: number; longitude: number };
export type RouteStatus = "idle" | "loading" | "available" | "unavailable" | "unknown" | "error";

export interface RouteSelectionState {
  selectedListingId?: string;
  route?: RouteDetail;
  status: RouteStatus;
  error?: string;
  requestId: number;
}

export type RouteSelectionAction =
  | { type: "select"; listingId: string; requestId: number }
  | { type: "resolved"; listingId: string; requestId: number; route?: RouteDetail }
  | { type: "rejected"; listingId: string; requestId: number; error: string }
  | { type: "reset" };

export const initialRouteSelectionState: RouteSelectionState = { status: "idle", requestId: 0 };

export function hasMapCoordinates(listing: Listing): listing is MapReadyListing {
  const { latitude, longitude } = listing;
  return (
    typeof latitude === "number"
    && Number.isFinite(latitude)
    && latitude >= -90
    && latitude <= 90
    && typeof longitude === "number"
    && Number.isFinite(longitude)
    && longitude >= -180
    && longitude <= 180
  );
}

export function mapReadyListings(listings: Listing[]): MapReadyListing[] {
  return listings.filter(hasMapCoordinates);
}

export function commutePresentation(commute?: Commute) {
  if (!commute || commute.status === "unknown") return { label: "Commute unknown", tone: "unknown" as const };
  if (commute.status === "unavailable") return { label: "Route unavailable", tone: "unavailable" as const };
  const mode = commute.mode?.toLowerCase();
  return {
    label: commute.durationMinutes === undefined
      ? "Commute available"
      : `${commute.durationMinutes} min${mode ? ` ${mode === "drive" ? "drive" : mode.toLowerCase()}` : ""}`,
    detail: commute.distanceMeters === undefined ? undefined : `${(commute.distanceMeters / 1609.344).toFixed(1)} mi`,
    tone: "available" as const,
  };
}

export function routeRequestMessage(listing: Listing): string {
  const label = listing.title ?? listing.address ?? "Rental home";
  const destination = listing.commute?.destination;
  const mode = listing.commute?.mode;
  return `Show the commute route for "${label}" (listing ID: ${listing.id})${destination ? ` to ${destination}` : ""}${mode ? ` by ${mode}` : ""}.`;
}

export function routeSelectionReducer(state: RouteSelectionState, action: RouteSelectionAction): RouteSelectionState {
  if (action.type === "reset") return initialRouteSelectionState;
  if (action.type === "select") return { selectedListingId: action.listingId, route: undefined, status: "loading", requestId: action.requestId };
  if (action.requestId !== state.requestId || action.listingId !== state.selectedListingId) return state;
  if (action.type === "rejected") return { ...state, route: undefined, status: "error", error: action.error };
  if (!action.route || action.route.listingId !== action.listingId) return { ...state, route: undefined, status: "unknown", error: undefined };
  return { ...state, route: action.route, status: action.route.status, error: undefined };
}

import { getFirebaseIdToken } from "@/lib/firebase-auth";
import type {
  Comparison,
  ComparisonResult,
  Commute,
  CommuteEvaluation,
  Listing,
  RouteDetail,
  RecentSearch,
  RecentSearchResponse,
  SelectedRouteRequest,
  SearchRequest,
  SearchResponse,
  ShortlistItem,
  ShortlistResponse,
  SourcePosting,
} from "@/types/search";

const backendUrl = (
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown, field: string): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "string") throw new ApiError(`Invalid ${field} in API response.`);
  return value;
}

function optionalNumber(value: unknown, field: string): number | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new ApiError(`Invalid ${field} in API response.`);
  }
  return value;
}

function optionalUrl(value: unknown, field: string): string | undefined {
  const url = optionalString(value, field);
  if (url === undefined) return undefined;
  try {
    const parsed = new URL(url);
    if (parsed.protocol === "http:" || parsed.protocol === "https:") return parsed.toString();
  } catch {
    // Fall through to the stable response-shape error below.
  }
  throw new ApiError(`Invalid ${field} in API response.`);
}

function parseSourcePosting(value: unknown): SourcePosting {
  if (!isRecord(value) || typeof value.id !== "string") {
    throw new ApiError("Invalid source posting in API response.");
  }
  return {
    id: value.id,
    source: optionalString(value.source, "source posting source"),
    label: optionalString(value.label, "source posting label"),
    url: optionalUrl(value.url, "source posting URL"),
    price: optionalNumber(value.price, "source posting price"),
    bedrooms: optionalNumber(value.bedrooms, "source posting bedrooms"),
    bathrooms: optionalNumber(value.bathrooms, "source posting bathrooms"),
  };
}

function parseCommute(value: unknown): Commute {
  if (!isRecord(value) || typeof value.destination !== "string") {
    throw new ApiError("Invalid commute in API response.");
  }
  if (
    value.status !== "available" &&
    value.status !== "unavailable" &&
    value.status !== "unknown"
  ) {
    throw new ApiError("Invalid commute status in API response.");
  }
  return {
    destination: value.destination,
    destinationPlaceId: optionalString(
      value.destinationPlaceId,
      "commute destination place ID",
    ),
    mode: optionalString(value.mode, "commute mode"),
    durationMinutes: optionalNumber(value.durationMinutes, "commute duration"),
    distanceMeters: optionalNumber(value.distanceMeters, "commute distance"),
    status: value.status,
    routingPreference: optionalString(value.routingPreference, "commute routing preference"),
  };
}

function parseCommuteEvaluation(value: unknown): CommuteEvaluation {
  if (!isRecord(value)) throw new ApiError("Invalid commute evaluation in API response.");
  const statuses = [
    "not_requested",
    "requires_input",
    "available",
    "partial",
    "unavailable",
    "unknown",
  ] as const;
  if (!statuses.includes(value.status as (typeof statuses)[number])) {
    throw new ApiError("Invalid commute evaluation status in API response.");
  }
  return {
    status: value.status as CommuteEvaluation["status"],
    evaluatedCount: optionalNumber(value.evaluatedCount, "commute evaluated count") ?? 0,
    availableCount: optionalNumber(value.availableCount, "commute available count") ?? 0,
    unavailableCount: optionalNumber(value.unavailableCount, "commute unavailable count") ?? 0,
    unknownCount: optionalNumber(value.unknownCount, "commute unknown count") ?? 0,
    withinLimitCount: optionalNumber(value.withinLimitCount, "commute within-limit count") ?? 0,
    overLimitCount: optionalNumber(value.overLimitCount, "commute over-limit count") ?? 0,
  };
}

function parseRouteDetail(value: unknown): RouteDetail {
  if (!isRecord(value) || typeof value.listingId !== "string") {
    throw new ApiError("Invalid route detail in API response.");
  }
  return {
    ...parseCommute(value),
    listingId: value.listingId,
    encodedPolyline: optionalString(value.encodedPolyline, "route encoded polyline"),
  };
}

function stringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new ApiError(`Invalid ${field} in API response.`);
  }
  return value;
}

function parseComparisonResult(value: unknown): ComparisonResult {
  if (!isRecord(value) || typeof value.listingId !== "string") {
    throw new ApiError("Invalid comparison result in API response.");
  }
  const statuses = ["pass", "fail", "evidence_only", "unknown"] as const;
  if (!statuses.includes(value.hardConstraintStatus as (typeof statuses)[number])) {
    throw new ApiError("Invalid hard-constraint status in API response.");
  }
  if (!Array.isArray(value.softPreferenceEvidence)) {
    throw new ApiError("Invalid soft-preference evidence in API response.");
  }
  if (value.softPreferenceEvidence.some((item) => !isRecord(item))) {
    throw new ApiError("Invalid soft-preference evidence in API response.");
  }
  if (typeof value.decisionReady !== "boolean") {
    throw new ApiError("Invalid comparison decision-ready value in API response.");
  }
  if (
    value.satisfiesCurrentRequirements !== undefined &&
    value.satisfiesCurrentRequirements !== null &&
    typeof value.satisfiesCurrentRequirements !== "boolean"
  ) {
    throw new ApiError("Invalid comparison requirement status in API response.");
  }
  return {
    listingId: value.listingId,
    hardConstraintStatus: value.hardConstraintStatus as ComparisonResult["hardConstraintStatus"],
    satisfiesCurrentRequirements:
      value.satisfiesCurrentRequirements === null
        ? undefined
        : value.satisfiesCurrentRequirements as boolean | undefined,
    softPreferenceEvidence: value.softPreferenceEvidence as Record<string, unknown>[],
    tradeoffs: stringArray(value.tradeoffs, "comparison tradeoffs"),
    comparisonUnknowns: stringArray(value.comparisonUnknowns, "comparison unknowns"),
    decisionUnknowns: stringArray(value.decisionUnknowns, "decision unknowns"),
    decisionReady: value.decisionReady,
    score: optionalNumber(value.score, "comparison score"),
    rank: optionalNumber(value.rank, "comparison rank"),
  };
}

function parseComparison(value: unknown): Comparison {
  if (!isRecord(value) || value.schemaVersion !== "kbf.canonical-comparison.v1") {
    throw new ApiError("Invalid comparison in API response.");
  }
  if (!Array.isArray(value.results)) {
    throw new ApiError("Invalid comparison results in API response.");
  }
  return {
    schemaVersion: value.schemaVersion,
    listingIds: stringArray(value.listingIds, "comparison listing IDs"),
    results: value.results.map(parseComparisonResult),
  };
}

function parseListing(value: unknown): Listing {
  if (!isRecord(value) || typeof value.id !== "string") {
    throw new ApiError("Invalid listing in API response.");
  }

  return {
    id: value.id,
    title: optionalString(value.title, "listing title"),
    address: optionalString(value.address, "listing address"),
    price: optionalNumber(value.price, "listing price"),
    priceMin: optionalNumber(value.priceMin, "listing minimum price"),
    priceMax: optionalNumber(value.priceMax, "listing maximum price"),
    bedrooms: optionalNumber(value.bedrooms, "listing bedrooms"),
    bathrooms: optionalNumber(value.bathrooms, "listing bathrooms"),
    latitude: optionalNumber(value.latitude, "listing latitude"),
    longitude: optionalNumber(value.longitude, "listing longitude"),
    url: optionalUrl(value.url, "listing URL"),
    score: optionalNumber(value.score, "listing score"),
    reason: optionalString(value.reason, "listing reason"),
    rank: optionalNumber(value.rank, "listing rank"),
    sourcePostings: Array.isArray(value.sourcePostings)
      ? value.sourcePostings.map(parseSourcePosting)
      : undefined,
    commute:
      value.commute === undefined || value.commute === null
        ? undefined
        : parseCommute(value.commute),
  };
}

function parseRecentSearch(value: unknown): RecentSearch {
  if (
    !isRecord(value) ||
    typeof value.conversationId !== "string" ||
    typeof value.createdAt !== "string" ||
    typeof value.updatedAt !== "string" ||
    typeof value.turnCount !== "number" ||
    !Number.isFinite(value.turnCount) ||
    !Array.isArray(value.listings)
  ) {
    throw new ApiError("Invalid recent search in API response.");
  }

  const lastCommuteStatus = optionalString(
    value.lastCommuteStatus,
    "recent search commute status",
  );
  if (
    lastCommuteStatus !== undefined &&
    lastCommuteStatus !== "not_requested" &&
    lastCommuteStatus !== "requires_input" &&
    lastCommuteStatus !== "available" &&
    lastCommuteStatus !== "partial" &&
    lastCommuteStatus !== "unavailable" &&
    lastCommuteStatus !== "unknown"
  ) {
    throw new ApiError("Invalid recent search commute status in API response.");
  }

  return {
    conversationId: value.conversationId,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
    turnCount: value.turnCount,
    listings: value.listings.map(parseListing),
    lastCommuteStatus: lastCommuteStatus as RecentSearch["lastCommuteStatus"],
  };
}

function parseRecentSearchResponse(value: unknown): RecentSearchResponse {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new ApiError("Invalid recent searches response.");
  }
  return { items: value.items.map(parseRecentSearch) };
}

function parseSearchResponse(value: unknown): SearchResponse {
  if (!isRecord(value)) throw new ApiError("Invalid API response.");
  if (typeof value.conversationId !== "string" || typeof value.message !== "string") {
    throw new ApiError("Invalid API response.");
  }
  if (value.mode !== "adk" && value.mode !== "stub") {
    throw new ApiError("Invalid API mode.");
  }
  if (!Array.isArray(value.listings)) {
    throw new ApiError("Invalid listings in API response.");
  }

  return {
    conversationId: value.conversationId,
    message: value.message,
    listings: value.listings.map(parseListing),
    commuteEvaluation:
      value.commuteEvaluation === undefined || value.commuteEvaluation === null
        ? undefined
        : parseCommuteEvaluation(value.commuteEvaluation),
    route:
      value.route === undefined || value.route === null
        ? undefined
        : parseRouteDetail(value.route),
    comparison:
      value.comparison === undefined || value.comparison === null
        ? undefined
        : parseComparison(value.comparison),
    mode: value.mode,
  };
}

function parseShortlistItem(value: unknown): ShortlistItem {
  if (
    !isRecord(value) ||
    typeof value.sourceConversationId !== "string" ||
    typeof value.savedAt !== "string" ||
    typeof value.updatedAt !== "string"
  ) {
    throw new ApiError("Invalid shortlist item in API response.");
  }
  return {
    listing: parseListing(value.listing),
    sourceConversationId: value.sourceConversationId,
    savedAt: value.savedAt,
    updatedAt: value.updatedAt,
  };
}

function parseShortlistResponse(value: unknown): ShortlistResponse {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new ApiError("Invalid shortlist response.");
  }
  return { items: value.items.map(parseShortlistItem) };
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (isRecord(payload) && typeof payload.detail === "string") return payload.detail;
  } catch {
    // Fall through to the status-based message.
  }
  return `Backend request failed with HTTP ${response.status}.`;
}

async function authenticatedHeaders(): Promise<Record<string, string>> {
  let idToken: string | undefined;
  try {
    idToken = await getFirebaseIdToken();
  } catch {
    throw new ApiError(
      "Couldn’t sign you in. Check the Firebase settings, then refresh the page.",
    );
  }

  const headers: Record<string, string> = {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
  if (idToken) headers.Authorization = `Bearer ${idToken}`;
  return headers;
}

export async function sendChat(
  request: SearchRequest,
  options: { signal?: AbortSignal } = {},
): Promise<SearchResponse> {
  const headers = await authenticatedHeaders();

  let response: Response;
  try {
    response = await fetch(`${backendUrl}/api/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify(request),
      cache: "no-store",
      signal: options.signal,
    });
  } catch (caught) {
    if (caught instanceof Error && caught.name === "AbortError") throw caught;
    throw new ApiError(
      "Can’t reach the rental service. Check that the backend is running, then try again.",
    );
  }

  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("Backend returned invalid JSON.");
  }
  return parseSearchResponse(payload);
}

export async function getSelectedRoute(
  request: SelectedRouteRequest,
  options: { signal?: AbortSignal } = {},
): Promise<RouteDetail> {
  const headers = await authenticatedHeaders();
  let response: Response;
  try {
    response = await fetch(`${backendUrl}/api/route`, {
      method: "POST",
      headers,
      body: JSON.stringify(request),
      cache: "no-store",
      signal: options.signal,
    });
  } catch (caught) {
    if (caught instanceof Error && caught.name === "AbortError") throw caught;
    throw new ApiError("Can’t reach the route service. Check that the backend is running.");
  }

  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("Backend returned invalid route JSON.");
  }
  return parseRouteDetail(payload);
}

export async function getShortlist(
  options: { signal?: AbortSignal } = {},
): Promise<ShortlistResponse> {
  const headers = await authenticatedHeaders();
  let response: Response;
  try {
    response = await fetch(`${backendUrl}/api/shortlist`, {
      method: "GET",
      headers,
      cache: "no-store",
      signal: options.signal,
    });
  } catch (caught) {
    if (caught instanceof Error && caught.name === "AbortError") throw caught;
    throw new ApiError("Can’t reach shortlist storage. Check that the backend is running.");
  }
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  return parseShortlistResponse(await response.json());
}

export async function getRecentSearches(
  options: { signal?: AbortSignal } = {},
): Promise<RecentSearchResponse> {
  const headers = await authenticatedHeaders();
  let response: Response;
  try {
    response = await fetch(`${backendUrl}/api/conversations?limit=20`, {
      method: "GET",
      headers,
      cache: "no-store",
      signal: options.signal,
    });
  } catch (caught) {
    if (caught instanceof Error && caught.name === "AbortError") throw caught;
    throw new ApiError("Can’t reach recent searches. Check that the backend is running.");
  }
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("Backend returned invalid recent searches JSON.");
  }
  return parseRecentSearchResponse(payload);
}

export async function saveShortlistItem(
  listingId: string,
  conversationId: string,
): Promise<ShortlistItem> {
  const headers = await authenticatedHeaders();
  let response: Response;
  try {
    response = await fetch(`${backendUrl}/api/shortlist`, {
      method: "POST",
      headers,
      body: JSON.stringify({ listingId, conversationId }),
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Can’t reach shortlist storage. Check that the backend is running.");
  }
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  return parseShortlistItem(await response.json());
}

export async function removeShortlistItem(listingId: string): Promise<void> {
  const headers = await authenticatedHeaders();
  let response: Response;
  try {
    response = await fetch(
      `${backendUrl}/api/shortlist/${encodeURIComponent(listingId)}`,
      {
        method: "DELETE",
        headers,
        cache: "no-store",
      },
    );
  } catch {
    throw new ApiError("Can’t reach shortlist storage. Check that the backend is running.");
  }
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
}

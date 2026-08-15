import type { Listing, SearchRequest, SearchResponse, SourcePosting } from "@/types/search";

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

function parseListing(value: unknown): Listing {
  if (!isRecord(value) || typeof value.id !== "string") {
    throw new ApiError("Invalid listing in API response.");
  }

  return {
    id: value.id,
    title: optionalString(value.title, "listing title"),
    address: optionalString(value.address, "listing address"),
    price: optionalNumber(value.price, "listing price"),
    bedrooms: optionalNumber(value.bedrooms, "listing bedrooms"),
    bathrooms: optionalNumber(value.bathrooms, "listing bathrooms"),
    url: optionalUrl(value.url, "listing URL"),
    score: optionalNumber(value.score, "listing score"),
    reason: optionalString(value.reason, "listing reason"),
    rank: optionalNumber(value.rank, "listing rank"),
    sourcePostings: Array.isArray(value.sourcePostings)
      ? value.sourcePostings.map(parseSourcePosting)
      : undefined,
  };
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
    mode: value.mode,
  };
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

export async function sendChat(
  request: SearchRequest,
  options: { signal?: AbortSignal } = {},
): Promise<SearchResponse> {
  let response: Response;
  try {
    response = await fetch(`${backendUrl}/api/chat`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
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

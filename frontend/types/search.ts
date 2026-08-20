export interface SourcePosting {
  id: string;
  source?: string;
  label?: string;
  url?: string;
  price?: number;
  bedrooms?: number;
  bathrooms?: number;
}

export interface Commute {
  destination: string;
  destinationPlaceId?: string;
  mode?: string;
  durationMinutes?: number;
  distanceMeters?: number;
  status: "available" | "unavailable" | "unknown";
  routingPreference?: string;
}

export interface CommuteEvaluation {
  status:
    | "not_requested"
    | "requires_input"
    | "available"
    | "partial"
    | "unavailable"
    | "unknown";
  evaluatedCount: number;
  availableCount: number;
  unavailableCount: number;
  unknownCount: number;
  withinLimitCount: number;
  overLimitCount: number;
}

export interface RouteDetail extends Commute {
  listingId: string;
  encodedPolyline?: string;
}

export interface SelectedRouteRequest {
  listingId: string;
  conversationId: string;
  destination?: string;
  mode?: string;
}

export interface CanonicalListing {
  schemaVersion: "kbf.canonical-listing.v1";
  identity: {
    id: string;
    sourceListingId: string | null;
    propertyName: string | null;
  };
  location: {
    address: string | null;
    city: string | null;
    state: string | null;
    zipCode: string | null;
    countryCode: string | null;
    latitude: number | null;
    longitude: number | null;
  };
  pricing: {
    rent: number | null;
    rentMin: number | null;
    rentMax: number | null;
  };
  property: {
    bedrooms: number | null;
    bedroomsMin: number | null;
    bedroomsMax: number | null;
    bathrooms: number | null;
    bathroomsMinEvidence: number | null;
    propertyType: string | null;
    [key: string]: unknown;
  };
  availability: Record<string, unknown>;
  policies: {
    petsAllowed?: boolean | null;
    petPolicy?: string | null;
    parkingAvailable?: boolean | null;
    parkingPolicy?: string | null;
    [key: string]: unknown;
  };
  features: Record<string, unknown>;
  media: Record<string, unknown>;
  contact: Record<string, unknown>;
  source: Record<string, unknown>;
  evidence: {
    detailVerified?: boolean;
    queryBackedFields?: string[];
    criticalQueryBackedFields?: string[];
    [key: string]: unknown;
  };
  completeness: {
    unknownFields?: string[];
    criticalUnknownFields?: string[];
    decisionReady?: boolean;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface CanonicalComparisonResult {
  listingId: string;
  hardConstraintStatus: "pass" | "fail" | "evidence_only" | "unknown";
  satisfiesCurrentRequirements: boolean | null;
  softPreferenceEvidence: Record<string, unknown>[];
  tradeoffs: (string | Record<string, unknown>)[];
  comparisonUnknowns: string[];
  decisionUnknowns: string[];
  decisionReady: boolean;
  score: number | null;
  rank: number | null;
}

export interface CanonicalComparison {
  schemaVersion: "kbf.canonical-comparison.v1";
  listingIds: string[];
  results: CanonicalComparisonResult[];
}

export interface Listing {
  id: string;
  title?: string;
  address?: string;
  price?: number;
  priceMin?: number;
  priceMax?: number;
  bedrooms?: number;
  bedroomsMin?: number;
  bedroomsMax?: number;
  bathrooms?: number;
  bathroomsMinEvidence?: number;
  latitude?: number;
  longitude?: number;
  url?: string;
  score?: number;
  reason?: string;
  rank?: number;
  sourcePostings?: SourcePosting[];
  commute?: Commute;
  canonicalListing?: CanonicalListing;
}

export interface SearchRequest {
  message: string;
  conversationId?: string;
}

export type AgentMode = "adk" | "stub";

export interface SearchResponse {
  conversationId: string;
  message: string;
  listings: Listing[];
  commuteEvaluation?: CommuteEvaluation;
  route?: RouteDetail;
  comparison?: CanonicalComparison;
  searchPerformed: boolean;
  mode: AgentMode;
}

export interface ShortlistItem {
  listing: Listing;
  sourceConversationId: string;
  note?: string;
  savedAt: string;
  updatedAt: string;
}

export interface ShortlistResponse {
  items: ShortlistItem[];
}

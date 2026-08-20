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

export type HardConstraintStatus = "pass" | "fail" | "evidence_only" | "unknown";

export interface ComparisonResult {
  listingId: string;
  hardConstraintStatus: HardConstraintStatus;
  satisfiesCurrentRequirements?: boolean;
  softPreferenceEvidence: Record<string, unknown>[];
  tradeoffs: string[];
  comparisonUnknowns: string[];
  decisionUnknowns: string[];
  decisionReady: boolean;
  score?: number;
  rank?: number;
}

export interface Comparison {
  schemaVersion: "kbf.canonical-comparison.v1";
  listingIds: string[];
  results: ComparisonResult[];
}

export interface SelectedRouteRequest {
  listingId: string;
  conversationId: string;
  destination?: string;
  mode?: string;
}

export interface Listing {
  id: string;
  title?: string;
  address?: string;
  price?: number;
  bedrooms?: number;
  bathrooms?: number;
  latitude?: number;
  longitude?: number;
  url?: string;
  score?: number;
  reason?: string;
  rank?: number;
  sourcePostings?: SourcePosting[];
  commute?: Commute;
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
  comparison?: Comparison;
  mode: AgentMode;
}

export interface ShortlistItem {
  listing: Listing;
  sourceConversationId: string;
  savedAt: string;
  updatedAt: string;
}

export interface ShortlistResponse {
  items: ShortlistItem[];
}

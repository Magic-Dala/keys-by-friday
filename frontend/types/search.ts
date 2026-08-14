export interface SourcePosting {
  id: string;
  source?: string;
  label?: string;
  url?: string;
  price?: number;
  bedrooms?: number;
  bathrooms?: number;
}

export interface Listing {
  id: string;
  title?: string;
  address?: string;
  price?: number;
  bedrooms?: number;
  bathrooms?: number;
  url?: string;
  score?: number;
  reason?: string;
  rank?: number;
  sourcePostings?: SourcePosting[];
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
  mode: AgentMode;
}

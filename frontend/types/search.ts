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

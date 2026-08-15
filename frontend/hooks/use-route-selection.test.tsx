import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRouteSelection } from "@/hooks/use-route-selection";
import { sendChat } from "@/lib/api";
import type { Listing, SearchResponse } from "@/types/search";

vi.mock("@/lib/api", () => ({ sendChat: vi.fn() }));

const home = (id: string): Listing => ({
  id,
  title: `Home ${id}`,
  latitude: 37.4,
  longitude: -122.1,
  commute: { destination: "Google Mountain View", mode: "DRIVE", status: "available", durationMinutes: 18 },
});

const response = (listingId: string): SearchResponse => ({
  conversationId: "conversation-1",
  message: "Route ready",
  listings: [],
  route: { listingId, destination: "Google Mountain View", mode: "DRIVE", status: "available", encodedPolyline: "abc" },
  mode: "adk",
});

beforeEach(() => vi.mocked(sendChat).mockReset());

describe("useRouteSelection", () => {
  it("keeps route-only listing data outside the hook and applies the selected route", async () => {
    vi.mocked(sendChat).mockResolvedValue(response("one"));
    const { result } = renderHook(() => useRouteSelection("conversation-1"));
    await act(() => result.current.selectListing(home("one")));
    expect(sendChat).toHaveBeenCalledWith(expect.objectContaining({ conversationId: "conversation-1" }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(result.current.state).toMatchObject({ selectedListingId: "one", status: "available", route: { listingId: "one" } });
  });

  it("aborts and ignores an older request when selection changes", async () => {
    let resolveFirst!: (value: SearchResponse) => void;
    vi.mocked(sendChat)
      .mockImplementationOnce((_request, options) => new Promise((resolve, reject) => {
        resolveFirst = resolve;
        options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
      }))
      .mockResolvedValueOnce(response("two"));
    const { result } = renderHook(() => useRouteSelection("conversation-1"));
    act(() => { void result.current.selectListing(home("one")); });
    await act(() => result.current.selectListing(home("two")));
    resolveFirst(response("one"));
    expect(result.current.state).toMatchObject({ selectedListingId: "two", route: { listingId: "two" } });
  });

  it("exposes a retryable error without restoring old geometry", async () => {
    vi.mocked(sendChat).mockRejectedValueOnce(new Error("Route service unavailable")).mockResolvedValueOnce(response("one"));
    const { result } = renderHook(() => useRouteSelection("conversation-1"));
    await act(() => result.current.selectListing(home("one")));
    expect(result.current.state).toMatchObject({ selectedListingId: "one", route: undefined, status: "error" });
    await act(() => result.current.retry());
    expect(result.current.state.status).toBe("available");
  });
});

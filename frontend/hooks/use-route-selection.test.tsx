import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRouteSelection } from "@/hooks/use-route-selection";
import { getSelectedRoute, sendChat } from "@/lib/api";
import type { Listing, RouteDetail } from "@/types/search";

vi.mock("@/lib/api", () => ({ getSelectedRoute: vi.fn(), sendChat: vi.fn() }));

const home = (id: string): Listing => ({
  id,
  title: `Home ${id}`,
  latitude: 37.4,
  longitude: -122.1,
  commute: { destination: "Google Mountain View", mode: "DRIVE", status: "available", durationMinutes: 18 },
});

const route = (listingId: string): RouteDetail => ({
  listingId,
  destination: "Google Mountain View",
  mode: "DRIVE",
  status: "available",
  encodedPolyline: "abc",
});

beforeEach(() => {
  vi.mocked(getSelectedRoute).mockReset();
  vi.mocked(sendChat).mockReset();
});

describe("useRouteSelection", () => {
  it("loads a selected listing through the route API without sending chat", async () => {
    vi.mocked(getSelectedRoute).mockResolvedValue(route("one"));
    const { result } = renderHook(() => useRouteSelection("conversation-1"));
    await act(() => result.current.selectListing(home("one")));
    expect(getSelectedRoute).toHaveBeenCalledWith(
      { listingId: "one", conversationId: "conversation-1", destination: "Google Mountain View", mode: "DRIVE" },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(sendChat).not.toHaveBeenCalled();
    expect(result.current.state).toMatchObject({ selectedListingId: "one", status: "available", route: { listingId: "one" } });
  });

  it("aborts and ignores an older request when selection changes", async () => {
    let resolveFirst!: (value: RouteDetail) => void;
    let firstSignal: AbortSignal | undefined;
    vi.mocked(getSelectedRoute)
      .mockImplementationOnce((_request, options) => new Promise<RouteDetail>((resolve) => {
        resolveFirst = resolve;
        firstSignal = options?.signal;
      }))
      .mockResolvedValueOnce(route("two"));
    const { result } = renderHook(() => useRouteSelection("conversation-1"));
    act(() => { void result.current.selectListing(home("one")); });
    await act(() => result.current.selectListing(home("two")));
    expect(firstSignal?.aborted).toBe(true);
    await act(async () => {
      resolveFirst(route("one"));
      await Promise.resolve();
    });
    expect(result.current.state).toMatchObject({ selectedListingId: "two", route: { listingId: "two" } });
  });

  it("exposes a retryable error without restoring old geometry", async () => {
    vi.mocked(getSelectedRoute).mockRejectedValueOnce(new Error("Route service unavailable")).mockResolvedValueOnce(route("one"));
    const { result } = renderHook(() => useRouteSelection("conversation-1"));
    await act(() => result.current.selectListing(home("one")));
    expect(result.current.state).toMatchObject({ selectedListingId: "one", route: undefined, status: "error" });
    await act(() => result.current.retry());
    expect(result.current.state.status).toBe("available");
  });
});

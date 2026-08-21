import { afterEach, beforeEach, expect, it, vi } from "vitest";

const { getFirebaseIdTokenMock } = vi.hoisted(() => ({
  getFirebaseIdTokenMock: vi.fn(),
}));

vi.mock("@/lib/firebase-auth", () => ({
  getFirebaseIdToken: getFirebaseIdTokenMock,
}));

import { getRecentSearches } from "@/lib/api";

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  getFirebaseIdTokenMock.mockReset().mockResolvedValue("firebase-token");
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("fetches authenticated recent searches in backend order and retains supported price evidence", async () => {
  vi.mocked(fetch).mockResolvedValue(
    response({
      items: [
        {
          conversationId: "newest",
          createdAt: "2026-08-20T18:00:00Z",
          updatedAt: "2026-08-20T18:15:00Z",
          turnCount: 4,
          listings: [
            {
              id: "listing-newest",
              priceMin: 3450,
              priceMax: 3950,
            },
          ],
          lastCommuteStatus: "available",
        },
        {
          conversationId: "older",
          createdAt: "2026-08-19T18:00:00Z",
          updatedAt: "2026-08-19T18:15:00Z",
          turnCount: 1,
          listings: [],
          lastCommuteStatus: "unknown",
        },
      ],
    }),
  );

  const result = await getRecentSearches();

  expect(result.items.map((item) => item.conversationId)).toEqual(["newest", "older"]);
  expect(result.items[0].listings[0]).toMatchObject({
    id: "listing-newest",
    priceMin: 3450,
    priceMax: 3950,
  });
  expect(fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/conversations?limit=20",
    expect.objectContaining({
      method: "GET",
      cache: "no-store",
      headers: expect.objectContaining({
        Accept: "application/json",
        Authorization: "Bearer firebase-token",
      }),
    }),
  );
  expect(vi.mocked(fetch).mock.calls[0][1]).not.toHaveProperty("body");
  expect(String(vi.mocked(fetch).mock.calls[0][0])).not.toContain("uid");
  expect(getFirebaseIdTokenMock).toHaveBeenCalledTimes(1);
});

it("rejects non-camelCase recent-search fields at the API boundary", async () => {
  vi.mocked(fetch).mockResolvedValue(
    response({
      items: [
        {
          conversation_id: "not-supported",
          created_at: "2026-08-20T18:00:00Z",
          updated_at: "2026-08-20T18:15:00Z",
          turn_count: 1,
          listings: [],
        },
      ],
    }),
  );

  await expect(getRecentSearches()).rejects.toThrow("Invalid recent search in API response.");
});

it("parses the full commute evaluation status contract", async () => {
  vi.mocked(fetch).mockResolvedValue(
    response({
      items: [
        {
          conversationId: "not-requested",
          createdAt: "2026-08-20T18:00:00Z",
          updatedAt: "2026-08-20T18:15:00Z",
          turnCount: 1,
          listings: [],
          lastCommuteStatus: "not_requested",
        },
        {
          conversationId: "partial",
          createdAt: "2026-08-19T18:00:00Z",
          updatedAt: "2026-08-19T18:15:00Z",
          turnCount: 2,
          listings: [],
          lastCommuteStatus: "partial",
        },
        {
          conversationId: "requires-input",
          createdAt: "2026-08-18T18:00:00Z",
          updatedAt: "2026-08-18T18:15:00Z",
          turnCount: 3,
          listings: [],
          lastCommuteStatus: "requires_input",
        },
      ],
    }),
  );

  const result = await getRecentSearches();

  expect(result.items.map((item) => item.lastCommuteStatus)).toEqual([
    "not_requested",
    "partial",
    "requires_input",
  ]);
});

it("passes abort errors through to the caller", async () => {
  const abortError = new Error("The request was aborted");
  abortError.name = "AbortError";
  vi.mocked(fetch).mockRejectedValue(abortError);

  await expect(getRecentSearches({ signal: new AbortController().signal })).rejects.toBe(
    abortError,
  );
});

it("times out a never-resolving recent-search request and aborts it", async () => {
  vi.useFakeTimers();
  try {
    let requestSignal: AbortSignal | null | undefined;
    vi.mocked(fetch).mockImplementation((_input, init) => {
      requestSignal = init?.signal;
      return new Promise<Response>(() => undefined);
    });

    const request = getRecentSearches();
    const requestFailure = expect(request).rejects.toMatchObject({
      name: "ApiError",
      message: "Recent searches request timed out. Try again.",
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(fetch).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(10_000);

    await requestFailure;
    expect(requestSignal?.aborted).toBe(true);
  } finally {
    vi.useRealTimers();
  }
});

it("normalizes recent-search HTTP failures using ApiError", async () => {
  vi.mocked(fetch).mockResolvedValue(response({ detail: "Recent searches are unavailable." }, 503));

  await expect(getRecentSearches()).rejects.toMatchObject({
    message: "Recent searches are unavailable.",
    status: 503,
    name: "ApiError",
  });
});

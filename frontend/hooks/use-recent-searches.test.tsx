import { act, render, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const { getRecentSearchesMock } = vi.hoisted(() => ({
  getRecentSearchesMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getRecentSearches: getRecentSearchesMock,
}));

import { useRecentSearches } from "@/hooks/use-recent-searches";
import type { RecentSearchResponse } from "@/types/search";

type RecentSearchesHookResult = ReturnType<typeof useRecentSearches>;

function account(uid: string, isAnonymous = false) {
  return { uid, isAnonymous } as never;
}

function recentSearch(conversationId: string): RecentSearchResponse {
  return {
    items: [
      {
        conversationId,
        createdAt: "2026-08-20T18:00:00Z",
        updatedAt: "2026-08-20T18:15:00Z",
        turnCount: 2,
        listings: [],
        lastCommuteStatus: "unknown",
      },
    ],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function SearchHookProbe({
  uid,
  onRender,
}: {
  uid: string;
  onRender: (result: RecentSearchesHookResult) => void;
}) {
  const result = useRecentSearches(account(uid));
  onRender(result);
  return null;
}

beforeEach(() => {
  getRecentSearchesMock.mockReset();
});

it("does not fetch durable history for an anonymous user", () => {
  const { result } = renderHook(() => useRecentSearches(account("anonymous", true)));

  expect(result.current.items).toEqual([]);
  expect(result.current.loading).toBe(false);
  expect(getRecentSearchesMock).not.toHaveBeenCalled();
});

it("fetches recent searches for the supplied non-anonymous auth user", async () => {
  getRecentSearchesMock.mockResolvedValue(recentSearch("account-search"));

  const { result } = renderHook(() => useRecentSearches(account("account-1")));

  await waitFor(() => expect(result.current.items[0]?.conversationId).toBe("account-search"));
  expect(getRecentSearchesMock).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) });
});

it("clears and aborts the previous account before ignoring its late response", async () => {
  const first = deferred<RecentSearchResponse>();
  const second = deferred<RecentSearchResponse>();
  getRecentSearchesMock
    .mockImplementationOnce(({ signal }: { signal?: AbortSignal }) => {
      expect(signal?.aborted).toBe(false);
      return first.promise;
    })
    .mockImplementationOnce(({ signal }: { signal?: AbortSignal }) => {
      expect(signal?.aborted).toBe(false);
      return second.promise;
    });

  const { result, rerender } = renderHook(
    ({ uid }) => useRecentSearches(account(uid)),
    { initialProps: { uid: "account-1" } },
  );

  await waitFor(() => expect(getRecentSearchesMock).toHaveBeenCalledTimes(1));
  const firstSignal = getRecentSearchesMock.mock.calls[0][0].signal as AbortSignal;

  rerender({ uid: "account-2" });

  await waitFor(() => expect(getRecentSearchesMock).toHaveBeenCalledTimes(2));
  expect(firstSignal.aborted).toBe(true);
  expect(result.current.items).toEqual([]);

  await act(async () => {
    first.resolve(recentSearch("old-account-search"));
  });
  expect(result.current.items).toEqual([]);

  await act(async () => {
    second.resolve(recentSearch("new-account-search"));
  });
  await waitFor(() => expect(result.current.items[0]?.conversationId).toBe("new-account-search"));
});

it("does not render the previous account's items during a direct UID switch", async () => {
  const nextAccount = deferred<RecentSearchResponse>();
  getRecentSearchesMock
    .mockResolvedValueOnce(recentSearch("old-account-search"))
    .mockImplementationOnce(() => nextAccount.promise);
  const renders: RecentSearchesHookResult[] = [];
  const view = render(
    <SearchHookProbe uid="account-1" onRender={(result) => renders.push(result)} />,
  );

  await waitFor(() =>
    expect(renders.some((result) => result.items[0]?.conversationId === "old-account-search")).toBe(true),
  );

  const switchRenderIndex = renders.length;
  view.rerender(<SearchHookProbe uid="account-2" onRender={(result) => renders.push(result)} />);

  expect(renders[switchRenderIndex]?.items).toEqual([]);
  expect(renders[switchRenderIndex]?.loading).toBe(true);
});

it("clears account history when the current user becomes anonymous", async () => {
  getRecentSearchesMock.mockResolvedValue(recentSearch("account-search"));

  const { result, rerender } = renderHook(
    ({ isAnonymous }) => useRecentSearches(account("account-1", isAnonymous)),
    { initialProps: { isAnonymous: false } },
  );

  await waitFor(() => expect(result.current.items[0]?.conversationId).toBe("account-search"));
  const requestSignal = getRecentSearchesMock.mock.calls[0][0].signal as AbortSignal;

  rerender({ isAnonymous: true });

  await waitFor(() => expect(result.current.items).toEqual([]));
  expect(requestSignal.aborted).toBe(true);
});

it("refreshes the same account without exposing a failed refresh as account data", async () => {
  getRecentSearchesMock
    .mockResolvedValueOnce(recentSearch("first-search"))
    .mockRejectedValueOnce(new Error("Recent searches are unavailable."));

  const { result } = renderHook(() => useRecentSearches(account("account-1")));
  await waitFor(() => expect(result.current.items[0]?.conversationId).toBe("first-search"));

  act(() => result.current.refresh());

  await waitFor(() => expect(result.current.error).toBe("Recent searches are unavailable."));
  expect(result.current.items[0]?.conversationId).toBe("first-search");
});

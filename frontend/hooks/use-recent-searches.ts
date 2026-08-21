import { useCallback, useEffect, useRef, useState } from "react";
import type { User } from "firebase/auth";

import { getRecentSearches } from "@/lib/api";
import type { RecentSearch } from "@/types/search";

interface RecentSearchesState {
  items: RecentSearch[];
  loading: boolean;
  error?: string;
}

const emptyState: RecentSearchesState = {
  items: [],
  loading: false,
};

export function useRecentSearches(authUser: User | null | undefined) {
  const accountKey = authUser && !authUser.isAnonymous ? authUser.uid : undefined;
  const [state, setState] = useState<RecentSearchesState>(emptyState);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const activeAccountKeyRef = useRef<string | undefined>(undefined);
  const identityGenerationRef = useRef(0);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const identityChanged = activeAccountKeyRef.current !== accountKey;
    if (identityChanged) {
      requestRef.current?.abort();
      requestRef.current = null;
      identityGenerationRef.current += 1;
      activeAccountKeyRef.current = accountKey;
      setState({ items: [], loading: Boolean(accountKey) });
    }

    if (!accountKey) return;

    const identityGeneration = identityGenerationRef.current;
    const controller = new AbortController();
    requestRef.current?.abort();
    requestRef.current = controller;
    setState((current) => ({ ...current, loading: true, error: undefined }));

    getRecentSearches({ signal: controller.signal })
      .then((response) => {
        if (
          requestRef.current !== controller ||
          activeAccountKeyRef.current !== accountKey ||
          identityGenerationRef.current !== identityGeneration
        ) return;
        setState({ items: response.items, loading: false });
      })
      .catch((caught) => {
        if (
          caught instanceof Error && caught.name === "AbortError" ||
          requestRef.current !== controller ||
          activeAccountKeyRef.current !== accountKey ||
          identityGenerationRef.current !== identityGeneration
        ) return;
        setState((current) => ({
          ...current,
          loading: false,
          error: caught instanceof Error
            ? caught.message
            : "Recent searches could not be loaded yet.",
        }));
      });

    return () => {
      controller.abort();
      if (requestRef.current === controller) requestRef.current = null;
    };
  }, [accountKey, refreshNonce]);

  const refresh = useCallback(() => {
    if (!accountKey) return;
    setRefreshNonce((current) => current + 1);
  }, [accountKey]);

  return { ...state, refresh };
}

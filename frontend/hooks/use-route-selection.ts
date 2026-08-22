"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import { getSelectedRoute } from "@/lib/api";
import {
  initialRouteSelectionState,
  routeSelectionReducer,
  type RouteSelectionState,
} from "@/lib/map-model";
import type { Listing } from "@/types/search";

export function useRouteSelection(conversationId?: string): {
  state: RouteSelectionState;
  selectListing(listing: Listing): Promise<void>;
  retry(): Promise<void>;
  reset(): void;
} {
  const [state, dispatch] = useReducer(routeSelectionReducer, initialRouteSelectionState);
  const controllerRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  const selectedListingRef = useRef<Listing | null>(null);

  const requestRoute = useCallback(async (listing: Listing): Promise<void> => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestId = ++requestIdRef.current;
    selectedListingRef.current = listing;
    dispatch({ type: "select", listingId: listing.id, requestId });

    try {
      const route = await getSelectedRoute(
        {
          listingId: listing.id,
          conversationId: conversationId ?? "",
          destination: listing.commute?.destination,
          mode: listing.commute?.mode,
        },
        { signal: controller.signal },
      );
      dispatch({ type: "resolved", listingId: listing.id, requestId, route });
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      dispatch({
        type: "rejected",
        listingId: listing.id,
        requestId,
        error: caught instanceof Error ? caught.message : "The commute route could not be loaded.",
      });
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  }, [conversationId]);

  const selectListing = useCallback((listing: Listing) => requestRoute(listing), [requestRoute]);

  const retry = useCallback(async (): Promise<void> => {
    if (selectedListingRef.current) await requestRoute(selectedListingRef.current);
  }, [requestRoute]);

  const reset = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    selectedListingRef.current = null;
    requestIdRef.current += 1;
    dispatch({ type: "reset" });
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  return { state, selectListing, retry, reset };
}

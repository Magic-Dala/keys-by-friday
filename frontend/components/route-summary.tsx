"use client";

import type { ReactNode } from "react";

import { commutePresentation, type RouteSelectionState } from "@/lib/map-model";
import type { CommuteEvaluation, Listing } from "@/types/search";

interface RouteSummaryProps {
  listing?: Listing;
  commuteEvaluation?: CommuteEvaluation;
  state: RouteSelectionState;
  onRetry: () => void;
}

function listingLabel(listing?: Listing): string {
  return listing?.title ?? listing?.address ?? "this home";
}

export function RouteSummary({ listing, commuteEvaluation, state, onRetry }: RouteSummaryProps) {
  const label = listingLabel(listing);
  let heading = listing ? `Route for ${label}` : "Compare every commute";
  let body: ReactNode;

  switch (state.status) {
    case "loading":
      body = `Loading the route for ${label}.`;
      break;
    case "available": {
      const presentation = commutePresentation(state.route);
      body = (
        <p>
          <strong>{presentation.label}</strong>
          {presentation.detail ? ` · ${presentation.detail}` : ""}
          {state.route?.destination ? ` to ${state.route.destination}` : ""}
        </p>
      );
      break;
    }
    case "unavailable":
      body = state.route?.destination
        ? `No route is available from ${label} to ${state.route.destination}.`
        : `No route is available for ${label}.`;
      break;
    case "unknown":
      body = `The commute route for ${label} is unknown.`;
      break;
    case "error":
      body = state.error ?? `The route for ${label} could not be loaded.`;
      break;
    case "idle":
      heading = "Compare every commute";
      body = commuteEvaluation && commuteEvaluation.evaluatedCount > 0
        ? `${commuteEvaluation.withinLimitCount} of ${commuteEvaluation.evaluatedCount} homes within your commute limit`
        : "Select a home to see its commute route.";
      break;
  }

  return (
    <section className={`routeSummary routeSummary-${state.status}`} aria-labelledby="route-summary-title">
      <span className="sectionEyebrow">Commute intelligence</span>
      <h2 id="route-summary-title">{heading}</h2>
      <div role="status" aria-live="polite">{body}</div>
      {state.status === "error" ? <button type="button" onClick={onRetry}>Retry route</button> : null}
    </section>
  );
}

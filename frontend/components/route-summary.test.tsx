import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { RouteSummary } from "@/components/route-summary";
import { initialRouteSelectionState } from "@/lib/map-model";

it("shows evaluation before a home is selected", () => {
  render(<RouteSummary state={initialRouteSelectionState} commuteEvaluation={{ status: "partial", evaluatedCount: 3, availableCount: 2, unavailableCount: 1, unknownCount: 0, withinLimitCount: 1, overLimitCount: 1 }} onRetry={vi.fn()} />);
  expect(screen.getByText("1 of 3 homes within your commute limit")).toBeVisible();
});

it("announces route loading and renders available facts", () => {
  const { rerender } = render(<RouteSummary listing={{ id: "one", title: "Heatherstone" }} state={{ selectedListingId: "one", status: "loading", requestId: 1 }} onRetry={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading the route for Heatherstone");
  rerender(<RouteSummary listing={{ id: "one", title: "Heatherstone" }} state={{ selectedListingId: "one", status: "available", requestId: 1, route: { listingId: "one", destination: "Google Mountain View", mode: "DRIVE", durationMinutes: 18, distanceMeters: 12400, status: "available", routingPreference: "TRAFFIC_AWARE" } }} onRetry={vi.fn()} />);
  expect(screen.getByText("18 min drive")).toBeVisible();
  expect(screen.getByText(/Google Mountain View/)).toBeVisible();
  expect(screen.getByText("Traffic-aware routing")).toBeVisible();
});

it("offers retry without hiding the selected home", async () => {
  const retry = vi.fn();
  render(<RouteSummary listing={{ id: "one", title: "Heatherstone" }} state={{ selectedListingId: "one", status: "error", requestId: 1, error: "Route service unavailable" }} onRetry={retry} />);
  await userEvent.click(screen.getByRole("button", { name: "Retry route" }));
  expect(retry).toHaveBeenCalledOnce();
});

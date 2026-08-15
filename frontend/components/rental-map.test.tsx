import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { RentalMap } from "@/components/rental-map";
import { initialRouteSelectionState } from "@/lib/map-model";

const listings = [
  { id: "one", title: "Heatherstone", address: "877 Heatherstone Way", latitude: 37.4, longitude: -122.1, commute: { destination: "Google", mode: "DRIVE", durationMinutes: 18, status: "available" as const } },
  { id: "two", title: "No coordinates", commute: { destination: "Google", status: "unknown" as const } },
];

it("shows an honest configuration fallback and real commute facts without a public key", () => {
  render(<RentalMap listings={listings} routeState={initialRouteSelectionState} onSelectListing={vi.fn()} apiKey="" mapId="DEMO_MAP_ID" />);
  expect(screen.getByText("Map needs a browser key")).toBeVisible();
  expect(screen.getByText("Heatherstone")).toBeVisible();
  expect(screen.getByText("18 min drive")).toBeVisible();
});

it("lets fallback rows select the same listing route", async () => {
  const select = vi.fn();
  render(<RentalMap listings={listings} routeState={initialRouteSelectionState} onSelectListing={select} apiKey="" mapId="DEMO_MAP_ID" />);
  await userEvent.click(screen.getByRole("button", { name: /Select Heatherstone/ }));
  expect(select).toHaveBeenCalledWith(listings[0]);
});

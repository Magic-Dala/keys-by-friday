import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { ListingCard } from "@/components/listing-card";

const listing = { id: "one", title: "Heatherstone", latitude: 37.4, longitude: -122.1, commute: { destination: "Google", mode: "DRIVE", durationMinutes: 18, status: "available" as const } };

it("selects the home from the card target and shows commute facts", async () => {
  const onMapSelect = vi.fn();
  render(<ListingCard listing={listing} rank={1} saved={false} comparisonSelected={false} mapSelected={false} onSave={vi.fn()} onSelect={vi.fn()} onMapSelect={onMapSelect} />);
  expect(screen.getByText("18 min drive")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Select Heatherstone on the map and load its route" }));
  expect(onMapSelect).toHaveBeenCalledWith(listing);
});

it("keeps save and compare independent from route selection", async () => {
  const onMapSelect = vi.fn();
  const onSave = vi.fn();
  const onSelect = vi.fn();
  render(<ListingCard listing={listing} rank={1} saved={false} comparisonSelected={false} mapSelected={false} onSave={onSave} onSelect={onSelect} onMapSelect={onMapSelect} />);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await userEvent.click(screen.getByRole("button", { name: "Compare" }));
  expect(onSave).toHaveBeenCalledOnce();
  expect(onSelect).toHaveBeenCalledOnce();
  expect(onMapSelect).not.toHaveBeenCalled();
});

it("exposes selected map state without relying on color", () => {
  render(<ListingCard listing={listing} rank={1} saved={false} comparisonSelected={false} mapSelected onSave={vi.fn()} onSelect={vi.fn()} onMapSelect={vi.fn()} />);
  expect(screen.getByText("Selected on map")).toBeVisible();
});

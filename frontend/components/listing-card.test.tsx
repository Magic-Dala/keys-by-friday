import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { ListingCard } from "@/components/listing-card";

const listing = { id: "one", title: "Heatherstone", latitude: 37.4, longitude: -122.1, commute: { destination: "Google", mode: "DRIVE", durationMinutes: 18, status: "available" as const } };

it("selects the home from the card target and shows commute facts", async () => {
  const onMapSelect = vi.fn();
  render(<ListingCard listing={listing} rank={1} saved={false} comparisonSelected={false} mapSelected={false} mapHighlighted={false} onSave={vi.fn()} onSelect={vi.fn()} onMapSelect={onMapSelect} onMapHighlight={vi.fn()} />);
  expect(screen.getByText("18 min drive")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Select Heatherstone on the map and load its route" }));
  expect(onMapSelect).toHaveBeenCalledWith(listing);
});

it("keeps save and compare independent from route selection", async () => {
  const onMapSelect = vi.fn();
  const onSave = vi.fn();
  const onSelect = vi.fn();
  render(<ListingCard listing={listing} rank={1} saved={false} comparisonSelected={false} mapSelected={false} mapHighlighted={false} onSave={onSave} onSelect={onSelect} onMapSelect={onMapSelect} onMapHighlight={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await userEvent.click(screen.getByRole("button", { name: "Compare" }));
  expect(onSave).toHaveBeenCalledOnce();
  expect(onSelect).toHaveBeenCalledOnce();
  expect(onMapSelect).not.toHaveBeenCalled();
});

it("exposes selected map state without relying on color", () => {
  render(<ListingCard listing={listing} rank={1} saved={false} comparisonSelected={false} mapSelected mapHighlighted={false} onSave={vi.fn()} onSelect={vi.fn()} onMapSelect={vi.fn()} onMapHighlight={vi.fn()} />);
  expect(screen.getByText("Selected on map")).toBeVisible();
});

it("keeps the commute fact when map coordinates are unavailable", () => {
  render(
    <ListingCard
      listing={{ ...listing, latitude: 91, longitude: -122.1 }}
      rank={1}
      saved={false}
      comparisonSelected={false}
      mapSelected={false}
      mapHighlighted={false}
      onSave={vi.fn()}
      onSelect={vi.fn()}
      onMapSelect={vi.fn()}
      onMapHighlight={vi.fn()}
    />,
  );

  expect(screen.getByText("18 min drive")).toBeVisible();
  expect(screen.getByText("Map location unavailable")).toBeVisible();
});

it("highlights the card from the matching marker without selecting it", () => {
  const onMapSelect = vi.fn();
  const { container } = render(
    <ListingCard
      listing={listing}
      rank={1}
      saved={false}
      comparisonSelected={false}
      mapSelected={false}
      mapHighlighted
      onSave={vi.fn()}
      onSelect={vi.fn()}
      onMapSelect={onMapSelect}
      onMapHighlight={vi.fn()}
    />,
  );

  expect(container.querySelector("article")).toHaveClass("isMapHighlighted");
  expect(onMapSelect).not.toHaveBeenCalled();
});

it("shares card hover and focus highlights without requesting a route", () => {
  const onMapSelect = vi.fn();
  const onMapHighlight = vi.fn();
  const { container } = render(
    <ListingCard
      listing={listing}
      rank={1}
      saved={false}
      comparisonSelected={false}
      mapSelected={false}
      mapHighlighted={false}
      onSave={vi.fn()}
      onSelect={vi.fn()}
      onMapSelect={onMapSelect}
      onMapHighlight={onMapHighlight}
    />,
  );
  const card = container.querySelector("article");
  const target = screen.getByRole("button", { name: "Select Heatherstone on the map and load its route" });

  fireEvent.mouseEnter(card!);
  fireEvent.mouseLeave(card!);
  fireEvent.focus(target);
  fireEvent.blur(target);

  expect(onMapHighlight.mock.calls).toEqual([["one"], [undefined], ["one"], [undefined]]);
  expect(onMapSelect).not.toHaveBeenCalled();
});

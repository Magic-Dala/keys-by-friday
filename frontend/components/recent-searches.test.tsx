import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { RecentSearches } from "@/components/recent-searches";
import type { RecentSearch } from "@/types/search";

function displayedDate(timestamp: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(timestamp));
}

function search(overrides: Partial<RecentSearch> = {}): RecentSearch {
  return {
    conversationId: "conversation-1",
    createdAt: "2026-08-20T18:00:00Z",
    updatedAt: "2026-08-20T18:15:00Z",
    turnCount: 4,
    listings: [
      {
        id: "listing-1",
        priceMin: 3450,
        priceMax: 3950,
      },
    ],
    lastCommuteStatus: "available",
    ...overrides,
  };
}

function renderPanel(overrides: Partial<React.ComponentProps<typeof RecentSearches>> = {}) {
  return render(
    <RecentSearches
      items={[]}
      loading={false}
      onRetry={vi.fn()}
      onViewResults={vi.fn()}
      onContinueSearch={vi.fn()}
      {...overrides}
    />,
  );
}

it("renders backend-ordered searches with truthful metadata and only three visible items", () => {
  const newestDate = displayedDate("2026-08-20T18:15:00Z");
  const middleDate = displayedDate("2026-08-19T18:15:00Z");
  const oldDate = displayedDate("2026-08-18T18:15:00Z");

  renderPanel({
    items: [
      search({ conversationId: "newest", updatedAt: "2026-08-20T18:15:00Z" }),
      search({ conversationId: "middle", updatedAt: "2026-08-19T18:15:00Z" }),
      search({ conversationId: "old", updatedAt: "2026-08-18T18:15:00Z" }),
      search({ conversationId: "hidden", updatedAt: "2026-08-17T18:15:00Z" }),
    ],
  });

  const listText = screen.getByRole("list").textContent ?? "";
  expect(listText.indexOf(`Updated ${newestDate}`)).toBeLessThan(listText.indexOf(`Updated ${middleDate}`));
  expect(listText.indexOf(`Updated ${middleDate}`)).toBeLessThan(listText.indexOf(`Updated ${oldDate}`));
  expect(screen.getAllByRole("heading", { name: "Rental search" })).toHaveLength(3);
  expect(screen.getByText(`Updated ${newestDate} · 4 turns`)).toBeVisible();
  expect(screen.getAllByText("1 latest home")).toHaveLength(3);
  expect(screen.getAllByText("$3,450 – $3,950")).toHaveLength(3);
  expect(screen.getAllByText("Commute data available")).toHaveLength(3);
  expect(screen.getByText("Showing the 3 most recent searches")).toBeVisible();
});

it("uses the rental-search fallback title without inventing a summary", () => {
  renderPanel({ items: [search({ listings: [] })] });

  expect(screen.getByRole("heading", { name: "Rental search" })).toBeVisible();
  expect(screen.queryByText(/Mountain View|near Caltrain|quiet apartment/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
});

it("handles partial and required commute states without presenting not-requested as available", () => {
  renderPanel({
    items: [
      search({ conversationId: "not-requested", lastCommuteStatus: "not_requested" }),
      search({ conversationId: "partial", lastCommuteStatus: "partial" }),
      search({ conversationId: "requires-input", lastCommuteStatus: "requires_input" }),
    ],
  });

  expect(screen.getByText("Partial commute data")).toBeVisible();
  expect(screen.getByText("Commute details needed")).toBeVisible();
  expect(screen.queryByText(/not requested/i)).not.toBeInTheDocument();
  expect(screen.queryByText("Commute data available")).not.toBeInTheDocument();
});

it("renders a safe loading state", () => {
  renderPanel({ loading: true });

  expect(screen.getByRole("status")).toHaveTextContent("Loading recent searches");
  expect(screen.getByRole("region", { name: "Recent Searches" })).toHaveAttribute("aria-busy", "true");
});

it("renders the empty state", () => {
  renderPanel();

  expect(screen.getByText("No recent searches yet.")).toBeVisible();
  expect(screen.getByText("Start a rental search and it’ll appear here.")).toBeVisible();
});

it("renders a recoverable error and invokes Retry", async () => {
  const onRetry = vi.fn();
  renderPanel({ error: "Recent searches are unavailable.", onRetry });
  const user = userEvent.setup();

  expect(screen.getByRole("alert")).toHaveTextContent("Recent searches are unavailable.");
  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(onRetry).toHaveBeenCalledTimes(1);
});

it("delegates View Results and Continue Search for the selected item", async () => {
  const onViewResults = vi.fn();
  const onContinueSearch = vi.fn();
  renderPanel({
    items: [search({ conversationId: "selected" })],
    onViewResults,
    onContinueSearch,
  });
  const user = userEvent.setup();
  const item = screen.getByRole("listitem");

  await user.click(within(item).getByRole("button", { name: "View Results" }));
  await user.click(within(item).getByRole("button", { name: "Continue Search" }));

  expect(onViewResults).toHaveBeenCalledWith(expect.objectContaining({ conversationId: "selected" }));
  expect(onContinueSearch).toHaveBeenCalledWith(expect.objectContaining({ conversationId: "selected" }));
});

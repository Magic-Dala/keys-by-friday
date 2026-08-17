import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { RentalSearch } from "@/components/rental-search";
import { getSelectedRoute, sendChat } from "@/lib/api";
import type { SearchResponse } from "@/types/search";

vi.mock("@/lib/api", () => ({ getSelectedRoute: vi.fn(), sendChat: vi.fn() }));

const searchResponse: SearchResponse = {
  conversationId: "conversation-1",
  message: "I found one strong match.",
  listings: [
    {
      id: "one",
      title: "Heatherstone",
      latitude: 37.4,
      longitude: -122.1,
      commute: {
        destination: "Google",
        mode: "DRIVE",
        durationMinutes: 18,
        status: "available",
      },
    },
  ],
  mode: "adk",
};

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(getSelectedRoute).mockReset();
  vi.mocked(sendChat).mockReset();
  vi.stubEnv("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "");
});

afterEach(() => vi.unstubAllEnvs());

it("aborts and clears an active route as soon as a refinement starts", async () => {
  let routeSignal: AbortSignal | undefined;
  vi.mocked(sendChat)
    .mockResolvedValueOnce(searchResponse)
    .mockImplementationOnce(() => new Promise(() => {}));
  vi.mocked(getSelectedRoute)
    .mockImplementationOnce((_request, options) => {
      routeSignal = options?.signal;
      return new Promise(() => {});
    });

  render(<RentalSearch />);
  const user = userEvent.setup();

  await user.type(screen.getByLabelText("Describe your ideal rental"), "Find one home");
  await user.click(screen.getByRole("button", { name: "Ask rental agent" }));
  const selectHome = await screen.findByRole("button", {
    name: "Select Heatherstone on the map and load its route",
  });

  await user.click(selectHome);
  expect(await screen.findByText("Selected on map")).toBeVisible();
  expect(routeSignal?.aborted).toBe(false);

  await user.type(screen.getByLabelText("Refine your request"), "Add parking");
  await user.click(screen.getByRole("button", { name: "Refine search" }));

  await waitFor(() => expect(routeSignal?.aborted).toBe(true));
  expect(screen.getByRole("status")).toHaveTextContent("Select a home to see its commute route.");
});

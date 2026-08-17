# PR #9 Map Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the two open PR #9 Maps review threads by validating both browser Maps settings and deferring mobile map creation until the Map tab is visible.

**Architecture:** `RentalSearch` owns viewport-aware tab visibility and passes it to `RentalMap`. `RentalMap` treats a missing API key, missing Map ID, or hidden pane as distinct prerequisites: missing configuration renders the existing accessible fallback; a hidden pane waits to create Maps and therefore waits to fit bounds.

**Tech Stack:** Next.js 16, React 19, TypeScript, Google Maps JavaScript API, Vitest, Testing Library.

## Global Constraints

- Require `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` and `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID`; do not introduce `DEMO_MAP_ID` as an application fallback.
- Keep the existing direct `getSelectedRoute()` / `/api/route` flow and route abort/race behavior unchanged.
- Preserve accessible fallback rows and the List/Map buttons’ existing pressed-state semantics.
- Add regression tests before production code and observe each new test fail before its corresponding implementation.

---

### Task 1: Guard Advanced Markers with complete Maps configuration

**Files:**
- Modify: `frontend/components/rental-map.tsx:10-18, 115-158, 267-281`
- Modify: `frontend/components/rental-map.test.tsx:108-135`

**Interfaces:**
- Consumes: `apiKey?: string` and `mapId?: string` supplied by `RentalSearch`.
- Produces: a configuration fallback when either value is absent; `loadGoogleMaps(apiKey)` is never called without both values.

- [ ] **Step 1: Write the failing test**

Add a sibling to the current missing-key test:

```tsx
it("shows the configuration fallback and skips Maps loading when the Map ID is missing", () => {
  render(<RentalMap listings={listings} routeState={initialRouteSelectionState} onSelectListing={vi.fn()} apiKey="browser-key" />);

  expect(screen.getByText("Map needs browser configuration")).toBeVisible();
  expect(screen.getByText(/browser key and Map ID/i)).toBeVisible();
  expect(loadGoogleMapsMock).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `npm.cmd exec vitest run components/rental-map.test.tsx`

Expected: FAIL because a present API key currently bypasses the fallback and calls the Maps loader even when `mapId` is undefined.

- [ ] **Step 3: Write the minimal implementation**

In `RentalMap`, derive `hasMapsConfiguration = Boolean(apiKey && mapId)`. Use it in the loader effect guard and configuration-fallback branch:

```tsx
if (!hasMapsConfiguration || readyListings.length === 0 || !mapElementRef.current || mapRef.current) return;

if (!hasMapsConfiguration) {
  return <MapFallback ... heading="Map needs browser configuration" message="Add both a Google Maps browser key and Map ID to see these homes on the map." />;
}
```

Keep the loader call as `loadGoogleMaps(apiKey)` only after `hasMapsConfiguration` proves that `apiKey` is defined.

- [ ] **Step 4: Run the map suite to verify it passes**

Run: `npm.cmd exec vitest run components/rental-map.test.tsx`

Expected: PASS, including the new missing-Map-ID regression test.

- [ ] **Step 5: Commit the completed task**

```bash
git add frontend/components/rental-map.tsx frontend/components/rental-map.test.tsx
git commit -m "fix: require Maps configuration for markers"
```

### Task 2: Initialize and fit the map only when its pane is visible on mobile

**Files:**
- Modify: `frontend/components/rental-search.tsx:1-20, 82, 287-388`
- Modify: `frontend/components/rental-map.tsx:10-18, 115-158`
- Modify: `frontend/components/rental-search.test.tsx:1-40, append mobile regression test`

**Interfaces:**
- Consumes: browser media query `(max-width: 900px)` and `mobileResultsView: "list" | "map"`.
- Produces: `mapVisible: boolean` passed to `RentalMap`; on desktop it is true once viewport state is known, and on mobile it is true only for the Map view.

- [ ] **Step 1: Write the failing mobile regression test**

In `rental-search.test.tsx`, mock `window.matchMedia` to return `matches: true`, set both public Maps environment variables, and mock `loadGoogleMaps` with a fake `Map` whose `fitBounds` is a spy. Submit `searchResponse`, then assert the map is not loaded until the Map control is selected:

```tsx
expect(loadGoogleMapsMock).not.toHaveBeenCalled();
await user.click(screen.getByRole("button", { name: "Map" }));
await waitFor(() => expect(loadGoogleMapsMock).toHaveBeenCalledWith("browser-key"));
expect(mapInstances[0].fitBounds).toHaveBeenCalled();
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `npm.cmd exec vitest run components/rental-search.test.tsx`

Expected: FAIL because `RentalMap` currently mounts, loads Maps, and fits bounds while the mobile List view applies `display: none` to its pane.

- [ ] **Step 3: Write the minimal implementation**

Add a small viewport hook in `rental-search.tsx` that subscribes to `window.matchMedia("(max-width: 900px)")` and begins in an unknown state. Derive:

```tsx
const mapVisible = isMobileViewport === false || (isMobileViewport === true && mobileResultsView === "map");
```

Pass `mapVisible` into `RentalMap`. Add `mapVisible: boolean` to `RentalMapProps` and require it in the Maps loader effect:

```tsx
if (!mapVisible || !hasMapsConfiguration || readyListings.length === 0 || !mapElementRef.current || mapRef.current) return;
```

Include `mapVisible` in that effect’s dependency list so selecting Map creates the Maps instance only after the pane is visible. Do not alter the route effect; it will run after `runtime` is set.

- [ ] **Step 4: Run focused suites to verify they pass**

Run: `npm.cmd exec vitest run components/rental-search.test.tsx components/rental-map.test.tsx`

Expected: PASS; desktop map tests continue to initialize and fit, while the new mobile test initializes only after Map is selected.

- [ ] **Step 5: Commit the completed task**

```bash
git add frontend/components/rental-search.tsx frontend/components/rental-map.tsx frontend/components/rental-search.test.tsx frontend/components/rental-map.test.tsx
git commit -m "fix: defer mobile map initialization"
```

### Task 3: Verify and publish the complete review fix

**Files:**
- Verify: `frontend/components/rental-map.tsx`
- Verify: `frontend/components/rental-search.tsx`
- Verify: `frontend/components/rental-map.test.tsx`
- Verify: `frontend/components/rental-search.test.tsx`

**Interfaces:**
- Consumes: the completed Tasks 1 and 2.
- Produces: a branch ready to push to PR #9’s `frontend/maps-spatial-comparison` head branch.

- [ ] **Step 1: Run the full frontend verification**

Run: `npm.cmd run check`

Expected: all tests, type checking, and production build exit successfully.

- [ ] **Step 2: Inspect the final change set**

Run: `git diff pr-9...HEAD --check` and `git status --short --branch`

Expected: only the planned Maps fixes, their regression tests, and the approved design/plan documentation are staged or committed.

- [ ] **Step 3: Push the reviewed commits to the existing PR branch**

Run: `git push origin HEAD:frontend/maps-spatial-comparison`

Expected: GitHub PR #9 updates without creating a new pull request.

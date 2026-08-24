# Recent Searches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a UID-safe, lightweight Recent Searches experience to the authenticated Next.js rental search frontend.

**Architecture:** The existing `RentalSearch` component remains the single Firebase auth observer and owns active conversation/listing state. A focused `useRecentSearches` hook consumes that auth state, fetches through `getRecentSearches`, and enforces UID/request-generation guards. A focused rail component renders summaries and delegates restoration back to `RentalSearch`, which reuses existing listing/map/shortlist UI.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Firebase Auth, Vitest, Testing Library, existing CSS design tokens.

**Spec:** `docs/superpowers/specs/2026-08-20-recent-searches-design.md`

## Global Constraints

- Use the product term “Recent Searches”; do not call it chat history or conversation history.
- Do not access Firestore from the browser.
- Do not send or accept Firebase UIDs in the Recent Searches API function.
- Use the existing Firebase auth observer in `RentalSearch`; do not create a second observer.
- Use the agreed camelCase API contract only; isolate response parsing in `frontend/lib/api.ts`.
- Preserve backend item ordering; do not client-sort Recent Searches.
- Reuse the normalized `Listing` type and existing listing/map/shortlist components.
- Do not fabricate historical `Turn[]` objects or restore full transcripts.
- Show no more than three Recent Searches in the compact decision rail preview.
- Refresh failures must not replace a successful rental-search result with an error.

---

### Task 1: Add the Recent Searches API contract and parser tests

**Files:**
- Create: `frontend/lib/api.test.ts`
- Modify: `frontend/types/search.ts`
- Modify: `frontend/lib/api.ts`

**Interfaces:**
- Produces `RecentSearch`, `RecentSearchResponse`, and `getRecentSearches(options?: { signal?: AbortSignal }): Promise<RecentSearchResponse>`.
- Extends `Listing` with optional parsed `priceMin` and `priceMax` evidence.

- [ ] **Step 1: Write failing API tests**

Test that `getRecentSearches` requests `GET http://localhost:8000/api/conversations?limit=20`, sends the bearer token from `getFirebaseIdToken`, parses the camelCase response into `RecentSearchResponse`, preserves item order, and retains `priceMin`/`priceMax` on listings. Add an abort test and an HTTP-error test using the existing `ApiError` message convention.

- [ ] **Step 2: Run the focused API test and verify it fails for the missing function/type**

Run: `npm test -- lib/api.test.ts`

Expected: FAIL because `getRecentSearches` and the Recent Searches response parser do not exist yet.

- [ ] **Step 3: Add the shared types and minimal API implementation**

Add the Recent Searches types in `frontend/types/search.ts`. Extend `parseListing` to parse optional finite `priceMin` and `priceMax`. Add a camelCase-only `parseRecentSearch`/`parseRecentSearchResponse` path and `getRecentSearches` beside `getShortlist`, using `authenticatedHeaders`, `cache: "no-store"`, the supplied signal, abort passthrough, and `ApiError` handling.

- [ ] **Step 4: Run the focused API tests and verify they pass**

Run: `npm test -- lib/api.test.ts`

Expected: PASS with all API contract, ordering, abort, and error assertions green.

### Task 2: Add UID-safe fetching without a second auth observer

**Files:**
- Create: `frontend/hooks/use-recent-searches.ts`
- Create: `frontend/hooks/use-recent-searches.test.tsx`

**Interfaces:**
- Consumes: `authUser` from `RentalSearch` (`User | null | undefined`).
- Produces `{ items, loading, error, refresh }` from `useRecentSearches(authUser)`.

- [ ] **Step 1: Write failing hook tests**

Cover: anonymous users make no request and expose empty data; a non-anonymous UID fetches once; a UID change clears the old list and starts a new request; a late response from the old UID is ignored; same-UID refresh starts another request without mixing accounts; abort errors do not become visible errors.

- [ ] **Step 2: Run the hook tests and verify they fail**

Run: `npm test -- hooks/use-recent-searches.test.tsx`

Expected: FAIL because `useRecentSearches` does not exist.

- [ ] **Step 3: Implement the hook minimally**

Derive `accountKey = authUser && !authUser.isAnonymous ? authUser.uid : undefined`. Track the active request, account key, and identity generation in refs. On account-key change, abort the prior request and clear `{ items, loading, error }` before fetching the new account. Commit only when controller, account key, and generation still match. Make `refresh` increment a nonce; keep refresh errors in the hook state.

- [ ] **Step 4: Run hook tests and verify they pass**

Run: `npm test -- hooks/use-recent-searches.test.tsx`

Expected: PASS with anonymous, UID-change, stale-response, refresh, and abort behavior covered.

### Task 3: Add the compact Recent Searches rail component

**Files:**
- Create: `frontend/components/recent-searches.tsx`
- Create: `frontend/components/recent-searches.test.tsx`
- Modify: `frontend/app/globals.css`

**Interfaces:**
- Consumes `RecentSearch[]`, loading/error state, retry callback, and restoration callbacks.
- Produces an accessible compact `section` using at most the first three backend-ordered items.

- [ ] **Step 1: Write failing component tests**

Cover newest-first rendering in the supplied order, truthful “Rental search” fallback, updated date/turn/listing/commute metadata, at most three visible items, loading state, empty state copy, error with Retry, and action callbacks.

- [ ] **Step 2: Run the component tests and verify they fail**

Run: `npm test -- components/recent-searches.test.tsx`

Expected: FAIL because the component and styles do not exist.

- [ ] **Step 3: Implement the compact component and styles**

Render only `searches.slice(0, 3)` without sorting. Use “Rental search” unless a future explicit title is present. Show the supported price range only when parsed `priceMin`/`priceMax` values exist; otherwise omit it. Use native buttons with descriptive labels, visible focus styles inherited from the app, and `aria-busy`/`role="alert"`/`role="status"` for state feedback. Add responsive rail-card styles without creating a permanent history column.

- [ ] **Step 4: Run component tests and verify they pass**

Run: `npm test -- components/recent-searches.test.tsx`

Expected: PASS with no snapshots or duplicated listing cards.

### Task 4: Integrate auth-safe fetching, restoration, and continuation into RentalSearch

**Files:**
- Modify: `frontend/components/rental-search.tsx`
- Modify: `frontend/components/rental-search.test.tsx`

**Interfaces:**
- Consumes `useRecentSearches(authUser)` and `RecentSearch` actions.
- Preserves existing `sendChat({ message, conversationId })`, auth, shortlist, route, map, and comparison behavior.

- [ ] **Step 1: Extend the existing component tests with failing behavior**

Mock `getRecentSearches` and add tests for authenticated visibility, anonymous non-visibility, UID-change clearing and stale response protection, View Results restoring the latest listings and correct conversation ID, Continue Search focusing/indicating continuation and posting the correct ID, no fabricated turns, refresh-after-chat, and refresh failure not changing the successful result/error state.

- [ ] **Step 2: Run the targeted rental-search tests and verify the new assertions fail**

Run: `npm test -- components/rental-search.test.tsx`

Expected: FAIL only for the new Recent Searches behaviors; existing auth, shortlist, map, and comparison assertions remain diagnostic baseline.

- [ ] **Step 3: Integrate the hook using the existing authUser**

Call `useRecentSearches(authUser)` from `RentalSearch`; do not call `observeFirebaseUser` anywhere else. Render the rail card only for `authUser && !authUser.isAnonymous`. Invoke `refreshRecentSearches()` after a successful `sendChat` without awaiting it or routing its failure through chat error handling.

- [ ] **Step 4: Add one restoration function for both actions**

Abort `requestRef`, reset route selection, clear transcript turns, draft, commute evaluation, map highlight, comparison IDs/panel, mode, and errors, set the historical conversation ID/listings, set list view, and write a UI-only notice based on `updatedAt`. Continue schedules focus on the existing textarea. The function must never create old `Turn` objects.

- [ ] **Step 5: Update the welcome condition for restored searches**

Use an active-search condition based on `conversationId || turns.length || listings.length`, so a restored search with `turns=[]` renders the existing conversation/results view. Make New search available for restored sessions and render the continuation notice outside the transcript turn list.

- [ ] **Step 6: Run targeted tests and verify they pass**

Run: `npm test -- components/rental-search.test.tsx`

Expected: PASS for new behavior and existing auth/shortlist/rental-search regressions.

### Task 5: Full verification and handoff

**Files:**
- Review: all changed frontend files and `git diff`

- [ ] **Step 1: Run the complete frontend test suite**

Run: `npm test`

Expected: PASS with zero failed tests.

- [ ] **Step 2: Run the TypeScript check**

Run: `npm run typecheck`

Expected: Next type generation and `tsc --noEmit` exit successfully.

- [ ] **Step 3: Run the production frontend build**

Run: `npm run build`

Expected: Next production build exits successfully.

- [ ] **Step 4: Run the project check command**

Run: `npm run check`

Expected: tests, typecheck, and build all complete successfully.

- [ ] **Step 5: Inspect branch/worktree safety and diff**

Run from the worktree: `git -c safe.directory=F:/All_Things_Agentic_Hackathon/keys-by-friday-recent-searches status --short --branch` and `git -c safe.directory=F:/All_Things_Agentic_Hackathon/keys-by-friday-recent-searches diff --stat`. Confirm only frontend/worktree plan files changed and the backend checkout remains on `backend/recent-searches-api` with its pre-existing changes.

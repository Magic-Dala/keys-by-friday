# Recent Searches Design

**Status:** Approved for implementation

## Goal

Give non-anonymous Firebase users a compact Recent Searches view backed by lightweight persisted conversation metadata. A user can inspect the latest saved listing snapshot and continue the same backend conversation without restoring a transcript.

## Boundaries

- The frontend calls `GET /api/conversations?limit=20` through the existing authenticated API client.
- The browser never supplies a Firebase UID and never accesses Firestore.
- The existing `RentalSearch` auth observer remains the single source of Firebase auth state. `useRecentSearches` consumes the current user/UID passed by that component.
- Backend ordering is authoritative. The frontend renders the returned order and only limits the visible rail preview.
- The API contract is camelCase-only. Contract parsing and validation stay in `frontend/lib/api.ts`.
- The feature stores no transcript turns and never fabricates old agent/user messages.

## Data model and API

`RecentSearch` contains `conversationId`, `createdAt`, `updatedAt`, `turnCount`, `listings`, and optional `lastCommuteStatus`. It reuses `Listing`. The shared listing model/parser gains optional `priceMin` and `priceMax`; Recent Searches shows a price range only when those parsed fields provide evidence. Unsupported price summaries are omitted.

`getRecentSearches({ signal })` uses `authenticatedHeaders()`, sends a GET request with `limit=20`, supports aborts, and uses the existing `ApiError` conventions.

## Identity and lifecycle

`useRecentSearches(authUser)` derives an account key only for non-anonymous users. It clears data and aborts in-flight work when that key changes or becomes unavailable. Each response must still match the request controller, active UID, and identity generation before it can update state. It exposes refresh; refresh errors remain local to the history card and never replace a successful chat result.

## Restore and continue behavior

View Results and Continue Search share one restoration function in `RentalSearch`. Restoration aborts active chat work, clears draft/transcript/errors, resets route selection, map highlight, comparison, commute evaluation, and mobile view, then sets the existing conversation ID and persisted listings. It records a UI-only continuation notice. Continue additionally focuses the existing composer. The normal `sendChat` path then posts the restored conversation ID.

## UI

The existing decision rail gains a compact authenticated-only Recent Searches card showing at most three returned items in backend order. Each item uses the truthful fallback title “Rental search” when no explicit backend title exists and shows updated date, turn count, listing count, supported price range, commute status, and actions. Loading, empty, recoverable error, and retry states are included. The existing listing card, map, route, shortlist, and comparison components remain the only result renderers.

## Verification

Tests cover API authentication/normalization, account visibility, ordering, empty/loading/error/retry states, anonymous isolation, UID changes, stale responses, restoration, continuation, and the no-transcript boundary. The frontend test suite, TypeScript typecheck, production build, and combined check command must run before handoff.

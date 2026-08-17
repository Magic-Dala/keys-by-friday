# PR #9 Map Review Fixes

## Goal

Resolve the two open PR #9 review threads without changing the search or route API contracts: make Maps configuration failures explicit, and prevent mobile map initialization while the map pane is hidden.

## Scope

### Maps configuration

`RentalMap` must require both `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` and `NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID` before it loads the Google Maps JavaScript API or creates Advanced Markers. If either setting is absent, it must render a clear fallback explaining that both browser Maps settings are required and retain the accessible list of homes.

The implementation must not substitute `DEMO_MAP_ID` in application code. A real Map ID is required for the production Advanced Markers integration.

### Mobile List-to-Map transition

`RentalSearch` must determine whether the browser is currently at the `max-width: 900px` breakpoint before allowing `RentalMap` to initialize. On desktop, the map remains available immediately. On mobile, it must initialize only after the user selects the Map tab.

`RentalMap` receives a visibility flag from its parent. Its Google Maps initialization and initial bounds fitting must wait until that flag is true. Selecting Map after starting on List therefore creates a map in a non-zero-sized visible pane, allowing `fitBounds()` to frame the listing markers correctly. Existing route rendering and abort/race safety remain unchanged.

## Error handling and accessibility

- The configuration fallback must state that a browser API key and Map ID are both needed.
- The fallback must preserve the existing selectable, text-based home list.
- The List and Map controls retain their pressed states; no new interactive controls are introduced.

## Tests

Add regression coverage that proves:

1. A present API key with no Map ID renders the configuration fallback and does not call the Maps loader.
2. On a mobile viewport, initial List view does not call the Maps loader; switching to Map calls it and fits the listings.
3. Existing desktop map, marker, route, and fallback tests continue to pass.

## Non-goals

- Changing the direct `/api/route` integration.
- Changing route ranking, listing results, or Maps styling.
- Using a demo Map ID as a production fallback.

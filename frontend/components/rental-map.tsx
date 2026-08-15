"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { RouteSummary } from "@/components/route-summary";
import { loadGoogleMaps } from "@/lib/google-maps";
import { commutePresentation, mapReadyListings, type RouteSelectionState } from "@/lib/map-model";
import type { CommuteEvaluation, Listing } from "@/types/search";

interface RentalMapProps {
  listings: Listing[];
  commuteEvaluation?: CommuteEvaluation;
  routeState: RouteSelectionState;
  highlightedListingId?: string;
  onSelectListing: (listing: Listing) => void;
  onHighlightListing?: (listingId?: string) => void;
  apiKey?: string;
  mapId?: string;
}

type GoogleMapsLibraries = Awaited<ReturnType<typeof loadGoogleMaps>>;

interface MapRuntime {
  map: google.maps.Map;
  libraries: GoogleMapsLibraries;
}

interface MarkerRuntime {
  listing: ReturnType<typeof mapReadyListings>[number];
  rank: number;
  marker: google.maps.marker.AdvancedMarkerElement;
  pin: google.maps.marker.PinElement;
  selectListing: EventListener;
  activateWithKeyboard: EventListener;
  highlightListing: EventListener;
  clearHighlight: EventListener;
}

const brandMarkerColor = "#c13f35";
const neutralMarkerColor = "#1d1d1f";
const markerContrastColor = "#ffffff";
const routePadding = { top: 220, right: 64, bottom: 64, left: 64 };

const visuallyHidden: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0, 0, 0, 0)",
  whiteSpace: "nowrap",
  border: 0,
};

function listingLabel(listing: Listing): string {
  return listing.title ?? listing.address ?? "Rental home";
}

function markerLabel(listing: Listing, rank: number): string {
  return `${rank}. ${listingLabel(listing)} — ${commutePresentation(listing.commute).label}`;
}

function markerTitle(listing: Listing, rank: number, selected: boolean): string {
  return `Rank ${rank}: ${listingLabel(listing)}. ${commutePresentation(listing.commute).label}.${selected ? " Selected." : ""}`;
}

function MapFallback({
  listings,
  onSelectListing,
  heading,
  message,
}: {
  listings: Listing[];
  onSelectListing: (listing: Listing) => void;
  heading: string;
  message: string;
}) {
  return (
    <div className="mapFallback" role="region" aria-label="Rental map fallback">
      <h3>{heading}</h3>
      <p>{message}</p>
      <ul>
        {listings.map((listing) => (
          <li key={listing.id}>
            <button type="button" onClick={() => onSelectListing(listing)} aria-label={`Select ${listingLabel(listing)}`}>
              <strong>{listingLabel(listing)}</strong>
              {listing.title && listing.address ? <span>{listing.address}</span> : null}
              <span>{commutePresentation(listing.commute).label}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RentalMap({
  listings,
  commuteEvaluation,
  routeState,
  highlightedListingId,
  onSelectListing,
  onHighlightListing,
  apiKey,
  mapId,
}: RentalMapProps) {
  const mapElementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map>(null);
  const markerRuntimesRef = useRef(new Map<string, MarkerRuntime>());
  const routePolylinesRef = useRef<google.maps.Polyline[]>([]);
  const onSelectListingRef = useRef(onSelectListing);
  const onHighlightListingRef = useRef(onHighlightListing);
  const fittedListingIdsRef = useRef<string>(undefined);
  const [runtime, setRuntime] = useState<MapRuntime>();
  const [loaderError, setLoaderError] = useState<string>();
  const [routeError, setRouteError] = useState<string>();
  const readyListings = useMemo(() => mapReadyListings(listings), [listings]);
  const listingIds = useMemo(
    () => readyListings.map((listing) => listing.id).sort().join("\u0000"),
    [readyListings],
  );
  const selectedListing = listings.find((listing) => listing.id === routeState.selectedListingId);

  useEffect(() => {
    onSelectListingRef.current = onSelectListing;
    onHighlightListingRef.current = onHighlightListing;
  }, [onHighlightListing, onSelectListing]);

  useEffect(() => {
    if (!apiKey || readyListings.length === 0 || !mapElementRef.current || mapRef.current) return;

    let cancelled = false;
    setLoaderError(undefined);

    void loadGoogleMaps(apiKey)
      .then((libraries) => {
        if (cancelled || !mapElementRef.current || mapRef.current) return;
        const map = new libraries.Map(mapElementRef.current, {
          mapId,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          clickableIcons: false,
        });
        mapRef.current = map;
        setRuntime({ map, libraries });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoaderError(error instanceof Error ? error.message : "The map could not be loaded.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [apiKey, mapId, readyListings.length]);

  useEffect(() => {
    if (!runtime) return;

    readyListings.forEach((listing, index) => {
      const rank = listing.rank ?? index + 1;
      const pin = new runtime.libraries.PinElement({
        glyphText: String(rank),
        background: neutralMarkerColor,
        borderColor: markerContrastColor,
        glyphColor: markerContrastColor,
      });
      const marker = new runtime.libraries.AdvancedMarkerElement({
        map: runtime.map,
        position: { lat: listing.latitude, lng: listing.longitude },
        content: pin,
        gmpClickable: true,
        title: markerTitle(listing, rank, false),
        zIndex: 1,
      });
      const selectListing = () => onSelectListingRef.current(listing);
      const activateWithKeyboard = (event: Event) => {
        const key = (event as globalThis.KeyboardEvent).key;
        if (key === "Enter" || key === " ") {
          event.preventDefault();
          selectListing();
        }
      };
      const highlightListing = () => onHighlightListingRef.current?.(listing.id);
      const clearHighlight = () => onHighlightListingRef.current?.(undefined);

      marker.addEventListener("gmp-click", selectListing);
      marker.addEventListener("keydown", activateWithKeyboard);
      marker.addEventListener("pointerenter", highlightListing);
      marker.addEventListener("pointerleave", clearHighlight);
      marker.addEventListener("focus", highlightListing);
      marker.addEventListener("blur", clearHighlight);
      markerRuntimesRef.current.set(listing.id, {
        listing,
        rank,
        marker,
        pin,
        selectListing,
        activateWithKeyboard,
        highlightListing,
        clearHighlight,
      });
    });

    if (fittedListingIdsRef.current !== listingIds) {
      fittedListingIdsRef.current = listingIds;
      if (readyListings.length === 1) {
        runtime.map.setCenter({ lat: readyListings[0].latitude, lng: readyListings[0].longitude });
        runtime.map.setZoom(14);
      } else if (readyListings.length > 1) {
        const bounds = new google.maps.LatLngBounds();
        readyListings.forEach((listing) => bounds.extend({ lat: listing.latitude, lng: listing.longitude }));
        runtime.map.fitBounds(bounds);
      }
    }

    return () => {
      markerRuntimesRef.current.forEach(({
        marker,
        selectListing,
        activateWithKeyboard,
        highlightListing,
        clearHighlight,
      }) => {
        marker.removeEventListener("gmp-click", selectListing);
        marker.removeEventListener("keydown", activateWithKeyboard);
        marker.removeEventListener("pointerenter", highlightListing);
        marker.removeEventListener("pointerleave", clearHighlight);
        marker.removeEventListener("focus", highlightListing);
        marker.removeEventListener("blur", clearHighlight);
        marker.map = null;
      });
      markerRuntimesRef.current.clear();
    };
  }, [listingIds, readyListings, runtime]);

  useEffect(() => {
    markerRuntimesRef.current.forEach(({ listing, marker, pin, rank }) => {
      const selected = listing.id === routeState.selectedListingId;
      const highlighted = listing.id === highlightedListingId;
      pin.background = selected ? brandMarkerColor : neutralMarkerColor;
      pin.borderColor = markerContrastColor;
      pin.glyphColor = markerContrastColor;
      pin.scale = highlighted && !selected ? 1.18 : selected ? 1.12 : 1;
      marker.title = markerTitle(listing, rank, selected);
      marker.zIndex = selected ? 3 : highlighted ? 2 : 1;
    });
  }, [highlightedListingId, listingIds, routeState.selectedListingId, runtime]);

  useEffect(() => {
    routePolylinesRef.current.forEach((polyline) => polyline.setMap(null));
    routePolylinesRef.current = [];
    setRouteError(undefined);

    const route = routeState.route;
    if (
      !runtime
      || routeState.status !== "available"
      || !route
      || route.listingId !== routeState.selectedListingId
      || !route.encodedPolyline
    ) return;

    try {
      const path = runtime.libraries.encoding.decodePath(route.encodedPolyline);
      const casing = new google.maps.Polyline({
        map: runtime.map,
        path,
        strokeColor: markerContrastColor,
        strokeOpacity: 0.9,
        strokeWeight: 9,
        zIndex: 1,
      });
      const foreground = new google.maps.Polyline({
        map: runtime.map,
        path,
        strokeColor: brandMarkerColor,
        strokeOpacity: 1,
        strokeWeight: 5,
        zIndex: 2,
      });
      routePolylinesRef.current = [casing, foreground];

      if (path.length > 0) {
        const bounds = new google.maps.LatLngBounds();
        path.forEach((position) => bounds.extend(position));
        const selectedMapListing = readyListings.find(
          (listing) => listing.id === routeState.selectedListingId,
        );
        if (selectedMapListing) {
          bounds.extend({ lat: selectedMapListing.latitude, lng: selectedMapListing.longitude });
        }
        runtime.map.fitBounds(bounds, routePadding);
      }
    } catch (error: unknown) {
      setRouteError(error instanceof Error ? error.message : "The route line could not be drawn.");
    }

    return () => {
      routePolylinesRef.current.forEach((polyline) => polyline.setMap(null));
      routePolylinesRef.current = [];
    };
  }, [readyListings, routeState.route, routeState.selectedListingId, routeState.status, runtime]);

  const retryRoute = () => {
    if (selectedListing) onSelectListing(selectedListing);
  };

  if (!apiKey) {
    return (
      <section className="rentalMap">
        <RouteSummary listing={selectedListing} commuteEvaluation={commuteEvaluation} state={routeState} onRetry={retryRoute} />
        <MapFallback
          listings={listings}
          onSelectListing={onSelectListing}
          heading="Map needs a browser key"
          message="Add a Google Maps browser key to see these homes on the map."
        />
      </section>
    );
  }

  return (
    <section className="rentalMap">
      <RouteSummary listing={selectedListing} commuteEvaluation={commuteEvaluation} state={routeState} onRetry={retryRoute} />
      {readyListings.length === 0 ? (
        <MapFallback
          listings={listings}
          onSelectListing={onSelectListing}
          heading="Map needs home locations"
          message="These homes do not include coordinates yet, so they cannot be placed on the map."
        />
      ) : null}
      {readyListings.length > 0 && loaderError ? <MapFallback listings={listings} onSelectListing={onSelectListing} heading="Map unavailable" message={loaderError} /> : null}
      {readyListings.length > 0 && routeError ? <MapFallback listings={listings} onSelectListing={onSelectListing} heading="Route line unavailable" message={routeError} /> : null}
      <div ref={mapElementRef} className="mapCanvas" hidden={readyListings.length === 0} aria-label="Map of recommended rental homes and the selected commute route" />
      <ul style={visuallyHidden}>
        {readyListings.map((listing, index) => (
          <li key={listing.id}>{markerLabel(listing, listing.rank ?? index + 1)}</li>
        ))}
      </ul>
    </section>
  );
}

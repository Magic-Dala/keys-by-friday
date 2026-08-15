"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { RouteSummary } from "@/components/route-summary";
import { loadGoogleMaps } from "@/lib/google-maps";
import { commutePresentation, mapReadyListings, type MapReadyListing, type RouteSelectionState } from "@/lib/map-model";
import type { CommuteEvaluation, Listing } from "@/types/search";

interface RentalMapProps {
  listings: Listing[];
  commuteEvaluation?: CommuteEvaluation;
  routeState: RouteSelectionState;
  onSelectListing: (listing: Listing) => void;
  apiKey?: string;
  mapId?: string;
}

type GoogleMapsLibraries = Awaited<ReturnType<typeof loadGoogleMaps>>;

interface MapRuntime {
  map: google.maps.Map;
  libraries: GoogleMapsLibraries;
}

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

function MapFallback({
  listings,
  onSelectListing,
  error,
}: {
  listings: MapReadyListing[];
  onSelectListing: (listing: Listing) => void;
  error?: string;
}) {
  return (
    <div className="mapFallback" role="region" aria-label="Rental map fallback">
      <h3>{error ? "Map unavailable" : "Map needs a browser key"}</h3>
      <p>{error ?? "Add a Google Maps browser key to see these homes on the map."}</p>
      <ul>
        {listings.map((listing, index) => {
          const rank = listing.rank ?? index + 1;
          return (
            <li key={listing.id}>
              <button type="button" onClick={() => onSelectListing(listing)} aria-label={`Select ${listingLabel(listing)}`}>
                <strong>{listingLabel(listing)}</strong>
                <span>{commutePresentation(listing.commute).label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function RentalMap({
  listings,
  commuteEvaluation,
  routeState,
  onSelectListing,
  apiKey,
  mapId,
}: RentalMapProps) {
  const mapElementRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map>(null);
  const polylineRef = useRef<google.maps.Polyline>(null);
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
    if (!apiKey || !mapElementRef.current || mapRef.current) return;

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
  }, [apiKey, mapId]);

  useEffect(() => {
    if (!runtime) return;

    const markers = readyListings.map((listing, index) => {
      const rank = listing.rank ?? index + 1;
      const pin = new runtime.libraries.PinElement({ glyph: String(rank) });
      const marker = new runtime.libraries.AdvancedMarkerElement({
        map: runtime.map,
        position: { lat: listing.latitude, lng: listing.longitude },
        content: pin,
        gmpClickable: true,
        title: markerLabel(listing, rank),
      });
      const selectListing = () => onSelectListing(listing);
      const activateWithKeyboard = (event: Event) => {
        const key = (event as globalThis.KeyboardEvent).key;
        if (key === "Enter" || key === " ") {
          event.preventDefault();
          selectListing();
        }
      };

      marker.addEventListener("gmp-click", selectListing);
      marker.addEventListener("keydown", activateWithKeyboard);

      return { marker, selectListing, activateWithKeyboard };
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
      markers.forEach(({ marker, selectListing, activateWithKeyboard }) => {
        marker.removeEventListener("gmp-click", selectListing);
        marker.removeEventListener("keydown", activateWithKeyboard);
        marker.map = null;
      });
    };
  }, [listingIds, onSelectListing, readyListings, runtime]);

  useEffect(() => {
    polylineRef.current?.setMap(null);
    polylineRef.current = null;
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
      const polyline = new google.maps.Polyline({ map: runtime.map, path });
      polylineRef.current = polyline;

      if (path.length > 0) {
        const bounds = new google.maps.LatLngBounds();
        path.forEach((position) => bounds.extend(position));
        runtime.map.fitBounds(bounds, 48);
      }
    } catch (error: unknown) {
      setRouteError(error instanceof Error ? error.message : "The route line could not be drawn.");
    }

    return () => {
      polylineRef.current?.setMap(null);
      polylineRef.current = null;
    };
  }, [routeState.route, routeState.selectedListingId, routeState.status, runtime]);

  const mapError = loaderError ?? routeError;
  const retryRoute = () => {
    if (selectedListing) onSelectListing(selectedListing);
  };

  if (!apiKey) {
    return (
      <section className="rentalMap">
        <RouteSummary listing={selectedListing} commuteEvaluation={commuteEvaluation} state={routeState} onRetry={retryRoute} />
        <MapFallback listings={readyListings} onSelectListing={onSelectListing} />
      </section>
    );
  }

  return (
    <section className="rentalMap">
      <RouteSummary listing={selectedListing} commuteEvaluation={commuteEvaluation} state={routeState} onRetry={retryRoute} />
      {mapError ? <MapFallback listings={readyListings} onSelectListing={onSelectListing} error={mapError} /> : null}
      <div ref={mapElementRef} className="mapCanvas" aria-label="Map of recommended rental homes and the selected commute route" />
      <ul style={visuallyHidden}>
        {readyListings.map((listing, index) => (
          <li key={listing.id}>{markerLabel(listing, listing.rank ?? index + 1)}</li>
        ))}
      </ul>
    </section>
  );
}

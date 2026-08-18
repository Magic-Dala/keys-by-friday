import { importLibrary, setOptions } from "@googlemaps/js-api-loader";

let configuredKey: string | undefined;

export async function loadGoogleMaps(apiKey: string) {
  if (!configuredKey) {
    setOptions({ key: apiKey, v: "weekly" });
    configuredKey = apiKey;
  } else if (configuredKey !== apiKey) {
    throw new Error("Google Maps was already configured with another browser key.");
  }

  const [maps, marker, geometry] = await Promise.all([
    importLibrary("maps"),
    importLibrary("marker"),
    importLibrary("geometry"),
  ]);

  return {
    Map: (maps as google.maps.MapsLibrary).Map,
    AdvancedMarkerElement: (marker as google.maps.MarkerLibrary).AdvancedMarkerElement,
    PinElement: (marker as google.maps.MarkerLibrary).PinElement,
    encoding: (geometry as google.maps.GeometryLibrary).encoding,
  };
}

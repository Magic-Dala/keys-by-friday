from __future__ import annotations

from rental_agent.models import Listing, SearchRequirements
from rental_agent.providers.base import ListingProvider


MOCK_LISTINGS = [
    Listing("mv-1", "800 California St, Mountain View, CA 94041", "Mountain View", "CA", "94041", 3650, 2, 2, property_type="Apartment", square_footage=980, status="Active", pets_allowed=True, parking_available=True, source="mock"),
    Listing("mv-2", "1555 W Middlefield Rd, Mountain View, CA 94043", "Mountain View", "CA", "94043", 3895, 2, 2, property_type="Apartment", square_footage=1050, status="Active", pets_allowed=False, parking_available=True, source="mock"),
    Listing("mv-3", "2255 Showers Dr, Mountain View, CA 94040", "Mountain View", "CA", "94040", 4200, 2, 2, property_type="Apartment", square_footage=1120, status="Active", pets_allowed=True, parking_available=True, source="mock"),
    Listing("mv-4", "1984 Old Middlefield Way, Mountain View, CA 94043", "Mountain View", "CA", "94043", 3350, 1, 1, property_type="Apartment", square_footage=760, status="Active", pets_allowed=True, parking_available=True, source="mock"),
    Listing("mv-5", "49 Showers Dr, Mountain View, CA 94040", "Mountain View", "CA", "94040", 3790, 2, 2, property_type="Condo", square_footage=1010, status="Active", pets_allowed=None, parking_available=None, source="mock"),
    Listing("mv-6", "555 San Antonio Rd, Mountain View, CA 94040", "Mountain View", "CA", "94040", 3990, 2, 2.5, property_type="Townhouse", square_footage=1250, status="Active", pets_allowed=True, parking_available=True, source="mock"),
    Listing("sv-1", "123 W Washington Ave, Sunnyvale, CA 94086", "Sunnyvale", "CA", "94086", 3500, 2, 2, property_type="Apartment", square_footage=950, status="Active", pets_allowed=True, parking_available=True, source="mock"),
]


class MockListingProvider(ListingProvider):
    def __init__(self, listings: list[Listing] | None = None):
        self._listings = list(listings or MOCK_LISTINGS)

    def search(self, requirements: SearchRequirements) -> list[Listing]:
        return [
            listing
            for listing in self._listings
            if listing.city.casefold() == requirements.city.casefold()
            and listing.state.upper() == requirements.state.upper()
        ][: requirements.limit]

    def get_listing(self, listing_id: str) -> Listing:
        for listing in self._listings:
            if listing.id == listing_id:
                return listing
        raise KeyError(f"Listing not found: {listing_id}")

    def health(self) -> dict[str, object]:
        return {"ok": True, "provider": "mock", "listing_count": len(self._listings)}

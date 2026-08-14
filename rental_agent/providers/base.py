from __future__ import annotations

from abc import ABC, abstractmethod

from rental_agent.models import Listing, SearchRequirements


class ListingProvider(ABC):
    @abstractmethod
    def search(self, requirements: SearchRequirements) -> list[Listing]:
        raise NotImplementedError

    @abstractmethod
    def get_listing(self, listing_id: str) -> Listing:
        raise NotImplementedError

    def get_changes(self) -> list[Listing]:
        """Reserved provider seam; change monitoring is outside this MVP."""
        raise NotImplementedError("Change monitoring is outside the MVP scope")

    @abstractmethod
    def health(self) -> dict[str, object]:
        raise NotImplementedError

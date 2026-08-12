from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

from rental_agent.providers.base import ListingProvider
from rental_agent.providers.mock import MockListingProvider
from rental_agent.providers.realtyapi import RealtyApiProvider

load_dotenv()


@lru_cache(maxsize=1)
def get_provider() -> ListingProvider:
    mode = os.getenv("LISTING_PROVIDER", "mock").strip().lower()
    if mode == "mock":
        return MockListingProvider()
    if mode == "realtyapi":
        api_key = os.getenv("REALTYAPI_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "LISTING_PROVIDER=realtyapi was requested, but REALTYAPI_API_KEY is missing."
            )
        return RealtyApiProvider(api_key=api_key)
    if mode == "rentcast":
        raise RuntimeError(
            "RentCast provider was replaced by RealtyAPI. Run scripts/setup_keys.ps1 "
            "after creating a RealtyAPI key."
        )
    raise RuntimeError(
        f"Unsupported LISTING_PROVIDER={mode!r}; expected 'mock' or 'realtyapi'."
    )


__all__ = ["ListingProvider", "MockListingProvider", "RealtyApiProvider", "get_provider"]

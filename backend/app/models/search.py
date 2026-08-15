from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SourcePostingResponse(BaseModel):
    id: str
    source: str | None = None
    label: str | None = None
    url: str | None = None
    price: float | None = None
    bedrooms: float | None = None
    bathrooms: float | None = None


class ListingResponse(BaseModel):
    id: str
    title: str | None = None
    address: str | None = None
    price: float | None = None
    bedrooms: float | None = None
    bathrooms: float | None = None
    url: str | None = None
    score: float | None = None
    reason: str | None = None
    rank: int | None = None
    sourcePostings: list[SourcePostingResponse] = Field(default_factory=list)


class SearchRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversationId: str | None = Field(default=None, max_length=128)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message must not be blank")
        return normalized

    @field_validator("conversationId")
    @classmethod
    def normalize_conversation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SearchResponse(BaseModel):
    conversationId: str
    message: str
    listings: list[ListingResponse] = Field(default_factory=list)
    mode: Literal["adk", "stub"]

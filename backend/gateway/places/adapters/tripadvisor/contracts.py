from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TripadvisorName(BaseModel):
    model_config = ConfigDict(extra="ignore")
    language: str | None = None
    primary: bool = False
    value: str = ""


class TripadvisorAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")
    city: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    formatted: str | None = None
    postal_code: str | None = None
    state: str | None = None
    street_address: str | None = None
    street_address2: str | None = None


class TripadvisorCoordinates(BaseModel):
    model_config = ConfigDict(extra="ignore")
    latitude: float | None = None
    longitude: float | None = None


class TripadvisorRating(BaseModel):
    model_config = ConfigDict(extra="ignore")
    count: int | None = None
    rating: float | None = None
    icon_url: str | None = None


class TripadvisorUrls(BaseModel):
    model_config = ConfigDict(extra="ignore")
    official: str | None = None
    tripadvisor: str | None = None
    menu: str | None = None


class TripadvisorCategory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    display_name: str | None = None
    top_level_category: str | None = None


class TripadvisorLocation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int | str
    geo: str | None = None
    geo_id: int | None = None
    names: list[TripadvisorName] = Field(default_factory=list)
    descriptions: list[dict[str, Any]] = Field(default_factory=list)
    addresses: list[TripadvisorAddress] = Field(default_factory=list)
    coordinates: TripadvisorCoordinates | None = None
    overall_rating: TripadvisorRating | None = None
    urls: TripadvisorUrls | None = None
    categories: list[TripadvisorCategory] = Field(default_factory=list)
    price_level: str | None = None


class TripadvisorSearchResultItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    location: TripadvisorLocation
    matched_value: str | None = None


class TripadvisorPagination(BaseModel):
    model_config = ConfigDict(extra="ignore")
    page: int = 1
    size: int = 20
    total_elements: int | None = None
    total_pages: int | None = None


class TripadvisorSearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: list[TripadvisorSearchResultItem] = Field(default_factory=list)
    pagination: TripadvisorPagination | None = None


class TripadvisorErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str | None = None
    title: str | None = None
    status: int | None = None
    detail: str | None = None
    trace_id: str | None = None

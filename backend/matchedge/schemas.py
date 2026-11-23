"""Request bodies for the API."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .timeutil import local_input_to_utc


class OverrideIn(BaseModel):
    kickoff_local: str | None = None
    status: Literal["scheduled", "postponed", "cancelled", "abandoned"] | None = None
    verified: bool = False
    verification_url: str | None = None
    note: str | None = None

    @field_validator("kickoff_local")
    @classmethod
    def _ko(cls, v):
        if v:
            local_input_to_utc(v)
        return v or None


class OddsIn(BaseModel):
    match_id: str
    bookmaker: str = Field(min_length=1, max_length=40)
    market: str
    selection: str
    line: float | None = None
    odds: float = Field(gt=1.0, lt=1000)
    checked_at: str | None = None  # local time 'YYYY-MM-DD HH:MM' (Europe/Belgrade) or ISO
    note: str | None = Field(default=None, max_length=300)


class ResearchIn(BaseModel):
    match_id: str
    url: str | None = None
    category: Literal["statistics", "lineup", "injury", "news", "referee", "weather", "other"] = "statistics"
    statistic: str | None = Field(default=None, max_length=300)
    value: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=4000)
    checked_at: str | None = None
    reliability: Literal["high", "medium", "low"] = "medium"
    impact: Literal["supports", "contradicts", "neutral"] = "neutral"
    related_market: str | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        if v and not re.match(r"^https?://", v.strip()):
            raise ValueError("URL must start with http:// or https://")
        return v.strip() if v else None


class LegRef(BaseModel):
    match_id: str
    key: str


class EvalIn(BaseModel):
    legs: list[LegRef]
    target: float | None = None


class BuildIn(BaseModel):
    date_from: str
    date_to: str | None = None
    target: float = Field(default=110.0, gt=1.0, le=100000)
    competitions: list[str] | None = None
    max_legs: int | None = Field(default=None, ge=1, le=30)
    legs: list[LegRef] | None = None
    ai: bool = False


class SaveIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    legs: list[LegRef]
    target: float | None = None
    kind: Literal["main", "alternative", "manual"] = "manual"
    report: dict | None = None


class SettleIn(BaseModel):
    status: Literal["won", "lost", "void", "half_won", "half_lost", "pending"]
    note: str | None = None


class AliasIn(BaseModel):
    alias_name: str
    target_team_id: str

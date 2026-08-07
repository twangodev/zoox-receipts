from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Ride:
    date: str
    canceled: bool
    start: str
    end: str
    started_at: str | None
    ended_at: str | None
    distance_miles: float
    duration_minutes: int
    price_usd: float

    @property
    def id(self) -> str:
        identity = json.dumps(
            {
                "date": self.date,
                "canceled": self.canceled,
                "start": self.start,
                "end": self.end,
                "startedAt": self.started_at,
                "endedAt": self.ended_at,
                "distanceMiles": self.distance_miles,
                "durationMinutes": self.duration_minutes,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return f"ride_{hashlib.sha256(identity.encode()).hexdigest()[:20]}"

    def as_dict(self) -> dict[str, str | float | int | bool | None]:
        return {
            "id": self.id,
            "date": self.date,
            "canceled": self.canceled,
            "start": self.start,
            "end": self.end,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "distanceMiles": self.distance_miles,
            "durationMinutes": self.duration_minutes,
            "priceUsd": self.price_usd,
        }

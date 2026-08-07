from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from ..config import RoutingConfig
from ..storage import ArtifactStore
from .candidates import RouteEngine, RoutingError
from .models import RouteCandidate


Progress = Callable[[int, int, str, bool], None]


def ride_id(ride: dict[str, object]) -> str:
    existing = ride.get("id")
    if isinstance(existing, str) and existing:
        return existing
    identity = {
        key: ride.get(key)
        for key in (
            "date",
            "canceled",
            "start",
            "end",
            "startedAt",
            "endedAt",
            "distanceMiles",
            "durationMinutes",
        )
    }
    encoded = json.dumps(identity, separators=(",", ":"), sort_keys=True)
    return f"ride_{hashlib.sha256(encoded.encode()).hexdigest()[:20]}"


def candidate_cache_key(
    ride: dict[str, object],
    graph_id: str,
    config_id: str,
) -> str:
    value = json.dumps(
        {
            "rideId": ride_id(ride),
            "startCoordinate": ride.get("startCoordinate"),
            "endCoordinate": ride.get("endCoordinate"),
            "distanceMiles": ride.get("distanceMiles"),
            "startedAt": ride.get("startedAt"),
            "graphId": graph_id,
            "configId": config_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(value.encode()).hexdigest()


def candidate_sets(
    rides: list[dict[str, object]],
    engine: RouteEngine,
    store: ArtifactStore,
    *,
    graph_id: str,
    config: RoutingConfig,
    progress: Progress | None = None,
) -> tuple[dict[str, list[RouteCandidate]], dict[str, str]]:
    completed = [ride for ride in rides if not bool(ride.get("canceled"))]
    results: dict[str, list[RouteCandidate]] = {}
    skipped: dict[str, str] = {}
    for index, ride in enumerate(completed, start=1):
        current_ride_id = ride_id(ride)
        cache_key = candidate_cache_key(ride, graph_id, config.id)
        cached = store.get_candidates(cache_key)
        from_cache = cached is not None
        try:
            candidates = (
                [RouteCandidate.from_dict(candidate) for candidate in cached]
                if cached is not None
                else engine.candidates_for(ride)
            )
            if cached is None:
                store.put_candidates(
                    cache_key=cache_key,
                    ride_id=current_ride_id,
                    graph_id=graph_id,
                    config_id=config.id,
                    candidates=[candidate.as_dict() for candidate in candidates],
                )
            results[current_ride_id] = candidates
        except RoutingError as error:
            skipped[current_ride_id] = str(error)
        if progress is not None:
            progress(index, len(completed), current_ride_id, from_cache)
    return results, skipped

from __future__ import annotations

import math
from collections import defaultdict
from statistics import median

import networkx as nx

from ..config import RoutingConfig
from .geometry import route_coordinates
from .models import RouteCandidate
from .pipeline import ride_id
from .traffic import period_name


def traffic_scales(
    rides: list[dict[str, object]],
    candidate_sets: dict[str, list[RouteCandidate]],
) -> dict[str, float]:
    ratios: dict[str, list[float]] = defaultdict(list)
    for ride in rides:
        candidates = candidate_sets.get(ride_id(ride), [])
        started_at = ride.get("startedAt")
        if not candidates or not isinstance(started_at, str):
            continue
        observed_distance = float(ride.get("distanceMiles", 0))
        observed_duration = float(ride.get("durationMinutes", 0))
        closest = min(
            candidates,
            key=lambda candidate: abs(candidate.distance_miles - observed_distance),
        )
        if closest.predicted_minutes > 0 and observed_duration > 0:
            ratio = observed_duration / closest.predicted_minutes
            ratios[period_name(started_at)].append(min(2.5, max(0.5, ratio)))
    return {period: median(values) for period, values in ratios.items()}


def candidate_score(
    candidate: RouteCandidate,
    ride: dict[str, object],
    config: RoutingConfig,
    traffic_scale: float,
) -> tuple[float, float]:
    observed_distance = float(ride.get("distanceMiles", 0))
    observed_duration = float(ride.get("durationMinutes", 0))
    predicted_duration = candidate.predicted_minutes * traffic_scale
    distance_uncertainty = max(0.1, observed_distance * 0.05)
    duration_uncertainty = max(1.5, observed_duration * 0.10)
    distance_error = (candidate.distance_miles - observed_distance) / distance_uncertainty
    duration_error = (predicted_duration - observed_duration) / duration_uncertainty
    score = (
        config.scoring.distance_weight * distance_error**2
        + config.scoring.duration_weight * duration_error**2
        + config.scoring.arterial_weight * candidate.arterial_ratio
        - config.scoring.side_street_reward * candidate.side_street_ratio
        + config.scoring.turn_weight * candidate.turn_count
    )
    return score, predicted_duration


def infer_routes(
    rides: list[dict[str, object]],
    candidate_sets: dict[str, list[RouteCandidate]],
    graph: nx.MultiDiGraph,
    *,
    graph_id: str,
    config: RoutingConfig,
    skipped: dict[str, str] | None = None,
) -> dict[str, object]:
    scales = traffic_scales(rides, candidate_sets)
    inferences: list[dict[str, object]] = []
    for ride in rides:
        current_ride_id = ride_id(ride)
        candidates = candidate_sets.get(current_ride_id)
        started_at = ride.get("startedAt")
        if not candidates or not isinstance(started_at, str):
            continue
        period = period_name(started_at)
        scale = scales.get(period, 1.0)
        scored = [
            (*candidate_score(candidate, ride, config, scale), candidate)
            for candidate in candidates
        ]
        minimum = min(score for score, _, _ in scored)
        weights = [
            math.exp(-(score - minimum) / config.scoring.temperature)
            for score, _, _ in scored
        ]
        total = sum(weights)
        ranked = sorted(
            (
                {
                    **candidate.as_dict(),
                    "score": score,
                    "probability": weight / total,
                    "adjustedPredictedMinutes": predicted,
                }
                for (score, predicted, candidate), weight in zip(
                    scored, weights, strict=True
                )
            ),
            key=lambda candidate: float(candidate["probability"]),
            reverse=True,
        )
        best = ranked[0]
        best_edges = tuple(
            (int(edge[0]), int(edge[1]), int(edge[2])) for edge in best["edges"]
        )
        inferences.append(
            {
                "rideId": current_ride_id,
                "confidence": best["probability"],
                "candidateCount": len(ranked),
                "distanceErrorMiles": float(best["distanceMiles"])
                - float(ride.get("distanceMiles", 0)),
                "durationErrorMinutes": float(best["adjustedPredictedMinutes"])
                - float(ride.get("durationMinutes", 0)),
                "route": {
                    "type": "LineString",
                    "coordinates": route_coordinates(graph, best_edges),
                },
                "candidates": ranked,
            }
        )
    return {
        "schemaVersion": 1,
        "graphId": graph_id,
        "configId": config.id,
        "trafficScaleByPeriod": scales,
        "rides": inferences,
        "skipped": skipped or {},
    }

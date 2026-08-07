from __future__ import annotations

from typing import Any

from .pipeline import ride_id


def route_feature_collection(
    rides: list[dict[str, object]],
    inference: dict[str, Any],
) -> dict[str, object]:
    """Return one compact GeoJSON feature for each successfully inferred ride."""
    inferred = inference.get("rides", [])
    if not isinstance(inferred, list):
        raise ValueError("inference document has no rides array")
    results = {
        str(result.get("rideId", "")): result
        for result in inferred
        if isinstance(result, dict)
    }
    skipped = inference.get("skipped", {})
    if not isinstance(skipped, dict):
        skipped = {}

    features: list[dict[str, object]] = []
    route_count = 0
    for receipt in rides:
        current_ride_id = ride_id(receipt)
        result = results.get(current_ride_id)
        canceled = bool(receipt.get("canceled"))
        geometry = result.get("route") if result is not None else None
        if not isinstance(geometry, dict):
            geometry = None
        else:
            route_count += 1
        status = "canceled" if canceled else "inferred" if geometry else "skipped"
        properties = {
            "rideId": current_ride_id,
            "status": status,
            "canceled": canceled,
            "estimated": geometry is not None,
            "date": receipt.get("date"),
            "start": receipt.get("start"),
            "end": receipt.get("end"),
            "startedAt": receipt.get("startedAt"),
            "endedAt": receipt.get("endedAt"),
            "distanceMiles": receipt.get("distanceMiles"),
            "durationMinutes": receipt.get("durationMinutes"),
            "priceUsd": receipt.get("priceUsd"),
            "confidence": result.get("confidence") if result else None,
            "candidateCount": result.get("candidateCount") if result else None,
            "distanceErrorMiles": (
                result.get("distanceErrorMiles") if result else None
            ),
            "durationErrorMinutes": (
                result.get("durationErrorMinutes") if result else None
            ),
        }
        if current_ride_id in skipped:
            properties["skipReason"] = skipped[current_ride_id]
        features.append(
            {
                "type": "Feature",
                "id": current_ride_id,
                "geometry": geometry,
                "properties": properties,
            }
        )

    canceled = sum(bool(ride.get("canceled")) for ride in rides)
    completed = len(rides) - canceled
    return {
        "type": "FeatureCollection",
        "schemaVersion": 1,
        "graphId": inference.get("graphId"),
        "configId": inference.get("configId"),
        "receiptCount": len(rides),
        "completedRideCount": completed,
        "canceledRideCount": canceled,
        "routeCount": route_count,
        "skippedRideCount": len(skipped),
        "trafficScaleByPeriod": inference.get("trafficScaleByPeriod", {}),
        "skipped": skipped,
        "features": features,
    }

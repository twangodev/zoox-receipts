from __future__ import annotations

import ast
from collections import defaultdict
from typing import Any

import networkx as nx

from .geometry import edge_coordinates
from .models import EdgeId


def _osmid(value: object) -> str:
    if isinstance(value, list):
        return ",".join(sorted(str(item) for item in value))
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list):
                return ",".join(sorted(str(item) for item in parsed))
        except (SyntaxError, ValueError):
            pass
    return str(value)


def aggregate_routes(
    inference: dict[str, Any],
    graph: nx.MultiDiGraph,
) -> dict[str, object]:
    weights: dict[tuple[int, int, str], float] = defaultdict(float)
    examples: dict[tuple[int, int, str], EdgeId] = {}
    rides = inference.get("rides", [])
    if not isinstance(rides, list):
        raise ValueError("inference document has no rides array")
    for ride in rides:
        if not isinstance(ride, dict):
            continue
        candidates = ride.get("candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            probability = float(candidate.get("probability", 0))
            edges = candidate.get("edges", [])
            if not isinstance(edges, list):
                continue
            for raw_edge in edges:
                edge = (int(raw_edge[0]), int(raw_edge[1]), int(raw_edge[2]))
                u, v, key = edge
                data = graph[u][v][key]
                identity = (min(u, v), max(u, v), _osmid(data.get("osmid", key)))
                weights[identity] += probability
                examples.setdefault(identity, edge)
    maximum = max(weights.values(), default=1.0)
    features = []
    for identity, weight in sorted(weights.items()):
        edge = examples[identity]
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(point) for point in edge_coordinates(graph, edge)],
                },
                "properties": {
                    "edgeId": f"{identity[0]}:{identity[1]}:{identity[2]}",
                    "expectedRides": weight,
                    "normalizedWeight": weight / maximum,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "schemaVersion": 1,
        "graphId": inference.get("graphId"),
        "rideCount": len(rides),
        "features": features,
    }

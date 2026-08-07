from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EdgeId = tuple[int, int, int]


@dataclass(frozen=True)
class RouteCandidate:
    id: str
    source: str
    nodes: tuple[int, ...]
    edges: tuple[EdgeId, ...]
    distance_miles: float
    predicted_minutes: float
    side_street_ratio: float
    arterial_ratio: float
    turn_count: int
    left_turn_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source": self.source,
            "nodes": list(self.nodes),
            "edges": [list(edge) for edge in self.edges],
            "distanceMiles": self.distance_miles,
            "predictedMinutes": self.predicted_minutes,
            "sideStreetRatio": self.side_street_ratio,
            "arterialRatio": self.arterial_ratio,
            "turnCount": self.turn_count,
            "leftTurnCount": self.left_turn_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RouteCandidate:
        return cls(
            id=str(value["id"]),
            source=str(value["source"]),
            nodes=tuple(int(node) for node in value["nodes"]),
            edges=tuple(
                (int(edge[0]), int(edge[1]), int(edge[2]))
                for edge in value["edges"]
            ),
            distance_miles=float(value["distanceMiles"]),
            predicted_minutes=float(value["predictedMinutes"]),
            side_street_ratio=float(value["sideStreetRatio"]),
            arterial_ratio=float(value["arterialRatio"]),
            turn_count=int(value["turnCount"]),
            left_turn_count=int(value["leftTurnCount"]),
        )

from __future__ import annotations

import math
from collections.abc import Iterable

import networkx as nx

from .models import EdgeId


Coordinate = tuple[float, float]


def edge_coordinates(graph: nx.MultiDiGraph, edge: EdgeId) -> list[Coordinate]:
    u, v, key = edge
    data = graph[u][v][key]
    geometry = data.get("geometry")
    if geometry is None:
        return [
            (float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"])),
            (float(graph.nodes[v]["x"]), float(graph.nodes[v]["y"])),
        ]
    coordinates = [(float(x), float(y)) for x, y in geometry.coords]
    origin = (float(graph.nodes[u]["x"]), float(graph.nodes[u]["y"]))
    if _distance(coordinates[-1], origin) < _distance(coordinates[0], origin):
        coordinates.reverse()
    return coordinates


def route_coordinates(
    graph: nx.MultiDiGraph,
    edges: Iterable[EdgeId],
) -> list[list[float]]:
    coordinates: list[Coordinate] = []
    for edge in edges:
        segment = edge_coordinates(graph, edge)
        if coordinates and segment[0] == coordinates[-1]:
            coordinates.extend(segment[1:])
        else:
            coordinates.extend(segment)
    return [[longitude, latitude] for longitude, latitude in coordinates]


def _distance(first: Coordinate, second: Coordinate) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])

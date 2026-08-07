from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable

import networkx as nx
import numpy as np
import osmnx as ox

from ..config import RoutingConfig, ServiceAreaConfig
from .models import EdgeId, RouteCandidate
from .traffic import ARTERIAL_TYPES, SIDE_STREET_TYPES, apply_typical_traffic, highway_types


METERS_PER_MILE = 1609.344


class RoutingError(ValueError):
    pass


def in_service_area(
    longitude: float,
    latitude: float,
    config: ServiceAreaConfig,
) -> bool:
    return (
        not config.enabled
        or longitude >= config.west_longitude
        and latitude >= config.south_latitude
    )


def service_area_graph(
    graph: nx.MultiDiGraph,
    config: ServiceAreaConfig,
) -> nx.MultiDiGraph:
    if not config.enabled:
        return graph
    nodes = [
        node
        for node, data in graph.nodes(data=True)
        if in_service_area(float(data["x"]), float(data["y"]), config)
    ]
    constrained = graph.subgraph(nodes).copy()
    if not constrained:
        raise RoutingError("configured service area contains no routing nodes")
    return constrained


class NodeIndex:
    def __init__(self, graph: nx.MultiDiGraph) -> None:
        self.node_ids = np.fromiter(graph.nodes, dtype=np.int64)
        self.longitudes = np.fromiter(
            (float(graph.nodes[node]["x"]) for node in self.node_ids),
            dtype=np.float64,
        )
        self.latitudes = np.fromiter(
            (float(graph.nodes[node]["y"]) for node in self.node_ids),
            dtype=np.float64,
        )

    def nearest(self, longitude: float, latitude: float) -> int:
        longitude_scale = math.cos(math.radians(latitude))
        distances = (
            ((self.longitudes - longitude) * longitude_scale) ** 2
            + (self.latitudes - latitude) ** 2
        )
        return int(self.node_ids[int(np.argmin(distances))])


def selected_edges(
    graph: nx.MultiDiGraph,
    nodes: Iterable[int],
    weight: str,
) -> tuple[EdgeId, ...]:
    route = tuple(nodes)
    edges: list[EdgeId] = []
    for u, v in zip(route, route[1:], strict=False):
        options = graph[u][v]
        key = min(
            options,
            key=lambda candidate: float(options[candidate].get(weight, math.inf)),
        )
        edges.append((int(u), int(v), int(key)))
    return tuple(edges)


def turn_counts(graph: nx.MultiDiGraph, nodes: tuple[int, ...]) -> tuple[int, int]:
    turns = 0
    left_turns = 0
    for first, middle, last in zip(nodes, nodes[1:], nodes[2:], strict=False):
        x1 = float(graph.nodes[middle]["x"]) - float(graph.nodes[first]["x"])
        y1 = float(graph.nodes[middle]["y"]) - float(graph.nodes[first]["y"])
        x2 = float(graph.nodes[last]["x"]) - float(graph.nodes[middle]["x"])
        y2 = float(graph.nodes[last]["y"]) - float(graph.nodes[middle]["y"])
        angle = math.degrees(math.atan2(x1 * y2 - y1 * x2, x1 * x2 + y1 * y2))
        if abs(angle) >= 30:
            turns += 1
            if angle > 0:
                left_turns += 1
    return turns, left_turns


def route_candidate(
    graph: nx.MultiDiGraph,
    nodes: tuple[int, ...],
    *,
    source: str,
    weight: str,
    config: RoutingConfig,
) -> RouteCandidate:
    edges = selected_edges(graph, nodes, weight)
    length = 0.0
    predicted_seconds = 0.0
    side_length = 0.0
    arterial_length = 0.0
    for u, v, key in edges:
        data = graph[u][v][key]
        edge_length = float(data.get("length", 0))
        length += edge_length
        predicted_seconds += float(data.get("typical_time", data.get("travel_time", 0)))
        road_types = highway_types(data.get("highway"))
        if road_types & SIDE_STREET_TYPES:
            side_length += edge_length
        if road_types & ARTERIAL_TYPES:
            arterial_length += edge_length
    turns, left_turns = turn_counts(graph, nodes)
    predicted_seconds += left_turns * config.traffic.left_turn_delay_seconds
    identity = ";".join(f"{u}:{v}:{key}" for u, v, key in edges)
    return RouteCandidate(
        id=f"route_{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        source=source,
        nodes=nodes,
        edges=edges,
        distance_miles=length / METERS_PER_MILE,
        predicted_minutes=predicted_seconds / 60,
        side_street_ratio=side_length / length if length else 0,
        arterial_ratio=arterial_length / length if length else 0,
        turn_count=turns,
        left_turn_count=left_turns,
    )


def target_distance_candidates(
    graph: nx.MultiDiGraph,
    origin: int,
    destination: int,
    target_miles: float,
    count: int,
    config: RoutingConfig,
) -> list[RouteCandidate]:
    """Build deterministic detours whose lengths approach the receipt mileage."""
    forward_distances, forward_paths = nx.single_source_dijkstra(
        graph,
        origin,
        weight="length",
    )
    reverse_distances, reverse_paths = nx.single_source_dijkstra(
        graph.reverse(copy=False),
        destination,
        weight="length",
    )
    target_meters = target_miles * METERS_PER_MILE
    waypoints = sorted(
        forward_distances.keys() & reverse_distances.keys(),
        key=lambda node: (
            abs(
                float(forward_distances[node])
                + float(reverse_distances[node])
                - target_meters
            ),
            int(node),
        ),
    )
    candidates: dict[str, RouteCandidate] = {}
    for waypoint in waypoints:
        first = tuple(int(node) for node in forward_paths[waypoint])
        second = tuple(int(node) for node in reversed(reverse_paths[waypoint]))
        nodes = first + second[1:]
        if len(nodes) < 2 or len(nodes) != len(set(nodes)):
            continue
        candidate = route_candidate(
            graph,
            nodes,
            source="target-distance",
            weight="length",
            config=config,
        )
        candidates.setdefault(candidate.id, candidate)
        if len(candidates) >= count:
            break
    return list(candidates.values())


class RouteEngine:
    def __init__(self, graph: nx.MultiDiGraph, config: RoutingConfig) -> None:
        self.graph = service_area_graph(graph, config.service_area)
        self.config = config
        self.node_index = NodeIndex(self.graph)

    def candidates_for(self, ride: dict[str, object]) -> list[RouteCandidate]:
        if bool(ride.get("canceled")):
            return []
        started_at = ride.get("startedAt")
        start = ride.get("startCoordinate")
        end = ride.get("endCoordinate")
        if not isinstance(started_at, str):
            raise RoutingError("completed ride has no start timestamp")
        if not _coordinate(start) or not _coordinate(end):
            raise RoutingError("completed ride has unresolved endpoint coordinates")
        if not in_service_area(float(start[0]), float(start[1]), self.config.service_area):
            raise RoutingError("pickup is outside the configured Zoox service area")
        if not in_service_area(float(end[0]), float(end[1]), self.config.service_area):
            raise RoutingError("drop-off is outside the configured Zoox service area")
        apply_typical_traffic(self.graph, started_at, self.config.traffic)
        origin = self.node_index.nearest(float(start[0]), float(start[1]))
        destination = self.node_index.nearest(float(end[0]), float(end[1]))
        if origin == destination:
            raise RoutingError("ride endpoints snap to the same routing node")

        observed_distance = float(ride.get("distanceMiles", 0))
        candidates: dict[str, RouteCandidate] = {}
        profiles = (
            ("distance", "length", self.config.candidates.distance_paths),
            ("typical-time", "typical_time", self.config.candidates.travel_time_paths),
        )
        for source, weight, count in profiles:
            try:
                paths = ox.routing.k_shortest_paths(
                    self.graph,
                    origin,
                    destination,
                    count,
                    weight=weight,
                )
                for path in paths:
                    candidate = route_candidate(
                        self.graph,
                        tuple(path),
                        source=source,
                        weight=weight,
                        config=self.config,
                    )
                    candidates.setdefault(candidate.id, candidate)
            except nx.NetworkXNoPath:
                continue

        try:
            for candidate in target_distance_candidates(
                self.graph,
                origin,
                destination,
                observed_distance,
                self.config.candidates.target_distance_paths,
                self.config,
            ):
                candidates.setdefault(candidate.id, candidate)
        except nx.NetworkXNoPath:
            pass

        if not candidates:
            raise RoutingError("routing graph found no candidate paths")
        maximum_error = max(
            self.config.candidates.maximum_distance_error_miles,
            observed_distance * self.config.candidates.maximum_distance_error_ratio,
        )
        filtered = [
            candidate
            for candidate in candidates.values()
            if abs(candidate.distance_miles - observed_distance) <= maximum_error
        ]
        return sorted(
            filtered or candidates.values(),
            key=lambda candidate: (
                abs(candidate.distance_miles - observed_distance),
                candidate.predicted_minutes,
            ),
        )


def _coordinate(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, int | float) for item in value)
    )

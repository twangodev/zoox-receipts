from __future__ import annotations

import ast
from datetime import datetime

import networkx as nx

from ..config import TrafficConfig


ARTERIAL_TYPES = {"motorway", "trunk", "primary", "secondary"}
SIDE_STREET_TYPES = {"living_street", "residential", "service", "unclassified"}


def highway_types(value: object) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value}
    if isinstance(value, str):
        if value.startswith("["):
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return {str(item) for item in parsed}
            except (SyntaxError, ValueError):
                pass
        return {value}
    return set()


def period_multiplier(started_at: str, config: TrafficConfig) -> float:
    local_time = datetime.fromisoformat(started_at)
    hour = local_time.hour + local_time.minute / 60
    if hour < 6 or hour >= 22:
        return config.night_multiplier
    if local_time.weekday() < 5:
        if 7 <= hour < 10 or 16 <= hour < 19:
            return config.weekday_peak_multiplier
        return config.weekday_day_multiplier
    return config.weekend_day_multiplier


def period_name(started_at: str) -> str:
    local_time = datetime.fromisoformat(started_at)
    hour = local_time.hour + local_time.minute / 60
    if hour < 6 or hour >= 22:
        return "night"
    if local_time.weekday() >= 5:
        return "weekend-day"
    if 7 <= hour < 10 or 16 <= hour < 19:
        return "weekday-peak"
    return "weekday-day"


def apply_typical_traffic(
    graph: nx.MultiDiGraph,
    started_at: str,
    config: TrafficConfig,
) -> None:
    period = period_multiplier(started_at, config)
    for u, v, key, data in graph.edges(keys=True, data=True):
        road_types = highway_types(data.get("highway"))
        if road_types & ARTERIAL_TYPES:
            congestion_factor = config.arterial_congestion_factor
        elif road_types & SIDE_STREET_TYPES:
            congestion_factor = config.side_street_congestion_factor
        else:
            congestion_factor = 1.0
        multiplier = 1 + (period - 1) * congestion_factor
        signal_delay = (
            config.signal_delay_seconds
            if graph.nodes[v].get("highway") == "traffic_signals"
            else 0.0
        )
        data["typical_time"] = float(data.get("travel_time", 0)) * multiplier + signal_delay

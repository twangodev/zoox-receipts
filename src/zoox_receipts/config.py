from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class NetworkConfig:
    region: str = "San Francisco, California, USA"
    network_type: str = "drive"
    graph_path: str = ".zooxr/san-francisco.graphml"


@dataclass(frozen=True)
class CandidateConfig:
    distance_paths: int = 8
    travel_time_paths: int = 12
    target_distance_paths: int = 12
    maximum_distance_error_ratio: float = 0.35
    maximum_distance_error_miles: float = 0.35


@dataclass(frozen=True)
class TrafficConfig:
    weekday_peak_multiplier: float = 1.45
    weekday_day_multiplier: float = 1.20
    weekend_day_multiplier: float = 1.10
    night_multiplier: float = 1.0
    arterial_congestion_factor: float = 1.20
    side_street_congestion_factor: float = 0.75
    signal_delay_seconds: float = 18.0
    left_turn_delay_seconds: float = 10.0


@dataclass(frozen=True)
class ScoringConfig:
    distance_weight: float = 4.0
    duration_weight: float = 2.0
    arterial_weight: float = 0.25
    side_street_reward: float = 0.15
    turn_weight: float = 0.05
    temperature: float = 0.35


@dataclass(frozen=True)
class RoutingConfig:
    schema_version: int = 1
    network: NetworkConfig = NetworkConfig()
    candidates: CandidateConfig = CandidateConfig()
    traffic: TrafficConfig = TrafficConfig()
    scoring: ScoringConfig = ScoringConfig()

    @property
    def id(self) -> str:
        value = json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(value.encode()).hexdigest()[:20]


def load_config(path: Path | None = None) -> RoutingConfig:
    if path is None:
        return RoutingConfig()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        config = RoutingConfig(
            schema_version=data.get("schema_version", 1),
            network=NetworkConfig(**data.get("network", {})),
            candidates=CandidateConfig(**data.get("candidates", {})),
            traffic=TrafficConfig(**data.get("traffic", {})),
            scoring=ScoringConfig(**data.get("scoring", {})),
        )
    except (OSError, tomllib.TOMLDecodeError, TypeError) as error:
        raise ConfigError(f"could not load {path}: {error}") from error
    if config.schema_version != 1:
        raise ConfigError(
            f"unsupported configuration schema version {config.schema_version}"
        )
    if (
        config.candidates.distance_paths < 1
        or config.candidates.travel_time_paths < 1
        or config.candidates.target_distance_paths < 1
    ):
        raise ConfigError("candidate path counts must be positive")
    if config.scoring.temperature <= 0:
        raise ConfigError("scoring temperature must be positive")
    return config

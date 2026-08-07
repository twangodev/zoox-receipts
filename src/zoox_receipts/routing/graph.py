from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import osmnx as ox

from ..config import NetworkConfig


@dataclass(frozen=True)
class GraphMetadata:
    id: str
    region: str
    network_type: str
    nodes: int
    edges: int
    built_at: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()[:20]


def metadata_path(path: Path) -> Path:
    return path.with_suffix(f"{path.suffix}.json")


def build_graph(config: NetworkConfig, output: Path) -> GraphMetadata:
    output.parent.mkdir(parents=True, exist_ok=True)
    ox.settings.cache_folder = output.parent / "osmnx-cache"
    graph = ox.graph.graph_from_place(
        config.region,
        network_type=config.network_type,
        simplify=True,
        retain_all=False,
    )
    graph = ox.routing.add_edge_speeds(graph, fallback=25.0)
    graph = ox.routing.add_edge_travel_times(graph)
    graph = ox.bearing.add_edge_bearings(graph)
    ox.io.save_graphml(graph, output)
    metadata = GraphMetadata(
        id=file_hash(output),
        region=config.region,
        network_type=config.network_type,
        nodes=graph.number_of_nodes(),
        edges=graph.number_of_edges(),
        built_at=datetime.now(UTC).isoformat(),
    )
    metadata_path(output).write_text(
        json.dumps(metadata.as_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def load_graph(path: Path) -> tuple[nx.MultiDiGraph, GraphMetadata]:
    if not path.exists():
        raise FileNotFoundError(f"routing graph does not exist: {path}")
    graph = ox.io.load_graphml(path)
    sidecar = metadata_path(path)
    if sidecar.exists():
        value = json.loads(sidecar.read_text(encoding="utf-8"))
        metadata = GraphMetadata(
            id=file_hash(path),
            region=str(value["region"]),
            network_type=str(value["network_type"]),
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
            built_at=str(value["built_at"]),
        )
    else:
        metadata = GraphMetadata(
            id=file_hash(path),
            region=str(graph.graph.get("name", "unknown")),
            network_type="unknown",
            nodes=graph.number_of_nodes(),
            edges=graph.number_of_edges(),
            built_at="unknown",
        )
    return graph, metadata

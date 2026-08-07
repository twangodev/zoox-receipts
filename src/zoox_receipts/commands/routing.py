from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from ..config import ConfigError, RoutingConfig, load_config
from ..geocoding import load_rides
from ..output import emit_json
from ..routing.aggregate import aggregate_routes
from ..routing.candidates import RouteEngine
from ..routing.graph import build_graph, load_graph
from ..routing.inference import infer_routes
from ..routing.pipeline import candidate_sets
from ..storage import ArtifactStore, StorageError


def _config(path: Path | None) -> RoutingConfig:
    if path is not None:
        return load_config(path)
    default = Path("zooxr.toml")
    return load_config(default) if default.exists() else load_config()


def build_network(
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Routing TOML; defaults to ./zooxr.toml when present.",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="GraphML output; defaults to the configured graph path.",
        ),
    ] = None,
) -> None:
    """Download and cache the configured OpenStreetMap driving graph."""
    try:
        config = _config(config_path)
        graph_path = output or Path(config.network.graph_path)
        metadata = build_graph(config.network, graph_path)
        typer.echo(
            f"Built {metadata.region}: {metadata.nodes} nodes, "
            f"{metadata.edges} edges, graph {metadata.id}."
        )
    except (ConfigError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error


def infer(
    rides: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Geocoded ride JSON to infer.",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Write probabilistic route inference JSON here.",
        ),
    ] = Path("routes.json"),
    graph_path: Annotated[
        Path | None,
        typer.Option(
            "--graph",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Cached GraphML; defaults to the configured graph path.",
        ),
    ] = None,
    state: Annotated[
        Path,
        typer.Option(
            "--state",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Resumable SQLite candidate cache.",
        ),
    ] = Path(".zooxr/state.sqlite3"),
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Routing TOML; defaults to ./zooxr.toml when present.",
        ),
    ] = None,
) -> None:
    """Infer probable routes from receipt mileage, duration, and local time."""
    try:
        config = _config(config_path)
        selected_graph_path = graph_path or Path(config.network.graph_path)
        graph, metadata = load_graph(selected_graph_path)
        ride_values = load_rides(rides)
        engine = RouteEngine(graph, config)

        def progress(index: int, total: int, _: str, cached: bool) -> None:
            if index == total or index % 10 == 0:
                source = "cache" if cached else "computed"
                typer.echo(f"Candidates: {index}/{total} ({source}).", err=True)

        with ArtifactStore(state) as store:
            candidates, skipped = candidate_sets(
                ride_values,
                engine,
                store,
                graph_id=metadata.id,
                config=config,
                progress=progress,
            )
        result = infer_routes(
            ride_values,
            candidates,
            graph,
            graph_id=metadata.id,
            config=config,
            skipped=skipped,
        )
        emit_json(result, output)
        typer.echo(
            f"Inferred {len(result['rides'])} rides; skipped {len(skipped)}.",
            err=True,
        )
    except (ConfigError, OSError, StorageError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error


def aggregate(
    routes: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Probabilistic route inference JSON.",
        ),
    ],
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Write aggregate block-weight GeoJSON here.",
        ),
    ] = Path("route-usage.geojson"),
    graph_path: Annotated[
        Path | None,
        typer.Option(
            "--graph",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Cached GraphML; defaults to the configured graph path.",
        ),
    ] = None,
    config_path: Annotated[
        Path | None,
        typer.Option(
            "--config",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Routing TOML; defaults to ./zooxr.toml when present.",
        ),
    ] = None,
) -> None:
    """Aggregate candidate probabilities into expected per-block ride usage."""
    try:
        config = _config(config_path)
        selected_graph_path = graph_path or Path(config.network.graph_path)
        graph, metadata = load_graph(selected_graph_path)
        value: Any = json.loads(routes.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("route inference must be a JSON object")
        if value.get("graphId") != metadata.id:
            raise ValueError("route inference graph does not match the selected graph")
        result = aggregate_routes(value, graph)
        emit_json(result, output)
        typer.echo(
            f"Aggregated {result['rideCount']} rides across "
            f"{len(result['features'])} street edges.",
            err=True,
        )
    except (ConfigError, json.JSONDecodeError, OSError, ValueError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

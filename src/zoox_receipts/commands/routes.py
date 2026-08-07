from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Annotated

import httpx
import typer
from geopy.exc import GeopyError

from ..config import ConfigError
from ..datasf import DataSfAddressIndex, DataSfError, sync_datasf_addresses
from ..geocoding import GeocodingError, geocode_rides
from ..output import emit_json
from ..receipts import ReceiptParseError, extract_rides
from ..routing.candidates import RouteEngine
from ..routing.geojson import route_feature_collection
from ..routing.graph import build_graph, load_graph
from ..routing.inference import infer_routes
from ..routing.pipeline import candidate_sets
from ..storage import ArtifactStore, StorageError
from .routing import _config


def export_routes(
    takeout: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Gmail Takeout ZIP or MBOX to convert directly to GeoJSON.",
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
            help="Write the route FeatureCollection here.",
        ),
    ] = Path("routes.geojson"),
    cache_dir: Annotated[
        Path,
        typer.Option(
            "--cache-dir",
            file_okay=False,
            dir_okay=True,
            resolve_path=True,
            help="Internal reusable data; never required as user-facing output.",
        ),
    ] = Path(".zooxr"),
    graph_path: Annotated[
        Path | None,
        typer.Option(
            "--graph",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Use this GraphML instead of the configured cached graph.",
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
    """Convert a Takeout archive directly into per-ride route GeoJSON."""
    try:
        config = _config(config_path)
        cache_dir.mkdir(parents=True, exist_ok=True)
        datasf_path = cache_dir / "datasf-addresses.jsonl"
        geocoding_cache = cache_dir / "geocoding-cache.json"
        state_path = cache_dir / "state.sqlite3"
        selected_graph_path = graph_path or Path(config.network.graph_path)

        if not datasf_path.exists():
            typer.echo("Caching San Francisco address points...", err=True)
            sync_datasf_addresses(datasf_path)
        if not selected_graph_path.exists():
            typer.echo("Building the San Francisco driving graph...", err=True)
            build_graph(config.network, selected_graph_path)

        ride_values = [ride.as_dict() for ride in extract_rides(takeout)]
        datasf = DataSfAddressIndex.from_path(datasf_path)
        geocoded, stats = geocode_rides(
            ride_values,
            geocoding_cache,
            local_geocode=datasf.geocode,
        )
        typer.echo(
            f"Geocoded {stats.address_matches + stats.street_matches} endpoints; "
            f"{stats.unresolved} unresolved.",
            err=True,
        )

        graph, metadata = load_graph(selected_graph_path)
        engine = RouteEngine(graph, config)

        def progress(index: int, total: int, _: str, cached: bool) -> None:
            if index == total or index % 10 == 0:
                source = "cache" if cached else "computed"
                typer.echo(f"Routes: {index}/{total} ({source}).", err=True)

        with ArtifactStore(state_path) as store:
            candidates, skipped = candidate_sets(
                geocoded,
                engine,
                store,
                graph_id=metadata.id,
                config=config,
                progress=progress,
            )
        inference = infer_routes(
            geocoded,
            candidates,
            graph,
            graph_id=metadata.id,
            config=config,
            skipped=skipped,
        )
        geojson = route_feature_collection(geocoded, inference)
        emit_json(geojson, output)
        typer.echo(
            f"Wrote {geojson['routeCount']} routes to {output}; "
            f"skipped {geojson['skippedRideCount']}.",
            err=True,
        )
    except (
        ConfigError,
        DataSfError,
        GeocodingError,
        GeopyError,
        ReceiptParseError,
        StorageError,
        httpx.HTTPError,
        OSError,
        ValueError,
        zipfile.BadZipFile,
    ) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import httpx
import typer
from geopy.exc import GeopyError

from ..datasf import DataSfAddressIndex, DataSfError, sync_datasf_addresses
from ..geocoding import GeocodingError, cache_path_for, geocode_rides, load_rides
from ..output import emit_json


def geocode(
    rides: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="JSON ride export to geocode.",
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Write enriched JSON to this file instead of standard output.",
        ),
    ] = None,
    cache: Annotated[
        Path | None,
        typer.Option(
            "--cache",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Geocoding result cache; defaults next to the input file.",
        ),
    ] = None,
    delay_seconds: Annotated[
        float,
        typer.Option(
            "--delay-seconds",
            min=0.0,
            help="Minimum delay between public Photon requests.",
        ),
    ] = 1.0,
    datasf_cache: Annotated[
        Path,
        typer.Option(
            "--datasf-cache",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Local DataSF address cache used before Photon.",
        ),
    ] = Path(".zooxr/datasf-addresses.jsonl"),
) -> None:
    """Add start and end coordinates using DataSF and public Photon."""
    cache_path = cache or cache_path_for(rides)
    try:
        datasf = (
            DataSfAddressIndex.from_path(datasf_cache)
            if datasf_cache.exists()
            else None
        )
        enriched, stats = geocode_rides(
            load_rides(rides),
            cache_path,
            min_delay_seconds=delay_seconds,
            local_geocode=datasf.geocode if datasf else None,
        )
        emit_json(enriched, output)
        typer.echo(
            f"Geocoding: {stats.cached} cached, {stats.resolved}/{stats.queried} "
            f"newly resolved, {stats.unresolved} unresolved; "
            f"{stats.address_matches} address-level and "
            f"{stats.street_matches} street-level matches; "
            f"{stats.datasf_matches} from DataSF.",
            err=True,
        )
    except (DataSfError, GeocodingError, GeopyError, OSError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error


def sync_addresses(
    output: Annotated[
        Path,
        typer.Option(
            "--output",
            "-o",
            file_okay=True,
            dir_okay=False,
            resolve_path=True,
            help="Write the local DataSF address cache here.",
        ),
    ] = Path(".zooxr/datasf-addresses.jsonl"),
) -> None:
    """Download San Francisco's public address-point dataset."""
    try:
        count = sync_datasf_addresses(output)
        typer.echo(f"Cached {count} DataSF address points in {output}.")
    except (DataSfError, httpx.HTTPError, OSError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

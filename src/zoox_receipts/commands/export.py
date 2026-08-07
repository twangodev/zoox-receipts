from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Annotated

import typer

from ..output import emit_json
from ..receipts import ReceiptParseError, extract_rides


def export_rides(
    takeout: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Gmail Takeout ZIP or MBOX to read.",
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
            help="Write JSON to this file instead of standard output.",
        ),
    ] = None,
) -> None:
    """Export Zoox ride receipts as structured JSON."""
    try:
        rides = extract_rides(takeout)
        emit_json([ride.as_dict() for ride in rides], output)
    except (OSError, ReceiptParseError, ValueError, zipfile.BadZipFile) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error

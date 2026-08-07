from __future__ import annotations

import typer

from .commands.export import export_rides
from .commands.geocode import geocode, sync_addresses


app = typer.Typer(
    add_completion=False,
    help="Export and geocode Zoox rides from Gmail Takeout.",
    name="zooxr",
    no_args_is_help=True,
)
data_app = typer.Typer(help="Download public reference datasets.", no_args_is_help=True)

app.command("export")(export_rides)
app.command("geocode")(geocode)
data_app.command("sync-addresses")(sync_addresses)
app.add_typer(data_app, name="data")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

from __future__ import annotations

import typer

from .commands.export import export_rides
from .commands.geocode import geocode, sync_addresses
from .commands.routing import aggregate, build_network, infer


app = typer.Typer(
    add_completion=False,
    help="Export, geocode, and infer Zoox ride routes.",
    name="zooxr",
    no_args_is_help=True,
)
data_app = typer.Typer(help="Download public reference datasets.", no_args_is_help=True)
network_app = typer.Typer(help="Build and inspect routing networks.", no_args_is_help=True)

app.command("export")(export_rides)
app.command("geocode")(geocode)
app.command("infer")(infer)
app.command("aggregate")(aggregate)
data_app.command("sync-addresses")(sync_addresses)
network_app.command("build")(build_network)
app.add_typer(data_app, name="data")
app.add_typer(network_app, name="network")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

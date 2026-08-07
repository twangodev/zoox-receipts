from __future__ import annotations

import typer

from .commands.export import export_rides
from .commands.geocode import geocode, sync_addresses
from .commands.routes import export_routes
from .commands.routing import aggregate, build_network, infer


app = typer.Typer(
    add_completion=False,
    help="Convert Zoox Takeout receipts directly to route GeoJSON.",
    name="zooxr",
    no_args_is_help=True,
)
data_app = typer.Typer(help="Download public reference datasets.", no_args_is_help=True)
network_app = typer.Typer(help="Build and inspect routing networks.", no_args_is_help=True)

app.command("export", hidden=True)(export_rides)
app.command("routes")(export_routes)
app.command("geocode", hidden=True)(geocode)
app.command("infer", hidden=True)(infer)
app.command("aggregate", hidden=True)(aggregate)
data_app.command("sync-addresses")(sync_addresses)
network_app.command("build")(build_network)
app.add_typer(data_app, name="data", hidden=True)
app.add_typer(network_app, name="network", hidden=True)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

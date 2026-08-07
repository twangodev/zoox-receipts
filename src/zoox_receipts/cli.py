from __future__ import annotations

import typer

from .commands.export import export_rides


app = typer.Typer(
    add_completion=False,
    help="Export structured Zoox rides from Gmail Takeout.",
    name="zooxr",
    no_args_is_help=True,
)
app.command("export")(export_rides)


def main() -> None:
    app()


if __name__ == "__main__":
    main()

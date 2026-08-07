from __future__ import annotations

import json
from pathlib import Path

import typer


def emit_json(value: object, output: Path | None) -> None:
    serialized = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if output is None:
        typer.echo(serialized, nl=False)
    else:
        output.write_text(serialized, encoding="utf-8")

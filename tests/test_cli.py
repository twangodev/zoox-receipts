from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import osmnx as ox
from typer.testing import CliRunner

from zoox_receipts.cli import app

from tests.fixtures import COMPLETED_RECEIPT, email_bytes, write_takeout
from tests.test_routing import RIDE, routing_graph


class CliTest(unittest.TestCase):
    def test_emits_machine_readable_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            takeout = Path(directory) / "takeout.zip"
            write_takeout(
                takeout,
                email_bytes("Your ride on August 5", COMPLETED_RECEIPT),
            )

            result = CliRunner().invoke(app, ["export", str(takeout)])

        self.assertEqual(result.exit_code, 0)
        ride = json.loads(result.stdout)[0]
        self.assertFalse(ride["canceled"])
        self.assertEqual(ride["distanceMiles"], 2.33)
        self.assertEqual(ride["priceUsd"], 0.0)

    def test_infers_and_aggregates_routes_offline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = root / "graph.graphml"
            rides = root / "rides.json"
            routes = root / "routes.json"
            aggregate = root / "route-usage.geojson"
            state = root / "state.sqlite3"
            config = root / "zooxr.toml"
            ox.io.save_graphml(routing_graph(), graph)
            rides.write_text(json.dumps([RIDE]), encoding="utf-8")
            config.write_text(
                """\
[candidates]
distance_paths = 2
travel_time_paths = 2
maximum_distance_error_ratio = 1.0
maximum_distance_error_miles = 1.0
""",
                encoding="utf-8",
            )

            inferred = CliRunner().invoke(
                app,
                [
                    "infer",
                    str(rides),
                    "--graph",
                    str(graph),
                    "--state",
                    str(state),
                    "--config",
                    str(config),
                    "--output",
                    str(routes),
                ],
            )
            aggregated = CliRunner().invoke(
                app,
                [
                    "aggregate",
                    str(routes),
                    "--graph",
                    str(graph),
                    "--config",
                    str(config),
                    "--output",
                    str(aggregate),
                ],
            )
            route_value = json.loads(routes.read_text()) if routes.exists() else None
            aggregate_value = (
                json.loads(aggregate.read_text()) if aggregate.exists() else None
            )

        self.assertEqual(inferred.exit_code, 0, inferred.output)
        self.assertEqual(aggregated.exit_code, 0, aggregated.output)
        self.assertIsNotNone(route_value)
        self.assertIsNotNone(aggregate_value)
        self.assertEqual(route_value["rides"][0]["rideId"], RIDE["id"])
        self.assertGreater(len(aggregate_value["features"]), 0)


if __name__ == "__main__":
    unittest.main()

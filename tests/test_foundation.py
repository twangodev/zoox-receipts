from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zoox_receipts.config import ConfigError, load_config
from zoox_receipts.models import Ride
from zoox_receipts.storage import ArtifactStore


class FoundationTest(unittest.TestCase):
    def test_ride_id_is_stable_and_content_addressed(self) -> None:
        ride = Ride(
            date="2026-08-05",
            canceled=False,
            start="123 Example Street",
            end="456 Sample Avenue",
            started_at="2026-08-05T20:33:00",
            ended_at="2026-08-05T20:48:00",
            distance_miles=2.33,
            duration_minutes=15,
            price_usd=0.0,
        )
        changed = Ride(**{**ride.__dict__, "duration_minutes": 16})

        self.assertEqual(ride.id, ride.id)
        self.assertNotEqual(ride.id, changed.id)
        self.assertEqual(ride.as_dict()["id"], ride.id)

    def test_loads_and_validates_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "zooxr.toml"
            path.write_text(
                "schema_version = 1\n[candidates]\ndistance_paths = 0\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "path counts"):
                load_config(path)

    def test_candidate_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite3"
            candidates = [{"id": "candidate_1", "distanceMiles": 2.3}]
            with ArtifactStore(path) as store:
                self.assertIsNone(store.get_candidates("key"))
                store.put_candidates(
                    cache_key="key",
                    ride_id="ride_1",
                    graph_id="graph_1",
                    config_id="config_1",
                    candidates=candidates,
                )
                self.assertEqual(store.get_candidates("key"), candidates)


if __name__ == "__main__":
    unittest.main()

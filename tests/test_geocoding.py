from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from geopy.location import Location
from typer.testing import CliRunner

from zoox_receipts.cli import app
from zoox_receipts.geocoding import geocode_rides


RIDES = [
    {
        "start": "123 Example Street, San Francisco, California 94102, United States",
        "end": "456 Sample Avenue, San Francisco, California 94103, United States",
    },
    {
        "start": "123 Example Street, San Francisco, California 94102, United States",
        "end": "789 Missing Street, San Francisco, California 94104, United States",
    },
]


class GeocodingTest(unittest.TestCase):
    def test_deduplicates_caches_and_marks_unresolved_addresses(self) -> None:
        calls: list[str] = []

        def lookup(address: str, **_: object) -> list[Location]:
            calls.append(address)
            if "Missing" in address:
                return []
            coordinate = (
                (37.77, -122.42)
                if address.startswith("123")
                else (37.78, -122.41)
            )
            number, street = address.split(",", 1)[0].split(" ", 1)
            return [
                Location(
                    address,
                    coordinate,
                    {
                        "properties": {
                            "type": "house",
                            "housenumber": number,
                            "street": street,
                            "city": "San Francisco",
                        }
                    },
                )
            ]

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            enriched, stats = geocode_rides(RIDES, cache, geocode=lookup)

            def cached_only(_: str, **__: object) -> list[Location]:
                raise AssertionError("cached address was queried again")

            cached_rides = [RIDES[0]]
            cached_enriched, cached_stats = geocode_rides(
                cached_rides,
                cache,
                geocode=cached_only,
            )

        self.assertEqual(len(calls), 6)
        self.assertEqual(stats.resolved, 2)
        self.assertEqual(stats.address_matches, 2)
        self.assertEqual(stats.unresolved, 1)
        self.assertEqual(enriched[0]["startCoordinate"], [-122.42, 37.77])
        self.assertEqual(enriched[0]["startCoordinatePrecision"], "address")
        self.assertEqual(enriched[0]["startCoordinateProvider"], "photon")
        self.assertIsNone(enriched[1]["endCoordinate"])
        self.assertEqual(cached_stats.cached, 2)
        self.assertEqual(cached_stats.queried, 0)
        self.assertEqual(cached_enriched[0]["endCoordinate"], [-122.41, 37.78])

    def test_cli_geocodes_a_ride_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            rides = Path(directory) / "rides.json"
            output = Path(directory) / "geocoded.json"
            cache = Path(directory) / "cache.json"
            rides.write_text(json.dumps([RIDES[0]]), encoding="utf-8")

            from unittest.mock import patch

            with patch("zoox_receipts.geocoding.Photon") as photon:
                photon.return_value.geocode.side_effect = [
                    [
                        Location(
                            "Matched start",
                            (37.77, -122.42),
                            {
                                "properties": {
                                    "type": "house",
                                    "housenumber": "123",
                                    "street": "Example Street",
                                    "city": "San Francisco",
                                }
                            },
                        )
                    ],
                    [
                        Location(
                            "Matched end",
                            (37.78, -122.41),
                            {
                                "properties": {
                                    "type": "house",
                                    "housenumber": "456",
                                    "street": "Sample Avenue",
                                    "city": "San Francisco",
                                }
                            },
                        )
                    ],
                ]
                result = CliRunner().invoke(
                    app,
                    [
                        "geocode",
                        str(rides),
                        "--output",
                        str(output),
                        "--cache",
                        str(cache),
                        "--delay-seconds",
                        "0",
                    ],
                )

            value = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.exit_code, 0)
        photon.assert_called_once_with(user_agent="zooxr", timeout=10)
        self.assertEqual(value[0]["startCoordinate"], [-122.42, 37.77])
        self.assertEqual(value[0]["startCoordinatePrecision"], "address")
        self.assertIn("2/2 newly resolved", result.stderr)

    def test_prefers_same_street_over_wrong_nearby_house(self) -> None:
        nearby_house = Location(
            "555 Other Street",
            (37.79, -122.40),
            {
                "properties": {
                    "type": "house",
                    "housenumber": "555",
                    "street": "Other Street",
                    "city": "San Francisco",
                    "postcode": "94102",
                }
            },
        )
        matching_street = Location(
            "Example Street",
            (37.78, -122.41),
            {
                "properties": {
                    "type": "street",
                    "name": "Example Street",
                    "city": "San Francisco",
                    "postcode": "94102",
                }
            },
        )
        ride = [{"start": RIDES[0]["start"], "end": RIDES[0]["start"]}]

        with tempfile.TemporaryDirectory() as directory:
            enriched, stats = geocode_rides(
                ride,
                Path(directory) / "cache.json",
                geocode=lambda _, **__: [nearby_house, matching_street],
            )

        self.assertEqual(enriched[0]["startCoordinate"], [-122.41, 37.78])
        self.assertEqual(enriched[0]["startCoordinatePrecision"], "street")
        self.assertEqual(stats.street_matches, 1)

    def test_accepts_an_endpoint_of_a_building_number_range(self) -> None:
        ride = [
            {
                "start": "114-116 Example Street, San Francisco, California 94102, United States",
                "end": "114-116 Example Street, San Francisco, California 94102, United States",
            }
        ]
        result = Location(
            "116 Example Street",
            (37.78, -122.41),
            {
                "properties": {
                    "type": "house",
                    "housenumber": "116",
                    "street": "Example Street",
                    "city": "San Francisco",
                    "postcode": "94102",
                }
            },
        )

        with tempfile.TemporaryDirectory() as directory:
            enriched, stats = geocode_rides(
                ride,
                Path(directory) / "cache.json",
                geocode=lambda _, **__: [result],
            )

        self.assertEqual(enriched[0]["startCoordinatePrecision"], "address")
        self.assertEqual(stats.address_matches, 1)

    def test_retries_an_unmatched_address_without_the_house_number(self) -> None:
        ride = [
            {
                "start": "123 Second Street, San Francisco, California 94105, United States",
                "end": "123 Second Street, San Francisco, California 94105, United States",
            }
        ]
        calls: list[str] = []

        def lookup(query: str, **_: object) -> list[Location]:
            calls.append(query)
            if query.startswith("123"):
                return []
            return [
                Location(
                    "2nd Street",
                    (37.78, -122.40),
                    {
                        "properties": {
                            "type": "street",
                            "name": "2nd Street",
                            "city": "San Francisco",
                            "postcode": "94105",
                        }
                    },
                )
            ]

        with tempfile.TemporaryDirectory() as directory:
            enriched, stats = geocode_rides(
                ride,
                Path(directory) / "cache.json",
                geocode=lookup,
            )

        self.assertEqual(
            calls,
            [
                "123 Second Street, San Francisco, California 94105, United States",
                "Second Street, San Francisco, California 94105, United States",
            ],
        )
        self.assertEqual(enriched[0]["startCoordinatePrecision"], "street")
        self.assertEqual(stats.street_matches, 1)

    def test_retries_hard_matches_around_the_resolved_dataset(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []
        rides = [RIDES[0], RIDES[1]]

        def lookup(query: str, **options: object) -> list[Location]:
            calls.append((query, options))
            if "Missing" in query and options.get("location_bias") is None:
                return []
            number, street = query.split(",", 1)[0].split(" ", 1)
            if not number[0].isdigit():
                number = "789" if "Missing" in query else "123"
                street = query.split(",", 1)[0]
            return [
                Location(
                    query,
                    (37.77, -122.42),
                    {
                        "properties": {
                            "type": "house",
                            "housenumber": number,
                            "street": street,
                            "city": "San Francisco",
                        }
                    },
                )
            ]

        with tempfile.TemporaryDirectory() as directory:
            enriched, stats = geocode_rides(
                rides,
                Path(directory) / "cache.json",
                geocode=lookup,
            )

        hard_calls = [options for query, options in calls if "Missing" in query]
        self.assertTrue(any(options.get("limit") == 50 for options in hard_calls))
        self.assertTrue(any(options.get("location_bias") for options in hard_calls))
        self.assertEqual(enriched[1]["endCoordinatePrecision"], "address")
        self.assertEqual(stats.unresolved, 0)


if __name__ == "__main__":
    unittest.main()

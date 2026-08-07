from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from zoox_receipts import extract_rides

from tests.fixtures import (
    CANCELED_RECEIPT,
    COMPLETED_RECEIPT,
    email_bytes,
    write_mbox,
    write_takeout,
)


class ExtractRidesTest(unittest.TestCase):
    def test_extracts_direct_mbox_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            mbox = Path(directory) / "mail.mbox"
            write_mbox(
                mbox,
                email_bytes("Your ride on August 5", COMPLETED_RECEIPT),
            )

            rides = extract_rides(mbox)

        self.assertEqual(len(rides), 1)
        self.assertEqual(rides[0].price_usd, 0.0)

    def test_extracts_completed_and_canceled_rides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            takeout = Path(directory) / "takeout.zip"
            write_takeout(
                takeout,
                email_bytes("Your canceled ride receipt", CANCELED_RECEIPT),
                email_bytes("Your ride on August 5", COMPLETED_RECEIPT),
            )

            rides = extract_rides(takeout)

        self.assertEqual(
            [ride.as_dict() for ride in rides],
            [
                {
                    "id": rides[0].id,
                    "date": "2026-08-05",
                    "canceled": True,
                    "start": "789 Canceled Street, San Francisco, California 94105, United States",
                    "end": "321 Unreached Avenue, San Francisco, California 94111, United States",
                    "startedAt": None,
                    "endedAt": None,
                    "distanceMiles": 0.0,
                    "durationMinutes": 0,
                    "priceUsd": 0.0,
                },
                {
                    "id": rides[1].id,
                    "date": "2026-08-05",
                    "canceled": False,
                    "start": "123 Example Street, San Francisco, California 94102, United States",
                    "end": "456 Sample Avenue, San Francisco, California 94110, United States",
                    "startedAt": "2026-08-05T20:33:00",
                    "endedAt": "2026-08-05T20:48:00",
                    "distanceMiles": 2.33,
                    "durationMinutes": 15,
                    "priceUsd": 0.0,
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()

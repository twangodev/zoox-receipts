from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from zoox_receipts.datasf import DataSfAddressIndex, sync_datasf_addresses


ROWS = [
    {
        "address": "123 EXAMPLE ST",
        "address_number": "123",
        "street_full_street_name": "EXAMPLE ST",
        "zip_code": "94102",
        "longitude": "-122.42",
        "latitude": "37.77",
    },
    {
        "address": "116 SAMPLE AVE",
        "address_number": "116",
        "street_full_street_name": "SAMPLE AVE",
        "zip_code": "94103",
        "longitude": "-122.41",
        "latitude": "37.78",
    },
]


class DataSfTest(unittest.TestCase):
    def test_exact_and_range_address_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "addresses.jsonl"
            path.write_text(
                "".join(json.dumps(row) + "\n" for row in ROWS),
                encoding="utf-8",
            )
            index = DataSfAddressIndex.from_path(path)

        exact = index.geocode(
            "123 Example Street, San Francisco, California 94102, United States"
        )
        ranged = index.geocode(
            "114-116 Sample Avenue, San Francisco, California 94103, United States"
        )

        self.assertIsNotNone(exact)
        self.assertEqual(exact.provider, "datasf")
        self.assertEqual([exact.longitude, exact.latitude], [-122.42, 37.77])
        self.assertIsNotNone(ranged)
        self.assertEqual([ranged.longitude, ranged.latitude], [-122.41, 37.78])

    def test_syncs_paginated_rows_atomically(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            offset = int(request.url.params["$offset"])
            page = ROWS[offset : offset + 1]
            return httpx.Response(200, json=page)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "addresses.jsonl"
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                count = sync_datasf_addresses(path, client=client, page_size=1)
            lines = path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(count, 2)
        self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()

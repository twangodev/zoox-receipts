from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .geocoding import GeocodedLocation, normalized, parse_address


DATASET_URL = "https://data.sfgov.org/resource/3mea-di5p.json"
SELECTED_FIELDS = (
    "address,address_number,address_number_suffix,street_full_street_name,"
    "zip_code,longitude,latitude"
)


class DataSfError(ValueError):
    pass


@dataclass(frozen=True)
class DataSfAddress:
    address: str
    number: str
    street: str
    postcode: str
    longitude: float
    latitude: float

    @classmethod
    def from_dict(cls, value: object) -> DataSfAddress:
        if not isinstance(value, dict):
            raise DataSfError("DataSF cache row is not an object")
        try:
            number = f"{value['address_number']}{value.get('address_number_suffix', '')}"
            return cls(
                address=str(value["address"]),
                number=normalized(number),
                street=normalized(value["street_full_street_name"]),
                postcode=str(value["zip_code"]),
                longitude=float(value["longitude"]),
                latitude=float(value["latitude"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DataSfError("DataSF cache row has an invalid shape") from error


class DataSfAddressIndex:
    def __init__(self, addresses: list[DataSfAddress]) -> None:
        self.addresses: dict[tuple[str, str, str], list[DataSfAddress]] = {}
        for address in addresses:
            key = (address.number, address.street, address.postcode)
            self.addresses.setdefault(key, []).append(address)

    @classmethod
    def from_path(cls, path: Path) -> DataSfAddressIndex:
        try:
            with path.open(encoding="utf-8") as source:
                addresses = [
                    DataSfAddress.from_dict(json.loads(line))
                    for line in source
                    if line.strip()
                ]
        except (OSError, json.JSONDecodeError) as error:
            raise DataSfError(f"could not load DataSF cache {path}: {error}") from error
        return cls(addresses)

    def geocode(self, address: str) -> GeocodedLocation | None:
        parsed = parse_address(address)
        matches = [
            match
            for number in parsed.house_numbers
            for match in self.addresses.get((number, parsed.street, parsed.postcode), [])
        ]
        if not matches:
            return None
        longitude = sum(match.longitude for match in matches) / len(matches)
        latitude = sum(match.latitude for match in matches) / len(matches)
        return GeocodedLocation(
            longitude=longitude,
            latitude=latitude,
            matched_address=matches[0].address,
            precision="address",
            provider="datasf",
        )


def sync_datasf_addresses(
    path: Path,
    *,
    client: httpx.Client | None = None,
    page_size: int = 50_000,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    owns_client = client is None
    service = client or httpx.Client(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "zooxr"},
    )
    count = 0
    try:
        with temporary.open("w", encoding="utf-8") as target:
            while True:
                response = service.get(
                    DATASET_URL,
                    params={
                        "$select": SELECTED_FIELDS,
                        "$order": "eas_baseid",
                        "$limit": page_size,
                        "$offset": count,
                    },
                )
                response.raise_for_status()
                page: Any = response.json()
                if not isinstance(page, list):
                    raise DataSfError("DataSF returned a non-array response")
                for row in page:
                    if not isinstance(row, dict):
                        raise DataSfError("DataSF returned a non-object row")
                    target.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += len(page)
                if len(page) < page_size:
                    break
        temporary.replace(path)
    except (OSError, httpx.HTTPError, json.JSONDecodeError):
        temporary.unlink(missing_ok=True)
        raise
    finally:
        if owns_client:
            service.close()
    return count

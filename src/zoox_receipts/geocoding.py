from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Photon
from geopy.location import Location


Geocode = Callable[..., list[Location]]


class GeocodingError(ValueError):
    pass


@dataclass(frozen=True)
class GeocodedLocation:
    longitude: float
    latitude: float
    matched_address: str
    precision: str
    provider: str = "photon"

    @classmethod
    def from_dict(cls, value: object) -> GeocodedLocation:
        if not isinstance(value, dict):
            raise GeocodingError("cached location is not an object")
        coordinates = value.get("coordinates")
        matched_address = value.get("matchedAddress")
        precision = value.get("precision")
        provider = value.get("provider", "photon")
        if (
            not isinstance(coordinates, list)
            or len(coordinates) != 2
            or not all(isinstance(item, int | float) for item in coordinates)
            or not isinstance(matched_address, str)
            or precision not in ("address", "street")
            or provider not in ("datasf", "photon")
        ):
            raise GeocodingError("cached location has an invalid shape")
        return cls(
            longitude=float(coordinates[0]),
            latitude=float(coordinates[1]),
            matched_address=matched_address,
            precision=str(precision),
            provider=str(provider),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "coordinates": [self.longitude, self.latitude],
            "matchedAddress": self.matched_address,
            "precision": self.precision,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class GeocodingStats:
    cached: int
    queried: int
    resolved: int
    unresolved: int
    address_matches: int
    street_matches: int
    datasf_matches: int


@dataclass(frozen=True)
class ParsedAddress:
    house_numbers: frozenset[str]
    street: str
    city: str
    postcode: str


def load_rides(path: Path) -> list[dict[str, object]]:
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GeocodingError(f"{path} is not valid JSON: {error.msg}") from error
    if not isinstance(value, list) or not all(isinstance(ride, dict) for ride in value):
        raise GeocodingError(f"{path} must contain a JSON array of ride objects")
    return value


def cache_path_for(rides_path: Path) -> Path:
    return rides_path.with_name(f"{rides_path.stem}.geocoding-cache.json")


def load_cache(path: Path) -> dict[str, GeocodedLocation]:
    if not path.exists():
        return {}
    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise GeocodingError(f"{path} is not valid JSON: {error.msg}") from error
    if not isinstance(value, dict) or value.get("version") not in (2, 3):
        raise GeocodingError(f"{path} is not a supported geocoding cache")
    if value.get("version") == 2 and value.get("provider") != "photon":
        raise GeocodingError(f"{path} is not a supported geocoding cache")
    locations = value.get("locations")
    if not isinstance(locations, dict):
        raise GeocodingError(f"{path} has no locations object")
    return {
        address: GeocodedLocation.from_dict(location)
        for address, location in locations.items()
        if isinstance(address, str)
    }


def write_cache(path: Path, locations: dict[str, GeocodedLocation]) -> None:
    value = {
        "version": 3,
        "locations": {
            address: location.as_dict()
            for address, location in sorted(locations.items())
        },
    }
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def photon_geocoder(min_delay_seconds: float) -> Geocode:
    service = Photon(user_agent="zooxr", timeout=10)
    limited = RateLimiter(
        service.geocode,
        min_delay_seconds=min_delay_seconds,
        swallow_exceptions=False,
    )

    def lookup(
        address: str,
        *,
        limit: int = 10,
        location_bias: tuple[float, float] | None = None,
    ) -> list[Location]:
        options: dict[str, object] = {"exactly_one": False, "limit": limit}
        if location_bias is not None:
            options["location_bias"] = location_bias
        results = limited(address, **options)
        if results is None:
            return []
        if isinstance(results, Location):
            return [results]
        return list(results)

    return lookup


def normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    words = re.findall(r"[a-z0-9]+", decomposed)
    replacements = {
        "ave": "avenue",
        "blvd": "boulevard",
        "dr": "drive",
        "first": "1st",
        "rd": "road",
        "second": "2nd",
        "st": "street",
        "third": "3rd",
    }
    return " ".join(replacements.get(word, word) for word in words)


def parse_address(address: str) -> ParsedAddress:
    parts = [part.strip() for part in address.split(",")]
    endpoint = re.fullmatch(
        r"(?P<number>\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?)\s+(?P<street>.+)",
        parts[0],
    )
    region = (
        re.fullmatch(r".+?\s+(?P<postcode>\d{5}(?:-\d{4})?)", parts[2])
        if len(parts) > 2
        else None
    )
    if endpoint is None or region is None or len(parts) < 4:
        raise GeocodingError(f"cannot parse address for geocoding: {address}")
    house_number = endpoint.group("number")
    return ParsedAddress(
        house_numbers=frozenset(
            normalized(number)
            for number in (house_number, *house_number.split("-"))
        ),
        street=normalized(endpoint.group("street")),
        city=normalized(parts[1]),
        postcode=region.group("postcode"),
    )


def street_query(address: str) -> str:
    return re.sub(
        r"^\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?\s+",
        "",
        address,
        count=1,
    )


def select_candidate(address: str, candidates: list[Location]) -> GeocodedLocation | None:
    query = parse_address(address)
    ranked: list[tuple[int, GeocodedLocation]] = []
    for candidate in candidates:
        raw = candidate.raw if isinstance(candidate.raw, dict) else {}
        properties = raw.get("properties", {})
        if not isinstance(properties, dict):
            continue
        candidate_type = normalized(properties.get("type"))
        candidate_street = normalized(
            properties.get("street")
            or (properties.get("name") if candidate_type == "street" else "")
        )
        street_matches = candidate_street == query.street
        city_matches = normalized(properties.get("city")) == query.city
        postcode_matches = str(properties.get("postcode", "")) == query.postcode
        if not street_matches or not (city_matches or postcode_matches):
            continue
        number = normalized(properties.get("housenumber"))
        number_matches = number in query.house_numbers
        precision = "address" if number_matches else "street"
        score = (
            (100 if number_matches else 0)
            + (30 if postcode_matches else 0)
            + (20 if city_matches else 0)
            + (10 if candidate_type == "street" and not number_matches else 0)
            - (10 if number and not number_matches else 0)
        )
        ranked.append(
            (
                score,
                GeocodedLocation(
                    longitude=candidate.longitude,
                    latitude=candidate.latitude,
                    matched_address=candidate.address,
                    precision=precision,
                    provider="photon",
                ),
            )
        )
    if not ranked:
        return None
    return max(ranked, key=lambda item: item[0])[1]


def ride_addresses(rides: list[dict[str, object]]) -> list[str]:
    addresses: list[str] = []
    seen: set[str] = set()
    for index, ride in enumerate(rides):
        for field in ("start", "end"):
            address = ride.get(field)
            if not isinstance(address, str) or not address.strip():
                raise GeocodingError(f"ride {index} has no valid {field} address")
            if address not in seen:
                seen.add(address)
                addresses.append(address)
    return addresses


def geocode_rides(
    rides: list[dict[str, object]],
    cache_path: Path,
    *,
    geocode: Geocode | None = None,
    local_geocode: Callable[[str], GeocodedLocation | None] | None = None,
    min_delay_seconds: float = 1.0,
) -> tuple[list[dict[str, object]], GeocodingStats]:
    addresses = ride_addresses(rides)
    locations = load_cache(cache_path)
    cached = sum(address in locations for address in addresses)
    lookup = geocode or photon_geocoder(min_delay_seconds)
    queried = 0
    resolved = 0
    unresolved: set[str] = set()

    if local_geocode is not None:
        cache_changed = False
        for address in addresses:
            local = local_geocode(address)
            if local is not None and locations.get(address) != local:
                locations[address] = local
                cache_changed = True
        if cache_changed:
            write_cache(cache_path, locations)

    for address in addresses:
        if address in locations:
            continue
        queried += 1
        location = select_candidate(address, lookup(address, limit=10))
        if location is None:
            location = select_candidate(
                address,
                lookup(street_query(address), limit=10),
            )
        if location is None:
            unresolved.add(address)
            continue
        locations[address] = location
        resolved += 1
        write_cache(cache_path, locations)

    current_locations = [
        location for address, location in locations.items() if address in addresses
    ]
    if unresolved and current_locations:
        location_bias = (
            median(location.latitude for location in current_locations),
            median(location.longitude for location in current_locations),
        )
        for address in list(unresolved):
            location = select_candidate(
                address,
                lookup(address, limit=50, location_bias=location_bias),
            )
            if location is None:
                location = select_candidate(
                    address,
                    lookup(
                        street_query(address),
                        limit=50,
                        location_bias=location_bias,
                    ),
                )
            if location is None:
                continue
            locations[address] = location
            unresolved.remove(address)
            resolved += 1
            write_cache(cache_path, locations)

    enriched: list[dict[str, object]] = []
    for ride in rides:
        enriched_ride = dict(ride)
        for field in ("start", "end"):
            address = ride[field]
            location = locations.get(str(address))
            enriched_ride[f"{field}Coordinate"] = (
                [location.longitude, location.latitude] if location else None
            )
            enriched_ride[f"{field}CoordinatePrecision"] = (
                location.precision if location else None
            )
            enriched_ride[f"{field}CoordinateProvider"] = (
                location.provider if location else None
            )
        enriched.append(enriched_ride)

    return enriched, GeocodingStats(
        cached=cached,
        queried=queried,
        resolved=resolved,
        unresolved=len(unresolved),
        address_matches=sum(
            location.precision == "address"
            for address, location in locations.items()
            if address in addresses
        ),
        street_matches=sum(
            location.precision == "street"
            for address, location in locations.items()
            if address in addresses
        ),
        datasf_matches=sum(
            location.provider == "datasf"
            for address, location in locations.items()
            if address in addresses
        ),
    )

# zoox-receipts

Export Zoox receipts from a Gmail Takeout ZIP or MBOX, geocode their endpoints,
and estimate the streets traveled.

```shell
uv run zooxr export takeout.zip --output rides.json
```

Each ride has a stable ID plus its receipt date, cancellation status, endpoints,
timestamps, reported distance and duration, and price:

```json
{
  "id": "ride_0123456789abcdef0123",
  "date": "2026-08-05",
  "canceled": false,
  "start": "123 Example Street, San Francisco, California 94102, United States",
  "end": "456 Sample Avenue, San Francisco, California 94110, United States",
  "startedAt": "2026-08-05T20:33:00",
  "endedAt": "2026-08-05T20:48:00",
  "distanceMiles": 2.33,
  "durationMinutes": 15,
  "priceUsd": 0.0
}
```

Canceled receipts set `canceled` to `true`. Zoox reports zero miles and zero
minutes for them, so the CLI preserves those values and does not invent canceled
ride mileage.

## Geocoding

Download San Francisco's public address-point dataset, then geocode the rides:

```shell
uv run zooxr data sync-addresses
uv run zooxr geocode rides.json --output rides.geocoded.json
```

The local DataSF dataset is checked first. Remaining unique addresses fall back
to public Photon through geopy, with one request per second and a persistent
cache. Photon requests send those remaining addresses to `photon.komoot.io`.
Coordinates use GeoJSON order: longitude, then latitude. A precision field marks
each result as an exact `address` or a street-level fallback, and a provider
field records whether it came from `datasf` or `photon`.

## Route inference

Build the reusable OpenStreetMap driving graph once, infer route candidates, and
aggregate their probabilities into expected per-street usage:

```shell
uv run zooxr network build
uv run zooxr infer rides.geocoded.json --output routes.json
uv run zooxr aggregate routes.json --output route-usage.geojson
```

`infer` generates distance- and traffic-time-oriented alternatives with OSMnx
and NetworkX. It scores them against Zoox's reported mileage and duration, the
ride's local time period, road class, side-street share, and turns. The result is
probabilistic: it is an estimate, not a GPS trace. Candidate work is cached in
`.zooxr/state.sqlite3`, so interrupted or repeated runs resume efficiently.

The versioned parameters in `zooxr.toml` are the single source of truth for the
network region, candidate counts, traffic assumptions, and scoring weights.
Generated graphs, caches, exports, routes, and GeoJSON are ignored by Git because
they can contain private trip data.

`zooxr` uses the standard-library `zipfile`, `mailbox`, and `email` parsers for
Takeout, Typer for the CLI, HTTPX for DataSF, geopy for Photon, OSMnx and NetworkX
for routing, NumPy for nearest-node lookup, and SQLite for resumable artifacts.
Takeout ZIPs are extracted to an automatically cleaned temporary directory.

# zoox-receipts

Convert Zoox receipts from a Gmail Takeout ZIP or MBOX directly into estimated
route GeoJSON.

```shell
uv run zooxr routes takeout.zip --output routes.geojson
```

That is the complete workflow. No `rides.json`, `rides.geocoded.json`, or
inference JSON is required. Reusable address, street-network, and candidate data
is kept internally under `.zooxr/` so subsequent runs are fast.

The output is a GeoJSON `FeatureCollection` containing every receipt. Completed
rides have a best-estimate `LineString`; canceled or unresolved rides have null
geometry. Every feature carries the receipt metadata:

```json
{
  "type": "Feature",
  "id": "ride_0123456789abcdef0123",
  "geometry": {
    "type": "LineString",
    "coordinates": [[-122.42, 37.77], [-122.41, 37.78]]
  },
  "properties": {
    "status": "inferred",
    "canceled": false,
    "date": "2026-08-05",
    "start": "123 Example Street, San Francisco, California 94102, United States",
    "end": "456 Sample Avenue, San Francisco, California 94110, United States",
    "distanceMiles": 2.33,
    "durationMinutes": 15,
    "priceUsd": 0.0,
    "confidence": 0.73
  }
}
```

Zoox reports zero miles and zero minutes for canceled receipts, so `zooxr` does
not invent a route for them. Completed rides whose addresses cannot be resolved
are marked `skipped` with a reason in the same GeoJSON.

On the first run, `zooxr` automatically caches San Francisco's public DataSF
address points and an OpenStreetMap driving graph. Addresses absent from DataSF
fall back to public Photon through geopy. Route inference generates distance- and
traffic-time-oriented alternatives with OSMnx and NetworkX. It scores them
against Zoox's reported mileage and duration, the
ride's local time period, road class, side-street share, and turns. The result is
probabilistic: it is an estimate, not a GPS trace. Candidate work is cached in
`.zooxr/state.sqlite3`, so interrupted or repeated runs resume efficiently.

Candidate routes are constrained to the configured operating area east of
Divisadero and north of Cesar Chavez. The boundary is versioned in `zooxr.toml`
so it can move as Zoox expands its service.

The versioned parameters in `zooxr.toml` are the single source of truth for the
network region, service area, candidate counts, traffic assumptions, and scoring weights.
Generated graphs, caches, exports, routes, and GeoJSON are ignored by Git because
they can contain private trip data.

`zooxr` uses the standard-library `zipfile`, `mailbox`, and `email` parsers for
Takeout, Typer for the CLI, HTTPX for DataSF, geopy for Photon, OSMnx and NetworkX
for routing, NumPy for nearest-node lookup, and SQLite for resumable artifacts.
Takeout ZIPs are extracted to an automatically cleaned temporary directory.

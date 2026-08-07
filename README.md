# zoox-receipts

Export estimated Zoox routes from Gmail Takeout as GeoJSON

## Run

```sh
uv run zooxr routes takeout.zip --output routes.geojson
```

Completed rides are `LineString` features. Canceled and unresolved receipts stay
in the collection with `null` geometry. Reusable geocoding and routing data is
cached in `.zooxr/`.

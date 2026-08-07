from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import networkx as nx
import osmnx as ox

from zoox_receipts.config import CandidateConfig, RoutingConfig, ServiceAreaConfig
from zoox_receipts.routing import RouteEngine, load_graph
from zoox_receipts.routing.aggregate import aggregate_routes
from zoox_receipts.routing.geojson import route_feature_collection
from zoox_receipts.routing.inference import infer_routes
from zoox_receipts.routing.pipeline import candidate_sets
from zoox_receipts.routing.traffic import apply_typical_traffic, period_multiplier
from zoox_receipts.storage import ArtifactStore


def routing_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="epsg:4326", name="fixture")
    graph.add_node(1, x=-122.4200, y=37.7700)
    graph.add_node(2, x=-122.4150, y=37.7700, highway="traffic_signals")
    graph.add_node(3, x=-122.4150, y=37.7750)
    graph.add_node(4, x=-122.4100, y=37.7700)
    graph.add_edge(
        1,
        2,
        key=0,
        length=500.0,
        travel_time=60.0,
        highway="primary",
        speed_kph=30.0,
    )
    graph.add_edge(
        2,
        4,
        key=0,
        length=500.0,
        travel_time=60.0,
        highway="primary",
        speed_kph=30.0,
    )
    graph.add_edge(
        1,
        3,
        key=0,
        length=700.0,
        travel_time=70.0,
        highway="residential",
        speed_kph=25.0,
    )
    graph.add_edge(
        3,
        4,
        key=0,
        length=700.0,
        travel_time=70.0,
        highway="residential",
        speed_kph=25.0,
    )
    return graph


RIDE = {
    "id": "ride_fixture",
    "canceled": False,
    "startedAt": "2026-08-05T08:30:00",
    "startCoordinate": [-122.4200, 37.7700],
    "endCoordinate": [-122.4100, 37.7700],
    "distanceMiles": 0.75,
    "durationMinutes": 4,
}


class RoutingTest(unittest.TestCase):
    def test_applies_time_and_road_class_traffic_weights(self) -> None:
        config = RoutingConfig().traffic
        graph = routing_graph()

        apply_typical_traffic(graph, "2026-08-05T08:30:00", config)

        self.assertEqual(
            period_multiplier("2026-08-05T08:30:00", config),
            config.weekday_peak_multiplier,
        )
        self.assertGreater(
            graph[1][2][0]["typical_time"],
            graph[1][3][0]["typical_time"],
        )

    def test_generates_and_deduplicates_candidate_routes(self) -> None:
        config = RoutingConfig(
            candidates=CandidateConfig(
                distance_paths=2,
                travel_time_paths=2,
                maximum_distance_error_ratio=1.0,
                maximum_distance_error_miles=1.0,
            )
        )

        candidates = RouteEngine(routing_graph(), config).candidates_for(RIDE)

        self.assertEqual(len(candidates), 2)
        self.assertEqual({candidate.nodes for candidate in candidates}, {(1, 2, 4), (1, 3, 4)})
        self.assertEqual(len({candidate.id for candidate in candidates}), 2)
        self.assertTrue(any(candidate.side_street_ratio == 1 for candidate in candidates))
        self.assertTrue(any(candidate.arterial_ratio == 1 for candidate in candidates))

    def test_adds_routes_targeted_to_reported_distance(self) -> None:
        graph = routing_graph()
        graph.add_node(5, x=-122.4200, y=37.7750)
        graph.add_node(6, x=-122.4100, y=37.7750)
        graph.add_edge(
            1,
            5,
            key=0,
            length=800.0,
            travel_time=100.0,
            highway="residential",
            speed_kph=25.0,
        )
        graph.add_edge(
            5,
            6,
            key=0,
            length=800.0,
            travel_time=100.0,
            highway="residential",
            speed_kph=25.0,
        )
        graph.add_edge(
            6,
            4,
            key=0,
            length=300.0,
            travel_time=40.0,
            highway="residential",
            speed_kph=25.0,
        )
        config = RoutingConfig(
            candidates=CandidateConfig(
                distance_paths=1,
                travel_time_paths=1,
                target_distance_paths=3,
                maximum_distance_error_ratio=1.0,
                maximum_distance_error_miles=1.0,
            )
        )
        ride = {**RIDE, "distanceMiles": 1.18}

        candidates = RouteEngine(graph, config).candidates_for(ride)

        targeted = [
            candidate
            for candidate in candidates
            if candidate.source == "target-distance"
        ]
        self.assertTrue(targeted)
        self.assertLess(
            min(abs(candidate.distance_miles - 1.18) for candidate in targeted),
            0.01,
        )

    def test_excludes_routes_outside_the_zoox_service_area(self) -> None:
        graph = routing_graph()
        graph.add_node(7, x=-122.4500, y=37.7700)
        graph.add_edge(
            1,
            7,
            key=0,
            length=100.0,
            travel_time=10.0,
            highway="residential",
            speed_kph=25.0,
        )
        graph.add_edge(
            7,
            4,
            key=0,
            length=100.0,
            travel_time=10.0,
            highway="residential",
            speed_kph=25.0,
        )
        config = RoutingConfig(
            service_area=ServiceAreaConfig(
                west_longitude=-122.4430,
                south_latitude=37.7475,
            ),
            candidates=CandidateConfig(
                distance_paths=3,
                travel_time_paths=3,
                target_distance_paths=3,
                maximum_distance_error_ratio=1.0,
                maximum_distance_error_miles=1.0,
            ),
        )

        candidates = RouteEngine(graph, config).candidates_for(RIDE)

        self.assertTrue(candidates)
        self.assertTrue(all(7 not in candidate.nodes for candidate in candidates))

        outside = {**RIDE, "startCoordinate": [-122.4500, 37.7700]}
        with self.assertRaisesRegex(ValueError, "pickup.*outside"):
            RouteEngine(graph, config).candidates_for(outside)

    def test_loads_a_cached_graph_and_hashes_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.graphml"
            ox.io.save_graphml(routing_graph(), path)

            graph, metadata = load_graph(path)

        self.assertEqual(graph.number_of_nodes(), 4)
        self.assertEqual(len(metadata.id), 20)
        self.assertEqual(metadata.region, "fixture")

    def test_caches_infers_and_aggregates_candidate_probabilities(self) -> None:
        config = RoutingConfig(
            candidates=CandidateConfig(
                distance_paths=2,
                travel_time_paths=2,
                maximum_distance_error_ratio=1.0,
                maximum_distance_error_miles=1.0,
            )
        )
        graph = routing_graph()
        engine = RouteEngine(graph, config)

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.sqlite3"
            with ArtifactStore(state) as store:
                first, skipped = candidate_sets(
                    [RIDE],
                    engine,
                    store,
                    graph_id="graph_fixture",
                    config=config,
                )
                second, _ = candidate_sets(
                    [RIDE],
                    engine,
                    store,
                    graph_id="graph_fixture",
                    config=config,
                )

        inference = infer_routes(
            [RIDE],
            first,
            graph,
            graph_id="graph_fixture",
            config=config,
            skipped=skipped,
        )
        aggregate = aggregate_routes(inference, graph)
        candidates = inference["rides"][0]["candidates"]

        self.assertEqual(first, second)
        self.assertAlmostEqual(
            sum(candidate["probability"] for candidate in candidates),
            1.0,
        )
        self.assertEqual(inference["rides"][0]["route"]["type"], "LineString")
        self.assertGreater(len(aggregate["features"]), 0)
        self.assertEqual(aggregate["rideCount"], 1)

        geojson = route_feature_collection([RIDE], inference)
        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertEqual(geojson["routeCount"], 1)
        self.assertEqual(geojson["features"][0]["properties"]["rideId"], RIDE["id"])

        canceled = {
            **RIDE,
            "id": "ride_canceled",
            "canceled": True,
            "startedAt": None,
            "distanceMiles": 0.0,
            "durationMinutes": 0,
        }
        with_canceled = route_feature_collection([RIDE, canceled], inference)
        self.assertEqual(with_canceled["canceledRideCount"], 1)
        self.assertEqual(with_canceled["routeCount"], 1)
        self.assertIsNone(with_canceled["features"][1]["geometry"])
        self.assertEqual(
            with_canceled["features"][1]["properties"]["status"],
            "canceled",
        )


if __name__ == "__main__":
    unittest.main()

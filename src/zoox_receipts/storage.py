from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class StorageError(RuntimeError):
    pass


class ArtifactStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def _initialize(self) -> None:
        version = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if version not in (0, SCHEMA_VERSION):
            raise StorageError(
                f"state database schema {version} is not supported; "
                f"expected {SCHEMA_VERSION}"
            )
        if version == 0:
            self.connection.execute(
                """
                CREATE TABLE candidate_sets (
                    cache_key TEXT PRIMARY KEY,
                    ride_id TEXT NOT NULL,
                    graph_id TEXT NOT NULL,
                    config_id TEXT NOT NULL,
                    candidates_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self.connection.commit()

    def get_candidates(self, cache_key: str) -> list[dict[str, Any]] | None:
        row = self.connection.execute(
            "SELECT candidates_json FROM candidate_sets WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if row is None:
            return None
        value: Any = json.loads(row["candidates_json"])
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise StorageError(f"candidate cache {cache_key} is malformed")
        return value

    def put_candidates(
        self,
        *,
        cache_key: str,
        ride_id: str,
        graph_id: str,
        config_id: str,
        candidates: list[dict[str, object]],
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO candidate_sets (
                cache_key, ride_id, graph_id, config_id, candidates_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                candidates_json = excluded.candidates_json,
                created_at = CURRENT_TIMESTAMP
            """,
            (
                cache_key,
                ride_id,
                graph_id,
                config_id,
                json.dumps(candidates, separators=(",", ":"), ensure_ascii=False),
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ArtifactStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

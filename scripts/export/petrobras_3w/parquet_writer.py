"""Write Petrobras 3W destination tables to Parquet via pure DuckDB SQL.

The slice covered by issue #19 only emits `event_types.parquet`. Later
slices (#20, #21, #22) add `instances.parquet`, `wells.parquet`, and
the hive-partitioned `observations/` tree alongside it.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def write_event_types(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "event_types.parquet"
    con.execute(
        f"COPY (SELECT * FROM event_types ORDER BY event_class) "
        f"TO '{target}' (FORMAT PARQUET)"
    )

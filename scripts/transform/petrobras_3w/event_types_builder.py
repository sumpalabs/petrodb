"""Build the `event_types` lookup table from the parsed `dataset.ini`.

One row per upstream event class (0..9). The four derived columns
(`has_transient`, `transient_code`, `has_normal_prefix`) materialize the
TRANSIENT-arc semantics described in CONTEXT.md without forcing
consumers to re-derive them from the per-observation `class` codes.

- `transient_code = event_class + 100` when `has_transient = true`,
  NULL otherwise (matching the per-observation labels seen in the data).
- `has_normal_prefix` correlates with `has_transient`: instances of
  events 0, 3, 4 do not carry a `NORMAL` precursor in `class`, so the
  flag tracks `has_transient` exactly.
"""

from __future__ import annotations

import duckdb

from scripts.transform.petrobras_3w.upstream_stager import DatasetIni


def build(con: duckdb.DuckDBPyConnection, dataset_ini: DatasetIni) -> None:
    """Create the `event_types` table from the parsed upstream `dataset.ini`."""
    rows = [
        (
            spec.event_class,
            spec.name,
            spec.description,
            spec.has_transient,
            spec.event_class + 100 if spec.has_transient else None,
            spec.has_transient,
        )
        for spec in dataset_ini.event_types
    ]

    con.execute(
        """
        CREATE OR REPLACE TABLE event_types (
            event_class      INTEGER NOT NULL PRIMARY KEY,
            name             VARCHAR NOT NULL,
            description      VARCHAR NOT NULL,
            has_transient    BOOLEAN NOT NULL,
            transient_code   INTEGER,
            has_normal_prefix BOOLEAN NOT NULL
        )
        """
    )
    con.executemany(
        "INSERT INTO event_types VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )

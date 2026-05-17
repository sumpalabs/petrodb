"""Build the `observations` view over the staged upstream tree.

Defines a view rather than a materialised table because the full
Observations corpus (2,228 files × tens of thousands of rows × 30
columns) is too large to keep in RAM. The view scans the staged
per-Instance parquets via a single `read_parquet(..., filename=true,
union_by_name=true)`, then derives four columns from the source
filename:

- `instance_id`  — upstream filename without `.parquet`
- `event_class`  — the integer carved out of `<staging>/dataset/N/`
- `well_id`      — leading-zero-stripped `WELL-NNNNN` prefix (NULL for
                   simulated / drawn instances)
- `well_kind`    — `real` / `simulated` / `drawn` keyed on the prefix

The view exists for the validator (rules 2, 5, 6 in CONTEXT.md need
per-Observation queries); the actual per-Instance parquets are written
by `parquet_writer.write_observations`, which reads the staged sources
directly rather than going through the view (one read per file vs. an
O(n²) re-scan against the view).

Per ADR-0001 the published layout hive-partitions by `event_class`
only, so `event_class` is NOT stored in the per-file body — but it is
present in the view so the validator can pivot on it.

`union_by_name=true` keeps the view tolerant of the test fixtures,
which only carry `timestamp` and `class`; columns missing from a file
become NULL in the view.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def build(con: duckdb.DuckDBPyConnection, staging_dir: Path) -> None:
    """Create or replace the `observations` view over staged sources."""
    staging_dir = Path(staging_dir)
    glob_pattern = str(staging_dir / "dataset" / "*" / "*.parquet")

    con.execute(
        f"""
        CREATE OR REPLACE VIEW observations AS
        SELECT
            * EXCLUDE (filename, _instance_id_, _event_class_),
            _instance_id_ AS instance_id,
            _event_class_ AS event_class,
            CASE
                WHEN starts_with(_instance_id_, 'WELL-')
                THEN CAST(regexp_extract(_instance_id_, '^WELL-0*([0-9]+)_', 1)
                          AS INTEGER)
            END AS well_id,
            CASE
                WHEN starts_with(_instance_id_, 'WELL-')      THEN 'real'
                WHEN starts_with(_instance_id_, 'SIMULATED_') THEN 'simulated'
                WHEN starts_with(_instance_id_, 'DRAWN_')     THEN 'drawn'
            END AS well_kind
        FROM (
            SELECT
                *,
                regexp_extract(filename, '/([^/]+)\\.parquet$', 1)
                    AS _instance_id_,
                CAST(regexp_extract(filename, '/dataset/([0-9]+)/', 1)
                     AS INTEGER) AS _event_class_
            FROM read_parquet(
                '{glob_pattern}',
                filename=true,
                union_by_name=true
            )
        )
        """
    )

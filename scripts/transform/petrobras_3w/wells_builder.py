"""Build the `wells` master table from the staged Instance catalog.

One row per distinct real-Well `well_id`, derived from `instances` rows
where `well_kind = 'real'`. Simulated and drawn instances have NULL
`well_id` and contribute nothing here — `wells.parquet` is for physical
wells only.

Upstream anonymises every physical-well attribute (no basin, field,
depth, or location is published), so the master is essentially an
identity-plus-statistics table: counts of instances and 1-Hz
observations, and the time span across which the well appears in the
corpus. Operator-actionable per-well summaries can be materialised here
without a full Observations scan.

Requires `instances` to already exist in the connection — call this
after `instances_builder.build`.
"""

from __future__ import annotations

import duckdb


def build(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `wells` table by aggregating real-Well instances."""
    con.execute(
        """
        CREATE OR REPLACE TABLE wells AS
        SELECT
            well_id,
            CAST(COUNT(*) AS BIGINT) AS n_instances,
            MIN(start_ts) AS first_ts,
            MAX(end_ts)   AS last_ts,
            CAST(SUM(n_rows) AS BIGINT) AS n_observations
        FROM instances
        WHERE well_kind = 'real'
        GROUP BY well_id
        ORDER BY well_id
        """
    )

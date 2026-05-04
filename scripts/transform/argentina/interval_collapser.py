"""Collapse a per-month value series into one row per contiguous-value run.

Table-in / table-out deep module. Reads from a source table with columns
`(idpozo, fecha, <value_col>)` and writes a target table with columns
`(idpozo, <value_col>, valid_from, valid_to)`.

NULL is treated as a value: a run of NULL months emits its own row, and
transitions to/from NULL emit boundaries. Single-month flips are emitted
as their own one-month run — no smoothing, no majority-vote, no
look-ahead. Source-fidelity is the contract; the gap is the data.

Implemented as the standard gap-and-island window pattern in pure
DuckDB SQL. Input need not be sorted.
"""

import duckdb


def collapse(
    con: duckdb.DuckDBPyConnection,
    source_table: str,
    target_table: str,
    value_col: str,
) -> None:
    """Materialize `target_table` from `source_table` via gap-and-island.

    `IS DISTINCT FROM` treats NULL == NULL, so a run-membership boundary
    fires only on a real value change. The first row of each well is
    always a boundary (rn = 1) — without that case, a well that starts
    with NULL would have its first NULL row absorbed into the preceding
    well's run.
    """
    con.execute(
        f"""
        CREATE OR REPLACE TABLE {target_table} AS
        WITH ordered AS (
            SELECT
                idpozo,
                fecha,
                {value_col} AS value,
                LAG({value_col}) OVER (
                    PARTITION BY idpozo ORDER BY fecha
                ) AS prev_value,
                ROW_NUMBER() OVER (
                    PARTITION BY idpozo ORDER BY fecha
                ) AS rn
            FROM {source_table}
        ),
        boundaries AS (
            SELECT
                idpozo,
                fecha,
                value,
                CASE
                    WHEN rn = 1 THEN 1
                    WHEN value IS DISTINCT FROM prev_value THEN 1
                    ELSE 0
                END AS is_new_run
            FROM ordered
        ),
        runs AS (
            SELECT
                idpozo,
                fecha,
                value,
                SUM(is_new_run) OVER (
                    PARTITION BY idpozo ORDER BY fecha
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS run_id
            FROM boundaries
        )
        SELECT
            idpozo,
            ANY_VALUE(value) AS {value_col},
            MIN(fecha) AS valid_from,
            MAX(fecha) AS valid_to
        FROM runs
        GROUP BY idpozo, run_id
        ORDER BY idpozo, valid_from
        """
    )

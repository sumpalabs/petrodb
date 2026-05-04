"""Detect monthly transitions in a per-well snapshot tuple.

Table-in / table-out deep module. Reads from a source table with columns
`(idpozo, fecha, *value_cols)` and writes a target table with the same
shape — but only the rows where the snapshot tuple changed since the
prior month.

The first row of every well is always emitted (initial-state contract):
the first month is a transition *into* the well's starting state, which
is itself a meaningful event. Without this clause a well starting in
state `(NULL, NULL, NULL)` would have its first row absorbed into the
preceding well's run by `IS DISTINCT FROM`.

NULL is treated as a value: transitions to/from NULL emit boundaries.
Single-month flips (A → B → A) emit three rows, not one — source
fidelity over smoothing.

Sibling of `interval_collapser`: same window-frame skeleton, different
projection. Where the collapser groups runs and emits intervals, this
module emits the boundary rows themselves and carries the new tuple
forward verbatim.

Pure DuckDB SQL. Sorts internally by (idpozo, fecha); callers need
not pre-sort.
"""

import duckdb


def detect(
    con: duckdb.DuckDBPyConnection,
    source_table: str,
    target_table: str,
    value_cols: list[str],
) -> None:
    """Materialize `target_table` from `source_table` via LAG-and-compare.

    `IS DISTINCT FROM` treats NULL == NULL, so a transition fires only
    on a real component change. The `rn = 1` clause guarantees the
    first row per well is emitted regardless of LAG (LAG returns NULL
    for the first row, which would spuriously match a NULL first
    component without the clause).
    """
    cols_csv = ", ".join(value_cols)
    lag_decls = ",\n                ".join(
        f"LAG({col}) OVER (PARTITION BY idpozo ORDER BY fecha) AS prev_{col}"
        for col in value_cols
    )
    distinct_clauses = " OR ".join(
        f"{col} IS DISTINCT FROM prev_{col}" for col in value_cols
    )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE {target_table} AS
        WITH ordered AS (
            SELECT
                idpozo,
                fecha,
                {cols_csv},
                {lag_decls},
                ROW_NUMBER() OVER (
                    PARTITION BY idpozo ORDER BY fecha
                ) AS rn
            FROM {source_table}
        )
        SELECT
            idpozo,
            fecha,
            {cols_csv}
        FROM ordered
        WHERE rn = 1 OR {distinct_clauses}
        ORDER BY idpozo, fecha
        """
    )

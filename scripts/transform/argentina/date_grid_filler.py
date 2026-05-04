"""Fill the per-well month grid between the first and last source row.

Table-in / table-out deep module. Reads from a source table with columns
`(idpozo, fecha, *value_cols)` and writes a target table with the same
shape — but with a row for every month in `[MIN(fecha), MAX(fecha)]`
per `idpozo`. Months absent from the source are synthesized with NULL
value-column entries.

Cousin of `interval_collapser` and `transition_detector`: same
table-in/table-out signature, also pure DuckDB SQL, but does gap-fill
rather than gap-and-island. Where those modules collapse runs or detect
boundaries, this one densifies the time axis so that every month
between the well's first and last appearance is present.

Semantic contract — see CONTEXT.md "Date-completeness in
monthly_production":
  - "no row for `idpozo`/`fecha`" means "well had not started yet, or
    had been abandoned past that date".
  - "row for `idpozo`/`fecha` with NULL value cols" means "well existed
    that month but no measurements were reported".

Source rows pass through verbatim — including their own NULL value
cols. The LEFT JOIN distinguishes "synthesized fill row" only by the
fact that no source row was matched, not by any flag column.

Pure DuckDB SQL. Sorts internally; callers need not pre-sort.
"""

import duckdb


def fill(
    con: duckdb.DuckDBPyConnection,
    source_table: str,
    target_table: str,
    value_cols: list[str],
) -> None:
    """Materialize `target_table` from `source_table` via per-well month spine.

    `generate_series(first, last, INTERVAL 1 MONTH)` produces the dense
    per-well month spine. The cast to DATE is required because
    `generate_series` returns TIMESTAMP even when both bounds are DATE.

    A LEFT JOIN back to the source aligns existing rows; missing months
    surface as rows whose value cols are NULL. Source rows with NULL
    value cols are indistinguishable from synthesized fill rows in the
    output — that is the documented contract, not a bug.
    """
    src_value_projection = ", ".join(f"src.{col} AS {col}" for col in value_cols)
    con.execute(
        f"""
        CREATE OR REPLACE TABLE {target_table} AS
        WITH bounds AS (
            SELECT
                idpozo,
                MIN(fecha) AS first_fecha,
                MAX(fecha) AS last_fecha
            FROM {source_table}
            GROUP BY idpozo
        ),
        spine AS (
            SELECT
                b.idpozo,
                CAST(
                    UNNEST(
                        generate_series(
                            b.first_fecha,
                            b.last_fecha,
                            INTERVAL 1 MONTH
                        )
                    ) AS DATE
                ) AS fecha
            FROM bounds b
        )
        SELECT
            s.idpozo,
            s.fecha,
            {src_value_projection}
        FROM spine s
        LEFT JOIN {source_table} src
            ON s.idpozo = src.idpozo
            AND s.fecha = src.fecha
        ORDER BY s.idpozo, s.fecha
        """
    )

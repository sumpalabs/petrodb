"""Build the gap-filled monthly production time-series for Argentina wells.

One row per `(idpozo, fecha)` for every month in
`[first_production_row, last_production_row]` per well. Source rows
pass through verbatim; missing months are synthesized with NULL
measurements. PK = `(idpozo, fecha)`.

This is the only Argentina destination table that is gap-filled. The
operator-history and events tables read `stg_production` directly to
preserve gaps as data — see CONTEXT.md "Source fidelity over
smoothing". Here, the date-completeness contract demands the inverse:
every month between a well's first and last appearance must be
represented, so that "no row" cleanly means "well had not started or
had been abandoned" and "row with NULL measurements" means "well
existed but no data was reported".

Source `anio` / `mes` are not retained — `fecha` (DATE, first-of-month)
is the only time column per CONTEXT.md.

Pre-aggregates over `(idpozo, anio, mes)` defensively via ANY_VALUE.
The four canonical Argentina source rows do not appear to ship
duplicate rows for the same well-month today, but the aggregation
makes the builder robust to source drift — and matches the same
defensive pattern in `events_builder` and `operator_history_builder`.
"""

import duckdb

from scripts.transform.argentina import date_grid_filler

MEASUREMENT_COLUMNS = (
    "prod_pet",
    "prod_gas",
    "prod_agua",
    "iny_agua",
    "iny_gas",
    "iny_co2",
    "iny_otro",
    "tef",
    "vida_util",
)


def build(con: duckdb.DuckDBPyConnection) -> None:
    measurement_aggs = ",\n            ".join(
        f"ANY_VALUE({col}) AS {col}" for col in MEASUREMENT_COLUMNS
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE _mp_input AS
        SELECT
            idpozo,
            MAKE_DATE(anio, mes, 1) AS fecha,
            {measurement_aggs}
        FROM stg_production
        GROUP BY idpozo, MAKE_DATE(anio, mes, 1)
        """
    )

    date_grid_filler.fill(
        con,
        source_table="_mp_input",
        target_table="_mp_filled",
        value_cols=list(MEASUREMENT_COLUMNS),
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE monthly_production AS
        SELECT * FROM _mp_filled
        ORDER BY idpozo, fecha
        """
    )

    con.execute("DROP TABLE _mp_input")
    con.execute("DROP TABLE _mp_filled")

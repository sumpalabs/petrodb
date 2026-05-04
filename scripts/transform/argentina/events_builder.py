"""Build the operational-state events table for Argentina wells.

One row per snapshot of `(tipoestado, tipoextraccion, tipopozo)` per
month where any of the three components changed. Reads `stg_production`
directly — NOT a gap-filled monthly_production. The gap is the data:
NULL components must survive into the output as transitions, not be
smoothed over.

The first row of every well is emitted (initial-state contract): the
first month of every well is itself a transition into its starting
operational state. This decision matches `interval_collapser` and is
documented in `transition_detector`.

Pre-aggregates over `(idpozo, anio, mes)` defensively — if the source
ever ships duplicate rows for the same well-month with conflicting
state, ANY_VALUE picks one rather than letting LAG see the duplicate
as a real change. The four canonical Argentina source rows do not
appear to carry such duplicates today, but the aggregation makes the
builder robust to source drift.
"""

import duckdb

from scripts.transform.argentina import transition_detector


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _events_input AS
        SELECT
            idpozo,
            MAKE_DATE(anio, mes, 1) AS fecha,
            ANY_VALUE(tipoestado)     AS tipoestado,
            ANY_VALUE(tipoextraccion) AS tipoextraccion,
            ANY_VALUE(tipopozo)       AS tipopozo
        FROM stg_production
        GROUP BY idpozo, MAKE_DATE(anio, mes, 1)
        """
    )

    transition_detector.detect(
        con,
        source_table="_events_input",
        target_table="_events_transitions",
        value_cols=["tipoestado", "tipoextraccion", "tipopozo"],
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE well_events AS
        SELECT
            idpozo,
            fecha AS event_date,
            tipoestado,
            tipoextraccion,
            tipopozo
        FROM _events_transitions
        ORDER BY idpozo, event_date
        """
    )

    con.execute("DROP TABLE _events_input")
    con.execute("DROP TABLE _events_transitions")

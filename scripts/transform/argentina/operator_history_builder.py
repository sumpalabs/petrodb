"""Build the slowly-changing-metadata table for Argentina well operators.

One row per contiguous-`idempresa` run per well, with `valid_from` /
`valid_to` (closed interval, both inclusive). Reads source rows from
`stg_production` directly — NOT from any gap-filled monthly_production
table built later in the pipeline. The gap is the data: a NULL
`idempresa` in source means "no operator reported", and that interval
must survive into the output.

The `empresa` display name is joined from the first month of each run.
If the operator name drifts mid-run for the same `idempresa` code (a
known source quirk — e.g. `YPF S.A.` → `YPF SA`), the first-month
value wins. This is not name normalization; it is source-fidelity at
the interval level.

`idempresa` is VARCHAR. Source values include alphanumeric codes
(`Z001`, `APEA`) — see CONTEXT.md "type quirks".
"""

import duckdb

from scripts.transform.argentina import interval_collapser


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _op_input AS
        SELECT
            idpozo,
            MAKE_DATE(anio, mes, 1) AS fecha,
            idempresa
        FROM stg_production
        """
    )

    interval_collapser.collapse(
        con,
        source_table="_op_input",
        target_table="_op_intervals",
        value_col="idempresa",
    )

    con.execute(
        """
        CREATE OR REPLACE TABLE well_operator_history AS
        WITH first_month_lookup AS (
            SELECT
                idpozo,
                MAKE_DATE(anio, mes, 1) AS fecha,
                ANY_VALUE(empresa) AS empresa
            FROM stg_production
            GROUP BY idpozo, MAKE_DATE(anio, mes, 1)
        )
        SELECT
            i.idpozo,
            i.idempresa,
            f.empresa,
            i.valid_from,
            i.valid_to
        FROM _op_intervals i
        LEFT JOIN first_month_lookup f
            ON i.idpozo = f.idpozo
            AND i.valid_from = f.fecha
        ORDER BY i.idpozo, i.valid_from
        """
    )

    con.execute("DROP TABLE _op_input")
    con.execute("DROP TABLE _op_intervals")

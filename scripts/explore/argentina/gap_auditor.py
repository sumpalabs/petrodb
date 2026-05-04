"""Per-idpozo source-month gap audit over the staged production rows.

For every well, computes:
- first_fecha, last_fecha   : observed-first and observed-last month
- expected_months           : full month-count of [first, last] inclusive
- observed_months           : distinct months actually present in source
- gap_count                 : expected_months - observed_months
- longest_gap_months        : longest run of consecutive missing months

Feeds the date-completeness rule for the future `monthly_production`
table (the time-series destination is gap-filled with NULL measurement
rows; the operator/event tables preserve gaps as NULL intervals).
"""

from pathlib import Path

import duckdb

OUTPUT_FILENAME = "gap_audit.parquet"


def audit(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / OUTPUT_FILENAME
    con.execute(
        f"""
        COPY (
            WITH well_months AS (
                SELECT
                    idpozo,
                    MAKE_DATE(CAST(anio AS INTEGER), CAST(mes AS INTEGER), 1) AS fecha
                FROM stg_production
                WHERE anio IS NOT NULL AND mes IS NOT NULL
                GROUP BY idpozo, anio, mes
            ),
            bounds AS (
                SELECT
                    idpozo,
                    MIN(fecha) AS first_fecha,
                    MAX(fecha) AS last_fecha,
                    COUNT(*) AS observed_months
                FROM well_months
                GROUP BY idpozo
            ),
            expected AS (
                SELECT
                    idpozo,
                    first_fecha,
                    last_fecha,
                    observed_months,
                    DATE_DIFF('month', first_fecha, last_fecha) + 1
                        AS expected_months
                FROM bounds
            ),
            ordered_months AS (
                SELECT
                    idpozo,
                    fecha,
                    DATE_DIFF(
                        'month',
                        LAG(fecha) OVER (PARTITION BY idpozo ORDER BY fecha),
                        fecha
                    ) AS step_months
                FROM well_months
            ),
            longest_gap AS (
                SELECT
                    idpozo,
                    COALESCE(MAX(step_months) - 1, 0) AS longest_gap_months
                FROM ordered_months
                WHERE step_months IS NOT NULL
                GROUP BY idpozo
            )
            SELECT
                e.idpozo,
                e.first_fecha,
                e.last_fecha,
                e.expected_months,
                e.observed_months,
                e.expected_months - e.observed_months AS gap_count,
                COALESCE(g.longest_gap_months, 0) AS longest_gap_months
            FROM expected e
            LEFT JOIN longest_gap g USING (idpozo)
            ORDER BY e.idpozo
        ) TO '{output_path}' (FORMAT PARQUET)
        """
    )

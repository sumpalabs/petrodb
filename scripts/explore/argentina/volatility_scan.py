"""Per-idpozo cross-year volatility scan over the staged production rows.

For every candidate column, computes the share of wells whose value ever
changes across the well's history. The result is the evidence base for the
four-bucket classification documented in CONTEXT.md (static / SCD / event /
time-series).

NULLs are excluded: a well that has all-NULL or NULL-then-single-value is
not counted as "changed". This matches the convention used to derive the
headline numbers (~67% idempresa, ~74% tipoestado, < 0.3% on the static
bucket).
"""

from pathlib import Path

import duckdb

# Expected bucket per column, per CONTEXT.md. The scan recomputes the
# evidence; this mapping just tags each row with its design-intent bucket
# so the output is human-readable without cross-referencing docs.
COLUMN_BUCKETS: dict[str, str] = {
    # Static master attributes (< 0.3% volatility expected)
    "sigla": "static",
    "formprod": "static",
    "profundidad": "static",
    "formacion": "static",
    "cuenca": "static",
    "provincia": "static",
    "idareapermisoconcesion": "static",
    "areapermisoconcesion": "static",
    "idareayacimiento": "static",
    "areayacimiento": "static",
    "tipo_de_recurso": "static",
    "sub_tipo_recurso": "static",
    "clasificacion": "static",
    "subclasificacion": "static",
    "proyecto": "static",
    # Slowly-changing dimensions (operator transfers)
    "idempresa": "scd",
    "empresa": "scd",
    # Event-snapshot columns
    "tipoestado": "event",
    "tipoextraccion": "event",
    "tipopozo": "event",
    # Numeric monthly time-series
    "prod_pet": "time-series",
    "prod_gas": "time-series",
    "prod_agua": "time-series",
    "iny_agua": "time-series",
    "iny_gas": "time-series",
    "iny_co2": "time-series",
    "iny_otro": "time-series",
    "tef": "time-series",
    "vida_util": "time-series",
}

OUTPUT_FILENAME = "volatility_report.parquet"


def scan(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    """Compute the per-column volatility report and persist it as Parquet."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    available = {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'stg_production'"
        ).fetchall()
    }

    select_parts = []
    for col, bucket in COLUMN_BUCKETS.items():
        if col not in available:
            continue
        select_parts.append(
            f"""
            SELECT
                '{col}' AS column_name,
                '{bucket}' AS expected_bucket,
                COUNT(*) FILTER (WHERE distinct_values > 1) AS wells_with_change,
                COUNT(*) FILTER (WHERE rows_with_value > 0) AS wells_with_value,
                COUNT(*) AS total_wells,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE distinct_values > 1)
                    / NULLIF(COUNT(*) FILTER (WHERE rows_with_value > 0), 0),
                    3
                ) AS pct_changed
            FROM (
                SELECT
                    idpozo,
                    COUNT(DISTINCT "{col}") AS distinct_values,
                    COUNT(*) FILTER (WHERE "{col}" IS NOT NULL) AS rows_with_value
                FROM stg_production
                GROUP BY idpozo
            )
            """
        )

    if not select_parts:
        raise RuntimeError("no candidate columns found in stg_production")

    union_sql = "\nUNION ALL\n".join(select_parts)
    output_path = output_dir / OUTPUT_FILENAME
    con.execute(
        f"COPY ({union_sql} ORDER BY expected_bucket, column_name) "
        f"TO '{output_path}' (FORMAT PARQUET)"
    )

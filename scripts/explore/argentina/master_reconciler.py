"""Reconcile the two master CSVs and the production well-id population.

Produces:
- master_coverage.parquet     : row counts and overlap on idpozo across the
                                three sources (capitulo-iv, listado, production).
- master_field_agreement.parquet : per-overlap-column agreement count and
                                disagreement count between capitulo-iv and listado.
- production_only_wells.parquet : idpozo rows that appear in production but
                                are absent from capitulo-iv (~37 in full source).
- capitulo_iv_only_orphans.parquet : idpozo rows in capitulo-iv that never
                                appear in production (~113 in full source).

These outputs feed the master-assembly rule in CONTEXT.md (capitulo-iv as
spine, LEFT JOIN listado for enrichment, fall back for production-only
wells, retain capitulo-iv-only orphans flagged has_production = false).
"""

from pathlib import Path

import duckdb

COVERAGE_FILE = "master_coverage.parquet"
FIELD_AGREEMENT_FILE = "master_field_agreement.parquet"
PRODUCTION_ONLY_FILE = "production_only_wells.parquet"
ORPHANS_FILE = "capitulo_iv_only_orphans.parquet"


def _columns(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            [table],
        ).fetchall()
    }


def reconcile(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cap_cols = _columns(con, "stg_capitulo_iv")
    list_cols = _columns(con, "stg_listado")
    overlap_cols = sorted(cap_cols & list_cols - {"idpozo"})

    coverage_path = output_dir / COVERAGE_FILE
    con.execute(
        f"""
        COPY (
            SELECT 'capitulo_iv' AS source,
                   COUNT(*) AS row_count,
                   COUNT(DISTINCT idpozo) AS distinct_idpozo
            FROM stg_capitulo_iv
            UNION ALL
            SELECT 'listado', COUNT(*), COUNT(DISTINCT idpozo)
            FROM stg_listado
            UNION ALL
            SELECT 'production', COUNT(*), COUNT(DISTINCT idpozo)
            FROM stg_production
            UNION ALL
            SELECT 'capitulo_iv_AND_listado',
                   NULL,
                   COUNT(DISTINCT a.idpozo)
            FROM stg_capitulo_iv a
            JOIN stg_listado b USING (idpozo)
            UNION ALL
            SELECT 'capitulo_iv_AND_production',
                   NULL,
                   COUNT(DISTINCT a.idpozo)
            FROM stg_capitulo_iv a
            JOIN (SELECT DISTINCT idpozo FROM stg_production) p USING (idpozo)
            UNION ALL
            SELECT 'listado_AND_production',
                   NULL,
                   COUNT(DISTINCT a.idpozo)
            FROM stg_listado a
            JOIN (SELECT DISTINCT idpozo FROM stg_production) p USING (idpozo)
        ) TO '{coverage_path}' (FORMAT PARQUET)
        """
    )

    if overlap_cols:
        select_parts = []
        for col in overlap_cols:
            select_parts.append(
                f"""
                SELECT '{col}' AS column_name,
                       COUNT(*) FILTER (
                           WHERE c."{col}" IS NOT DISTINCT FROM l."{col}"
                       ) AS agreement_count,
                       COUNT(*) FILTER (
                           WHERE c."{col}" IS DISTINCT FROM l."{col}"
                       ) AS disagreement_count,
                       COUNT(*) AS overlap_well_count
                FROM stg_capitulo_iv c
                JOIN stg_listado l USING (idpozo)
                """
            )
        union_sql = "\nUNION ALL\n".join(select_parts)
        agreement_path = output_dir / FIELD_AGREEMENT_FILE
        con.execute(
            f"COPY ({union_sql} ORDER BY column_name) "
            f"TO '{agreement_path}' (FORMAT PARQUET)"
        )

    production_only_path = output_dir / PRODUCTION_ONLY_FILE
    con.execute(
        f"""
        COPY (
            SELECT DISTINCT p.idpozo
            FROM stg_production p
            ANTI JOIN stg_capitulo_iv c USING (idpozo)
            ORDER BY p.idpozo
        ) TO '{production_only_path}' (FORMAT PARQUET)
        """
    )

    orphans_path = output_dir / ORPHANS_FILE
    con.execute(
        f"""
        COPY (
            SELECT c.idpozo, c.sigla
            FROM stg_capitulo_iv c
            ANTI JOIN (SELECT DISTINCT idpozo FROM stg_production) p
              USING (idpozo)
            ORDER BY c.idpozo
        ) TO '{orphans_path}' (FORMAT PARQUET)
        """
    )

"""Argentina explore-phase orchestrator.

Runs the five explore modules in order against the staged Argentina
DuckDB intermediate, writing all reference outputs into
`scripts/explore/argentina/output/` (or a caller-provided directory).

If the staged tables are not present in the DuckDB file, the orchestrator
invokes `csv_stager` itself when given a `csv_dir` rather than failing.
"""

from pathlib import Path

import duckdb

from scripts.explore.argentina import (
    eda_plotter,
    findings_writer,
    gap_auditor,
    master_reconciler,
    volatility_scan,
)
from scripts.transform.argentina import csv_stager

DEFAULT_DB_PATH = Path("database/argentina.duckdb")
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"
STAGED_TABLES = ("stg_capitulo_iv", "stg_listado", "stg_production")


def _staged_tables_exist(con: duckdb.DuckDBPyConnection) -> bool:
    rows = con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    return {r[0] for r in rows} >= set(STAGED_TABLES)


def run(
    db_path: Path | None = None,
    csv_dir: Path | None = None,
    output_dir: Path | None = None,
) -> None:
    db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    output_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT_DIR
    db_path.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(db_path)) as con:
        if not _staged_tables_exist(con):
            if csv_dir is None:
                raise RuntimeError(
                    "staged tables missing in DuckDB and no csv_dir provided "
                    "to stage them"
                )
            csv_stager.stage(con, Path(csv_dir))

        volatility_scan.scan(con, output_dir)
        master_reconciler.reconcile(con, output_dir)
        gap_auditor.audit(con, output_dir)
        eda_plotter.plot(con, output_dir)
        findings_writer.write(con, output_dir)

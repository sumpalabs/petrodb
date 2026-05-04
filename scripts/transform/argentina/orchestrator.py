"""Argentina transform-phase orchestrator.

Stages source CSVs into the DuckDB intermediate, then builds the
destination tables. `wells` and `well_operator_history` are built;
later issues add `well_events` and `monthly_production`.
"""

from pathlib import Path

import duckdb

from scripts.transform.argentina import (
    csv_stager,
    operator_history_builder,
    wells_builder,
)


def run(db_path: Path, csv_dir: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(db_path)) as con:
        csv_stager.stage(con, csv_dir)
        wells_builder.build(con)
        operator_history_builder.build(con)

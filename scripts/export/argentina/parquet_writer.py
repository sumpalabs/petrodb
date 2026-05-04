"""Write Argentina destination tables to Parquet via pure DuckDB SQL.

`wells.parquet` and `well_operator_history.parquet` are emitted as
single files. Later issues add `well_events.parquet` and the
hive-partitioned `monthly_production/anio=YYYY/data.parquet` tree.
"""

from pathlib import Path

import duckdb


def write_wells(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "wells.parquet"
    con.execute(f"COPY (SELECT * FROM wells) TO '{target}' (FORMAT PARQUET)")


def write_operator_history(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "well_operator_history.parquet"
    con.execute(
        f"COPY (SELECT * FROM well_operator_history) TO '{target}' (FORMAT PARQUET)"
    )

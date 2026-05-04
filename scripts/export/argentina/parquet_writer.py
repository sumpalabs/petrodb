"""Write Argentina destination tables to Parquet via pure DuckDB SQL.

`wells.parquet`, `well_operator_history.parquet`, and
`well_events.parquet` are emitted as single files.
`monthly_production` is hive-partitioned by `anio` into
`monthly_production/anio=YYYY/data.parquet`, with a `_files.json`
manifest at the partition root.
"""

import json
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


def write_well_events(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "well_events.parquet"
    con.execute(f"COPY (SELECT * FROM well_events) TO '{target}' (FORMAT PARQUET)")


def write_monthly_production(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    """Hive-partition `monthly_production` by `anio` and emit a manifest.

    DuckDB's COPY ... PARTITION_BY appends a thread/index suffix to the
    filename even when FILENAME_PATTERN is set, producing `data0.parquet`
    rather than `data.parquet`. To get the exact published filename we
    iterate years and write each partition with a single COPY targeting
    the file directly. Each partition is sorted by `(idpozo, fecha)`
    so that DuckDB row-group statistics enable single-well pruning on
    httpfs reads.

    The `_files.json` manifest lists relative partition paths, sorted
    by `anio`, so consumers that prefer enumeration over the
    `generate_series` URL-template trick have a flat list to read.
    """
    output_dir = Path(output_dir)
    partition_root = output_dir / "monthly_production"
    partition_root.mkdir(parents=True, exist_ok=True)

    years = [
        row[0]
        for row in con.execute(
            "SELECT DISTINCT EXTRACT(YEAR FROM fecha)::INTEGER AS anio "
            "FROM monthly_production ORDER BY anio"
        ).fetchall()
    ]

    relative_paths: list[str] = []
    for year in years:
        partition_dir = partition_root / f"anio={year}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        target = partition_dir / "data.parquet"
        con.execute(
            f"""
            COPY (
                SELECT
                    idpozo,
                    fecha,
                    prod_pet, prod_gas, prod_agua,
                    iny_agua, iny_gas, iny_co2, iny_otro,
                    tef, vida_util
                FROM monthly_production
                WHERE EXTRACT(YEAR FROM fecha) = {year}
                ORDER BY idpozo, fecha
            )
            TO '{target}' (FORMAT PARQUET)
            """
        )
        relative_paths.append(f"anio={year}/data.parquet")

    manifest_path = partition_root / "_files.json"
    manifest_path.write_text(json.dumps(relative_paths, indent=2) + "\n")

"""Stage Argentina source CSVs into DuckDB tables via read_csv_auto.

Three staged tables are produced:
- stg_capitulo_iv:  capitulo-iv-pozos.csv
- stg_listado:      listado-de-pozos-cargados-por-empresas-operadoras.csv
- stg_production:   produccin-de-pozos-de-gas-y-petrleo-*.csv (all years, union_by_name)
"""

from pathlib import Path

import duckdb

CAPITULO_IV_FILE = "capitulo-iv-pozos.csv"
LISTADO_FILE = "listado-de-pozos-cargados-por-empresas-operadoras.csv"
PRODUCTION_GLOB = "produccin-de-pozos-de-gas-y-petrleo-*.csv"


def stage(con: duckdb.DuckDBPyConnection, csv_dir: Path) -> None:
    csv_dir = Path(csv_dir)
    capitulo_iv = csv_dir / CAPITULO_IV_FILE
    listado = csv_dir / LISTADO_FILE
    production_glob = csv_dir / PRODUCTION_GLOB

    con.execute(
        f"CREATE OR REPLACE TABLE stg_capitulo_iv AS "
        f"SELECT * FROM read_csv_auto('{capitulo_iv}')"
    )
    con.execute(
        f"CREATE OR REPLACE TABLE stg_listado AS "
        f"SELECT * FROM read_csv_auto('{listado}')"
    )
    con.execute(
        f"CREATE OR REPLACE TABLE stg_production AS "
        f"SELECT * FROM read_csv_auto('{production_glob}', union_by_name=true)"
    )

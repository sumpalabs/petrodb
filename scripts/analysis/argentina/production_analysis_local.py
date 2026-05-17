"""
Argentina Oil & Gas — local DuckDB version

Same four-panel figure as `production_analysis_remote.py`, but pointed at
the local `database/argentina.duckdb` file built by `scripts/transform/
argentina/`. No network needed.

SQL templates and matplotlib layout live in `utils.py`, shared with the
remote variants so the panels render identically across all combinations.
The only differences in this file from the remote SI script are:

  (a) the data source — `monthly_production` / `wells` table names rather
      than `read_parquet('https://...')` strings,
  (b) the output filename and source caption.

Dependencies: duckdb, polars, matplotlib, contextily.
"""

from __future__ import annotations

import duckdb

from utils import UNITS_SI, run_production_analysis

DATABASE_PATH = "database/argentina.duckdb"
OUTPUT_PATH = "scripts/analysis/argentina/output/production_analysis_local.png"

# Table sources for the local DuckDB file — bare table names, no read_parquet.
PRODUCTION_SRC = "monthly_production"
WELLS_SRC = "wells"


def main() -> None:
    print("Argentina Oil & Gas — local DuckDB")
    print(f"Source: {DATABASE_PATH}\n")

    conn = duckdb.connect(DATABASE_PATH, read_only=True)
    try:
        run_production_analysis(
            conn,
            production_src=PRODUCTION_SRC,
            wells_src=WELLS_SRC,
            output_path=OUTPUT_PATH,
            units=UNITS_SI,
            suptitle="Argentina Oil & Gas — local DuckDB",
            subtitle=(
                "Monthly production 2006–2025, four independent DuckDB queries "
                "against the local argentina.duckdb"
            ),
            source_caption=f"Local DuckDB: {DATABASE_PATH}  ·  Basemap © Esri",
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

"""
Argentina Oil & Gas — a DuckDB sneak peek at petrodb.ocortez.com

What this script does
---------------------
Reads the Argentina production dataset live from petrodb.ocortez.com via
DuckDB's `httpfs` extension (no local download), runs four independent
queries, and renders a single PNG with four panels:

    ┌───────────────────────────┐ ┌───────────────────────────┐
    │ Monthly OIL (m³)          │ │ Monthly GAS (Mm³)         │
    │ stacked: Unconv vs Other  │ │ stacked: Unconv vs Other  │
    └───────────────────────────┘ └───────────────────────────┘
    ┌───────────────────────────┐ ┌───────────────────────────┐
    │ Satellite map of wells    │ │ Top 6 cuencas: twin bars  │
    │ (Esri WorldImagery tiles) │ │ cumulative oil + gas      │
    └───────────────────────────┘ └───────────────────────────┘

This is the SI / remote-Parquet entrypoint. SQL templates and matplotlib
layout live in `utils.py`, shared with the local DuckDB and imperial
variants so the four panels render identically across all combinations.

Try it yourself: https://petrodb.ocortez.com
Dependencies: duckdb, polars, matplotlib, contextily.
"""

from __future__ import annotations

import duckdb

from utils import (
    UNITS_SI,
    build_remote_sources,
    run_production_analysis,
)

BASE_URL = "https://petrodb.ocortez.com/argentina"
OUTPUT_PATH = "scripts/analysis/argentina/output/production_analysis_remote.png"


def main() -> None:
    print("Argentina Oil & Gas — DuckDB sneak peek")
    print(f"Source: {BASE_URL}\n")

    production_src, wells_src = build_remote_sources(BASE_URL)

    # `:memory:` because nothing needs to persist between runs. DuckDB will
    # auto-install/load httpfs the first time we hit a https:// URL.
    conn = duckdb.connect(":memory:")
    try:
        run_production_analysis(
            conn,
            production_src=production_src,
            wells_src=wells_src,
            output_path=OUTPUT_PATH,
            units=UNITS_SI,
            suptitle="Argentina Oil & Gas — a DuckDB sneak peek at petrodb.ocortez.com",
            subtitle=(
                "Monthly production 2006–2025, four independent DuckDB queries "
                "against publicly hosted Parquet files"
            ),
            source_caption="Parquet mirror: petrodb.ocortez.com  ·  Basemap © Esri",
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

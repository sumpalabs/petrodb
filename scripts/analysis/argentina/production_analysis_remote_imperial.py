"""
Argentina Oil & Gas — DuckDB sneak peek (field units, calendar daily rate)

Same four panels as `production_analysis_remote.py`, but with two changes
that make the chart read more naturally to an engineering audience used
to imperial petroleum units:

  1. Oil  in barrels (bbl);  gas in standard cubic feet (scf).
  2. Time-series panels report **calendar daily rate** = monthly volume
     divided by the number of days in the month — not the monthly volume
     itself. So the y-axis units are bbl/d and scf/d, not bbl/month.

Both transformations happen server-side in DuckDB (see `UNITS_IMPERIAL` in
`utils.py`), so the raw monthly values never materialise on the client.

Magnitudes you'll see:
    Oil daily rate : ~0–1   MMbbl/d (million barrels / day)
    Gas daily rate : ~0–6   Bscf/d  (billion scf / day)
    Cumulative oil : ~0–2   Bbbl    (billion barrels)
    Cumulative gas : ~0–20  Tcf     (trillion cubic feet)

Try it yourself: https://huggingface.co/datasets/sumpalabs/petrodb
Dependencies: duckdb, polars, matplotlib, contextily.
"""

from __future__ import annotations

import os

import duckdb

from utils import (
    UNITS_IMPERIAL,
    build_remote_sources,
    run_production_analysis,
)

# Data lives on Hugging Face (ADR-0005); `resolve` URLs honour HTTP Range so
# DuckDB `httpfs` fetches only the byte ranges each query needs. Override with
# the `BASE_URL` env var for a local Caddy dev host or a frozen HF revision.
BASE_URL = (
    os.environ.get(
        "BASE_URL", "https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main"
    ).rstrip("/")
    + "/argentina"
)
OUTPUT_PATH = (
    "scripts/analysis/argentina/output/production_analysis_remote_imperial.png"
)


def main() -> None:
    print("Argentina Oil & Gas — DuckDB sneak peek (field units)")
    print(f"Source: {BASE_URL}\n")

    production_src, wells_src = build_remote_sources(BASE_URL)

    conn = duckdb.connect(":memory:")
    try:
        run_production_analysis(
            conn,
            production_src=production_src,
            wells_src=wells_src,
            output_path=OUTPUT_PATH,
            units=UNITS_IMPERIAL,
            suptitle="Argentina Oil & Gas — DuckDB sneak peek",
            subtitle=(
                "Daily rate · 2006–2025 · four independent DuckDB queries "
                "against publicly hosted Parquet"
            ),
            source_caption="Parquet host: Hugging Face (sumpalabs/petrodb)  ·  Basemap © Esri",
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()

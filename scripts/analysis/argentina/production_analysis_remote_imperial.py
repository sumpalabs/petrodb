"""
Argentina Oil & Gas — DuckDB sneak peek (field units, calendar daily rate)

Same four panels as `production_analysis_remote.py`, but with two changes
that make the chart read more naturally to an engineering audience used
to imperial petroleum units:

  1. Oil  in barrels (bbl);  gas in standard cubic feet (scf).
  2. Time-series panels report **calendar daily rate** = monthly volume
     divided by the number of days in the month — not the monthly volume
     itself. So the y-axis units are bbl/d and scf/d, not bbl/month.

The unit conversion and the per-day division both happen server-side in
the DuckDB query, which doubles as a demo of date functions (`LAST_DAY`,
`EXTRACT`). The Python side just renders.

Conversions used (exact, not rounded):
    1 m³ oil = 6.2898 bbl                       → multiply prod_pet by 6.2898
    1 m³ gas = 35.3147 scf
        and source `prod_gas` is in "Mm³" where the Argentine convention
        is M = mil = thousand, so source units → m³ requires ×1000,
        and m³ → scf requires ×35.3147 → net factor 35,314.7.

Magnitudes you'll see:
    Oil daily rate : ~0–1   MMbbl/d (million barrels / day)
    Gas daily rate : ~0–6   Bscf/d  (billion scf / day)
    Cumulative oil : ~0–2   Bbbl    (billion barrels)
    Cumulative gas : ~0–20  Tcf     (trillion cubic feet)

Try it yourself: https://petrodb.ocortez.com
Dependencies: duckdb, polars, matplotlib, contextily.
"""

from __future__ import annotations

import time
from pathlib import Path

import contextily as cx
import duckdb
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import polars as pl

# --- Tweakable knobs --------------------------------------------------------
BASE_URL = "https://petrodb.ocortez.com/argentina"
OUTPUT_PATH = "scripts/analysis/argentina/output/production_analysis_remote_imperial.png"
TOP_N_BASINS = 6

# Map bounding box — same trim as the SI script.
LON_RANGE = (-74.0, -53.0)
LAT_RANGE = (-56.0, -30.0)

# Colour discipline (same as SI script):
#   Unconv vs Other → red / dark slate    (panels 1, 2, 3)
#   Oil    vs Gas   → green / blue        (panel 4 only)
C_UNCONV = "#d62728"
C_OTHER = "#37474f"
C_OIL = "#2ca02c"
C_GAS = "#1f77b4"

# Unit-conversion constants. Kept as named SQL fragments so each query can
# include them inline and the reader can see exactly what's happening.
M3_TO_BBL = 6.2898            # 1 m³ of oil   = 6.2898 barrels
SOURCE_MM3_TO_SCF = 35_314.7  # 1 "Mm³"  gas  = 1000 m³ × 35.3147 scf/m³

# Parquet URLs. `monthly_production` is year-partitioned hive-style
# (`monthly_production/anio=YYYY/data.parquet`). Static HTTP can't do
# directory listings so we enumerate the years in Python and bake the
# URL list into the SQL as a literal array; bump the upper bound when
# new partitions land. `hive_partitioning = true` recovers the `anio`
# column from the file path so DuckDB can prune partitions.
PRODUCTION_YEARS = range(2006, 2026)
_PRODUCTION_URLS = ",\n            ".join(
    f"'{BASE_URL}/monthly_production/anio={y}/data.parquet'"
    for y in PRODUCTION_YEARS
)
WELLS = f"read_parquet('{BASE_URL}/wells.parquet')"
PRODUCTION = f"""read_parquet(
        [
            {_PRODUCTION_URLS}
        ],
        hive_partitioning = true
    )"""


# --- Helpers ----------------------------------------------------------------

def run_query(conn: duckdb.DuckDBPyConnection, label: str, sql: str) -> pl.DataFrame:
    """Run a DuckDB query, print elapsed time, return a polars frame."""
    t0 = time.perf_counter()
    df = conn.execute(sql).pl()
    dt = time.perf_counter() - t0
    print(f"  {label:<28s} {len(df):>7,d} rows  ({dt:5.1f} s)")
    return df


# --- Query 1 ----------------------------------------------------------------
# Monthly OIL calendar daily rate, in bbl/d, by bucket.
#
#   prod_pet            : monthly oil volume in m³ (source)
#   * M3_TO_BBL         : convert to barrels
#   / days_in_month     : convert monthly volume → calendar daily rate
#
# `LAST_DAY(fecha)` returns the last calendar date of the month; extracting
# its day-of-month gives 28/29/30/31. This stays inside DuckDB so we never
# materialise the raw monthly volumes on the client.
SQL_OIL_BY_BUCKET = f"""
    SELECT
        m.fecha,
        CASE
            WHEN w.tipo_recurso = 'NO CONVENCIONAL' THEN 'Unconv'
            ELSE 'Other'
        END AS bucket,
        SUM(m.prod_pet) * {M3_TO_BBL}
            / EXTRACT(DAY FROM LAST_DAY(m.fecha)) AS oil_bbl_per_day
    FROM {PRODUCTION} m
    JOIN {WELLS} w USING (idpozo)
    GROUP BY 1, 2
    ORDER BY 1, 2
"""

# --- Query 2 ----------------------------------------------------------------
# Monthly GAS calendar daily rate, in scf/d, by bucket. Same shape as Q1.
SQL_GAS_BY_BUCKET = f"""
    SELECT
        m.fecha,
        CASE
            WHEN w.tipo_recurso = 'NO CONVENCIONAL' THEN 'Unconv'
            ELSE 'Other'
        END AS bucket,
        SUM(m.prod_gas) * {SOURCE_MM3_TO_SCF}
            / EXTRACT(DAY FROM LAST_DAY(m.fecha)) AS gas_scf_per_day
    FROM {PRODUCTION} m
    JOIN {WELLS} w USING (idpozo)
    GROUP BY 1, 2
    ORDER BY 1, 2
"""

# --- Query 3 ----------------------------------------------------------------
# Well locations — identical to the SI script. No production data, no unit
# conversion needed; geography is geography.
SQL_WELL_LOCATIONS = f"""
    SELECT
        coordenadax AS lon,
        coordenaday AS lat,
        CASE
            WHEN tipo_recurso = 'NO CONVENCIONAL' THEN 'Unconv'
            ELSE 'Other'
        END AS bucket
    FROM {WELLS}
    WHERE coordenadax BETWEEN {LON_RANGE[0]} AND {LON_RANGE[1]}
      AND coordenaday BETWEEN {LAT_RANGE[0]} AND {LAT_RANGE[1]}
"""

# --- Query 4 ----------------------------------------------------------------
# Top-N basins. Cumulative values are NOT divided by days — they're totals,
# not rates. Just unit-convert.
SQL_TOP_BASINS = f"""
    SELECT
        w.cuenca,
        SUM(m.prod_pet) * {M3_TO_BBL}          AS oil_bbl_total,
        SUM(m.prod_gas) * {SOURCE_MM3_TO_SCF}  AS gas_scf_total
    FROM {PRODUCTION} m
    JOIN {WELLS} w USING (idpozo)
    WHERE w.cuenca IS NOT NULL
    GROUP BY w.cuenca
    -- Same producing-basin filter as the SI script. 1e6 m³ in source units
    -- ≈ 6.3 million bbl — still a tiny threshold relative to real basins.
    HAVING SUM(m.prod_pet) > 1e6
    ORDER BY oil_bbl_total DESC
    LIMIT {TOP_N_BASINS}
"""


# --- Plot helpers -----------------------------------------------------------

def plot_stacked_area(ax, df: pl.DataFrame, value_col: str, scale: float,
                      title: str, ylabel: str):
    """Pivot (fecha, bucket, value) to wide and draw a stacked area.

    `scale` divides the source values into friendly units (1e6 → MMbbl/d,
    1e9 → Bscf/d). Doing this in Python avoids the `1eN` scientific
    multiplier matplotlib would otherwise put on the y-axis."""
    wide = df.pivot(values=value_col, index="fecha", on="bucket").sort("fecha")
    dates = wide["fecha"].to_list()
    other = (wide["Other"].fill_null(0) / scale).to_list()
    unconv = (wide["Unconv"].fill_null(0) / scale).to_list()

    ax.stackplot(
        dates, other, unconv,
        labels=["Conv. / Other", "Unconventional"],
        colors=[C_OTHER, C_UNCONV],
        alpha=0.95,
    )
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.25, linestyle="--")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.85)
    ax.xaxis.set_major_locator(mdates.YearLocator(base=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def plot_map(ax, df: pl.DataFrame):
    """Scatter wells over an Esri WorldImagery satellite basemap."""
    other = df.filter(pl.col("bucket") == "Other")
    unconv = df.filter(pl.col("bucket") == "Unconv")

    ax.scatter(other["lon"], other["lat"],
               s=2.5, c=C_OTHER, alpha=0.45, linewidths=0,
               label=f"Other ({len(other):,})")
    ax.scatter(unconv["lon"], unconv["lat"],
               s=8, c=C_UNCONV, alpha=0.85, linewidths=0,
               label=f"Unconv ({len(unconv):,})")

    ax.set_xlim(LON_RANGE)
    ax.set_ylim(LAT_RANGE)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title("Well locations — Unconventional vs Other",
                 fontsize=12, fontweight="bold")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.legend(loc="lower right", fontsize=9, facecolor="white",
              edgecolor="#666", framealpha=0.95, markerscale=3)
    cx.add_basemap(
        ax,
        crs="EPSG:4326",
        source=cx.providers.Esri.WorldImagery,
        attribution_size=6,
        alpha=0.65,
    )


def plot_top_basins(ax, df: pl.DataFrame):
    """Twin horizontal bars per basin (oil + gas), each normalised to its
    own leader so they're visually comparable despite the magnitude gap."""
    df = df.sort("oil_bbl_total")  # ascending so largest sits at top after barh
    basins = df["cuenca"].to_list()
    oil = df["oil_bbl_total"].to_numpy()
    gas = df["gas_scf_total"].to_numpy()

    oil_n = oil / oil.max()
    gas_n = gas / gas.max()

    y = range(len(basins))
    h = 0.38
    ax.barh([i + h / 2 for i in y], oil_n, height=h, color=C_OIL, label="Oil (cum.)")
    ax.barh([i - h / 2 for i in y], gas_n, height=h, color=C_GAS, label="Gas (cum.)")

    # Label units chosen for readability:
    #   Oil : Bbbl (billion barrels) — Neuquina ~ 2 Bbbl over 20 yr
    #   Gas : Tcf  (trillion cubic feet) — Neuquina ~ 20 Tcf over 20 yr
    for i, (o_raw, g_raw, o_n, g_n) in enumerate(zip(oil, gas, oil_n, gas_n)):
        ax.text(o_n + 0.01, i + h / 2, f"{o_raw / 1e9:,.2f} Bbbl",
                va="center", fontsize=8, color="black")
        # 2 decimals on gas too, so small basins (Cuyana ≈ 0.04 Tcf) don't
        # read as literally zero.
        ax.text(g_n + 0.01, i - h / 2, f"{g_raw / 1e12:,.2f} Tcf",
                va="center", fontsize=8, color="black")

    ax.set_yticks(list(y))
    ax.set_yticklabels(basins, fontsize=9)
    ax.set_xlim(0, 1.25)
    ax.set_xticks([0, 0.5, 1.0])
    ax.set_xticklabels(["0", "50%", "100% of leader"])
    ax.set_title(f"Top {len(basins)} basins (cuencas) by cumulative oil",
                 fontsize=12, fontweight="bold")
    ax.legend(loc="lower right", fontsize=9, framealpha=0.85)
    ax.grid(True, axis="x", alpha=0.25, linestyle="--")


# --- Main -------------------------------------------------------------------

def main() -> None:
    print("Argentina Oil & Gas — DuckDB sneak peek (field units)")
    print(f"Source: {BASE_URL}\n")

    conn = duckdb.connect(":memory:")

    print("Running 4 independent queries (one per panel):")
    df_oil = run_query(conn, "1/4  oil rate (bbl/d)", SQL_OIL_BY_BUCKET)
    df_gas = run_query(conn, "2/4  gas rate (scf/d)", SQL_GAS_BY_BUCKET)
    df_locs = run_query(conn, "3/4  well locations", SQL_WELL_LOCATIONS)
    df_basins = run_query(conn, "4/4  top basins", SQL_TOP_BASINS)

    conn.close()

    print("\nRendering figure...")
    fig = plt.figure(figsize=(15, 10))
    gs = fig.add_gridspec(2, 2, hspace=0.32, wspace=0.22,
                          left=0.06, right=0.97, top=0.90, bottom=0.07)
    gs_bottom = gs[1, :].subgridspec(1, 2, width_ratios=[1, 2], wspace=0.20)

    # Y-axis scaling chosen so the values land in single-digit ranges:
    #   oil  bbl/d  ÷ 1e6 → MMbbl/d   (peak ≈ 0.8)
    #   gas  scf/d  ÷ 1e9 → Bscf/d    (peak ≈ 6)
    plot_stacked_area(fig.add_subplot(gs[0, 0]), df_oil,
                      value_col="oil_bbl_per_day", scale=1e6,
                      title="Oil — daily rate",
                      ylabel="Oil (MMbbl/d)")
    plot_stacked_area(fig.add_subplot(gs[0, 1]), df_gas,
                      value_col="gas_scf_per_day", scale=1e9,
                      title="Gas — daily rate",
                      ylabel="Gas (Bscf/d)")
    plot_map(fig.add_subplot(gs_bottom[0, 0]), df_locs)
    plot_top_basins(fig.add_subplot(gs_bottom[0, 1]), df_basins)

    fig.suptitle(
        "Argentina Oil & Gas — DuckDB sneak peek",
        fontsize=16, fontweight="bold", y=0.97,
    )
    fig.text(
        0.5, 0.93,
        "Daily rate · 2006–2025 · four independent DuckDB queries "
        "against publicly hosted Parquet",
        ha="center", fontsize=10, style="italic", color="#444",
    )
    fig.text(
        0.06, 0.012,
        "Unconv = tipo_recurso = 'NO CONVENCIONAL' (Shale + Tight). "
        "Other = Conv + 'No informado' (~26% of wells) + tail.",
        fontsize=8, color="#555",
    )
    # Two-line attribution: full upstream URL on top (small), friendly
    # mirror + basemap credit on the line below.
    fig.text(
        0.97, 0.025,
        "Original data: datos.gob.ar/dataset/energia-produccion-petroleo-gas-por-pozo-capitulo-iv",
        ha="right", fontsize=7, color="#555",
    )
    fig.text(
        0.97, 0.010,
        "Parquet mirror: petrodb.ocortez.com  ·  Basemap © Esri",
        ha="right", fontsize=8, color="#555",
    )

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUTPUT_PATH, dpi=200, bbox_inches="tight")
    print(f"✓ Saved: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

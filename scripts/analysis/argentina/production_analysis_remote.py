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

Each panel = one independent DuckDB query. This is intentional: in a real
analysis you'd fetch once and reuse the frame, but here the point is to
show what the SQL looks like for each plot in isolation so a reader can
copy any one of them and play.

Try it yourself
---------------
The site that backs every query is publicly browsable:
    https://petrodb.ocortez.com
Replace `petrodb.ocortez.com` below with your own mirror if you host one.

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
OUTPUT_PATH = "scripts/analysis/argentina/output/production_analysis_remote.png"
TOP_N_BASINS = 6

# Map bounding box. The northern cap at -30 latitude trims the small NOA /
# Noroeste cluster (Salta–Jujuy–Tucumán, ~996 wells) so the map zooms into
# the heart of Argentine production — Neuquén, Mendoza, Patagonia. This is
# a map-only filter; those wells are still counted in the time-series and
# basin-ranking panels.
LON_RANGE = (-74.0, -53.0)
LAT_RANGE = (-56.0, -30.0)

# Colour discipline:
#   Unconv vs Other      → red / grey   (panels 1, 2, 3)
#   Oil vs Gas           → green / blue (panel 4 only)
# The two dimensions never share a panel, so there is no overload.
C_UNCONV = "#d62728"
# Dark slate (Material BlueGrey 700-ish). Pure grey was invisible against
# the satellite tile texture; this colour still reads as a neutral
# "baseline" but pops on both the basemap and the stacked-area panels.
C_OTHER = "#37474f"
C_OIL = "#2ca02c"
C_GAS = "#1f77b4"

# Parquet URLs. `wells.parquet` is a single file. `monthly_production` is
# year-partitioned hive-style (`monthly_production/anio=YYYY/data.parquet`).
# Static HTTP can't do directory listings so a `*` glob in the URL fails,
# and DuckDB doesn't (yet) accept a subquery inside `read_parquet(...)`.
# Cheapest robust pattern: enumerate the years in Python, bake the URL
# list into the SQL as a literal array. Bump the upper bound when new
# partitions land. `hive_partitioning = true` recovers the `anio` column
# from the file path so DuckDB can prune partitions on a year filter.

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
    """Run a DuckDB query, print elapsed time, return a polars frame.

    The print is the pedagogical bit: readers should *see* that each chart
    costs one network round-trip and roughly how long it takes."""
    t0 = time.perf_counter()
    df = conn.execute(sql).pl()
    dt = time.perf_counter() - t0
    print(f"  {label:<28s} {len(df):>7,d} rows  ({dt:5.1f} s)")
    return df


# --- Query 1 ----------------------------------------------------------------
# Monthly OIL by bucket. The CASE expression on tipo_recurso is the canonical
# "Unconv" definition for this script: anything tagged NO CONVENCIONAL is
# Unconventional (Shale + Tight); everything else (Conv + No informado +
# tail) is folded into "Other". The 26% "No informado" wells almost
# certainly are old conventional but the source doesn't say so, hence the
# honest "Other" label.
SQL_OIL_BY_BUCKET = f"""
    SELECT
        m.fecha,
        CASE
            WHEN w.tipo_recurso = 'NO CONVENCIONAL' THEN 'Unconv'
            ELSE 'Other'
        END AS bucket,
        SUM(m.prod_pet) AS prod_pet_m3
    FROM {PRODUCTION} m
    JOIN {WELLS} w USING (idpozo)
    GROUP BY 1, 2
    ORDER BY 1, 2
"""

# --- Query 2 ----------------------------------------------------------------
# Monthly GAS by bucket. Same shape as Q1 — separate query (not a pivot of
# Q1's result) because oil and gas live on different axes and we want each
# panel's SQL to stand on its own.
SQL_GAS_BY_BUCKET = f"""
    SELECT
        m.fecha,
        CASE
            WHEN w.tipo_recurso = 'NO CONVENCIONAL' THEN 'Unconv'
            ELSE 'Other'
        END AS bucket,
        SUM(m.prod_gas) AS prod_gas_mm3
    FROM {PRODUCTION} m
    JOIN {WELLS} w USING (idpozo)
    GROUP BY 1, 2
    ORDER BY 1, 2
"""

# --- Query 3 ----------------------------------------------------------------
# Well locations. Single-table scan of wells.parquet — no monthly join, so
# this is by far the cheapest query. The bbox filter on lon/lat drops a few
# outliers without losing real wells.
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
# Top-N basins by cumulative oil, returning both oil & gas totals. We rank
# by oil and bring gas along for the ride; in panel 4 we'll draw two bars
# per basin (oil in green, gas in blue) so readers see which basins are
# oily, gassy, or mixed.
SQL_TOP_BASINS = f"""
    SELECT
        w.cuenca,
        SUM(m.prod_pet) AS prod_pet_m3_total,
        SUM(m.prod_gas) AS prod_gas_mm3_total
    FROM {PRODUCTION} m
    JOIN {WELLS} w USING (idpozo)
    WHERE w.cuenca IS NOT NULL
    GROUP BY w.cuenca
    -- A handful of basins (ÑIRIHUAU, NORESTE, CAÑADON ASFALTO, …) appear
    -- in `wells.parquet` with either zero or trivial (a few thousand m³)
    -- production. Filter at 1 Mm³ cumulative so the chart only ranks
    -- basins that actually produced at meaningful scale.
    HAVING SUM(m.prod_pet) > 1e6
    ORDER BY prod_pet_m3_total DESC
    LIMIT {TOP_N_BASINS}
"""


# --- Plot helpers -----------------------------------------------------------

def plot_stacked_area(ax, df: pl.DataFrame, value_col: str, scale: float,
                      title: str, ylabel: str):
    """Pivot (fecha, bucket, value) to wide and draw a stacked area.

    `scale` divides the raw source values into friendly units (e.g. 1e6 for
    m³ → million m³ on the oil panel). Doing this in Python avoids
    matplotlib's `1e6` scientific-notation multiplier on the y-axis."""
    wide = df.pivot(values=value_col, index="fecha", on="bucket").sort("fecha")
    dates = wide["fecha"].to_list()
    other = (wide["Other"].fill_null(0) / scale).to_list()
    unconv = (wide["Unconv"].fill_null(0) / scale).to_list()

    # Order matters: Other on the bottom (grey baseline), Unconv on top so
    # the growth wedge reads as the figure's punchline.
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

    # Other goes down first as a low-alpha cloud — it traces the country's
    # producing-well distribution like a faint shadow. Unconv goes on top,
    # bigger and brighter, so the Vaca Muerta cluster pops in Neuquén.
    ax.scatter(other["lon"], other["lat"],
               s=2.5, c=C_OTHER, alpha=0.45, linewidths=0, label=f"Other ({len(other):,})")
    ax.scatter(unconv["lon"], unconv["lat"],
               s=8, c=C_UNCONV, alpha=0.85, linewidths=0, label=f"Unconv ({len(unconv):,})")

    ax.set_xlim(LON_RANGE)
    ax.set_ylim(LAT_RANGE)
    # `datalim` lets matplotlib widen the lat/lon limits so the panel fills
    # without distorting the basemap tiles. Argentina is tall and skinny;
    # without this, the panel has lots of wasted ocean on left & right.
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title("Well locations — Unconventional vs Other",
                 fontsize=12, fontweight="bold")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    # Legend sits over open Atlantic on the right so the well points along
    # the Andes / Patagonia aren't obscured. Force an opaque white face so
    # the grey "Other" marker is readable (it would otherwise blend into
    # the semi-transparent satellite tile beneath the legend frame), and
    # bump `markerscale` so the legend dots are bigger than the data dots.
    ax.legend(loc="lower right", fontsize=9, facecolor="white",
              edgecolor="#666", framealpha=0.95, markerscale=3)

    # contextily fetches Esri satellite tiles in Web Mercator (EPSG:3857)
    # and reprojects them on the fly to match our WGS84 data (EPSG:4326).
    # That's one network round-trip; the result is cached in memory.
    cx.add_basemap(
        ax,
        crs="EPSG:4326",
        source=cx.providers.Esri.WorldImagery,
        attribution_size=6,
        # Mute the satellite tiles slightly so the grey "Other" dots stay
        # readable on top of high-contrast terrain (especially the bright
        # Andes ridges).
        alpha=0.65,
    )


def plot_top_basins(ax, df: pl.DataFrame):
    """Twin horizontal bars per basin: oil and gas, each normalised to its
    own max so they're visually comparable as 'share of the leader'."""
    df = df.sort("prod_pet_m3_total")  # ascending so largest sits at top after barh
    basins = df["cuenca"].to_list()
    oil = df["prod_pet_m3_total"].to_numpy()
    gas = df["prod_gas_mm3_total"].to_numpy()

    # Normalise each fluid against its own leader so the bar lengths are
    # readable side-by-side despite the magnitude difference (oil m³ vs
    # gas Mm³). Absolute values are written next to each bar for honesty.
    oil_n = oil / oil.max()
    gas_n = gas / gas.max()

    y = range(len(basins))
    h = 0.38
    ax.barh([i + h / 2 for i in y], oil_n, height=h, color=C_OIL, label="Oil (cum.)")
    ax.barh([i - h / 2 for i in y], gas_n, height=h, color=C_GAS, label="Gas (cum.)")

    # Display in friendly units alongside each bar. Same conversions as
    # the time-series: oil m³ → million m³, gas source-Mm³ → bcm.
    for i, (o_raw, g_raw, o_n, g_n) in enumerate(zip(oil, gas, oil_n, gas_n)):
        ax.text(o_n + 0.01, i + h / 2, f"{o_raw / 1e6:,.0f} M m³",
                va="center", fontsize=8, color="black")
        ax.text(g_n + 0.01, i - h / 2, f"{g_raw / 1e6:,.0f} bcm",
                va="center", fontsize=8, color="black")

    ax.set_yticks(list(y))
    ax.set_yticklabels(basins, fontsize=9)
    ax.set_xlim(0, 1.25)
    ax.set_xticks([0, 0.5, 1.0])
    ax.set_xticklabels(["0", "50%", "100% of leader"])
    # Title uses the realised row count, not TOP_N_BASINS: the HAVING
    # filter may return fewer rows than the LIMIT asked for.
    ax.set_title(f"Top {len(basins)} basins (cuencas) by cumulative oil",
                 fontsize=12, fontweight="bold")
    ax.legend(loc="lower right", fontsize=9, framealpha=0.85)
    ax.grid(True, axis="x", alpha=0.25, linestyle="--")


# --- Main -------------------------------------------------------------------

def main() -> None:
    print("Argentina Oil & Gas — DuckDB sneak peek")
    print(f"Source: {BASE_URL}\n")

    # `:memory:` because nothing needs to persist between runs. DuckDB will
    # auto-install/load httpfs the first time we hit a https:// URL.
    conn = duckdb.connect(":memory:")

    print("Running 4 independent queries (one per panel):")
    df_oil = run_query(conn, "1/4  oil by bucket", SQL_OIL_BY_BUCKET)
    df_gas = run_query(conn, "2/4  gas by bucket", SQL_GAS_BY_BUCKET)
    df_locs = run_query(conn, "3/4  well locations", SQL_WELL_LOCATIONS)
    df_basins = run_query(conn, "4/4  top basins", SQL_TOP_BASINS)

    conn.close()

    print("\nRendering figure...")
    fig = plt.figure(figsize=(15, 10))
    gs = fig.add_gridspec(2, 2, hspace=0.32, wspace=0.22,
                          left=0.06, right=0.97, top=0.90, bottom=0.07)

    # Argentina is tall and skinny (~21° lon × 35° lat). Equal-aspect on a
    # ~square panel either wastes width with ocean or shrinks the points.
    # A nested gridspec gives the map a 1:2 width split with the bars so
    # its aspect roughly matches the country's.
    gs_bottom = gs[1, :].subgridspec(1, 2, width_ratios=[1, 2], wspace=0.20)

    # Unit conversions to friendly axes:
    #   oil: source m³            ÷ 1e6 → million m³
    #   gas: source Mm³ (mil m³)  ÷ 1e6 → bcm   (Argentine "M" = thousand)
    plot_stacked_area(fig.add_subplot(gs[0, 0]), df_oil,
                      value_col="prod_pet_m3", scale=1e6,
                      title="Monthly oil production",
                      ylabel="Oil (million m³ / month)")
    plot_stacked_area(fig.add_subplot(gs[0, 1]), df_gas,
                      value_col="prod_gas_mm3", scale=1e6,
                      title="Monthly gas production",
                      ylabel="Gas (bcm / month)")
    plot_map(fig.add_subplot(gs_bottom[0, 0]), df_locs)
    plot_top_basins(fig.add_subplot(gs_bottom[0, 1]), df_basins)

    fig.suptitle(
        "Argentina Oil & Gas — a DuckDB sneak peek at petrodb.ocortez.com",
        fontsize=16, fontweight="bold", y=0.97,
    )
    fig.text(
        0.5, 0.93,
        "Monthly production 2006–2025, four independent DuckDB queries "
        "against publicly hosted Parquet files",
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

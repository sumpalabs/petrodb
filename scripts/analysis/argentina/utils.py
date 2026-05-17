"""
Argentina Oil & Gas — shared queries + plotting for production analysis.

This module is the single source of SQL and matplotlib code shared by the
three Argentina production-analysis entrypoints:

    production_analysis_local.py            (SI,        local DuckDB)
    production_analysis_remote.py           (SI,        remote Parquet)
    production_analysis_remote_imperial.py  (Imperial,  remote Parquet)

The chosen "units" pattern: both the SQL and the plot take a `units`
parameter (Literal["si", "imperial"]). Entrypoints stay thin — pick a
data source (local DuckDB tables vs httpfs `read_parquet(...)` strings)
plus a units flag, then hand both to the shared module. A future
local-imperial variant is a two-line file.

The two source-specific scripts therefore differ only in:
  (a) the table-source SQL expressions passed into the shared queries,
  (b) the output filename / title suffix.

Data semantics (preserved from the original remote script):
    Unconv = tipo_recurso = 'NO CONVENCIONAL' (Shale + Tight).
    Other  = Conv + 'No informado' (~26% of wells) + tail.

Dependencies: duckdb, polars, matplotlib, contextily.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import contextily as cx
import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

Units = Literal["si", "imperial"]


# --- Visual / geographic constants ------------------------------------------

# Map bounding box. The northern cap at -30 latitude trims the small NOA /
# Noroeste cluster (Salta–Jujuy–Tucumán, ~996 wells) so the map zooms into
# the heart of Argentine production — Neuquén, Mendoza, Patagonia. Map-only
# filter; those wells are still counted in the time-series and basin panels.
LON_RANGE = (-74.0, -53.0)
LAT_RANGE = (-56.0, -30.0)

# Colour discipline:
#   Unconv vs Other → red / dark slate    (panels 1, 2, 3)
#   Oil    vs Gas   → green / blue        (panel 4 only)
# The two dimensions never share a panel, so there is no overload.
C_UNCONV = "#d62728"
# Dark slate (Material BlueGrey 700-ish). Pure grey was invisible against
# the satellite tile texture; this still reads as a neutral "baseline" but
# pops on both the basemap and the stacked-area panels.
C_OTHER = "#37474f"
C_OIL = "#2ca02c"
C_GAS = "#1f77b4"

DEFAULT_TOP_N_BASINS = 6


# --- Units configuration ----------------------------------------------------

# Unit conversion constants (exact, not rounded):
#   1 m³ oil = 6.2898 bbl
#   1 m³ gas = 35.3147 scf
#       source `prod_gas` is in "Mm³" (Argentine M = mil = thousand), so
#       source → m³ requires ×1000 and m³ → scf ×35.3147 → net 35,314.7.
M3_TO_BBL = 6.2898
SOURCE_MM3_TO_SCF = 35_314.7


@dataclass(frozen=True)
class UnitsConfig:
    """SQL conversions + plot styling for a unit system."""

    name: Units
    # SQL: per-panel value expressions, ready to drop into a SELECT clause.
    oil_value_expr: str
    gas_value_expr: str
    oil_total_expr: str
    gas_total_expr: str
    # SQL: aliases the queries assign to the value expressions.
    oil_value_col: str
    gas_value_col: str
    oil_total_col: str
    gas_total_col: str
    # Plot: y-axis scales (divisor applied in Python to keep matplotlib from
    # adding a `1eN` scientific multiplier on the axis).
    oil_plot_scale: float
    gas_plot_scale: float
    oil_plot_title: str
    gas_plot_title: str
    oil_plot_ylabel: str
    gas_plot_ylabel: str
    # Plot: per-bar labels for the basin panel.
    oil_total_scale: float
    gas_total_scale: float
    oil_total_label: str  # e.g. "M m³" or "Bbbl"
    gas_total_label: str  # e.g. "bcm"  or "Tcf"
    oil_total_fmt: str  # e.g. "{:,.0f}" or "{:,.2f}"
    gas_total_fmt: str


# `EXTRACT(DAY FROM LAST_DAY(m.fecha))` = number of days in the month.
# Used by the imperial variant to convert monthly volume → calendar daily
# rate (bbl/d, scf/d) server-side. Stays inside DuckDB so the raw monthly
# values never materialise on the client.
_DAYS_IN_MONTH = "EXTRACT(DAY FROM LAST_DAY(m.fecha))"

UNITS_SI = UnitsConfig(
    name="si",
    oil_value_expr="SUM(m.prod_pet)",
    gas_value_expr="SUM(m.prod_gas)",
    oil_total_expr="SUM(m.prod_pet)",
    gas_total_expr="SUM(m.prod_gas)",
    oil_value_col="prod_pet_m3",
    gas_value_col="prod_gas_mm3",
    oil_total_col="prod_pet_m3_total",
    gas_total_col="prod_gas_mm3_total",
    # oil m³ ÷ 1e6 → million m³; gas source-Mm³ ÷ 1e6 → bcm (Argentine M = thousand).
    oil_plot_scale=1e6,
    gas_plot_scale=1e6,
    oil_plot_title="Monthly oil production",
    gas_plot_title="Monthly gas production",
    oil_plot_ylabel="Oil (million m³ / month)",
    gas_plot_ylabel="Gas (bcm / month)",
    oil_total_scale=1e6,
    gas_total_scale=1e6,
    oil_total_label="M m³",
    gas_total_label="bcm",
    oil_total_fmt="{:,.0f}",
    gas_total_fmt="{:,.0f}",
)

UNITS_IMPERIAL = UnitsConfig(
    name="imperial",
    # Imperial: convert units AND divide by days in month → calendar daily rate.
    oil_value_expr=f"SUM(m.prod_pet) * {M3_TO_BBL} / {_DAYS_IN_MONTH}",
    gas_value_expr=f"SUM(m.prod_gas) * {SOURCE_MM3_TO_SCF} / {_DAYS_IN_MONTH}",
    # Cumulative totals are not divided by days — they're totals, not rates.
    oil_total_expr=f"SUM(m.prod_pet) * {M3_TO_BBL}",
    gas_total_expr=f"SUM(m.prod_gas) * {SOURCE_MM3_TO_SCF}",
    oil_value_col="oil_bbl_per_day",
    gas_value_col="gas_scf_per_day",
    oil_total_col="oil_bbl_total",
    gas_total_col="gas_scf_total",
    # Scales chosen so values land in single-digit ranges (peak ≈ 0.8 MMbbl/d, ≈ 6 Bscf/d).
    oil_plot_scale=1e6,
    gas_plot_scale=1e9,
    oil_plot_title="Oil — daily rate",
    gas_plot_title="Gas — daily rate",
    oil_plot_ylabel="Oil (MMbbl/d)",
    gas_plot_ylabel="Gas (Bscf/d)",
    oil_total_scale=1e9,
    gas_total_scale=1e12,
    oil_total_label="Bbbl",
    gas_total_label="Tcf",
    # Two decimals so small basins (e.g. Cuyana ≈ 0.04 Tcf) don't read as zero.
    oil_total_fmt="{:,.2f}",
    gas_total_fmt="{:,.2f}",
)


def get_units(name: Units) -> UnitsConfig:
    if name == "si":
        return UNITS_SI
    if name == "imperial":
        return UNITS_IMPERIAL
    raise ValueError(f"Unknown units: {name!r} (expected 'si' or 'imperial')")


# --- Query helpers ----------------------------------------------------------


def run_query(conn: duckdb.DuckDBPyConnection, label: str, sql: str) -> pl.DataFrame:
    """Run a DuckDB query, print elapsed time, return a polars frame.

    The print is the pedagogical bit: readers should *see* that each chart
    costs one query and roughly how long it takes."""
    t0 = time.perf_counter()
    df = conn.execute(sql).pl()
    dt = time.perf_counter() - t0
    print(f"  {label:<28s} {len(df):>7,d} rows  ({dt:5.1f} s)")
    return df


# Bucket CASE expression used by every per-well-classified query. The 26%
# "No informado" wells almost certainly are old conventional but the source
# doesn't say so, hence the honest "Other" label.
_BUCKET_CASE = """CASE
            WHEN w.tipo_recurso = 'NO CONVENCIONAL' THEN 'Unconv'
            ELSE 'Other'
        END AS bucket"""


def query_oil_by_bucket(
    conn: duckdb.DuckDBPyConnection,
    production_src: str,
    wells_src: str,
    units: UnitsConfig,
) -> pl.DataFrame:
    """Monthly oil per bucket (SI: m³/month, imperial: bbl/day)."""
    sql = f"""
        SELECT
            m.fecha,
            {_BUCKET_CASE},
            {units.oil_value_expr} AS {units.oil_value_col}
        FROM {production_src} m
        JOIN {wells_src} w USING (idpozo)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    return run_query(conn, "1/4  oil by bucket", sql)


def query_gas_by_bucket(
    conn: duckdb.DuckDBPyConnection,
    production_src: str,
    wells_src: str,
    units: UnitsConfig,
) -> pl.DataFrame:
    """Monthly gas per bucket (SI: Mm³/month, imperial: scf/day).

    Separate query (not a pivot of the oil result) because oil and gas live
    on different axes and each panel's SQL should stand on its own."""
    sql = f"""
        SELECT
            m.fecha,
            {_BUCKET_CASE},
            {units.gas_value_expr} AS {units.gas_value_col}
        FROM {production_src} m
        JOIN {wells_src} w USING (idpozo)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    return run_query(conn, "2/4  gas by bucket", sql)


def query_well_locations(
    conn: duckdb.DuckDBPyConnection,
    wells_src: str,
) -> pl.DataFrame:
    """Single-table scan of wells — geography is geography, no units."""
    sql = f"""
        SELECT
            coordenadax AS lon,
            coordenaday AS lat,
            CASE
                WHEN tipo_recurso = 'NO CONVENCIONAL' THEN 'Unconv'
                ELSE 'Other'
            END AS bucket
        FROM {wells_src}
        WHERE coordenadax BETWEEN {LON_RANGE[0]} AND {LON_RANGE[1]}
          AND coordenaday BETWEEN {LAT_RANGE[0]} AND {LAT_RANGE[1]}
    """
    return run_query(conn, "3/4  well locations", sql)


def query_top_basins(
    conn: duckdb.DuckDBPyConnection,
    production_src: str,
    wells_src: str,
    units: UnitsConfig,
    top_n: int = DEFAULT_TOP_N_BASINS,
) -> pl.DataFrame:
    """Top-N basins by cumulative oil; gas comes along for the ride.

    A handful of basins (ÑIRIHUAU, NORESTE, CAÑADON ASFALTO, …) appear in
    `wells` with either zero or trivial (a few thousand m³) production; the
    HAVING > 1 Mm³ filter drops them so the chart only ranks basins that
    actually produced at meaningful scale. The threshold is in source m³
    (~6.3 million bbl) so the filter behaves the same in both unit systems."""
    sql = f"""
        SELECT
            w.cuenca,
            {units.oil_total_expr} AS {units.oil_total_col},
            {units.gas_total_expr} AS {units.gas_total_col}
        FROM {production_src} m
        JOIN {wells_src} w USING (idpozo)
        WHERE w.cuenca IS NOT NULL
        GROUP BY w.cuenca
        HAVING SUM(m.prod_pet) > 1e6
        ORDER BY {units.oil_total_col} DESC
        LIMIT {top_n}
    """
    return run_query(conn, "4/4  top basins", sql)


# --- Plot helpers -----------------------------------------------------------


def _plot_stacked_area(
    ax,
    df: pl.DataFrame,
    value_col: str,
    scale: float,
    title: str,
    ylabel: str,
) -> None:
    """Pivot (fecha, bucket, value) to wide and draw a stacked area."""
    wide = df.pivot(values=value_col, index="fecha", on="bucket").sort("fecha")
    dates = wide["fecha"].to_list()
    other = (wide["Other"].fill_null(0) / scale).to_list()
    unconv = (wide["Unconv"].fill_null(0) / scale).to_list()

    # Order matters: Other on the bottom (grey baseline), Unconv on top so
    # the growth wedge reads as the figure's punchline.
    ax.stackplot(
        dates,
        other,
        unconv,
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


def _plot_map(ax, df: pl.DataFrame) -> None:
    """Scatter wells over an Esri WorldImagery satellite basemap."""
    other = df.filter(pl.col("bucket") == "Other")
    unconv = df.filter(pl.col("bucket") == "Unconv")

    # Other goes down first as a low-alpha cloud — it traces the country's
    # producing-well distribution like a faint shadow. Unconv goes on top,
    # bigger and brighter, so the Vaca Muerta cluster pops in Neuquén.
    ax.scatter(
        other["lon"],
        other["lat"],
        s=2.5,
        c=C_OTHER,
        alpha=0.45,
        linewidths=0,
        label=f"Other ({len(other):,})",
    )
    ax.scatter(
        unconv["lon"],
        unconv["lat"],
        s=8,
        c=C_UNCONV,
        alpha=0.85,
        linewidths=0,
        label=f"Unconv ({len(unconv):,})",
    )

    ax.set_xlim(LON_RANGE)
    ax.set_ylim(LAT_RANGE)
    # `datalim` lets matplotlib widen the lat/lon limits so the panel fills
    # without distorting the basemap tiles. Argentina is tall and skinny.
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(
        "Well locations — Unconventional vs Other",
        fontsize=12,
        fontweight="bold",
    )
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    # Legend sits over open Atlantic on the right so wells along the Andes
    # / Patagonia aren't obscured. Opaque white face so the grey marker
    # reads against the semi-transparent satellite tile beneath it.
    ax.legend(
        loc="lower right",
        fontsize=9,
        facecolor="white",
        edgecolor="#666",
        framealpha=0.95,
        markerscale=3,
    )
    # contextily fetches Esri satellite tiles in Web Mercator (EPSG:3857)
    # and reprojects them on the fly to match our WGS84 data (EPSG:4326).
    cx.add_basemap(
        ax,
        crs="EPSG:4326",
        source=cx.providers.Esri.WorldImagery,
        attribution_size=6,
        # Mute the tiles slightly so the grey "Other" dots stay readable.
        alpha=0.65,
    )


def _plot_top_basins(ax, df: pl.DataFrame, units: UnitsConfig) -> None:
    """Twin horizontal bars per basin (oil + gas), each normalised to its
    own leader so they're visually comparable despite the magnitude gap."""
    df = df.sort(units.oil_total_col)  # ascending so largest sits at top after barh
    basins = df["cuenca"].to_list()
    oil = df[units.oil_total_col].to_numpy()
    gas = df[units.gas_total_col].to_numpy()

    oil_n = oil / oil.max()
    gas_n = gas / gas.max()

    y = range(len(basins))
    h = 0.38
    ax.barh([i + h / 2 for i in y], oil_n, height=h, color=C_OIL, label="Oil (cum.)")
    ax.barh([i - h / 2 for i in y], gas_n, height=h, color=C_GAS, label="Gas (cum.)")

    for i, (o_raw, g_raw, o_n, g_n) in enumerate(zip(oil, gas, oil_n, gas_n)):
        ax.text(
            o_n + 0.01,
            i + h / 2,
            f"{units.oil_total_fmt.format(o_raw / units.oil_total_scale)} {units.oil_total_label}",
            va="center",
            fontsize=8,
            color="black",
        )
        ax.text(
            g_n + 0.01,
            i - h / 2,
            f"{units.gas_total_fmt.format(g_raw / units.gas_total_scale)} {units.gas_total_label}",
            va="center",
            fontsize=8,
            color="black",
        )

    ax.set_yticks(list(y))
    ax.set_yticklabels(basins, fontsize=9)
    ax.set_xlim(0, 1.25)
    ax.set_xticks([0, 0.5, 1.0])
    ax.set_xticklabels(["0", "50%", "100% of leader"])
    # Title uses the realised row count, not TOP_N: the HAVING filter may
    # return fewer rows than the LIMIT asked for.
    ax.set_title(
        f"Top {len(basins)} basins (cuencas) by cumulative oil",
        fontsize=12,
        fontweight="bold",
    )
    ax.legend(loc="lower right", fontsize=9, framealpha=0.85)
    ax.grid(True, axis="x", alpha=0.25, linestyle="--")


def create_production_visualizations(
    df_oil: pl.DataFrame,
    df_gas: pl.DataFrame,
    df_locs: pl.DataFrame,
    df_basins: pl.DataFrame,
    output_path: str,
    units: UnitsConfig,
    *,
    suptitle: str,
    subtitle: str,
    source_caption: str,
) -> None:
    """Render the four-panel figure for whichever (units, source) combo the
    entrypoint chose. Layout is fixed across all combos so the panels line up
    visually for any pair of (local, remote) renders."""
    print("\nRendering figure...")
    fig = plt.figure(figsize=(15, 10))
    gs = fig.add_gridspec(
        2,
        2,
        hspace=0.32,
        wspace=0.22,
        left=0.06,
        right=0.97,
        top=0.90,
        bottom=0.07,
    )
    # Argentina is tall and skinny (~21° lon × 35° lat). Equal-aspect on a
    # ~square panel either wastes width with ocean or shrinks the points.
    # A nested gridspec gives the map a 1:2 width split with the bars.
    gs_bottom = gs[1, :].subgridspec(1, 2, width_ratios=[1, 2], wspace=0.20)

    _plot_stacked_area(
        fig.add_subplot(gs[0, 0]),
        df_oil,
        value_col=units.oil_value_col,
        scale=units.oil_plot_scale,
        title=units.oil_plot_title,
        ylabel=units.oil_plot_ylabel,
    )
    _plot_stacked_area(
        fig.add_subplot(gs[0, 1]),
        df_gas,
        value_col=units.gas_value_col,
        scale=units.gas_plot_scale,
        title=units.gas_plot_title,
        ylabel=units.gas_plot_ylabel,
    )
    _plot_map(fig.add_subplot(gs_bottom[0, 0]), df_locs)
    _plot_top_basins(fig.add_subplot(gs_bottom[0, 1]), df_basins, units)

    fig.suptitle(suptitle, fontsize=16, fontweight="bold", y=0.97)
    fig.text(
        0.5,
        0.93,
        subtitle,
        ha="center",
        fontsize=10,
        style="italic",
        color="#444",
    )
    fig.text(
        0.06,
        0.012,
        "Unconv = tipo_recurso = 'NO CONVENCIONAL' (Shale + Tight). "
        "Other = Conv + 'No informado' (~26% of wells) + tail.",
        fontsize=8,
        color="#555",
    )
    # Two-line attribution: full upstream URL on top (small), data source
    # on the line below (varies by entrypoint).
    fig.text(
        0.97,
        0.025,
        "Original data: datos.gob.ar/dataset/energia-produccion-petroleo-gas-por-pozo-capitulo-iv",
        ha="right",
        fontsize=7,
        color="#555",
    )
    fig.text(
        0.97,
        0.010,
        source_caption,
        ha="right",
        fontsize=8,
        color="#555",
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    print(f"✓ Saved: {output_path}")


# --- Remote-source helpers --------------------------------------------------

# Year-partitioned hive-style layout (`monthly_production/anio=YYYY/data.parquet`).
# Static HTTP can't do directory listings so a `*` glob in the URL fails,
# and DuckDB doesn't accept a subquery inside `read_parquet(...)`. Cheapest
# robust pattern: enumerate the years in Python, bake the URL list into the
# SQL as a literal array. Bump the upper bound when new partitions land.
# `hive_partitioning = true` recovers the `anio` column from the file path
# so DuckDB can prune partitions on a year filter.
DEFAULT_PRODUCTION_YEARS = range(2006, 2026)


def build_remote_sources(
    base_url: str,
    production_years: range = DEFAULT_PRODUCTION_YEARS,
) -> tuple[str, str]:
    """Return (production_src, wells_src) `read_parquet(...)` expressions
    for the remote httpfs entrypoints."""
    urls = ",\n            ".join(
        f"'{base_url}/monthly_production/anio={y}/data.parquet'"
        for y in production_years
    )
    production_src = f"""read_parquet(
        [
            {urls}
        ],
        hive_partitioning = true
    )"""
    wells_src = f"read_parquet('{base_url}/wells.parquet')"
    return production_src, wells_src


# --- Pipeline ---------------------------------------------------------------


def run_production_analysis(
    conn: duckdb.DuckDBPyConnection,
    production_src: str,
    wells_src: str,
    output_path: str,
    units: UnitsConfig,
    *,
    suptitle: str,
    subtitle: str,
    source_caption: str,
    top_n_basins: int = DEFAULT_TOP_N_BASINS,
) -> None:
    """End-to-end: run the four queries, render the figure.

    This is the function entrypoints call; they own the connection (which
    differs between local DuckDB file vs in-memory + httpfs) and the human
    text (titles, captions, output path), and delegate everything else."""
    print("Running 4 independent queries (one per panel):")
    df_oil = query_oil_by_bucket(conn, production_src, wells_src, units)
    df_gas = query_gas_by_bucket(conn, production_src, wells_src, units)
    df_locs = query_well_locations(conn, wells_src)
    df_basins = query_top_basins(
        conn, production_src, wells_src, units, top_n=top_n_basins
    )

    create_production_visualizations(
        df_oil=df_oil,
        df_gas=df_gas,
        df_locs=df_locs,
        df_basins=df_basins,
        output_path=output_path,
        units=units,
        suptitle=suptitle,
        subtitle=subtitle,
        source_caption=source_caption,
    )

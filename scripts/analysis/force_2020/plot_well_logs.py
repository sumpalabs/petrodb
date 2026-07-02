# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "duckdb",
#     "polars",
#     "matplotlib",
#     "numpy",
#     "pyarrow",
# ]
# ///
"""
FORCE 2020 Well Log Plot

Fetches well data from petrodb remote parquet files and produces a 3-track
vertical well log plot: GR, Density/Neutron, and Deep Resistivity.

Usage:
    uv run plot_well_logs.py <well_name> [--top TOP] [--base BASE]

Example:
    uv run plot_well_logs.py 15-9-13
    uv run plot_well_logs.py 15-9-13 --top 1000 --base 2000
"""

import argparse
import os
import sys
from pathlib import Path

import duckdb
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import polars as pl

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Data lives on Hugging Face (ADR-0005); `resolve` URLs honour HTTP Range so
# DuckDB `httpfs` fetches only the row groups a query needs. Override with the
# `BASE_URL` env var to point at a local Caddy dev host or a frozen HF revision.
BASE_URL = (
    os.environ.get(
        "BASE_URL", "https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main"
    ).rstrip("/")
    + "/force_2020/wells"
)
COLUMNS = ["DEPTH_MD", "GR", "RHOB", "NPHI", "RDEP"]

# Track scales
GR_MIN, GR_MAX = 0, 150
RHOB_MIN, RHOB_MAX = 1.95, 2.95
NPHI_MIN, NPHI_MAX = 0.45, -0.15  # reversed: high porosity on left
RDEP_MIN, RDEP_MAX = 0.2, 200

OUTPUT_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------
def fetch_well_data(
    well_name: str, top: float | None = None, base: float | None = None
) -> pl.DataFrame:
    url = f"{BASE_URL}/{well_name}.parquet"
    cols = ", ".join(COLUMNS)
    where = ""
    if top is not None or base is not None:
        clauses = []
        if top is not None:
            clauses.append(f"DEPTH_MD >= {top}")
        if base is not None:
            clauses.append(f"DEPTH_MD <= {base}")
        where = " WHERE " + " AND ".join(clauses)

    query = f"SELECT {cols} FROM read_parquet('{url}'){where} ORDER BY DEPTH_MD"
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    result = con.execute(query).pl()
    con.close()
    return result


# ---------------------------------------------------------------------------
# Track plotting helpers
# ---------------------------------------------------------------------------
def plot_gr_track(ax, depth, gr):
    """GR track with colormap fill using 100 color-index bands."""
    ax.set_xlim(GR_MIN, GR_MAX)
    ax.set_xlabel("GR (API)", fontsize=9)
    ax.xaxis.set_label_position("top")
    ax.xaxis.tick_top()
    ax.grid(True, alpha=0.3)
    ax.set_ylabel("Depth (m MD)")

    span = abs(GR_MIN - GR_MAX)
    cmap = mcolors.LinearSegmentedColormap.from_list("gr", ["#FFD700", "#006400"])
    color_index = np.arange(GR_MIN, GR_MAX, span / 100)

    for index in color_index:
        color = cmap((index - GR_MIN) / span)
        ax.fill_betweenx(depth, GR_MIN, gr, where=gr >= index, color=color)

    ax.plot(gr, depth, color="black", linewidth=0.5)


def plot_density_neutron_track(ax, depth, rhob, nphi):
    """Density + Neutron with crossover fill.

    Each curve is plotted on its own axis in native units. NPHI is mapped
    into RHOB-axis space only for the fill_betweenx calls.
    """
    # Primary axis — RHOB
    ax.set_xlim(RHOB_MIN, RHOB_MAX)
    ax.set_xlabel("RHOB (g/cc)", fontsize=9)
    ax.xaxis.label.set_color("red")
    ax.xaxis.set_label_position("top")
    ax.xaxis.tick_top()
    ax.tick_params(axis="x", labelsize=7, colors="red")
    ax.spines["top"].set_edgecolor("red")
    ax.grid(True, alpha=0.3)

    print(f"NPHI min: {nphi.min()}, max: {nphi.max()}")

    # Twin axis for NPHI — reversed: 0.45 left, -0.15 right
    ax2 = ax.twiny()
    ax2.set_xlim(NPHI_MIN, NPHI_MAX)
    ax2.set_xlabel("NPHI (v/v)", fontsize=9)
    ax2.xaxis.label.set_color("blue")
    ax2.spines["top"].set_position(("axes", 1.08))
    ax2.spines["top"].set_edgecolor("blue")
    ax2.tick_params(axis="x", labelsize=7, colors="blue")
    ax2.xaxis.set_ticks_position("top")
    ax2.xaxis.set_label_position("top")

    # Re-apply after twiny() steals the top position from ax
    ax.xaxis.set_ticks_position("top")
    ax.xaxis.set_label_position("top")

    # Map NPHI into RHOB-axis space for fill_betweenx
    x = np.array(ax.get_xlim())
    z = np.array(ax2.get_xlim())
    nphi_mapped = ((nphi - np.max(z)) / (np.min(z) - np.max(z))) * (np.max(x) - np.min(x)) + np.min(x)

    # Shale: density to the RIGHT of neutron → green
    ax.fill_betweenx(depth, rhob, nphi_mapped,
                     where=rhob >= nphi_mapped, interpolate=True, color="green", alpha=0.5)
    # Sand/gas crossover: density to the LEFT of neutron → yellow
    ax.fill_betweenx(depth, rhob, nphi_mapped,
                     where=rhob <= nphi_mapped, interpolate=True, color="yellow", alpha=0.5)

    ax.plot(rhob, depth, color="red", linewidth=0.8)
    ax2.plot(nphi, depth, color="blue", linewidth=0.8)


def plot_resistivity_track(ax, depth, rdep):
    """Deep resistivity on logarithmic scale."""
    ax.set_xscale("log")
    ax.set_xlim(RDEP_MIN, RDEP_MAX)
    ax.set_xlabel("RDEP (ohm.m)", fontsize=9)
    ax.xaxis.set_label_position("top")
    ax.xaxis.tick_top()
    ax.grid(True, which="both", alpha=0.3)
    ax.plot(rdep, depth, color="black", linewidth=0.8)


# ---------------------------------------------------------------------------
# Main plot assembly
# ---------------------------------------------------------------------------
def create_well_log_plot(
    df: pl.DataFrame, well_name: str, top: float | None, base: float | None
) -> Path:
    depth = df["DEPTH_MD"].to_numpy()
    gr = df["GR"].to_numpy()
    rhob = df["RHOB"].to_numpy()
    nphi = df["NPHI"].to_numpy()
    rdep = df["RDEP"].to_numpy()

    fig, axes = plt.subplots(1, 3, figsize=(10, 16), sharey=True)
    fig.suptitle(f"Well: {well_name}", fontsize=14, fontweight="bold", y=0.98)

    # Invert depth axis (shared)
    axes[0].invert_yaxis()

    print("Plotting GR track...")
    plot_gr_track(axes[0], depth, gr)
    print("Plotting Density/Neutron track...")
    plot_density_neutron_track(axes[1], depth, rhob, nphi)
    print("Plotting Resistivity track...")
    plot_resistivity_track(axes[2], depth, rdep)

    # Show y-tick labels only on the first track
    axes[1].tick_params(labelleft=False)
    axes[2].tick_params(labelleft=False)

    # Manual layout: leave room at top for double axis header and suptitle
    fig.subplots_adjust(left=0.08, right=0.97, top=0.84, bottom=0.04, wspace=0.08)

    out_path = OUTPUT_DIR / f"{well_name}_logs.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# CLI
def main():
    parser = argparse.ArgumentParser(description="Plot FORCE 2020 well logs")
    parser.add_argument("well_name", help="Well name, e.g. 15-9-13")
    parser.add_argument("--top", type=float, default=None, help="Top depth (m MD)")
    parser.add_argument("--base", type=float, default=None, help="Base depth (m MD)")
    args = parser.parse_args()

    print(f"Fetching data for well {args.well_name}...")
    df = fetch_well_data(args.well_name, args.top, args.base)
    print(f"  Rows: {len(df)}, Depth range: {df['DEPTH_MD'].min():.1f} - {df['DEPTH_MD'].max():.1f} m")

    # Drop rows where all log columns are null
    log_cols = ["GR", "RHOB", "NPHI", "RDEP"]
    df = df.filter(~pl.all_horizontal(pl.col(c).is_null() for c in log_cols))
    print(f"  Rows after filtering nulls: {len(df)}")

    out = create_well_log_plot(df, args.well_name, args.top, args.base)
    print(f"Plot saved to {out}")


if __name__ == "__main__":
    main()

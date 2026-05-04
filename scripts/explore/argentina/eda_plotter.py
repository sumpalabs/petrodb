"""Twelve matplotlib PNGs that summarize the Argentina source data.

Each plot is a deterministic re-rendering off the staged DuckDB tables and
the volatility / gap-audit / reconciliation outputs already on disk. Plots
are written into `<output_dir>/` so `findings_writer` can embed them.
"""

from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PLOTS = (
    "01_annual_production_volume.png",
    "02_active_wells_per_year.png",
    "03_wells_per_basin.png",
    "04_wells_per_province.png",
    "05_operator_volatility_distribution.png",
    "06_state_volatility_distribution.png",
    "07_extraction_volatility_distribution.png",
    "08_gap_count_distribution.png",
    "09_longest_gap_distribution.png",
    "10_resource_type_distribution.png",
    "11_classification_distribution.png",
    "12_geometry_coverage_map.png",
)


def _save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=100, bbox_inches="tight")
    plt.close(fig)


def _bar(
    con: duckdb.DuckDBPyConnection, sql: str, title: str, xlabel: str
) -> plt.Figure:
    rows = con.execute(sql).fetchall()
    labels = [str(r[0]) if r[0] is not None else "(null)" for r in rows]
    values = [r[1] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 5))
    if rows:
        ax.bar(labels, values)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("count")
    if rows and len(labels) > 6:
        ax.tick_params(axis="x", labelrotation=60)
    fig.tight_layout()
    return fig


def _hist(values: list[float], title: str, xlabel: str, bins: int = 20) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8, 5))
    if values:
        ax.hist(values, bins=bins)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("wells")
    fig.tight_layout()
    return fig


def plot(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = con.execute(
        """
        SELECT CAST(anio AS INTEGER) AS anio,
               SUM(prod_pet) AS oil,
               SUM(prod_gas) AS gas,
               SUM(prod_agua) AS water
        FROM stg_production
        WHERE anio IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """
    ).fetchall()
    fig, ax = plt.subplots(figsize=(9, 5))
    if rows:
        anios = [r[0] for r in rows]
        for series_idx, label in enumerate(("oil", "gas", "water"), start=1):
            ax.plot(anios, [r[series_idx] or 0 for r in rows], marker="o", label=label)
        ax.legend()
    ax.set_title("Annual production volume (oil, gas, water)")
    ax.set_xlabel("year")
    ax.set_ylabel("volume (source units)")
    fig.tight_layout()
    _save(fig, output_dir / PLOTS[0])

    fig = _bar(
        con,
        """
        SELECT CAST(anio AS INTEGER), COUNT(DISTINCT idpozo)
        FROM stg_production WHERE anio IS NOT NULL GROUP BY 1 ORDER BY 1
        """,
        "Active wells per year",
        "year",
    )
    _save(fig, output_dir / PLOTS[1])

    fig = _bar(
        con,
        """
        SELECT cuenca, COUNT(DISTINCT idpozo)
        FROM stg_capitulo_iv GROUP BY 1 ORDER BY 2 DESC LIMIT 20
        """,
        "Wells per basin (capitulo-iv)",
        "cuenca",
    )
    _save(fig, output_dir / PLOTS[2])

    fig = _bar(
        con,
        """
        SELECT provincia, COUNT(DISTINCT idpozo)
        FROM stg_capitulo_iv GROUP BY 1 ORDER BY 2 DESC LIMIT 20
        """,
        "Wells per province (capitulo-iv)",
        "provincia",
    )
    _save(fig, output_dir / PLOTS[3])

    operator_distinct = [
        r[0]
        for r in con.execute(
            """
            SELECT COUNT(DISTINCT idempresa)
            FROM stg_production
            WHERE idempresa IS NOT NULL
            GROUP BY idpozo
            """
        ).fetchall()
    ]
    fig = _hist(
        operator_distinct,
        "Operator-volatility distribution (distinct idempresa per well)",
        "distinct idempresa",
        bins=max(1, min(20, max(operator_distinct) if operator_distinct else 1)),
    )
    _save(fig, output_dir / PLOTS[4])

    state_distinct = [
        r[0]
        for r in con.execute(
            """
            SELECT COUNT(DISTINCT tipoestado)
            FROM stg_production
            WHERE tipoestado IS NOT NULL
            GROUP BY idpozo
            """
        ).fetchall()
    ]
    fig = _hist(
        state_distinct,
        "State-volatility distribution (distinct tipoestado per well)",
        "distinct tipoestado",
        bins=max(1, min(20, max(state_distinct) if state_distinct else 1)),
    )
    _save(fig, output_dir / PLOTS[5])

    extraction_distinct = [
        r[0]
        for r in con.execute(
            """
            SELECT COUNT(DISTINCT tipoextraccion)
            FROM stg_production
            WHERE tipoextraccion IS NOT NULL
            GROUP BY idpozo
            """
        ).fetchall()
    ]
    fig = _hist(
        extraction_distinct,
        "Extraction-volatility distribution (distinct tipoextraccion per well)",
        "distinct tipoextraccion",
        bins=max(1, min(20, max(extraction_distinct) if extraction_distinct else 1)),
    )
    _save(fig, output_dir / PLOTS[6])

    gap_audit_path = output_dir / "gap_audit.parquet"
    if gap_audit_path.exists():
        gap_counts = [
            r[0]
            for r in con.execute(
                f"SELECT gap_count FROM read_parquet('{gap_audit_path}')"
            ).fetchall()
        ]
        longest_gaps = [
            r[0]
            for r in con.execute(
                f"SELECT longest_gap_months FROM read_parquet('{gap_audit_path}')"
            ).fetchall()
        ]
    else:
        gap_counts = []
        longest_gaps = []
    fig = _hist(gap_counts, "Per-well source-month gap count", "gap count", bins=30)
    _save(fig, output_dir / PLOTS[7])
    fig = _hist(
        longest_gaps,
        "Per-well longest source-month gap",
        "longest gap (months)",
        bins=30,
    )
    _save(fig, output_dir / PLOTS[8])

    fig = _bar(
        con,
        """
        SELECT tipo_recurso, COUNT(*)
        FROM stg_capitulo_iv GROUP BY 1 ORDER BY 2 DESC
        """,
        "Wells by resource type (capitulo-iv)",
        "tipo_recurso",
    )
    _save(fig, output_dir / PLOTS[9])

    fig = _bar(
        con,
        """
        SELECT clasificacion, COUNT(*)
        FROM stg_capitulo_iv GROUP BY 1 ORDER BY 2 DESC
        """,
        "Wells by classification (capitulo-iv)",
        "clasificacion",
    )
    _save(fig, output_dir / PLOTS[10])

    coords = con.execute(
        """
        SELECT coordenadax, coordenaday
        FROM stg_listado
        WHERE coordenadax IS NOT NULL AND coordenaday IS NOT NULL
        """
    ).fetchall()
    fig, ax = plt.subplots(figsize=(7, 7))
    if coords:
        ax.scatter([c[0] for c in coords], [c[1] for c in coords], s=2, alpha=0.5)
    ax.set_title("Well geometry coverage (listado coordenadax/y)")
    ax.set_xlabel("coordenadax")
    ax.set_ylabel("coordenaday")
    fig.tight_layout()
    _save(fig, output_dir / PLOTS[11])

"""Generate the Volve/FORCE-style documentation deliverables for Argentina.

Produces four artifacts under the dataset root:

- `schema.json` — machine-readable column list, types, nullability, PKs, FKs.
- `schema.sql` — DDL that mirrors the published structure in a fresh DuckDB.
- `schema.md`  — English column docs, table relationships, the four-bucket
  rationale, plus a glossary covering opaque source codes such as `tef`
  and `vida_util`.
- `README.md`  — dataset overview + four canonical DuckDB query examples
  (single-well, year-range, basin-aggregate, manifest-driven via
  `generate_series`).

All prose in the published artifacts is English. Column identifiers and
data values are preserved verbatim in their source Spanish (`idpozo`,
`cuenca`, `prod_pet`, …) — only the *explanations about* them are
translated.

The column list and types are reflected from the published Parquets via
`DESCRIBE SELECT * FROM read_parquet(...)` so the published schema cannot
drift from the data. Primary keys, foreign keys, and column descriptions
are not derivable from Parquet metadata, so they live as module-level
constants here — the single source of truth for the documented contract.
"""

import json
import os
from pathlib import Path

import duckdb

TABLE_ORDER = (
    "wells",
    "well_operator_history",
    "well_events",
    "monthly_production",
)

TABLE_DESCRIPTIONS = {
    "wells": (
        "Static well master. One row per `idpozo` (~85,418 wells, "
        "including ~113 orphans from `capitulo-iv` flagged with "
        "`has_production = false`)."
    ),
    "well_operator_history": (
        "Operator history per well (slowly-changing dimension). One row "
        "per contiguous run of `idempresa` per `idpozo`. Runs with a NULL "
        "`idempresa` are preserved as-is: the absence of an operator is "
        "information carried by the source."
    ),
    "well_events": (
        "Operational state events. One row per month in which any of "
        "`(tipoestado, tipoextraccion, tipopozo)` changed. The first row "
        "of every well is included as the transition into its starting "
        "state; single-month flips are not smoothed."
    ),
    "monthly_production": (
        "Monthly time series of numeric measurements. One row per "
        "`(idpozo, fecha)` for every month in `[first_row, last_row]` "
        "per well (gaps are filled with NULL measurements). Hive-"
        "partitioned by `anio` (`monthly_production/anio=YYYY/data.parquet`) "
        "and internally sorted by `(idpozo, fecha)` so row-group "
        "statistics let single-well queries over `httpfs` prune."
    ),
}

PRIMARY_KEYS = {
    "wells": ("idpozo",),
    "well_operator_history": ("idpozo", "valid_from"),
    "well_events": ("idpozo", "event_date"),
    "monthly_production": ("idpozo", "fecha"),
}

FOREIGN_KEYS = {
    "well_operator_history": (
        {
            "column": "idpozo",
            "references_table": "wells",
            "references_column": "idpozo",
        },
    ),
    "well_events": (
        {
            "column": "idpozo",
            "references_table": "wells",
            "references_column": "idpozo",
        },
    ),
    "monthly_production": (
        {
            "column": "idpozo",
            "references_table": "wells",
            "references_column": "idpozo",
        },
    ),
}

# English, plain-language descriptions for every published column. The
# glossary in `schema.md` is generated from this table, so opaque source
# codes like `tef` and `vida_util` get a one-shot definition. Column
# identifiers are kept verbatim in their source Spanish.
COLUMN_DESCRIPTIONS = {
    # wells — identity and labels
    "idpozo": "Integer well identifier (wellbore × producing formation). Primary key of the model.",
    "sigla": "Human-readable well code (e.g. `YPF.BLO.x-8`). Treated as a label, possibly mutable; not the PK.",
    "formprod": "Producing formation of the well. Static attribute of `idpozo` (encoded in the ID).",
    "codigopropio": "Internal code assigned by the operator in the `listado` registry.",
    "nombrepropio": "Internal name assigned by the operator in the `listado` registry.",
    # wells — location
    "area": "Permit or concession area where the well is located.",
    "cod_area": "Code of the permit/concession area.",
    "yacimiento": "Field (yacimiento) where the well is located.",
    "cod_yacimiento": "Code of the field (yacimiento).",
    "cuenca": "Sedimentary basin.",
    "provincia": "Argentine province where the well is located.",
    "idcuenca": "Basin code.",
    "idprovincia": "Province code.",
    # wells — geophysics
    "formacion": "Geological formation reported for the well.",
    "cota": "Surface elevation (m above sea level).",
    "profundidad": "Final well depth (m).",
    # wells — classification
    "clasificacion": "Regulatory well classification (e.g. `Petrolífero`, `Gasífero`).",
    "subclasificacion": "Regulatory sub-classification.",
    "tipo_recurso": "Resource type (e.g. `Convencional`, `No Convencional`).",
    "sub_tipo_recurso": "Resource subtype (e.g. `Shale`, `Tight`).",
    "gasplus": "Gas Plus programme indicator (capítulo IV source).",
    "proyecto": "Project the well belongs to (carried over from the production source).",
    # wells — initial operator
    "empresa": (
        "Operator associated with the run (in `wells`: initial operator from the "
        "capítulo IV record; in `well_operator_history`: display name of the interval)."
    ),
    # wells — spatial
    "coordenadax": "Well X coordinate (in the system reported by the `listado` registry).",
    "coordenaday": "Well Y coordinate (in the system reported by the `listado` registry).",
    "geom": "Well geometry as WKB (BLOB). Decodable with `ST_GeomFromWKB(geom)` (the `spatial` extension).",
    # wells — dates
    "adjiv_fecha_inicio_perf": "Drilling start date (capítulo IV).",
    "adjiv_fecha_fin_perf": "Drilling end date (capítulo IV).",
    "adjiv_fecha_inicio_term": "Completion start date (capítulo IV).",
    "adjiv_fecha_fin_term": "Completion end date (capítulo IV).",
    "adjiv_fecha_inicio": "Start date reported in the `listado` registry.",
    "adjiv_fecha_fin": "End date reported in the `listado` registry.",
    "adjiv_fecha_abandono": "Well abandonment date, if applicable.",
    "adjiv_equipo_utilizar": "Drilling rig used.",
    "adjiv_capacidad_perf": "Drilling capacity of the rig.",
    # wells — initial rates (static discovery test)
    "pet_inicial": "Initial oil rate from the discovery test (m³/d).",
    "gas_inicial": "Initial gas rate from the discovery test (Mm³/d).",
    "agua_inicial": "Initial water rate from the discovery test (m³/d).",
    "iny_agua_inicial": "Initial water injection reported in the test (m³/d).",
    "iny_gas_inicial": "Initial gas injection reported in the test (Mm³/d).",
    "iny_otros_inicial": "Initial injection of other fluids reported in the test.",
    "iny_co2_inicial": "Initial CO₂ injection reported in the test.",
    "vida_util_inicial": "Estimated useful life at the time of the initial test (months).",
    "has_production": (
        "`true` if the `idpozo` ever appears in monthly production; `false` for "
        "capítulo IV orphan wells that never produced."
    ),
    # well_operator_history
    "idempresa": "Alphanumeric operator code (`Z001`, `APEA`, …). Stored as VARCHAR.",
    "valid_from": "First month of the contiguous operator run (DATE, first of month, inclusive).",
    "valid_to": "Last month of the contiguous operator run (DATE, first of month, inclusive).",
    # well_events
    "event_date": "Month of the operational-state snapshot (DATE, first of month).",
    "tipoestado": "Operational state of the well (e.g. `Extracción Efectiva`, `Parado Transitoriamente`).",
    "tipoextraccion": "Extraction method (e.g. `Bombeo Mecánico`, `Surgente`).",
    "tipopozo": "Well type by fluid (e.g. `Petrolífero`, `Gasífero`, `Inyector`).",
    # monthly_production
    "fecha": "Measurement month (DATE, first day of month, derived from the source's `anio`/`mes`).",
    "prod_pet": "Monthly oil production (m³).",
    "prod_gas": "Monthly gas production (Mm³).",
    "prod_agua": "Monthly water production (m³).",
    "iny_agua": "Monthly water injection (m³).",
    "iny_gas": "Monthly gas injection (Mm³).",
    "iny_co2": "Monthly CO₂ injection.",
    "iny_otro": "Monthly injection of other fluids.",
    "tef": "Effective production time for the month — *Tiempo Efectivo de Producción* (hours).",
    "vida_util": "Declared useful life of the well in the month — *vida útil* (months).",
}

DROPPED_COLUMNS = (
    "geojson",
    "observaciones",
    "idusuario",
    "rectificado",
    "habilitado",
    "fechaingreso",
    "fecha_data",
)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    """Reflect the published Parquets and write the four documentation artifacts.

    `output_dir` is the dataset root (i.e. where `wells.parquet` lives).
    All writes are full overwrites so the call is idempotent.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    schemas = _reflect_schemas(con, output_dir)
    _write_schema_json(schemas, output_dir / "schema.json")
    _write_schema_sql(schemas, output_dir / "schema.sql")
    _write_schema_md(schemas, output_dir / "schema.md")
    _write_readme(schemas, output_dir / "README.md")


# ---------------------------------------------------------------------------
# Reflection from published parquets
# ---------------------------------------------------------------------------


def _parquet_path(table: str, output_dir: Path) -> str:
    """Resolve the read path for `read_parquet` per published table.

    `monthly_production` is hive-partitioned, so we reflect from one
    partition file with `hive_partitioning = false` to see only the
    columns physically stored in the file (the partition column reappears
    via directory inference and is not part of the file schema).
    """
    if table == "monthly_production":
        partition = next(
            iter(
                sorted((output_dir / "monthly_production").glob("anio=*/data.parquet"))
            )
        )
        return f"read_parquet('{partition}', hive_partitioning = false)"
    return f"read_parquet('{output_dir / f'{table}.parquet'}')"


def _reflect_schemas(
    con: duckdb.DuckDBPyConnection, output_dir: Path
) -> dict[str, dict]:
    """For every published table, reflect column list + types from the parquet.

    Returns a dict keyed by table name with values of the form:
        {"columns": [{"name", "type", "not_null", "primary_key"}, ...],
         "primary_key": ("col1", ...),
         "foreign_keys": (...,),
         "description": "..."}
    PKs cannot be NULL, so the PK declaration overrides whatever DESCRIBE
    reports for those columns.
    """
    schemas: dict[str, dict] = {}
    for table in TABLE_ORDER:
        described = con.execute(
            f"DESCRIBE SELECT * FROM {_parquet_path(table, output_dir)}"
        ).fetchall()
        pk = PRIMARY_KEYS[table]
        columns = [
            {
                "name": row[0],
                "type": row[1],
                "not_null": row[0] in pk or row[2] == "NO",
                "primary_key": row[0] in pk,
            }
            for row in described
        ]
        schemas[table] = {
            "columns": columns,
            "primary_key": pk,
            "foreign_keys": FOREIGN_KEYS.get(table, ()),
            "description": TABLE_DESCRIPTIONS[table],
        }
    return schemas


# ---------------------------------------------------------------------------
# schema.json
# ---------------------------------------------------------------------------


def _write_schema_json(schemas: dict[str, dict], path: Path) -> None:
    payload = {
        "dataset": "argentina",
        "description": (
            "Monthly oil and gas well production for Argentina (2006–present)."
        ),
        "tables": {
            table: {
                "description": meta["description"],
                "columns": meta["columns"],
                "primary_key": list(meta["primary_key"]),
                "foreign_keys": [dict(fk) for fk in meta["foreign_keys"]],
            }
            for table, meta in schemas.items()
        },
    }
    # `ensure_ascii=false` keeps Spanish accents in column-value examples
    # (e.g. `Petrolífero`) intact.
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# schema.sql
# ---------------------------------------------------------------------------


def _write_schema_sql(schemas: dict[str, dict], path: Path) -> None:
    """Emit DDL that recreates the published structure in a fresh DuckDB.

    PRIMARY KEY constraints are inlined; FOREIGN KEY constraints reference
    the parent `wells` table. Types are reproduced verbatim from the
    DESCRIBE output, so the DDL is round-trippable against the published
    parquets.
    """
    lines = [
        "-- Argentina production dataset — DDL",
        "-- Auto-generated from the published Parquet schemas. Do not edit by hand.",
        "",
    ]
    for table in TABLE_ORDER:
        meta = schemas[table]
        col_defs = []
        for col in meta["columns"]:
            null_clause = " NOT NULL" if col["not_null"] else ""
            col_defs.append(f"  {col['name']} {col['type']}{null_clause}")
        pk_cols = ", ".join(meta["primary_key"])
        col_defs.append(f"  PRIMARY KEY ({pk_cols})")
        for fk in meta["foreign_keys"]:
            col_defs.append(
                f"  FOREIGN KEY ({fk['column']}) REFERENCES "
                f"{fk['references_table']} ({fk['references_column']})"
            )
        lines.append(f"CREATE TABLE {table} (")
        lines.append(",\n".join(col_defs))
        lines.append(");")
        lines.append("")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# schema.md
# ---------------------------------------------------------------------------


def _write_schema_md(schemas: dict[str, dict], path: Path) -> None:
    """English column docs covering every published column + the four-bucket
    rationale + a glossary of opaque source codes.
    """
    lines: list[str] = []
    lines.append("# Argentina — Dataset Schema")
    lines.append("")
    lines.append(
        "Monthly oil and gas well production for Argentina, organised into "
        "four tables by per-`idpozo` volatility. Column identifiers are "
        "preserved in Spanish exactly as the source publishes them; all "
        "explanatory prose below is in English."
    )
    lines.append("")
    lines.append("## Four buckets, four tables")
    lines.append("")
    lines.append(
        "The schema splits by **change frequency** within each `idpozo`: "
        "static attributes, slowly-changing metadata, events, and a numeric "
        "time series. This avoids redundancy across the ~17.6 M monthly rows."
    )
    lines.append("")
    lines.append("| Table | Bucket | Grain |")
    lines.append("|-------|--------|-------|")
    lines.append(
        "| `wells` | Static master (< 0.3 % of wells change) | 1 row per `idpozo` |"
    )
    lines.append(
        "| `well_operator_history` | Slowly-changing metadata (~67 % change) | 1 row per operator run |"
    )
    lines.append(
        "| `well_events` | State events (~74 % change `tipoestado`) | 1 row per transition month |"
    )
    lines.append(
        "| `monthly_production` | Monthly numeric series | 1 row per `(idpozo, fecha)` |"
    )
    lines.append("")
    lines.append("## Tables")
    lines.append("")
    for table in TABLE_ORDER:
        meta = schemas[table]
        lines.append(f"### `{table}`")
        lines.append("")
        lines.append(meta["description"])
        lines.append("")
        lines.append("**Columns:**")
        lines.append("")
        lines.append("| Column | Type | Nullable | PK | Description |")
        lines.append("|--------|------|----------|----|-------------|")
        for col in meta["columns"]:
            nullable = "No" if col["not_null"] else "Yes"
            pk = "✓" if col["primary_key"] else ""
            desc = COLUMN_DESCRIPTIONS.get(col["name"], "")
            lines.append(
                f"| `{col['name']}` | {col['type']} | {nullable} | {pk} | {desc} |"
            )
        lines.append("")
        if meta["foreign_keys"]:
            lines.append("**Foreign keys:**")
            lines.append("")
            for fk in meta["foreign_keys"]:
                lines.append(
                    f"- `{fk['column']}` → "
                    f"`{fk['references_table']}.{fk['references_column']}`"
                )
            lines.append("")
        lines.append("---")
        lines.append("")
    lines.append("## Relationships")
    lines.append("")
    lines.append("```")
    for table in TABLE_ORDER:
        for fk in schemas[table]["foreign_keys"]:
            lines.append(
                f"{table}.{fk['column']} → "
                f"{fk['references_table']}.{fk['references_column']}"
            )
    lines.append("```")
    lines.append("")
    lines.append("## Glossary of source codes")
    lines.append("")
    lines.append(
        "Some abbreviations inherited from the source are not obvious at first glance:"
    )
    lines.append("")
    lines.append("| Code | Meaning |")
    lines.append("|------|---------|")
    lines.append(
        "| `tef` | Effective production time for the month — *Tiempo Efectivo de Producción* (hours). |"
    )
    lines.append(
        "| `vida_util` | Declared useful life of the well in the month — *vida útil* (months). |"
    )
    lines.append(
        "| `formprod` | Producing formation of the `idpozo`. Static attribute. |"
    )
    lines.append(
        "| `idpozo` | Canonical identity: wellbore × producing formation. Primary key of the model. |"
    )
    lines.append(
        "| `sigla` | Human-readable well code. Label, possibly mutable, not the PK. |"
    )
    lines.append(
        "| `idempresa` | Alphanumeric operator code. **VARCHAR**, not INTEGER. |"
    )
    lines.append("")
    lines.append("## Dropped columns")
    lines.append("")
    lines.append(
        "The following source columns are administrative/audit fields and "
        "are not published:"
    )
    lines.append("")
    for col in DROPPED_COLUMNS:
        lines.append(f"- `{col}`")
    lines.append("")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------


def _manifest_urls(base_url: str, filt: str | None = None) -> list[str]:
    """Python lines resolving the `monthly_production` partition URLs.

    The static host (HF, per ADR-0005) serves no directory index, so DuckDB
    cannot glob `anio=*/data.parquet`. Per ADR-0004 the file list is read from
    the `_files.json` manifest — the discovery contract — and passed to
    `read_parquet(?)` as an explicit list; `hive_partitioning = true` recovers
    the `anio` column from each path. `filt` optionally narrows the partitions
    client-side (a Python boolean expression over the manifest entry `p`).
    """
    lines = [
        "import json, urllib.request, duckdb",
        "",
        f"base = '{base_url}/monthly_production/'",
        "manifest = json.load(urllib.request.urlopen(base + '_files.json'))",
    ]
    if filt:
        lines.append(f"urls = [base + p for p in manifest if {filt}]")
    else:
        lines.append("urls = [base + p for p in manifest]")
    return lines


def _write_readme(schemas: dict[str, dict], path: Path) -> None:
    """Dataset overview + the four canonical DuckDB query examples.

    Examples cover: single-well lookup (row-group pruning), year-range across
    hive partitions, basin aggregate joining `wells` to `monthly_production`,
    and a corpus-wide read. Every multi-partition read discovers files from the
    `_files.json` manifest (ADR-0004) — never a `.../*.parquet` glob — so the
    examples work against the static Hugging Face host (ADR-0005).
    """
    # `BASE_URL` is the HF resolve base in CI (ADR-0005); local runs fall
    # through to the dev Caddy host. `/argentina` matches this dataset's
    # directory under `parquet/`.
    base_url = (
        os.environ.get("BASE_URL", "https://dev-petrodb.ocortez.com").rstrip("/")
        + "/argentina"
    )
    lines: list[str] = []
    lines.append("# Argentina Production Dataset")
    lines.append("")
    lines.append(
        "Monthly oil and gas well production for Argentina (2006–present), "
        "published as four Parquet tables. Column identifiers are preserved "
        "in Spanish exactly as the source publishes them; all documentation "
        "below is in English."
    )
    lines.append("")
    lines.append("## Published files")
    lines.append("")
    lines.append("```")
    lines.append("argentina/")
    lines.append("├── wells.parquet                   # 1 row per idpozo (~85,418)")
    lines.append("├── well_operator_history.parquet   # 1 row per operator run")
    lines.append(
        "├── well_events.parquet             # 1 row per state-transition month"
    )
    lines.append("├── monthly_production/")
    lines.append("│   ├── anio=2006/data.parquet")
    lines.append("│   ├── anio=2007/data.parquet")
    lines.append("│   ├── ...")
    lines.append("│   └── _files.json                 # partition manifest")
    lines.append("├── schema.md")
    lines.append("├── schema.json")
    lines.append("└── schema.sql")
    lines.append("```")
    lines.append("")
    lines.append(
        "Column identifiers are preserved verbatim in their source Spanish "
        "(`idpozo`, `cuenca`, `sigla`, `formprod`, `prod_pet`, …). The "
        "glossary of opaque codes such as `tef` and `vida_util` lives in "
        "`schema.md`."
    )
    lines.append("")
    lines.append("## Dropped columns")
    lines.append("")
    lines.append(
        "These source columns are administrative/audit fields and are "
        "**not published**:"
    )
    lines.append("")
    for col in DROPPED_COLUMNS:
        lines.append(f"- `{col}`")
    lines.append("")
    lines.append("## Access via DuckDB `httpfs`")
    lines.append("")
    lines.append(
        "All examples assume DuckDB ≥ 1.0 with the `httpfs` extension "
        "enabled. Queries read straight from the site without downloading."
    )
    lines.append("")
    lines.append("```sql")
    lines.append("INSTALL httpfs; LOAD httpfs;")
    lines.append("```")
    lines.append("")
    lines.append(
        "`monthly_production` is a multi-parquet table; discover its partition "
        "files from the `_files.json` manifest (ADR-0004) and hand DuckDB the "
        "explicit URL list — the static host serves no directory listing, so "
        "wildcard globbing over the partitions does not resolve. "
        "`hive_partitioning = true` recovers the `anio` column from each path."
    )
    lines.append("")
    lines.append("### 1. Single well by `idpozo`")
    lines.append("")
    lines.append(
        "Each partition is sorted by `(idpozo, fecha)`, so Parquet row-group "
        "statistics let DuckDB prune the row groups that do not contain the "
        "requested well: the query downloads minimal byte ranges."
    )
    lines.append("")
    lines.append("```python")
    lines.extend(_manifest_urls(base_url))
    lines.append("")
    lines.append('duckdb.sql("""')
    lines.append("    SELECT idpozo, fecha, prod_pet, prod_gas")
    lines.append("    FROM read_parquet(?, hive_partitioning = true)")
    lines.append("    WHERE idpozo = 12345")
    lines.append("    ORDER BY fecha")
    lines.append('""", params=[urls]).show()')
    lines.append("```")
    lines.append("")
    lines.append("### 2. Year range")
    lines.append("")
    lines.append(
        "Narrow the manifest to the requested years client-side so only those "
        "partition files are fetched; `hive_partitioning` still derives `anio` "
        "from the path for the `WHERE` filter."
    )
    lines.append("")
    lines.append("```python")
    lines.extend(
        _manifest_urls(base_url, filt="2018 <= int(p.split('=')[1][:4]) <= 2022")
    )
    lines.append("")
    lines.append('duckdb.sql("""')
    lines.append("    SELECT anio, COUNT(*) AS rows, SUM(prod_pet) AS prod_pet_total")
    lines.append("    FROM read_parquet(?, hive_partitioning = true)")
    lines.append("    WHERE anio BETWEEN 2018 AND 2022")
    lines.append("    GROUP BY anio")
    lines.append("    ORDER BY anio")
    lines.append('""", params=[urls]).show()')
    lines.append("```")
    lines.append("")
    lines.append("### 3. Aggregate by basin (join `wells` ↔ `monthly_production`)")
    lines.append("")
    lines.append(
        "The `wells` master is a single file, read directly; "
        "`monthly_production` is reduced to the year of interest by narrowing "
        "the manifest to that partition before the join."
    )
    lines.append("")
    lines.append("```python")
    lines.extend(_manifest_urls(base_url, filt="p.startswith('anio=2023/')"))
    lines.append("")
    lines.append('duckdb.sql(f"""')
    lines.append("    SELECT w.cuenca,")
    lines.append("           SUM(m.prod_pet) AS prod_pet_total,")
    lines.append("           SUM(m.prod_gas) AS prod_gas_total")
    lines.append(f"    FROM '{base_url}/wells.parquet' w")
    lines.append("    JOIN read_parquet(?, hive_partitioning = true) m USING (idpozo)")
    lines.append("    WHERE m.anio = 2023")
    lines.append("    GROUP BY w.cuenca")
    lines.append("    ORDER BY prod_pet_total DESC")
    lines.append('""", params=[urls]).show()')
    lines.append("```")
    lines.append("")
    lines.append("### 4. Read the whole series (the manifest is the contract)")
    lines.append("")
    lines.append(
        "`_files.json` lists every partition's path relative to "
        "`monthly_production/`; it is the file-discovery contract (ADR-0004) "
        "and the only supported way to enumerate the table over static "
        "hosting. Read them all for a corpus-wide aggregate:"
    )
    lines.append("")
    lines.append("```python")
    lines.extend(_manifest_urls(base_url))
    lines.append("")
    lines.append('duckdb.sql("""')
    lines.append(
        "    SELECT anio, SUM(prod_pet) AS prod_pet_total, "
        "SUM(prod_gas) AS prod_gas_total"
    )
    lines.append("    FROM read_parquet(?, hive_partitioning = true)")
    lines.append("    GROUP BY anio")
    lines.append("    ORDER BY anio")
    lines.append('""", params=[urls]).show()')
    lines.append("```")
    lines.append("")
    lines.append("## Full schema")
    lines.append("")
    lines.append(
        "See `schema.md` (human-readable) / `schema.json` (programmatic "
        "consumption) / `schema.sql` (DDL to reproduce the structure "
        "locally)."
    )
    lines.append("")
    path.write_text("\n".join(lines))

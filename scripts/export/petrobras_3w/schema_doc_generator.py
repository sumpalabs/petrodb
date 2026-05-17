"""Generate the published documentation artifacts for the Petrobras 3W dataset.

Five files under the dataset root:

- `schema.json`  — machine-readable column list, types, nullability, PKs, FKs.
- `schema.sql`   — DDL that mirrors the published structure in a fresh DuckDB.
- `schema.md`    — English column docs + table relationships + 27-sensor
                   glossary mirrored from upstream `dataset.ini`'s
                   `PARQUET_FILE_PROPERTIES`.
- `README.md`    — dataset overview, pinned upstream identity, access info,
                   query examples.
- `LICENSE-3W-DATA.md` — CC BY 4.0 license text with attribution back to the
                   upstream `petrobras/3W` repo.

The list of tables documented grows as subsequent slices (#20, #21, #22)
add their parquets — `TABLE_ORDER` is the single registration point.
The reflection is read straight from the published parquet via DuckDB
`DESCRIBE`, so the published schema and the documented schema cannot
drift.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from scripts.transform.petrobras_3w.constants import (
    PIN_DATASET_VERSION,
    PIN_GIT_TAG,
    UPSTREAM_REPO_URL,
)
from scripts.transform.petrobras_3w.upstream_stager import DatasetIni

# Tables documented in this slice. Later slices append to this tuple.
TABLE_ORDER = ("event_types",)

TABLE_DESCRIPTIONS = {
    "event_types": (
        "Static lookup of upstream event classes (`0..9`). Mirrors the "
        "`[NAMES]` / per-class `LABEL`/`DESCRIPTION`/`TRANSIENT` sections "
        "from upstream `dataset.ini`, plus the two derived columns "
        "`transient_code` and `has_normal_prefix` that materialize the "
        "NORMAL → TRANSIENT → STEADY arc semantics so consumers do not "
        "have to re-derive them from per-observation `class` codes."
    ),
}

PRIMARY_KEYS = {
    "event_types": ("event_class",),
}

FOREIGN_KEYS: dict[str, tuple[dict, ...]] = {}

COLUMN_DESCRIPTIONS = {
    # event_types
    "event_class": (
        "Integer event class (0 = NORMAL; 1..9 = anomaly categories). "
        "Primary key. Matches upstream's `LABEL`."
    ),
    "name": (
        "Internal name (PascalCase with underscores, e.g. "
        "`HYDRATE_IN_PRODUCTION_LINE`). Mirrors upstream's `NAMES` list."
    ),
    "description": (
        "Human-readable description (e.g. `Hydrate in Production Line`). "
        "Mirrors upstream's per-class `DESCRIPTION`."
    ),
    "has_transient": (
        "`true` for classes that carry a `TRANSIENT` precursor phase in "
        "their `class` column (1, 2, 5, 6, 7, 8, 9). `false` for "
        "`NORMAL` (0) and the two events upstream marks `TRANSIENT=False` "
        "(3 = Severe Slugging, 4 = Flow Instability)."
    ),
    "transient_code": (
        "Per-observation label seen during the transient phase: "
        "`event_class + 100` when `has_transient = true`, NULL otherwise. "
        "Decodes raw `class` codes such as 101, 105, 108 in the "
        "observations time-series."
    ),
    "has_normal_prefix": (
        "`true` when instances of this class include a `class = 0` "
        "(NORMAL) precursor before the labelled event. Correlates with "
        "`has_transient` — events 0, 3, 4 carry only the steady class."
    ),
}


def generate(
    con: duckdb.DuckDBPyConnection,
    output_dir: Path,
    dataset_ini: DatasetIni,
) -> None:
    """Reflect the published Parquets and emit the documentation artifacts.

    `output_dir` is the dataset root (i.e. where `event_types.parquet`
    lives). All writes are full overwrites so the call is idempotent.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    schemas = _reflect_schemas(con, output_dir)
    _write_schema_json(schemas, output_dir / "schema.json")
    _write_schema_sql(schemas, output_dir / "schema.sql")
    _write_schema_md(schemas, dataset_ini, output_dir / "schema.md")
    _write_readme(schemas, output_dir / "README.md")
    _write_license(output_dir / "LICENSE-3W-DATA.md")


def _reflect_schemas(
    con: duckdb.DuckDBPyConnection, output_dir: Path
) -> dict[str, dict]:
    schemas: dict[str, dict] = {}
    for table in TABLE_ORDER:
        path = output_dir / f"{table}.parquet"
        described = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path}')"
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
        "dataset": "petrobras_3w",
        "description": (
            "Labelled 1-Hz sensor-data windows from the Petrobras 3W "
            "dataset, sliced into Instances and grouped by Event class."
        ),
        "upstream": {
            "repo": UPSTREAM_REPO_URL,
            "git_tag": PIN_GIT_TAG,
            "dataset_version": PIN_DATASET_VERSION,
        },
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
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# schema.sql
# ---------------------------------------------------------------------------


def _write_schema_sql(schemas: dict[str, dict], path: Path) -> None:
    lines = [
        "-- Petrobras 3W dataset — DDL",
        "-- Auto-generated from the published Parquet schemas. Do not edit by hand.",
        f"-- Upstream: {UPSTREAM_REPO_URL}",
        f"-- Pinned git tag: {PIN_GIT_TAG}",
        f"-- Upstream dataset version: {PIN_DATASET_VERSION}",
        "",
    ]
    for table in TABLE_ORDER:
        meta = schemas[table]
        col_defs = []
        for col in meta["columns"]:
            null_clause = " NOT NULL" if col["not_null"] else ""
            col_defs.append(
                f"  {_quote_identifier(col['name'])} {col['type']}{null_clause}"
            )
        pk_cols = ", ".join(_quote_identifier(c) for c in meta["primary_key"])
        col_defs.append(f"  PRIMARY KEY ({pk_cols})")
        for fk in meta["foreign_keys"]:
            col_defs.append(
                f"  FOREIGN KEY ({_quote_identifier(fk['column'])}) REFERENCES "
                f"{fk['references_table']} ({_quote_identifier(fk['references_column'])})"
            )
        lines.append(f"CREATE TABLE {table} (")
        lines.append(",\n".join(col_defs))
        lines.append(");")
        lines.append("")
    path.write_text("\n".join(lines))


def _quote_identifier(name: str) -> str:
    """Double-quote identifiers that contain characters DuckDB needs escaped.

    Upstream sensor columns include hyphens (`P-PDG`, `ABER-CKGL`) — those
    must be quoted in any SQL identifier position. Plain lowercase
    identifiers do not need quoting.
    """
    if name.isidentifier() and name.islower():
        return name
    return f'"{name}"'


# ---------------------------------------------------------------------------
# schema.md
# ---------------------------------------------------------------------------


def _write_schema_md(
    schemas: dict[str, dict], dataset_ini: DatasetIni, path: Path
) -> None:
    lines: list[str] = []
    lines.append("# Petrobras 3W — Dataset Schema")
    lines.append("")
    lines.append(
        f"Sourced from [`petrobras/3W`]({UPSTREAM_REPO_URL}), pinned at git "
        f"tag `{PIN_GIT_TAG}` (upstream dataset version `{PIN_DATASET_VERSION}`). "
        f"Column identifiers — including the upstream sensor columns with "
        f"hyphens (`P-PDG`, `ABER-CKGL`, `ESTADO-SDV-GL`, …) — are preserved "
        f"verbatim; consumers must double-quote those identifiers in SQL. "
        f"All explanatory prose below is in English."
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
    lines.append("## Sensor-column glossary (Observations time-series)")
    lines.append("")
    lines.append(
        "Mirrored verbatim from upstream `dataset.ini`'s "
        "`PARQUET_FILE_PROPERTIES` section. These columns will appear in "
        "`observations/event_class=N/<instance_id>.parquet` once issue "
        "#22 lands; the glossary is published here so consumers can plan "
        "queries against the table layout in advance."
    )
    lines.append("")
    lines.append("| Column | Description |")
    lines.append("|--------|-------------|")
    for column, description in dataset_ini.sensor_descriptions.items():
        lines.append(f"| `{column}` | {description} |")
    lines.append("")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------


def _write_readme(schemas: dict[str, dict], path: Path) -> None:
    base_url = "https://dev-petrodb.ocortez.com/petrobras_3w"
    lines: list[str] = []
    lines.append("# Petrobras 3W Dataset")
    lines.append("")
    lines.append(
        "Labelled 1-Hz sensor-data windows for the Petrobras 3W dataset, "
        "republished as Parquet files. The full per-Instance time-series "
        "(`observations/`), the Instance catalog (`instances.parquet`), "
        "and the real-Well master (`wells.parquet`) ship in subsequent "
        "issues (#22, #20, #21); this initial release publishes only the "
        "event-class lookup (`event_types.parquet`) and the documentation "
        "scaffolding so consumers can preview the schema."
    )
    lines.append("")
    lines.append("## Upstream pin")
    lines.append("")
    lines.append(f"- Repository: <{UPSTREAM_REPO_URL}>")
    lines.append(f"- Pinned git tag: `{PIN_GIT_TAG}`")
    lines.append(f"- Upstream dataset version: `{PIN_DATASET_VERSION}`")
    lines.append("")
    lines.append(
        "Refreshes are event-driven on new upstream tags (see "
        "[ADR-0002](../../docs/adr/0002-petrobras-3w-pin-upstream-release-tag.md)). "
        "Both the git tag and the dataset version are emitted in the "
        "publish orchestrator's validation log."
    )
    lines.append("")
    lines.append("## Published files (this slice)")
    lines.append("")
    lines.append("```")
    lines.append("petrobras_3w/")
    lines.append("├── event_types.parquet     # 10 rows, one per upstream event class")
    lines.append("├── schema.md")
    lines.append("├── schema.json")
    lines.append("├── schema.sql")
    lines.append(
        "└── LICENSE-3W-DATA.md      # CC BY 4.0 mirror with upstream attribution"
    )
    lines.append("```")
    lines.append("")
    lines.append(
        "Source column names from upstream (`P-PDG`, `ABER-CKGL`, "
        "`ESTADO-SDV-GL`, …) are preserved verbatim including hyphens; "
        "consumers must double-quote those identifiers in SQL."
    )
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
    lines.append("### List every event class")
    lines.append("")
    lines.append("```sql")
    lines.append("SELECT event_class, name, description, has_transient, transient_code")
    lines.append(f"FROM '{base_url}/event_types.parquet'")
    lines.append("ORDER BY event_class;")
    lines.append("```")
    lines.append("")
    lines.append("### Filter to anomaly classes only")
    lines.append("")
    lines.append("```sql")
    lines.append("SELECT name, description, transient_code")
    lines.append(f"FROM '{base_url}/event_types.parquet'")
    lines.append("WHERE event_class > 0")
    lines.append("ORDER BY event_class;")
    lines.append("```")
    lines.append("")
    lines.append("## License")
    lines.append("")
    lines.append(
        "Upstream data is released under [Creative Commons Attribution 4.0]"
        "(https://creativecommons.org/licenses/by/4.0/). See "
        "`LICENSE-3W-DATA.md` in this directory for the attribution text."
    )
    lines.append("")
    lines.append("## Full schema")
    lines.append("")
    lines.append(
        "See `schema.md` (human-readable, with the 27-sensor glossary), "
        "`schema.json` (programmatic), and `schema.sql` (DDL to reproduce "
        "the structure locally)."
    )
    lines.append("")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# LICENSE-3W-DATA.md
# ---------------------------------------------------------------------------


def _write_license(path: Path) -> None:
    body = f"""\
# Petrobras 3W Dataset — License & Attribution

The Petrobras 3W dataset is released by Petrobras under the
[Creative Commons Attribution 4.0 International License (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

This redistribution preserves the upstream data byte-for-byte (sensor
columns, `class`, `state`, `timestamp`) and adds derived structure
(catalog tables, per-row constant columns identifying the source
Instance and Well). All credit for the underlying measurements,
labelling, and dataset design belongs to Petrobras and the upstream
maintainers.

## Attribution

Upstream repository: <{UPSTREAM_REPO_URL}>
Pinned git tag: `{PIN_GIT_TAG}`
Upstream dataset version: `{PIN_DATASET_VERSION}`

When using the data published here, please cite the upstream `petrobras/3W`
repository and credit Petrobras as the original publisher. The full text
of the CC BY 4.0 license is available at the link above.
"""
    path.write_text(body)

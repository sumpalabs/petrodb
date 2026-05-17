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

TABLE_ORDER = ("event_types", "wells", "instances", "observations")

TABLE_DESCRIPTIONS = {
    "event_types": (
        "Static lookup of upstream event classes (`0..9`). Mirrors the "
        "`[NAMES]` / per-class `LABEL`/`DESCRIPTION`/`TRANSIENT` sections "
        "from upstream `dataset.ini`, plus the two derived columns "
        "`transient_code` and `has_normal_prefix` that materialize the "
        "NORMAL → TRANSIENT → STEADY arc semantics so consumers do not "
        "have to re-derive them from per-observation `class` codes."
    ),
    "wells": (
        "Real-Well master, one row per distinct `well_id` derived from "
        "Instances with `well_kind = 'real'` (40 rows at the current "
        "upstream pin). Upstream anonymises every physical-well attribute "
        "(no basin, field, depth, or location), so the master is an "
        "identity-plus-statistics table: count of Instances, total 1-Hz "
        "Observations, and the time span across which the Well appears "
        "in the corpus. Simulated and drawn Instances have NULL `well_id` "
        "and contribute nothing here."
    ),
    "instances": (
        "One row per upstream Instance file (~2,228 rows). Identifies the "
        "Instance (`instance_id`), its provenance (`well_kind`, `well_id`, "
        "`source_file`), the operational regime it is framed around "
        "(`event_class`), and pre-aggregated per-Instance statistics "
        "(`start_ts`, `end_ts`, `duration_s`, `n_rows`, plus four "
        "`n_rows_*` counts that partition `n_rows` by `class` value). "
        "Corpus-wide balance and labelled-mass queries can run purely "
        "against this catalog without scanning the Observations time-series. "
        "`source_url` points at the published Observations file for the "
        "Instance (the URL pattern is fixed by ADR-0001)."
    ),
    "observations": (
        "Per-Instance 1-Hz sensor time-series. Hive-partitioned by "
        "`event_class` into `observations/event_class=N/<instance_id>.parquet` "
        "— one file per Instance, ~2,228 files in total. Each file preserves "
        "the upstream sensor columns verbatim (including hyphens: `P-PDG`, "
        "`ABER-CKGL`, `ESTADO-SDV-GL`, …), plus `class`, `state`, and "
        "`timestamp`. Three constant columns identify provenance per row: "
        "`instance_id`, `well_id`, `well_kind` (RLE-encoded, negligible "
        "storage). `event_class` is provided by the hive partition and is "
        "NOT stored in the file body. A `_files.json` manifest at the "
        "partition root lists every published file's relative path for "
        "consumers that prefer enumeration over wildcards."
    ),
}

PRIMARY_KEYS = {
    "event_types": ("event_class",),
    "wells": ("well_id",),
    "instances": ("instance_id",),
    # Observations PK is logical, not enforceable from a DDL on hive
    # partitions — `(instance_id, timestamp)` uniquely identifies a row
    # within the published tree.
    "observations": ("instance_id", "timestamp"),
}

FOREIGN_KEYS: dict[str, tuple[dict, ...]] = {
    "instances": (
        {
            "column": "event_class",
            "references_table": "event_types",
            "references_column": "event_class",
        },
        {
            "column": "well_id",
            "references_table": "wells",
            "references_column": "well_id",
        },
    ),
    "observations": (
        {
            "column": "instance_id",
            "references_table": "instances",
            "references_column": "instance_id",
        },
        {
            "column": "event_class",
            "references_table": "event_types",
            "references_column": "event_class",
        },
        {
            "column": "well_id",
            "references_table": "wells",
            "references_column": "well_id",
        },
    ),
}

COLUMN_DESCRIPTIONS = {
    # event_types
    "event_class": (
        "Integer event class (0 = NORMAL; 1..9 = anomaly categories). "
        "On `event_types` this is the primary key; on `instances` it is "
        "a foreign key back to `event_types.event_class`."
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
    # instances
    "instance_id": (
        "Primary key. The upstream source filename without `.parquet` "
        "(e.g. `WELL-00019_20120601165020`, `SIMULATED_00012`, "
        "`DRAWN_00003`). Stable across refreshes."
    ),
    "well_kind": (
        "Provenance of the Instance: `real` (from a physical Petrobras "
        "well), `simulated` (synthetic, generated upstream), or `drawn` "
        "(hand-crafted series). `well_id` is non-NULL only when "
        "`well_kind = 'real'`."
    ),
    "well_id": (
        "Anonymised physical-well integer ID. On `wells` this is the "
        "primary key (one row per real Well). On `instances` it is parsed "
        "from the `WELL-NNNNN` prefix of `instance_id` and is NULL when "
        "`well_kind != 'real'` — a foreign key back to `wells.well_id`."
    ),
    # wells
    "n_instances": (
        "Number of Instances in the corpus drawn from this real Well. "
        "Equal to `COUNT(*) FROM instances WHERE well_kind = 'real' AND "
        "well_id = wells.well_id`."
    ),
    "first_ts": (
        "Earliest Instance `start_ts` for the Well. The Well's first "
        "appearance in the corpus."
    ),
    "last_ts": (
        "Latest Instance `end_ts` for the Well. The Well's last "
        "appearance in the corpus."
    ),
    "n_observations": (
        "Total count of 1-Hz Observations contributed by this Well across "
        "all of its Instances. Equal to `SUM(n_rows) FROM instances WHERE "
        "well_kind = 'real' AND well_id = wells.well_id`."
    ),
    "start_ts": ("First `timestamp` value in the upstream Instance file."),
    "end_ts": ("Last `timestamp` value in the upstream Instance file."),
    "duration_s": (
        "`end_ts - start_ts` in seconds. Derived from the per-Instance "
        "aggregates so consumers do not have to recompute it."
    ),
    "n_rows": (
        "Number of 1-Hz observations in the upstream Instance file. "
        "Range across the corpus: ~21k (~6h) to ~243k (~3 days)."
    ),
    "n_rows_warmup_null": (
        "Count of rows where `class IS NULL` — the warmup prefix seen on "
        "real-Well Instances (typically ~1 hour) where upstream chose not "
        "to assign a label."
    ),
    "n_rows_normal": (
        "Count of rows where `class = 0` and the Instance's `event_class` "
        "is not itself 0 — i.e. the NORMAL precursor before an anomaly. "
        "Event 0's `class = 0` rows are its labelled regime itself and "
        "are counted under `n_rows_steady` instead, so the four "
        "`n_rows_*` columns always partition `n_rows` without overlap."
    ),
    "n_rows_transient": (
        "Count of rows where `class = event_class + 100` (the developing "
        "phase before steady state). NULL when the row's `event_class` "
        "has `has_transient = false` in `event_types` (events 0, 3, 4) — "
        "the transient phase does not exist by design, distinct from a "
        "zero-row count."
    ),
    "n_rows_steady": (
        "Count of rows where `class = event_class` (the labelled "
        "operational regime at steady state)."
    ),
    "source_file": (
        "Upstream parquet filename including `.parquet` extension, for "
        "cross-reference with the upstream repository."
    ),
    "source_url": (
        "URL of the published Observations file for this Instance "
        "(`observations/event_class=N/<instance_id>.parquet`). The URL "
        "pattern is fixed by ADR-0001 so it can be materialised here "
        "before the Observations files exist."
    ),
    # observations
    "timestamp": (
        "Wall-clock timestamp of the 1-Hz observation. Strictly monotonic "
        "within an Instance file at exactly 1-second cadence."
    ),
    "class": (
        "Per-observation regime label: `NULL` during the warmup prefix of "
        "a real-Well Instance, `0` for the NORMAL precursor before an "
        "anomaly, `event_class` for the labelled steady regime, or "
        "`event_class + 100` for the TRANSIENT phase (only on events "
        "where `event_types.has_transient = true`). Events 3 and 4 ship "
        "only the steady code — no transient and no NORMAL precursor."
    ),
    "state": (
        "Upstream-provided well operational status. Preserved verbatim "
        "from the source file; semantics are documented in upstream's "
        "`dataset.ini`."
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
        if table == "observations":
            columns = _reflect_observations_columns(con, output_dir)
        else:
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
                    "hive_partition": False,
                }
                for row in described
            ]
        schemas[table] = {
            "columns": columns,
            "primary_key": PRIMARY_KEYS[table],
            "foreign_keys": FOREIGN_KEYS.get(table, ()),
            "description": TABLE_DESCRIPTIONS[table],
        }
    return schemas


def _reflect_observations_columns(
    con: duckdb.DuckDBPyConnection, output_dir: Path
) -> list[dict]:
    """Reflect the Observations file body columns and prepend `event_class`.

    The first file in the manifest is representative — every Observations
    file is produced from the same writer and carries the same body
    columns. `event_class` is added explicitly because it lives in the
    hive partition path, not the file body.
    """
    manifest_path = output_dir / "observations" / "_files.json"
    relative_paths = json.loads(manifest_path.read_text())
    if not relative_paths:
        raise ValueError(
            f"observations manifest at {manifest_path} is empty — no files to "
            f"reflect schema from"
        )
    sample = output_dir / "observations" / relative_paths[0]
    # `hive_partitioning=false` — `event_class` is the hive partition and
    # we are reflecting the file body. The auto-detect would otherwise
    # surface it as a column twice (once here, once prepended below).
    described = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{sample}', hive_partitioning=false)"
    ).fetchall()
    pk = PRIMARY_KEYS["observations"]
    columns: list[dict] = [
        {
            "name": "event_class",
            "type": "INTEGER",
            "not_null": True,
            "primary_key": False,
            "hive_partition": True,
        }
    ]
    for row in described:
        columns.append(
            {
                "name": row[0],
                "type": row[1],
                "not_null": row[0] in pk or row[2] == "NO",
                "primary_key": row[0] in pk,
                "hive_partition": False,
            }
        )
    return columns


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
        if table == "observations":
            lines.append("-- `observations` is published as a hive-partitioned tree:")
            lines.append("--   observations/event_class=N/<instance_id>.parquet")
            lines.append(
                "-- `event_class` lives in the partition path; every other "
                "column lives in the file body."
            )
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
        lines.append("| Column | Type | Nullable | PK | Source | Description |")
        lines.append("|--------|------|----------|----|--------|-------------|")
        for col in meta["columns"]:
            nullable = "No" if col["not_null"] else "Yes"
            pk = "✓" if col["primary_key"] else ""
            source = "hive partition" if col.get("hive_partition") else "file body"
            desc = COLUMN_DESCRIPTIONS.get(col["name"], "")
            lines.append(
                f"| `{col['name']}` | {col['type']} | {nullable} | {pk} | "
                f"{source} | {desc} |"
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
        "republished as Parquet files. This release publishes the "
        "event-class lookup (`event_types.parquet`), the full Instance "
        "catalog (`instances.parquet`), the real-Well master "
        "(`wells.parquet`), and the per-Instance Observations time-series "
        "(`observations/event_class=N/<instance_id>.parquet`)."
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
    lines.append("## Published files")
    lines.append("")
    lines.append("```")
    lines.append("petrobras_3w/")
    lines.append("├── event_types.parquet     # 10 rows, one per upstream event class")
    lines.append("├── wells.parquet           # 40 rows, one per real Well")
    lines.append("├── instances.parquet       # one row per upstream Instance file")
    lines.append("├── observations/")
    lines.append("│   ├── event_class=0/<instance_id>.parquet   # ~594 files")
    lines.append("│   ├── …")
    lines.append("│   ├── event_class=9/<instance_id>.parquet   # ~207 files")
    lines.append(
        "│   └── _files.json                            # manifest of every Observations file's relative path"
    )
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
    lines.append("### Corpus balance from the Instance catalog")
    lines.append("")
    lines.append(
        "The per-Instance `n_rows_*` counts let you measure the labelled "
        "data balance across the corpus without scanning the Observations "
        "time-series:"
    )
    lines.append("")
    lines.append("```sql")
    lines.append("SELECT")
    lines.append("    et.event_class,")
    lines.append("    et.description,")
    lines.append("    COUNT(*)              AS n_instances,")
    lines.append("    SUM(i.n_rows)         AS n_observations,")
    lines.append("    SUM(i.n_rows_steady)  AS n_observations_steady")
    lines.append(f"FROM '{base_url}/instances.parquet' i")
    lines.append(f"JOIN '{base_url}/event_types.parquet' et")
    lines.append("    ON et.event_class = i.event_class")
    lines.append("GROUP BY et.event_class, et.description")
    lines.append("ORDER BY et.event_class;")
    lines.append("```")
    lines.append("")
    lines.append("### List Instances of a single event class (real wells only)")
    lines.append("")
    lines.append("```sql")
    lines.append("SELECT instance_id, well_id, start_ts, n_rows, source_url")
    lines.append(f"FROM '{base_url}/instances.parquet'")
    lines.append("WHERE event_class = 8")
    lines.append("  AND well_kind = 'real'")
    lines.append("ORDER BY start_ts;")
    lines.append("```")
    lines.append("")
    lines.append("### Per-Well corpus footprint (join `wells` with `instances`)")
    lines.append("")
    lines.append(
        "The `wells` master pre-aggregates each Well's Instance and "
        "Observation counts so coverage tables can be built without "
        "scanning Observations:"
    )
    lines.append("")
    lines.append("```sql")
    lines.append("SELECT")
    lines.append("    w.well_id,")
    lines.append("    w.n_instances,")
    lines.append("    w.n_observations,")
    lines.append("    w.first_ts,")
    lines.append("    w.last_ts,")
    lines.append("    COUNT(DISTINCT i.event_class) AS distinct_event_classes")
    lines.append(f"FROM '{base_url}/wells.parquet' w")
    lines.append(f"JOIN '{base_url}/instances.parquet' i USING (well_id)")
    lines.append("GROUP BY w.well_id, w.n_instances, w.n_observations,")
    lines.append("         w.first_ts, w.last_ts")
    lines.append("ORDER BY w.n_instances DESC;")
    lines.append("```")
    lines.append("")
    lines.append("### Load all real-Well Observations of one event class")
    lines.append("")
    lines.append(
        "The Observations tree is hive-partitioned by `event_class`, so a "
        "wildcard against one partition is a pruned scan — DuckDB only "
        "touches files under that path. Each file carries `instance_id`, "
        "`well_id`, `well_kind` as constant columns, so consumers can "
        "filter by Well or provenance without joining the catalog:"
    )
    lines.append("")
    lines.append("```sql")
    lines.append('SELECT instance_id, well_id, "timestamp", "P-PDG", "T-PDG", class')
    lines.append(f"FROM '{base_url}/observations/event_class=8/*.parquet'")
    lines.append("WHERE well_kind = 'real'")
    lines.append('ORDER BY instance_id, "timestamp";')
    lines.append("```")
    lines.append("")
    lines.append("### Fetch one specific Instance by `source_url`")
    lines.append("")
    lines.append(
        "Each row of `instances.parquet` carries the published URL of its "
        "Observations file. Round-trip the catalog and the time-series in "
        "two queries:"
    )
    lines.append("")
    lines.append("```sql")
    lines.append("-- 1. find the URL")
    lines.append("SELECT source_url")
    lines.append(f"FROM '{base_url}/instances.parquet'")
    lines.append("WHERE instance_id = 'WELL-00019_20120601165020';")
    lines.append("")
    lines.append("-- 2. read the Observations")
    lines.append(
        f"SELECT * FROM '{base_url}/observations/"
        f"event_class=8/WELL-00019_20120601165020.parquet';"
    )
    lines.append("```")
    lines.append("")
    lines.append("### Enumerate every Observations file (`_files.json`)")
    lines.append("")
    lines.append(
        "A JSON-array manifest at `observations/_files.json` lists every "
        "published file's path relative to the partition root, in catalog "
        "order. Useful for consumers that prefer enumeration over "
        "wildcard scans (e.g. ML training loops that iterate Instances "
        "one at a time)."
    )
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

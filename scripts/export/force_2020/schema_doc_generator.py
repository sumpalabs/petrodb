"""Generate the published documentation artifacts for the FORCE 2020 dataset.

The FORCE 2020 well-log corpus is published as one Parquet file per well under
``parquet/force_2020/wells/`` (108 files, one row per 0.15 m log sample). Unlike
every other petrodb dataset it shipped without schema documentation; this
generator closes that gap (issue #33) by emitting four files under the dataset
root plus the multi-parquet manifest mandated by ADR-0004:

- ``schema.json`` — machine-readable column list, types, nullability, PK.
- ``schema.sql``  — DDL that mirrors the published structure in a fresh DuckDB.
- ``schema.md``   — English column docs (units + petrophysical meaning) and the
                    12-class lithology code table.
- ``README.md``   — dataset overview, per-well file layout, DuckDB ``httpfs``
                    access patterns.
- ``wells/_files.json`` — JSON array of every well file's path relative to
                    ``wells/`` (the file-discovery contract from ADR-0004).

Column types are reflected straight from a published Parquet via DuckDB
``DESCRIBE``, so the documented schema cannot drift from the data. The per-column
prose (units, meaning) and the lithology mapping live in this module as the
single source of truth for the human docs.

Run from the repo root::

    uv run python -m scripts.export.force_2020.schema_doc_generator
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

DATASET_DIR = Path("parquet/force_2020")
WELLS_DIR = DATASET_DIR / "wells"

# Base URL the access examples read from (matches the other dataset READMEs).
BASE_URL = "https://dev-petrodb.ocortez.com/force_2020"

# Sourced from the FORCE 2020 Machine Predicted Lithology challenge.
UPSTREAM = {
    "name": "FORCE 2020 Machine Predicted Lithology challenge",
    "url": "https://github.com/bolgebrygg/Force-2020-Machine-Learning-competition",
    "license": "CC BY 4.0",
}

# Columns with a `0` (WELL) or `1` (DEPTH_MD) primary-key rank; everybody else
# is a regular column. (WELL, DEPTH_MD) is unique across the whole corpus.
PRIMARY_KEY = ("WELL", "DEPTH_MD")

# Per-column documentation: unit (or "" when dimensionless/categorical) and an
# English, reservoir-engineering-framed description. Keyed by column name; the
# ordering and type come from the reflected Parquet schema.
COLUMN_DOCS: dict[str, tuple[str, str]] = {
    "WELL": (
        "",
        "Well identifier in NPD notation (e.g. `15/9-13`). With `DEPTH_MD` "
        "forms the primary key. The per-well Parquet file is named after this "
        "value with `/` → `-` and spaces → `_` (`15/9-13` → `15-9-13.parquet`); "
        "per ADR-0004 the leaf filename carries no query semantics.",
    ),
    "DEPTH_MD": (
        "m",
        "Measured depth along the wellbore — the log sample index, on a regular "
        "~0.15 m step. Strictly increasing within a well; with `WELL` forms the "
        "primary key.",
    ),
    "X_LOC": (
        "m",
        "Easting of the sample in the survey projection (UTM zone 31N, ED50; "
        "Norwegian North Sea).",
    ),
    "Y_LOC": (
        "m",
        "Northing of the sample in the survey projection (UTM zone 31N, ED50).",
    ),
    "Z_LOC": (
        "m",
        "True vertical depth subsea (TVDSS) of the sample; negative downward "
        "below mean sea level.",
    ),
    "GROUP": (
        "",
        "Lithostratigraphic group at the sample depth, in NPD nomenclature "
        "(e.g. `HORDALAND GP.`, `SHETLAND GP.`). 14 distinct groups.",
    ),
    "FORMATION": (
        "",
        "Lithostratigraphic formation at the sample depth, in NPD nomenclature "
        "(e.g. `Draupne Fm.`, `Balder Fm.`). 69 distinct formations; a finer "
        "subdivision of `GROUP`.",
    ),
    "CALI": ("in", "Caliper — measured borehole diameter."),
    "RSHA": ("ohm·m", "Shallow-reading resistivity (flushed/invaded zone)."),
    "RMED": ("ohm·m", "Medium-reading resistivity (transition zone)."),
    "RDEP": (
        "ohm·m",
        "Deep-reading resistivity (virgin/uninvaded zone) — the primary true "
        "resistivity (Rt) curve for water-saturation analysis.",
    ),
    "RHOB": ("g/cm³", "Bulk density from the formation density tool."),
    "GR": (
        "gAPI",
        "Total gamma ray — the principal shaliness and lithology indicator.",
    ),
    "SGR": (
        "gAPI",
        "Spectral (total) gamma ray from the spectral GR tool. Sparsely "
        "recorded (~5% of samples).",
    ),
    "NPHI": (
        "v/v",
        "Neutron porosity (limestone-calibrated, fractional). Read against "
        "`RHOB` for the density–neutron crossover.",
    ),
    "PEF": (
        "b/e",
        "Photoelectric absorption factor — a mineralogy/lithology indicator.",
    ),
    "DTC": (
        "µs/ft",
        "Compressional-wave slowness (delta-T compressional) from the sonic "
        "tool. Used for porosity and synthetic seismic ties.",
    ),
    "SP": ("mV", "Spontaneous potential."),
    "BS": (
        "in",
        "Bit size — nominal hole diameter drilled; the reference gauge for "
        "caliper washout (`DCAL`).",
    ),
    "ROP": ("m/h", "Rate of penetration recorded while drilling."),
    "DTS": (
        "µs/ft",
        "Shear-wave slowness (delta-T shear). Sparsely recorded (~17% of "
        "samples); paired with `DTC` for geomechanics and Vp/Vs.",
    ),
    "DCAL": (
        "in",
        "Differential caliper (`CALI − BS`): positive indicates washout, "
        "negative indicates mudcake or hole swelling.",
    ),
    "DRHO": (
        "g/cm³",
        "Density correction curve from the density tool — a borehole-quality "
        "flag for `RHOB`.",
    ),
    "MUDWEIGHT": ("g/cm³", "Drilling-mud density (specific gravity)."),
    "RMIC": ("ohm·m", "Micro-resistivity (microlog-class flushed-zone reading)."),
    "ROPA": ("m/h", "Averaged rate of penetration."),
    "RXO": (
        "ohm·m",
        "Flushed-zone resistivity (Rxo); read against `RDEP` to gauge invasion "
        "and movable hydrocarbons.",
    ),
    "FORCE_2020_LITHOFACIES_LITHOLOGY": (
        "code",
        "Interpreted lithology label — the prediction target of the FORCE 2020 "
        "contest. Twelve classes encoded as integer keys; see the lithology "
        "code table below.",
    ),
    "dataset": (
        "",
        "Competition split the row belongs to: `train` or `test`.",
    ),
}

# Lithology key → human label, in ascending key order. Keys are the canonical
# FORCE 2020 lithology codes used by `FORCE_2020_LITHOFACIES_LITHOLOGY`.
LITHOLOGY_LABELS: dict[int, str] = {
    30000: "Sandstone",
    65000: "Shale",
    65030: "Sandstone/Shale",
    70000: "Limestone",
    70032: "Chalk",
    74000: "Dolomite",
    80000: "Marl",
    86000: "Anhydrite",
    88000: "Halite",
    90000: "Coal",
    93000: "Basement",
    99000: "Tuff",
}

# Curves that carry upstream sentinel placeholders (-999, -999.25, -999.9) for
# missing samples — flagged for consumers so they are treated as NULL, not data.
SENTINEL_NOTE = (
    "A few raw curves (notably `SP`, `ROPA`, `RXO`) carry upstream sentinel "
    "placeholders such as `-999`, `-999.25`, and `-999.9` for missing samples. "
    "These are preserved verbatim from the source; treat them as NULL rather "
    "than as measured values."
)


def reflect_columns() -> list[tuple[str, str]]:
    """Return ``[(name, duckdb_type), ...]`` in file order from a published well."""
    sample = sorted(WELLS_DIR.glob("*.parquet"))[0]
    con = duckdb.connect()
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{sample.as_posix()}')"
    ).fetchall()
    con.close()
    return [(r[0], r[1]) for r in rows]


def dataset_stats() -> dict:
    """Corpus-level counts used in the README narrative."""
    files = sorted(WELLS_DIR.glob("*.parquet"))
    paths = [f.as_posix() for f in files]
    con = duckdb.connect()
    con.execute(f"CREATE VIEW allw AS SELECT * FROM read_parquet({paths})")
    total_rows = con.execute("SELECT COUNT(*) FROM allw").fetchone()[0]
    n_wells = con.execute("SELECT COUNT(DISTINCT WELL) FROM allw").fetchone()[0]
    litho_counts = dict(
        con.execute(
            "SELECT FORCE_2020_LITHOFACIES_LITHOLOGY, COUNT(*) "
            "FROM allw GROUP BY 1"
        ).fetchall()
    )
    split_counts = dict(
        con.execute("SELECT dataset, COUNT(*) FROM allw GROUP BY 1").fetchall()
    )
    con.close()
    return {
        "n_files": len(files),
        "total_rows": total_rows,
        "n_wells": n_wells,
        "litho_counts": litho_counts,
        "split_counts": split_counts,
    }


def is_pk(name: str) -> bool:
    return name in PRIMARY_KEY


def write_files_manifest() -> None:
    """Emit ``wells/_files.json`` — the ADR-0004 file-discovery manifest."""
    names = sorted(p.name for p in WELLS_DIR.glob("*.parquet"))
    (WELLS_DIR / "_files.json").write_text(json.dumps(names, indent=2) + "\n")


def write_schema_json(columns: list[tuple[str, str]]) -> None:
    payload = {
        "dataset": "force_2020",
        "description": (
            "Wireline and LWD well logs from 108 Norwegian North Sea wells, "
            "with an interpreted lithology label per sample — the FORCE 2020 "
            "Machine Predicted Lithology challenge corpus, republished as one "
            "Parquet file per well."
        ),
        "upstream": UPSTREAM,
        "tables": {
            "wells": {
                "description": (
                    "One row per ~0.15 m log sample. Published as one file per "
                    "well under `wells/<well>.parquet` (a flat multi-parquet "
                    "table per ADR-0004: no Hive key, discovery via "
                    "`wells/_files.json`)."
                ),
                "layout": "wells/<well>.parquet",
                "files_manifest": "wells/_files.json",
                "columns": [
                    {
                        "name": name,
                        "type": dtype,
                        "unit": COLUMN_DOCS[name][0] or None,
                        "not_null": is_pk(name),
                        "primary_key": is_pk(name),
                    }
                    for name, dtype in columns
                ],
                "primary_key": list(PRIMARY_KEY),
                "foreign_keys": [],
            }
        },
        "lithology_labels": {
            str(code): label for code, label in LITHOLOGY_LABELS.items()
        },
    }
    (DATASET_DIR / "schema.json").write_text(json.dumps(payload, indent=2) + "\n")


def write_schema_sql(columns: list[tuple[str, str]]) -> None:
    lines = [
        "-- FORCE 2020 dataset — DDL",
        "-- Auto-generated from the published Parquet schema. Do not edit by hand.",
        f"-- Upstream: {UPSTREAM['url']}",
        "",
        "-- One row per ~0.15 m log sample. Published as one Parquet file per",
        "-- well under wells/<well>.parquet; (WELL, DEPTH_MD) is the primary key.",
        "CREATE TABLE wells (",
    ]
    # Only the SQL reserved word `GROUP` needs quoting; every other column is a
    # plain identifier (uppercase mnemonics, or lowercase `dataset`).
    reserved = {"GROUP"}
    col_lines = []
    for name, dtype in columns:
        ident = f'"{name}"' if name.upper() in reserved else name
        suffix = " NOT NULL" if is_pk(name) else ""
        col_lines.append(f"  {ident} {dtype}{suffix}")
    col_lines.append(
        "  PRIMARY KEY (" + ", ".join(PRIMARY_KEY) + ")"
    )
    lines.append(",\n".join(col_lines))
    lines.append(");")
    (DATASET_DIR / "schema.sql").write_text("\n".join(lines) + "\n")


def write_schema_md(columns: list[tuple[str, str]], stats: dict) -> None:
    out: list[str] = []
    out.append("# FORCE 2020 — Dataset Schema")
    out.append("")
    out.append(
        f"Wireline and LWD well logs from {stats['n_wells']} Norwegian North Sea "
        "wells, with an interpreted lithology label per sample. Sourced from the "
        f"[{UPSTREAM['name']}]({UPSTREAM['url']}). Column identifiers are "
        "preserved verbatim from the source (uppercase log mnemonics such as "
        "`GR`, `RHOB`, `NPHI`); the reserved word `GROUP` must be double-quoted "
        "in SQL. All explanatory prose below is in English."
    )
    out.append("")
    out.append("## Tables")
    out.append("")
    out.append("### `wells`")
    out.append("")
    out.append(
        f"One row per ~0.15 m log sample ({stats['total_rows']:,} rows across "
        f"{stats['n_files']} wells). Published as one Parquet file per well "
        "under `wells/<well>.parquet` — a flat multi-parquet table per "
        "[ADR-0004](../../docs/adr/0004-multi-parquet-table-convention.md): "
        "no Hive partition key, with file discovery via `wells/_files.json`. "
        "The primary key is `(WELL, DEPTH_MD)`."
    )
    out.append("")
    out.append(SENTINEL_NOTE)
    out.append("")
    out.append("**Columns:**")
    out.append("")
    out.append("| Column | Type | Unit | Nullable | PK | Description |")
    out.append("|--------|------|------|----------|----|-------------|")
    for name, dtype in columns:
        unit, desc = COLUMN_DOCS[name]
        ident = f'`{name}`'
        nullable = "No" if is_pk(name) else "Yes"
        pk = "✓" if is_pk(name) else ""
        unit_cell = unit if unit else "—"
        out.append(
            f"| {ident} | {dtype} | {unit_cell} | {nullable} | {pk} | {desc} |"
        )
    out.append("")
    out.append("**Primary key:** `(WELL, DEPTH_MD)`")
    out.append("")
    out.append("---")
    out.append("")
    out.append("## Lithology code table")
    out.append("")
    out.append(
        "`FORCE_2020_LITHOFACIES_LITHOLOGY` encodes the interpreted lithology as "
        "an integer key. The twelve classes and their corpus sample counts:"
    )
    out.append("")
    out.append("| Code | Lithology | Samples |")
    out.append("|------|-----------|---------|")
    for code, label in LITHOLOGY_LABELS.items():
        count = stats["litho_counts"].get(code, 0)
        out.append(f"| {code} | {label} | {count:,} |")
    out.append("")
    (DATASET_DIR / "schema.md").write_text("\n".join(out) + "\n")


def write_readme(stats: dict) -> None:
    litho_rows = "\n".join(
        f"| {code} | {label} | {stats['litho_counts'].get(code, 0):,} |"
        for code, label in LITHOLOGY_LABELS.items()
    )
    train = stats["split_counts"].get("train", 0)
    test = stats["split_counts"].get("test", 0)
    readme = f"""# FORCE 2020 Dataset

Wireline and LWD well logs from {stats['n_wells']} Norwegian North Sea wells,
with an interpreted lithology label per sample — the corpus of the
[{UPSTREAM['name']}]({UPSTREAM['url']}). Republished as one Parquet file per well
({stats['total_rows']:,} log samples in total).

## Upstream

- Source: <{UPSTREAM['url']}>
- License: {UPSTREAM['license']}

## Published files

```
force_2020/
├── wells/
│   ├── 15-9-13.parquet     # one file per well, named after the WELL id
│   ├── 15-9-14.parquet     #   ({stats['n_files']} files)
│   ├── …
│   └── _files.json         # manifest of every well file's path (ADR-0004)
├── schema.md
├── schema.json
└── schema.sql
```

Each row is one ~0.15 m log sample; the primary key is `(WELL, DEPTH_MD)`. The
per-well file is named after the `WELL` identifier with `/` → `-` and spaces
→ `_` (`15/9-13` → `15-9-13.parquet`). Per
[ADR-0004](../../docs/adr/0004-multi-parquet-table-convention.md) the leaf
filename carries no query semantics — file discovery is the `_files.json`
manifest, not the filename.

Column identifiers are the source log mnemonics, preserved verbatim (uppercase:
`GR`, `RHOB`, `NPHI`, `RDEP`, …). The reserved word `GROUP` must be
double-quoted in SQL. {SENTINEL_NOTE}

## Lithology label

`FORCE_2020_LITHOFACIES_LITHOLOGY` is the interpreted lithology — the prediction
target of the FORCE 2020 contest — encoded as an integer key:

| Code | Lithology | Samples |
|------|-----------|---------|
{litho_rows}

Rows are tagged `train` ({train:,} samples) or `test` ({test:,} samples) by the
`dataset` column, mirroring the original competition split.

## Access via DuckDB `httpfs`

All examples assume DuckDB ≥ 1.0 with the `httpfs` extension enabled. Queries
read straight from the site without downloading.

```sql
INSTALL httpfs; LOAD httpfs;
```

### Read one well

Each well is a single file named after its `WELL` id, so a single-well log read
is a direct fetch — no manifest or wildcard needed:

```sql
SELECT DEPTH_MD, GR, RHOB, NPHI, RDEP, "GROUP", FORMATION,
       FORCE_2020_LITHOFACIES_LITHOLOGY AS lithology
FROM '{BASE_URL}/wells/15-9-13.parquet'
ORDER BY DEPTH_MD;
```

### Discover and read across wells (`_files.json`)

There is no directory listing over static hosting, so cross-well queries read
the `_files.json` manifest first, then hand DuckDB the explicit list of URLs
(per [ADR-0004](../../docs/adr/0004-multi-parquet-table-convention.md)):

```python
import json, urllib.request, duckdb

base = '{BASE_URL}/wells/'
manifest = json.load(urllib.request.urlopen(base + '_files.json'))
urls = [base + name for name in manifest]

duckdb.sql(\"\"\"
    SELECT WELL,
           COUNT(*)                              AS n_samples,
           COUNT(DISTINCT FORCE_2020_LITHOFACIES_LITHOLOGY) AS n_lithologies
    FROM read_parquet(?)
    GROUP BY WELL
    ORDER BY n_samples DESC
\"\"\", params=[urls]).show()
```

### Lithology balance across the corpus

```python
import json, urllib.request, duckdb

base = '{BASE_URL}/wells/'
urls = [base + n for n in json.load(urllib.request.urlopen(base + '_files.json'))]

duckdb.sql(\"\"\"
    SELECT FORCE_2020_LITHOFACIES_LITHOLOGY AS lithology,
           dataset,
           COUNT(*) AS n_samples
    FROM read_parquet(?)
    GROUP BY lithology, dataset
    ORDER BY lithology, dataset
\"\"\", params=[urls]).show()
```

### Leave-one-well-out cross-validation

Lithology models on FORCE 2020 should split by `WELL`, not by random sample —
adjacent samples in the same well are highly correlated and would leak signal
across a naive shuffle. With one file per well, holding a well out is just
dropping its URL from the read list:

```python
import json, urllib.request, duckdb

base = '{BASE_URL}/wells/'
manifest = json.load(urllib.request.urlopen(base + '_files.json'))

held_out = '15-9-13.parquet'
train_urls = [base + n for n in manifest if n != held_out]
test_urls = [base + held_out]
# read_parquet(train_urls) → training set; read_parquet(test_urls) → held-out well
```

## Full schema

See `schema.md` (human-readable, with units and the 12-class lithology table),
`schema.json` (programmatic), and `schema.sql` (DDL to reproduce the structure
locally).
"""
    (DATASET_DIR / "README.md").write_text(readme)


def main() -> None:
    columns = reflect_columns()
    missing = [name for name, _ in columns if name not in COLUMN_DOCS]
    if missing:
        raise SystemExit(f"Undocumented columns in COLUMN_DOCS: {missing}")
    stats = dataset_stats()
    write_files_manifest()
    write_schema_json(columns)
    write_schema_sql(columns)
    write_schema_md(columns, stats)
    write_readme(stats)
    print(
        f"Wrote schema docs for force_2020: {len(columns)} columns, "
        f"{stats['n_files']} well files, {stats['total_rows']:,} rows."
    )


if __name__ == "__main__":
    main()

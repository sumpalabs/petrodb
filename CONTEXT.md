# PetroDB

Open petroleum datasets converted to columnar Parquet files, served via HTTP and queried remotely with DuckDB `httpfs`. The project transforms heterogeneous public sources (Volve, FORCE 2020, Argentina production) into a clean, non-redundant relational schema.

## Language

### Argentina production dataset

**Well** (`idpozo`):
The canonical entity in the Argentina production data. An integer ID that identifies a producing unit at the granularity of *(physical wellbore × producing formation)*. A single physical wellbore producing from two formations gets two distinct `idpozo`s.
_Avoid_: "wellbore" (ambiguous — does not capture the formation split), `sigla` (human-readable label, may change).

**Sigla**:
The human-readable code for a well (e.g. `YPF.BLO.x-8`). Treated as a label, not an identity. Possibly mutable over time; not a primary key.

**Formprod** (producing formation):
The geological formation a given `idpozo` produces from. Static per `idpozo` by construction (encoded into the ID itself), so it lives in the master table, never in the time-series.

## Relationships

- A **Well** (`idpozo`) is the unit of identity for both the master table and the production time-series.
- **Formprod** is a static attribute of a **Well** — recorded once in the master, never repeated in monthly rows.

## Flagged ambiguities

- "well" was used to refer to both the physical wellbore and the producing-formation-specific record — resolved: in this dataset a **Well** = `idpozo` = wellbore × formprod. Use "physical wellbore" if the bore-only concept is needed.

## Argentina dataset — column buckets

Driven by per-`idpozo` cross-year volatility (17.6M rows / 85,305 wells, 2006-2025). Four destinations:

**Static master** (`wells.parquet`, 1 row per `idpozo`) — < 0.3% of wells ever change these:
`sigla`, `formprod`, `formacion`, `profundidad`, `cuenca`, `provincia`, `(id)areapermisoconcesion`, `(id)areayacimiento`, `tipo_de_recurso`, `sub_tipo_recurso`, `clasificacion`, `subclasificacion`, `proyecto`. Plus enrichments from `listado` (`coordenadax`, `coordenaday`, initial test rates, drilling/completion/abandonment dates, `codigopropio`, `nombrepropio`) and `capitulo-iv` (`geom`).
- Spine: capitulo-iv (broadest coverage, 100% geometry, 100% field agreement on overlap).
- LEFT JOIN listado for enrichment columns capitulo-iv lacks.
- Includes 113 orphan wells (in capitulo-iv but never produced) flagged with `has_production = false`.
- `geojson` is dropped (redundant text encoding of the same lat/lon already in `coordenadax`/`coordenaday`/`geom`).

**Time-changing metadata** (`well_operator_history.parquet`) — operator transfers, ~67% of wells change at least once:
`idpozo`, `idempresa`, `empresa`, `valid_from`, `valid_to`. One row per contiguous-operator interval.

**Events** (`well_events.parquet`) — operational state transitions:
`idpozo`, `event_date`, `tipoestado`, `tipoextraccion`, `tipopozo`. Snapshot at each month where any of the three changed. ~74% of wells change `tipoestado`, ~45% change the others.

**Time-series** (`monthly_production.parquet`) — numeric monthly measurements only:
`idpozo`, `fecha` (DATE, first-of-month derived from source `anio`/`mes`), `prod_pet`, `prod_gas`, `prod_agua`, `iny_agua`, `iny_gas`, `iny_co2`, `iny_otro`, `tef`, `vida_util`. PK = (`idpozo`, `fecha`). Source `anio`/`mes` are not retained separately.

**Dropped:** `observaciones`, `idusuario`, `rectificado`, `habilitado`, `fechaingreso`, `fecha_data` — administrative/audit fields with no downstream value.

## Argentina dataset — operating principles

- **Spanish column names preserved** as in source (idpozo, cuenca, sigla, formprod, prod_pet, etc.). Column-meaning glossary lives on the website, not in renames.
- **Source fidelity over smoothing**: NULL gaps in the operator history are kept as-is (emit a NULL-operator interval). One-month flips in events / operators are emitted, not smoothed. The transformations are de-duplication and re-shaping, never reinterpretation.
- **Date-completeness in `monthly_production`**: every well must have a row for every month in `[first_production_row, last_production_row]`. If the source skipped a month, the transform synthesizes a row with NULL numeric measurements. This makes "no row" mean "well had not started / had been abandoned" and "row with NULL measurements" mean "well existed but no data was reported." Operator-history and events tables are NOT gap-filled — they are built from the original source where the gap is the data.
- **Initial test rates** (`pet_inicial`, `gas_inicial`, `agua_inicial`, `vida_util_inicial`, etc.) are static master attributes, not events.

## Argentina dataset — output layout

`parquet/argentina/`
- `wells.parquet` — single file, ~85,418 rows (incl. 113 orphans, flagged `has_production = false`)
- `well_operator_history.parquet` — single file, one row per contiguous-`idempresa` run per `idpozo` (NULLs preserved as their own runs)
- `well_events.parquet` — single file, one row per snapshot of `(tipoestado, tipoextraccion, tipopozo)` per transition month
- `monthly_production/anio=YYYY/data.parquet` — hive-partitioned by year (22 files), each sorted by `(idpozo, mes)` for row-group pruning on single-well queries
- `monthly_production/_files.json` — manifest of partition URLs for httpfs consumers

Rationale: keep individual file sizes well under Cloudflare's edge-cache file-size limits so the site is zero-cost static hosting. Year partitioning lets DuckDB httpfs prune by `anio`; sorting within each file lets it prune by `idpozo` via row-group statistics, so single-well queries fetch only the rows they need.

## Argentina dataset — pipeline

**Diverges from the Volve SQLite/SQLAlchemy/pandas pattern** because of the ~1000× data-volume difference (17.6M rows vs 16k).

- Intermediate: `database/argentina.duckdb` (gitignored).
- `scripts/explore/argentina/` — produces statistics and matplotlib PNGs into `scripts/explore/argentina/output/` plus a `FINDINGS.md` summary. Outputs are reference material, not served.
- `scripts/transform/argentina/` — reads source CSVs into the DuckDB file via `read_csv_auto`, builds the four destination tables in pure SQL.
- `scripts/export/argentina/` — emits Parquets via `COPY ... TO ... (FORMAT PARQUET, PARTITION_BY anio)` for `monthly_production`; single-file `COPY` for the rest.
- Polars is permitted only where SQL becomes unreadable; pandas is not used.

## Argentina dataset — type quirks

- `idempresa` is **VARCHAR**, not INTEGER. Source values include alphanumeric codes (`Z001`, `APEA`).

## Argentina dataset — published deliverables

Mirrors the Volve / FORCE 2020 pattern.

- `parquet/argentina/schema.md` — human-readable column docs (Spanish), table relationships.
- `parquet/argentina/schema.json` — machine-readable schema for tooling.
- `parquet/argentina/schema.sql` — DDL to mirror the structure locally.
- `parquet/argentina/README.md` — dataset overview + access patterns (URL-template `generate_series` trick + manifest usage).
- `parquet/index.html` — patched with an Argentina entry alongside Volve and FORCE 2020.
- Root `README.md` `## Datasets` section — Argentina blurb + DuckDB query example.

## Argentina dataset — pre-publish validation

The export step asserts the following before writing Parquets; failure aborts publish.

1. `monthly_production` has unique `(idpozo, fecha)`.
2. Every `idpozo` in `monthly_production`, `well_operator_history`, `well_events` exists in `wells.parquet` (FK integrity).
3. Date-completeness: for every well, monthly row count == `(last_fecha - first_fecha)` in months + 1.
4. Geometry in `wells.parquet` is parseable WKB for every row that carries a `geom`.
5. Year-partition count is 22 and the sum of partition row counts equals the staged-source row count.
6. Soft-warn if any year-partition Parquet exceeds 50 MB (Cloudflare cache headroom).

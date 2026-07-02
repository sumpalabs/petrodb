# Argentina Production Dataset

Monthly oil and gas well production for Argentina (2006–present), published as four Parquet tables. Column identifiers are preserved in Spanish exactly as the source publishes them; all documentation below is in English.

## Published files

```
argentina/
├── wells.parquet                   # 1 row per idpozo (~85,418)
├── well_operator_history.parquet   # 1 row per operator run
├── well_events.parquet             # 1 row per state-transition month
├── monthly_production/
│   ├── anio=2006/data.parquet
│   ├── anio=2007/data.parquet
│   ├── ...
│   └── _files.json                 # partition manifest
├── schema.md
├── schema.json
└── schema.sql
```

Column identifiers are preserved verbatim in their source Spanish (`idpozo`, `cuenca`, `sigla`, `formprod`, `prod_pet`, …). The glossary of opaque codes such as `tef` and `vida_util` lives in `schema.md`.

## Dropped columns

These source columns are administrative/audit fields and are **not published**:

- `geojson`
- `observaciones`
- `idusuario`
- `rectificado`
- `habilitado`
- `fechaingreso`
- `fecha_data`

## Access via DuckDB `httpfs`

All examples assume DuckDB ≥ 1.0 with the `httpfs` extension enabled. Queries read straight from the site without downloading.

```sql
INSTALL httpfs; LOAD httpfs;
```

`monthly_production` is a multi-parquet table; discover its partition files from the `_files.json` manifest (ADR-0004) and hand DuckDB the explicit URL list — the static host serves no directory listing, so wildcard globbing over the partitions does not resolve. `hive_partitioning = true` recovers the `anio` column from each path.

### 1. Single well by `idpozo`

Each partition is sorted by `(idpozo, fecha)`, so Parquet row-group statistics let DuckDB prune the row groups that do not contain the requested well: the query downloads minimal byte ranges.

```python
import json, urllib.request, duckdb

base = 'https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main/argentina/monthly_production/'
manifest = json.load(urllib.request.urlopen(base + '_files.json'))
urls = [base + p for p in manifest]

duckdb.sql("""
    SELECT idpozo, fecha, prod_pet, prod_gas
    FROM read_parquet(?, hive_partitioning = true)
    WHERE idpozo = 12345
    ORDER BY fecha
""", params=[urls]).show()
```

### 2. Year range

Narrow the manifest to the requested years client-side so only those partition files are fetched; `hive_partitioning` still derives `anio` from the path for the `WHERE` filter.

```python
import json, urllib.request, duckdb

base = 'https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main/argentina/monthly_production/'
manifest = json.load(urllib.request.urlopen(base + '_files.json'))
urls = [base + p for p in manifest if 2018 <= int(p.split('=')[1][:4]) <= 2022]

duckdb.sql("""
    SELECT anio, COUNT(*) AS rows, SUM(prod_pet) AS prod_pet_total
    FROM read_parquet(?, hive_partitioning = true)
    WHERE anio BETWEEN 2018 AND 2022
    GROUP BY anio
    ORDER BY anio
""", params=[urls]).show()
```

### 3. Aggregate by basin (join `wells` ↔ `monthly_production`)

The `wells` master is a single file, read directly; `monthly_production` is reduced to the year of interest by narrowing the manifest to that partition before the join.

```python
import json, urllib.request, duckdb

base = 'https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main/argentina/monthly_production/'
manifest = json.load(urllib.request.urlopen(base + '_files.json'))
urls = [base + p for p in manifest if p.startswith('anio=2023/')]

duckdb.sql(f"""
    SELECT w.cuenca,
           SUM(m.prod_pet) AS prod_pet_total,
           SUM(m.prod_gas) AS prod_gas_total
    FROM 'https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main/argentina/wells.parquet' w
    JOIN read_parquet(?, hive_partitioning = true) m USING (idpozo)
    WHERE m.anio = 2023
    GROUP BY w.cuenca
    ORDER BY prod_pet_total DESC
""", params=[urls]).show()
```

### 4. Read the whole series (the manifest is the contract)

`_files.json` lists every partition's path relative to `monthly_production/`; it is the file-discovery contract (ADR-0004) and the only supported way to enumerate the table over static hosting. Read them all for a corpus-wide aggregate:

```python
import json, urllib.request, duckdb

base = 'https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main/argentina/monthly_production/'
manifest = json.load(urllib.request.urlopen(base + '_files.json'))
urls = [base + p for p in manifest]

duckdb.sql("""
    SELECT anio, SUM(prod_pet) AS prod_pet_total, SUM(prod_gas) AS prod_gas_total
    FROM read_parquet(?, hive_partitioning = true)
    GROUP BY anio
    ORDER BY anio
""", params=[urls]).show()
```

## Full schema

See `schema.md` (human-readable) / `schema.json` (programmatic consumption) / `schema.sql` (DDL to reproduce the structure locally).

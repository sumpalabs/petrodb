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

### 1. Single well by `idpozo`

Each partition is sorted by `(idpozo, fecha)`, so Parquet row-group statistics let DuckDB prune the row groups that do not contain the requested well: the query downloads minimal byte ranges.

```sql
SELECT idpozo, fecha, prod_pet, prod_gas
FROM 'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=*/data.parquet'
WHERE idpozo = 12345
ORDER BY fecha;
```

### 2. Year range

Hive partitioning on `anio` lets DuckDB prune partitions outside the requested range. Enable `hive_partitioning` so the `anio` column is derived from the path.

```sql
SELECT anio, COUNT(*) AS rows, SUM(prod_pet) AS prod_pet_total
FROM read_parquet(
  'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=*/data.parquet',
  hive_partitioning = true
)
WHERE anio BETWEEN 2018 AND 2022
GROUP BY anio
ORDER BY anio;
```

### 3. Aggregate by basin (join `wells` ↔ `monthly_production`)

The `wells` master table is loaded once (it is small); `monthly_production` is reduced by `anio` before the join.

```sql
SELECT w.cuenca,
       SUM(m.prod_pet) AS prod_pet_total,
       SUM(m.prod_gas) AS prod_gas_total
FROM 'https://dev-petrodb.ocortez.com/argentina/wells.parquet' w
JOIN read_parquet(
  'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=*/data.parquet',
  hive_partitioning = true
) m USING (idpozo)
WHERE m.anio = 2023
GROUP BY w.cuenca
ORDER BY prod_pet_total DESC;
```

### 4. Manifest + `generate_series`

The `_files.json` manifest lists the relative URL of every partition. If you prefer to avoid the wildcard pattern (which requires a LIST), build the URLs with `generate_series` and read them via a VALUES list — handy when the front edge caches by exact URL.

```sql
WITH urls AS (
  SELECT
    'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=' || y || '/data.parquet' AS url
  FROM generate_series(2006, 2025) AS t(y)
)
SELECT m.idpozo, m.fecha, m.prod_pet
FROM read_parquet((SELECT LIST(url) FROM urls), hive_partitioning = true) m
WHERE m.idpozo = 12345
ORDER BY m.fecha;
```

Alternatively, read the manifest and build the URL list from the client application:

```python
import json, urllib.request, duckdb
manifest = json.load(urllib.request.urlopen('https://dev-petrodb.ocortez.com/argentina/monthly_production/_files.json'))
urls = [f'https://dev-petrodb.ocortez.com/argentina/monthly_production/' + p for p in manifest]
duckdb.sql("SELECT * FROM read_parquet(?, hive_partitioning = true) "
           "WHERE idpozo = 12345", params=[urls]).show()
```

## Full schema

See `schema.md` (human-readable) / `schema.json` (programmatic consumption) / `schema.sql` (DDL to reproduce the structure locally).

# FORCE 2020 Dataset

Wireline and LWD well logs from 108 Norwegian North Sea wells,
with an interpreted lithology label per sample — the corpus of the
[FORCE 2020 Machine Predicted Lithology challenge](https://github.com/bolgebrygg/Force-2020-Machine-Learning-competition). Republished as one Parquet file per well
(1,307,297 log samples in total).

## Upstream

- Source: <https://github.com/bolgebrygg/Force-2020-Machine-Learning-competition>
- License: CC BY 4.0

## Published files

```
force_2020/
├── wells/
│   ├── 15-9-13.parquet     # one file per well, named after the WELL id
│   ├── 15-9-14.parquet     #   (108 files)
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
double-quoted in SQL. A few raw curves (notably `SP`, `ROPA`, `RXO`) carry upstream sentinel placeholders such as `-999`, `-999.25`, and `-999.9` for missing samples. These are preserved verbatim from the source; treat them as NULL rather than as measured values.

## Lithology label

`FORCE_2020_LITHOFACIES_LITHOLOGY` is the interpreted lithology — the prediction
target of the FORCE 2020 contest — encoded as an integer key:

| Code | Lithology | Samples |
|------|-----------|---------|
| 30000 | Sandstone | 192,985 |
| 65000 | Shale | 804,778 |
| 65030 | Sandstone/Shale | 168,013 |
| 70000 | Limestone | 61,118 |
| 70032 | Chalk | 11,138 |
| 74000 | Dolomite | 2,104 |
| 80000 | Marl | 36,635 |
| 86000 | Anhydrite | 1,210 |
| 88000 | Halite | 8,213 |
| 90000 | Coal | 4,510 |
| 93000 | Basement | 103 |
| 99000 | Tuff | 16,490 |

Rows are tagged `train` (1,170,511 samples) or `test` (136,786 samples) by the
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
FROM 'https://dev-petrodb.ocortez.com/force_2020/wells/15-9-13.parquet'
ORDER BY DEPTH_MD;
```

### Discover and read across wells (`_files.json`)

There is no directory listing over static hosting, so cross-well queries read
the `_files.json` manifest first, then hand DuckDB the explicit list of URLs
(per [ADR-0004](../../docs/adr/0004-multi-parquet-table-convention.md)):

```python
import json, urllib.request, duckdb

base = 'https://dev-petrodb.ocortez.com/force_2020/wells/'
manifest = json.load(urllib.request.urlopen(base + '_files.json'))
urls = [base + name for name in manifest]

duckdb.sql("""
    SELECT WELL,
           COUNT(*)                              AS n_samples,
           COUNT(DISTINCT FORCE_2020_LITHOFACIES_LITHOLOGY) AS n_lithologies
    FROM read_parquet(?)
    GROUP BY WELL
    ORDER BY n_samples DESC
""", params=[urls]).show()
```

### Lithology balance across the corpus

```python
import json, urllib.request, duckdb

base = 'https://dev-petrodb.ocortez.com/force_2020/wells/'
urls = [base + n for n in json.load(urllib.request.urlopen(base + '_files.json'))]

duckdb.sql("""
    SELECT FORCE_2020_LITHOFACIES_LITHOLOGY AS lithology,
           dataset,
           COUNT(*) AS n_samples
    FROM read_parquet(?)
    GROUP BY lithology, dataset
    ORDER BY lithology, dataset
""", params=[urls]).show()
```

### Leave-one-well-out cross-validation

Lithology models on FORCE 2020 should split by `WELL`, not by random sample —
adjacent samples in the same well are highly correlated and would leak signal
across a naive shuffle. With one file per well, holding a well out is just
dropping its URL from the read list:

```python
import json, urllib.request, duckdb

base = 'https://dev-petrodb.ocortez.com/force_2020/wells/'
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

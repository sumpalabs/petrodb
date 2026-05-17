# Petrobras 3W Dataset

Labelled 1-Hz sensor-data windows for the Petrobras 3W dataset, republished as Parquet files. This release publishes the event-class lookup (`event_types.parquet`), the full Instance catalog (`instances.parquet`), the real-Well master (`wells.parquet`), and the per-Instance Observations time-series (`observations/event_class=N/<instance_id>.parquet`).

## Upstream pin

- Repository: <https://github.com/petrobras/3W.git>
- Pinned git tag: `v.1.70.0`
- Upstream dataset version: `2.0.0`

Refreshes are event-driven on new upstream tags (see [ADR-0002](../../docs/adr/0002-petrobras-3w-pin-upstream-release-tag.md)). Both the git tag and the dataset version are emitted in the publish orchestrator's validation log.

## Published files

```
petrobras_3w/
├── event_types.parquet     # 10 rows, one per upstream event class
├── wells.parquet           # 40 rows, one per real Well
├── instances.parquet       # one row per upstream Instance file
├── observations/
│   ├── event_class=0/<instance_id>.parquet   # ~594 files
│   ├── …
│   ├── event_class=9/<instance_id>.parquet   # ~207 files
│   └── _files.json                            # manifest of every Observations file's relative path
├── schema.md
├── schema.json
├── schema.sql
└── LICENSE-3W-DATA.md      # CC BY 4.0 mirror with upstream attribution
```

Source column names from upstream (`P-PDG`, `ABER-CKGL`, `ESTADO-SDV-GL`, …) are preserved verbatim including hyphens; consumers must double-quote those identifiers in SQL.

## Access via DuckDB `httpfs`

All examples assume DuckDB ≥ 1.0 with the `httpfs` extension enabled. Queries read straight from the site without downloading.

```sql
INSTALL httpfs; LOAD httpfs;
```

### List every event class

```sql
SELECT event_class, name, description, has_transient, transient_code
FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/event_types.parquet'
ORDER BY event_class;
```

### Filter to anomaly classes only

```sql
SELECT name, description, transient_code
FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/event_types.parquet'
WHERE event_class > 0
ORDER BY event_class;
```

### Corpus balance from the Instance catalog

The per-Instance `n_rows_*` counts let you measure the labelled data balance across the corpus without scanning the Observations time-series:

```sql
SELECT
    et.event_class,
    et.description,
    COUNT(*)              AS n_instances,
    SUM(i.n_rows)         AS n_observations,
    SUM(i.n_rows_steady)  AS n_observations_steady
FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/instances.parquet' i
JOIN 'https://dev-petrodb.ocortez.com/petrobras_3w/event_types.parquet' et
    ON et.event_class = i.event_class
GROUP BY et.event_class, et.description
ORDER BY et.event_class;
```

### List Instances of a single event class (real wells only)

```sql
SELECT instance_id, well_id, start_ts, n_rows, source_url
FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/instances.parquet'
WHERE event_class = 8
  AND well_kind = 'real'
ORDER BY start_ts;
```

### Per-Well corpus footprint (join `wells` with `instances`)

The `wells` master pre-aggregates each Well's Instance and Observation counts so coverage tables can be built without scanning Observations:

```sql
SELECT
    w.well_id,
    w.n_instances,
    w.n_observations,
    w.first_ts,
    w.last_ts,
    COUNT(DISTINCT i.event_class) AS distinct_event_classes
FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/wells.parquet' w
JOIN 'https://dev-petrodb.ocortez.com/petrobras_3w/instances.parquet' i USING (well_id)
GROUP BY w.well_id, w.n_instances, w.n_observations,
         w.first_ts, w.last_ts
ORDER BY w.n_instances DESC;
```

### Per-Well cross-validation split (leave-one-Well-out)

Training models on Petrobras 3W should split by `well_id`, not by Instance — Instances drawn from the same physical Well share operating conditions and would leak signal across a naive shuffle. Assign each real Well a stable fold index from the `well_id` modulo the desired fold count, then derive the test Instances for fold `k` directly from `instances.parquet`:

```sql
WITH folded AS (
    SELECT well_id, well_id % 5 AS fold
    FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/wells.parquet'
)
SELECT i.instance_id, i.event_class, i.n_rows, i.source_url
FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/instances.parquet' i
JOIN folded f USING (well_id)
WHERE f.fold = 0  -- held-out test set; train on fold != 0
ORDER BY i.event_class, i.instance_id;
```

The simulated and drawn Instances (`well_kind <> 'real'`, `well_id IS NULL`) are excluded from the join above and can be added to the training set independently — they have no physical Well to leak against.

### Load all real-Well Observations of one event class

The Observations tree is hive-partitioned by `event_class`, so a wildcard against one partition is a pruned scan — DuckDB only touches files under that path. Each file carries `instance_id`, `well_id`, `well_kind` as constant columns, so consumers can filter by Well or provenance without joining the catalog:

```sql
SELECT instance_id, well_id, "timestamp", "P-PDG", "T-PDG", class
FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/observations/event_class=8/*.parquet'
WHERE well_kind = 'real'
ORDER BY instance_id, "timestamp";
```

### Fetch one specific Instance by `source_url`

Each row of `instances.parquet` carries the published URL of its Observations file. Round-trip the catalog and the time-series in two queries:

```sql
-- 1. find the URL
SELECT source_url
FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/instances.parquet'
WHERE instance_id = 'WELL-00019_20120601165020';

-- 2. read the Observations
SELECT * FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/observations/event_class=8/WELL-00019_20120601165020.parquet';
```

### Enumerate every Observations file (`_files.json`)

A JSON-array manifest at `observations/_files.json` lists every published file's path relative to the partition root, in catalog order. Useful for consumers that prefer enumeration over wildcard scans (e.g. ML training loops that iterate Instances one at a time).

## License

Upstream data is released under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). See `LICENSE-3W-DATA.md` in this directory for the attribution text.

## Full schema

See `schema.md` (human-readable, with the 27-sensor glossary), `schema.json` (programmatic), and `schema.sql` (DDL to reproduce the structure locally).

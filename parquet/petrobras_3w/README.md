# Petrobras 3W Dataset

Labelled 1-Hz sensor-data windows for the Petrobras 3W dataset, republished as Parquet files. The full per-Instance time-series (`observations/`), the Instance catalog (`instances.parquet`), and the real-Well master (`wells.parquet`) ship in subsequent issues (#22, #20, #21); this initial release publishes only the event-class lookup (`event_types.parquet`) and the documentation scaffolding so consumers can preview the schema.

## Upstream pin

- Repository: <https://github.com/petrobras/3W.git>
- Pinned git tag: `v.1.70.0`
- Upstream dataset version: `2.0.0`

Refreshes are event-driven on new upstream tags (see [ADR-0002](../../docs/adr/0002-petrobras-3w-pin-upstream-release-tag.md)). Both the git tag and the dataset version are emitted in the publish orchestrator's validation log.

## Published files (this slice)

```
petrobras_3w/
├── event_types.parquet     # 10 rows, one per upstream event class
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

## License

Upstream data is released under [Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/). See `LICENSE-3W-DATA.md` in this directory for the attribution text.

## Full schema

See `schema.md` (human-readable, with the 27-sensor glossary), `schema.json` (programmatic), and `schema.sql` (DDL to reproduce the structure locally).

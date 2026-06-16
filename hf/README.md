---
license: cc-by-4.0
pretty_name: PetroDB
tags:
  - petroleum
  - reservoir-engineering
  - parquet
  - duckdb
---

# PetroDB

Public petroleum datasets served as a partitioned **parquet** tree, designed for
remote columnar queries with DuckDB `httpfs` (HTTP Range pushdown).

This Hugging Face dataset repo hosts the **parquet bytes only**. It mirrors the
`parquet/` root and is queried directly via `resolve` URLs, which honour HTTP
Range requests so consumers fetch only the row groups a predicate needs.

```sql
INSTALL httpfs; LOAD httpfs;
SELECT *
FROM 'https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main/<dataset>/...';
```

The human-facing landing page, per-dataset schema docs, and discovery manifests
live at **https://sumpalabs.com/petrodb/**.

- `main` — public production deployment
- `stage` — pre-production validation branch

See ADR-0005 in the project repository for the hosting rationale.

# Multi-parquet table convention: directory + `_files.json` manifest, Hive optional

**Status:** accepted

## Context

Several petrodb tables are published as a directory of many Parquet files rather than one file — because a single file would bust Cloudflare's per-file edge-cache target, or because the table is naturally one-file-per-entity (one Instance, one well). The primary consumer is DuckDB `httpfs` reading directly from static Cloudflare Pages hosting. Static hosting offers no directory index and no S3-style object listing, so DuckDB cannot glob `.../*.parquet`. Until now each dataset improvised its own multi-file layout: Argentina and Petrobras 3W ship Hive partitions plus a `_files.json` manifest, while FORCE 2020 ships a flat `wells/` directory with neither — and the repo had no written convention to converge on.

## Decision

A **multi-parquet table** is a directory of two or more schema-sharing Parquet files plus a `_files.json` manifest — a JSON array of paths relative to the directory — at its root. The manifest is the file-discovery contract. Hive-style `key=value/` partitioning is an optional optimization, applied only when a low-cardinality column makes partition pruning worthwhile; absent such a key, files sit flat. Leaf filenames carry no query semantics. A repo-wide test enforces that every directory under `parquet/` holding ≥2 Parquet files has a `_files.json` whose entries match the files present.

## Considered alternatives

- **The HuggingFace Hub convention** — size-based shards (`{split}-NNNNN-of-MMMMM.parquet`) declared via dataset-card YAML `configs`/`data_files` globs. Rejected: it targets the `datasets` library, which streams whole shards and does no predicate pushdown; the YAML globs are resolved by the HF Hub API, not by DuckDB. Adopting it would abandon Hive partition pruning — petrodb's main performance lever — and still leave DuckDB unable to discover files over static HTTP.
- **Rely on HTTP globbing / directory listing.** Rejected: Cloudflare Pages serves no directory index, and DuckDB `httpfs` does not glob plain HTTP(S) endpoints. This constraint is the entire reason a manifest is needed.
- **A table format with a built-in manifest (Apache Iceberg, Delta Lake, Hudi).** Rejected: these carry transaction logs, metadata trees, and a runtime far heavier than a static, read-only, append-rarely dataset needs. A one-line JSON array is sufficient.
- **Mandatory Hive partitioning for every multi-file table.** Rejected: FORCE 2020's only natural key is the well identifier itself (its primary key); Hive-partitioning by a primary key adds a directory level and a redundant column for no pruning benefit over a flat directory.

## Consequences

- `_files.json` is part of the public API of every multi-parquet table; consumers depend on its shape and location.
- Access documentation must use manifest-based discovery, never `.../*.parquet` globbing.
- FORCE 2020's `force_2020/wells/` directory must gain a `_files.json` to comply (tracked in issue #32).

# Serve the parquet tree from Hugging Face; keep the landing on Cloudflare

**Status:** accepted — supersedes [ADR-0003](0003-cloudflare-pages-hosting.md)

## Context

ADR-0003 put the prod parquet tree on Cloudflare Pages so consumers could run DuckDB `httpfs` queries directly against a stable public URL space (ADR-0001). The entire value proposition — query remote parquet, fetching only the row groups a predicate needs — depends on the host honouring HTTP **Range** requests. Without Range, `httpfs` falls back to downloading whole files, defeating columnar pushdown and the project's reason to exist (CONTEXT.md line 1).

Cloudflare Pages does not honour Range reliably for `.parquet`. Investigation found Range (`206` + `Accept-Ranges`) is served **only when a file is already in Cloudflare's edge cache**, and `.parquet` is not a default-cached extension, so objects sit `DYNAMIC` (uncached) and answer Range requests with a full `200`. A direct `Range: bytes=0-99` returned the whole 25.7 MB file; three trivial queries that should each touch only the few-KB footer pulled the full bytes every time. Edge-cache residency is non-deterministic on the free plan, so even with caching nudged on, Range worked only *intermittently*. Deterministic edge-cache control requires a paid Cloudflare plan. Hugging Face `resolve` URLs (LFS/Xet objects served via CloudFront) honour Range **unconditionally on every request**, verified by direct test.

## Decision

Publish the parquet **bytes** to a single Hugging Face **dataset** repo, `sumpalabs/petrodb`, a monorepo mirroring the `parquet/` root. Consumers query
`https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main/<dataset>/...` with DuckDB `httpfs`. `BASE_URL` (`scripts/transform/petrobras_3w/constants.py`) becomes the HF resolve base; the existing `{BASE_URL}/<dataset>/...` convention is unchanged, so this is a one-line host swap, not a URL-space change.

The human-facing **landing** (`index.html`), the per-dataset **schema docs** (`schema.md/json/sql`, `README.md`), and the svg stay on **Cloudflare Pages** at `petrodb.ocortez.com` — static HTML that needs no Range. Cloudflare no longer carries `*.parquet` or `_files.json`.

Two HF branches mirror the two GitHub branches: push to `main` → HF `main` revision (the public, discovered deployment); push to `stage` → HF `stage` branch (`/resolve/stage/`), the one place real HF Range/`resolve` behaviour can be validated before prod (local Caddy dev cannot exercise it). LFS/Xet content-addressing deduplicates identical bytes across branches, so a `stage` branch that mirrors `main` costs negligible extra storage. `source_url` in `instances.parquet` bakes `/resolve/main/`; consumers wanting a frozen snapshot swap `main` for a commit SHA.

CI uploads the data with the **`hf` CLI** — `hf upload sumpalabs/petrodb parquet . --repo-type dataset --revision <branch> --include '**/*.parquet' --include '**/_files.json' --delete '**/*.parquet'`, plus a create-branch step for `stage` and a thin root dataset card — authenticated by a fine-grained, write-scoped **`HF_TOKEN`** GitHub secret. A slim Wrangler deploy still publishes the landing + docs.

## Considered alternatives

- **Cloudflare Cache Rule to make `.parquet` cache-eligible.** The intended fix under ADR-0003. Rejected empirically: Range on Cloudflare is gated on edge-cache residency, which is non-deterministic on the free plan, so Range worked intermittently in testing — unacceptable for a host whose whole purpose is Range-based pushdown. Reliable control requires a paid plan; HF gives reliable Range at no cost.
- **A paid Cloudflare plan or Cloudflare R2.** Either could deliver reliable Range, but adds recurring cost for a free public dataset, and R2 still lacks the atomic immutable-deploy model ADR-0003 already weighed. HF gives reliable Range *plus* generous free public storage/bandwidth, purpose-built for dataset delivery.
- **Adopt the HuggingFace `datasets`-library layout** (size-based shards + dataset-card `configs`/`data_files`). Rejected for the same reasons as [ADR-0004](0004-multi-parquet-table-convention.md): it abandons Hive pruning and the `_files.json` discovery contract and targets the streaming `datasets` library, not DuckDB `httpfs`. We host *on* HF without adopting its layout convention.
- **One HF repo per dataset.** Rejected: HF's limits are account-level, not per-repo (the data is ~2.5 GB / 2,365 files against 17–42× headroom either way), so splitting buys no capacity. The motivation is CDN-with-Range, not HF-native discoverability, so the monorepo's 1:1 mapping to `parquet/` and single `BASE_URL` win over four base URLs and four upload targets.

## Consequences

- The public URL space (ADR-0001) now resolves under the HF base. `instances.parquet#source_url` and all access docs / example queries point at `huggingface.co/datasets/sumpalabs/petrodb/resolve/main/...`. The `_files.json` manifests hold host-agnostic relative paths and are unchanged — served from HF alongside the data.
- Cloudflare's 25 MiB per-file cap (ADR-0003 consequence) no longer constrains the data; HF's per-file limits (200 GB recommended / 500 GB hard) are irrelevant at our ~24 MB max. The pre-publish 50 MB soft-warn is **retained but re-motivated**: Range-granularity / parallel-fetch hygiene, not Cloudflare cache headroom.
- The deploy splits into two targets: `hf upload` (data, per-branch) + a slim Wrangler deploy (landing + docs). One-time prerequisites: create the `sumpalabs/petrodb` HF dataset repo and its `stage` branch; add the `HF_TOKEN` secret and `BASE_URL_MAIN`/`BASE_URL_STAGE` vars pointing at the HF resolve bases.
- Local Caddy dev is unchanged — it serves the whole tree (data + docs) from disk and Caddy honours Range. Only the prod/stage hosts move.
- HF requires a dataset card to host a dataset; a thin root `README.md` linking to `petrodb.ocortez.com` satisfies this. Canonical schema docs stay on Cloudflare.

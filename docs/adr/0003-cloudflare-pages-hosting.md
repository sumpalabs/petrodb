# Host the prod parquet tree on Cloudflare Pages

**Status:** superseded by [ADR-0005](0005-host-parquet-on-huggingface.md)

> **Superseded.** Cloudflare Pages serves HTTP `Range` only from edge cache, and `.parquet` is not cache-eligible by default, so DuckDB `httpfs` Range reads worked only intermittently — defeating columnar pushdown. The parquet **bytes** moved to Hugging Face (`resolve` URLs honour Range unconditionally); Cloudflare Pages still serves the **landing + schema docs**. See [ADR-0005](0005-host-parquet-on-huggingface.md).

## Context

The prod parquet tree is published at a stable public URL so consumers can run DuckDB `httpfs` queries directly against it. ADR-0001 commits that URL space — `observations/event_class=N/<instance_id>.parquet` and friends — as the dataset's public API, so the chosen host has to honour those paths verbatim.

The Petrobras 3W dataset, generated end-to-end (event-class lookup, real-Well master, Instance catalog, per-Instance Observations tree at the pinned upstream tag — see ADR-0002), weighs ~2.3 GB across ~2,228 parquet files. The current prod deploy targets GitHub Pages, which enforces a hard 1 GB published-site cap; the next push including the full 3W tree would fail at `actions/upload-pages-artifact`. GitHub Pages also imposes a 100 GB/month soft bandwidth cap, which a public ML dataset is well-positioned to blow through.

Refreshes are event-driven (a new upstream git tag — ADR-0002), not calendar-driven, so the deploy model needs to handle "one immutable publish per push" gracefully — not "stream tiny diffs continuously."

## Decision

Publish the prod parquet tree to Cloudflare Pages at `petrodb.ocortez.com`. The `parquet/` directory is the deploy root; Wrangler uploads it from a GitHub Actions workflow on push-to-main. Cloudflare's content-hash deduplication on the Wrangler upload path means subsequent deploys only re-transfer files whose bytes changed.

The dev environment (`dev-petrodb.ocortez.com`, Caddy reverse proxy fed by `deploy.sh` rsync) is unaffected — Cloudflare Pages replaces the prod host only.

## Considered alternatives

- **Stay on GitHub Pages.** Rejected at the forcing function: the 3W tree is over twice the 1 GB site cap and would fail to publish. Even if it fit, the 100 GB/month bandwidth ceiling is a foreseeable problem for a public, queryable parquet dataset that ML consumers may scan from many regions.
- **Cloudflare R2.** R2 is excellent object storage and would fit the byte volume, but it lacks the atomic "one immutable deploy per push" model that Pages provides. A refresh against R2 is a per-file PUT loop with no transactional boundary — a partially completed refresh can serve a mix of old and new bytes against the committed URL space (ADR-0001), and there is no first-class rollback to a prior known-good snapshot. Pages's atomic deploys with instant rollback fit the event-driven refresh cadence (ADR-0002) far better, where each upstream tag bump should be one reviewable publish.
- **Self-host behind Caddy on the dev VM.** Rejected — prod traffic on a single home-lab host is a liability for a dataset meant to be publicly queryable, and the dev VM's bandwidth and uptime are not the right SLA for the public API.

## Consequences

- The published URL space committed in ADR-0001 stays exactly what consumers expect — Pages serves `parquet/` at the deploy root, so `https://petrodb.ocortez.com/petrobras_3w/observations/event_class=N/<instance_id>.parquet` resolves unchanged.
- Cloudflare Pages enforces a **25 MiB per-file hard cap** on uploads. The pre-publish validator's existing 50 MB soft-warn (CONTEXT.md *Petrobras 3W dataset — pre-publish validation* rule 9; mirrored as rule 6 for Argentina) sits comfortably below this — at the currently pinned upstream tag every Observations file is under 25 MiB, so the soft-warn fires well before Pages would reject a file. If a future upstream change ever produces an outlier Instance, the soft-warn surfaces it during pre-publish, not as a 4xx during the Wrangler upload.
- Cloudflare Pages free plan caps deploys at 500/month and concurrent builds at 1 — both comfortably above the event-driven refresh cadence (ADR-0002), where a publish is gated on upstream cutting a new tag.
- DNS for `ocortez.com` already lives in Cloudflare, so wiring `petrodb.ocortez.com` to the Pages project is a one-time UI action with no zone-transfer or split-DNS complexity.
- The deploy contract becomes "every push to `main` is a publish." This matches the existing reviewable-merge workflow but is worth naming: there is no separate "promote to prod" step.

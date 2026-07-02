"""Retarget every published data URL to the deploy's own per-branch HF revision.

Every published doc / example query / download link must resolve to the HF
revision that matches the deploy (ADR-0005): a push to ``stage`` ships artifacts
whose data URLs are ``…/resolve/stage/…``; a push to ``main`` ships
``…/resolve/main/…``. Otherwise a ``stage`` preview 404s on any surface frozen
at ``/resolve/main/`` until ``main`` is deployed (issue #42).

The committed tree carries a single canonical host for every hand-authored and
website-integrator-produced data URL — the HF ``main`` resolve base — so the
working tree never drifts per-branch (the commit stays canonical ``main``, and a
``stage`` build leaves no ``stage`` URLs behind in git). The locally generated,
gitignored surfaces (the 3W docs) plus the root-README "Browse and download"
pointer carry the dev Caddy host. This pass rewrites both to the deploy's
``BASE_URL`` at build time.

Unlike the schema-doc generators and website integrators (which each embed
``BASE_URL`` when they *run*), this is a single blunt host rewrite over the
already-built artifacts. It therefore covers the four datasets uniformly —
including the hand-authored Volve/FORCE tabs in ``index.html`` and the root
README quick-start, which have no generator of their own — and needs no dataset
sources, so it runs in CI without the transform DBs (pure stdlib, no uv). The 3W
pipeline still bakes ``BASE_URL`` into its own surfaces first; this pass is a
no-op on anything already pointed at ``BASE_URL``.

Run it in the deploy after the 3W tree is built and before both publish targets.
Locally, with no ``BASE_URL`` set, it retargets to the dev Caddy host (the
``constants.py`` convention), matching ``deploy.sh``'s local rsync flow.
"""

from __future__ import annotations

import os
from pathlib import Path

# Dev Caddy fallback, shared with the generators/constants when BASE_URL is
# unset. Also the host baked into the locally generated (gitignored) 3W docs and
# the root-README "Browse and download" pointer.
DEV_CADDY_HOST = "https://dev-petrodb.ocortez.com"

# The canonical committed HF host. Every tracked deployed surface (index.html,
# the per-dataset schema READMEs, the root README, the HF dataset card) is
# committed against this base — it MUST equal `vars.BASE_URL_MAIN` in the deploy
# workflow so a `main` deploy is a no-op on it.
CANONICAL_HF_BASE = "https://huggingface.co/datasets/sumpalabs/petrodb/resolve/main"

# Non-deploy data hosts frozen in the built tree; each is rewritten to BASE_URL
# so no host other than the deploy's own revision survives.
CANONICAL_HOSTS = (CANONICAL_HF_BASE, DEV_CADDY_HOST)


def _target_files(repo_root: Path) -> list[Path]:
    """Deployed artifacts that carry data URLs, in a stable order.

    The landing page, the HF dataset card, the root README, and every
    per-dataset schema README under ``parquet/*/``. Callers skip files that do
    not exist (e.g. the gitignored 3W tree before it is built).
    """
    candidates = [
        repo_root / "README.md",
        repo_root / "hf" / "README.md",
        repo_root / "parquet" / "index.html",
        *sorted((repo_root / "parquet").glob("*/README.md")),
    ]
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def retarget_text(text: str, base_url: str) -> str:
    """Rewrite every non-deploy data host in ``text`` to ``base_url``."""
    for host in CANONICAL_HOSTS:
        if host != base_url:
            text = text.replace(host, base_url)
    return text


def _assert_no_stray_host(path: Path, text: str, base_url: str) -> None:
    """Fail if a non-deploy data host survived the rewrite in ``text``."""
    for host in CANONICAL_HOSTS:
        if host != base_url and host in text:
            raise RuntimeError(
                f"{path}: non-deploy data host {host!r} remains after "
                f"retargeting to {base_url!r}"
            )


def retarget(repo_root: Path, base_url: str) -> list[Path]:
    """Retarget every deployed artifact under ``repo_root`` to ``base_url``.

    Returns the files whose contents changed. Verifies afterwards that no
    non-deploy data host survives in any processed file.
    """
    base_url = base_url.rstrip("/")
    changed: list[Path] = []
    for path in _target_files(repo_root):
        if not path.exists():
            continue
        original = path.read_text()
        updated = retarget_text(original, base_url)
        _assert_no_stray_host(path, updated, base_url)
        if updated != original:
            path.write_text(updated)
            changed.append(path)
    return changed


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    base_url = os.environ.get("BASE_URL", DEV_CADDY_HOST).rstrip("/")
    changed = retarget(repo_root, base_url)
    print(f"Retargeted data URLs to {base_url}")
    for path in changed:
        print(f"  updated {path.relative_to(repo_root)}")
    if not changed:
        print("  (no changes)")


if __name__ == "__main__":
    main()

"""Per-branch host propagation for the deploy's data-URL retargeting (issue #42).

The deploy must ship artifacts whose every data URL resolves to the deploy's own
HF revision (ADR-0005). These tests pin that the retarget pass rewrites the
surfaces that gained per-branch awareness — the hand-authored Volve/FORCE tabs
in ``index.html``, the root-README quick-start, the HF dataset card, and the
FORCE/Argentina schema READMEs — from the canonical committed host to a
per-branch ``BASE_URL``, and that a no-``BASE_URL`` run falls back to the dev
Caddy host without leaving stray hosts behind.
"""

import shutil
from pathlib import Path

import pytest

from scripts.deploy import retarget_data_urls as rt

STAGE_BASE = "https://huggingface.co/datasets/sumpalabs/petrodb/resolve/stage"
MAIN_BASE = rt.CANONICAL_HF_BASE
DEV_HOST = rt.DEV_CADDY_HOST

REPO_ROOT = Path(__file__).resolve().parents[2]

# The tracked deployed surfaces that carry data URLs and get retargeted.
TRACKED_SURFACES = [
    "README.md",
    "hf/README.md",
    "parquet/index.html",
    "parquet/argentina/README.md",
    "parquet/force_2020/README.md",
]


# ---------------------------------------------------------------------------
# Pure text rewrite
# ---------------------------------------------------------------------------


def test_rewrites_hf_main_base_to_target_branch() -> None:
    text = f"FROM '{MAIN_BASE}/volve/wells.parquet'"
    assert rt.retarget_text(text, STAGE_BASE) == (
        f"FROM '{STAGE_BASE}/volve/wells.parquet'"
    )


def test_rewrites_dev_caddy_host_to_target_branch() -> None:
    text = f"FROM '{DEV_HOST}/petrobras_3w/wells.parquet'"
    assert rt.retarget_text(text, STAGE_BASE) == (
        f"FROM '{STAGE_BASE}/petrobras_3w/wells.parquet'"
    )


def test_main_deploy_is_noop_on_hf_base_but_still_clears_dev_host() -> None:
    # On a `main` deploy BASE_URL == the canonical HF base: main URLs stay put,
    # but the dev Caddy host is still rewritten so nothing off-branch survives.
    text = f"a {MAIN_BASE}/x.parquet b {DEV_HOST}/y.parquet"
    assert rt.retarget_text(text, MAIN_BASE) == (
        f"a {MAIN_BASE}/x.parquet b {MAIN_BASE}/y.parquet"
    )


def test_plain_dataset_link_is_not_touched() -> None:
    # The HF dataset landing link lacks `/resolve/<rev>` and must survive.
    link = "https://huggingface.co/datasets/sumpalabs/petrodb"
    assert rt.retarget_text(link, STAGE_BASE) == link


# ---------------------------------------------------------------------------
# End-to-end over copies of the real deployed artifacts
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A minimal repo tree with the real deployed artifacts copied in."""
    for rel in TRACKED_SURFACES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, dst)
    return tmp_path


def test_stage_deploy_retargets_every_surface(repo_copy: Path) -> None:
    changed = rt.retarget(repo_copy, STAGE_BASE)
    changed_rel = {p.relative_to(repo_copy).as_posix() for p in changed}
    assert changed_rel == set(TRACKED_SURFACES)

    for rel in TRACKED_SURFACES:
        text = (repo_copy / rel).read_text()
        assert MAIN_BASE not in text, f"{rel} still points at the main HF base"
        assert DEV_HOST not in text, f"{rel} still points at the dev Caddy host"
        assert STAGE_BASE in text, f"{rel} gained no stage URL"


def test_stage_deploy_covers_volve_and_force_static_tabs(repo_copy: Path) -> None:
    rt.retarget(repo_copy, STAGE_BASE)
    index = (repo_copy / "parquet/index.html").read_text()
    # The hand-authored Volve and FORCE 2020 tabs (no generator of their own).
    assert f"{STAGE_BASE}/volve/daily_production.parquet" in index
    assert f"{STAGE_BASE}/force_2020/wells/15-9-13.parquet" in index


def test_stage_deploy_covers_root_readme_quickstart(repo_copy: Path) -> None:
    rt.retarget(repo_copy, STAGE_BASE)
    readme = (repo_copy / "README.md").read_text()
    assert f'HF = "{STAGE_BASE}"' in readme
    # And the "Browse and download" pointer no longer names the dev host.
    assert DEV_HOST not in readme


def test_main_deploy_leaves_only_main_urls(repo_copy: Path) -> None:
    rt.retarget(repo_copy, MAIN_BASE)
    for rel in TRACKED_SURFACES:
        text = (repo_copy / rel).read_text()
        assert DEV_HOST not in text
        assert STAGE_BASE not in text


def test_no_base_url_falls_back_to_dev_host(
    repo_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The local convention: an unset BASE_URL retargets to the dev Caddy host.
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.setattr(rt, "__file__", str(repo_copy / "scripts/deploy/x.py"))
    rt.main()
    index = (repo_copy / "parquet/index.html").read_text()
    assert MAIN_BASE not in index
    assert f"{DEV_HOST}/volve/daily_production.parquet" in index


def test_committed_tree_is_canonical_main() -> None:
    # Guards the invariant the retarget pass relies on: the committed surfaces
    # carry only the canonical main HF base (no stray stage/dev data URLs), so a
    # stage build never leaves stage URLs in git.
    for rel in TRACKED_SURFACES:
        text = (REPO_ROOT / rel).read_text()
        assert STAGE_BASE not in text, f"{rel} unexpectedly carries a stage URL"

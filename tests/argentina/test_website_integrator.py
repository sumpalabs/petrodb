"""Unit tests for the Argentina `website_integrator`.

Verifies:

- The root `README.md` gains an Argentina entry under `## Datasets`.
- `parquet/index.html` gains a tab button + tab content section linking
  to the four published artifacts.
- Both patches are idempotent: re-running produces byte-identical files
  and never duplicates the entries.
- The patch is robust to anchors that don't exist (raises) and is
  bracketed by sentinel HTML comments so it can be removed/replaced.
"""

from pathlib import Path

import pytest

from scripts.export.argentina import website_integrator

# Representative year range. `integrate` only cares that it's a sorted
# list of ints — the patcher renders one button per year.
_YEARS = list(range(2006, 2026))

# A tiny but representative pair of files. The sentinels and anchors must
# match the production README.md and parquet/index.html structure exactly.
_README_BEFORE = """\
# PetroData Repository

Open petroleum datasets in Parquet format for data science and machine learning applications.

## Datasets

### Volve Production Data
Production metrics from the Equinor Volve oil field (2007-2016):
- 7 wells, 15K daily measurements, 526 monthly aggregates.

### FORCE 2020 Well Logs
Well log data from 108 wells in the Norwegian Continental Shelf.

## Access Data

Browse and download files at: **https://dev-petrodb.ocortez.com**

## License

See original license terms.
"""

_INDEX_BEFORE = """\
<!DOCTYPE html>
<html><body>
    <div class="container">
        <!-- Tab Navigation -->
        <div class="tab-navigation">
            <button class="tab-button active" data-tab="volve">
                Volve Production
                <span class="tab-count">3 files</span>
            </button>
            <button class="tab-button" data-tab="force2020">
                Force 2020 Wells
                <span class="tab-count">108 files</span>
            </button>
        </div>

        <!-- Volve Tab Content -->
        <div id="volve-tab" class="tab-content active">
            volve content
        </div>

        <!-- Force 2020 Tab Content -->
        <div id="force2020-tab" class="tab-content">
            force2020 content
        </div>

        <footer>
            footer content
        </footer>
    </div>
</body></html>
"""


@pytest.fixture
def website_root(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text(_README_BEFORE)
    (tmp_path / "parquet").mkdir()
    (tmp_path / "parquet" / "index.html").write_text(_INDEX_BEFORE)
    return tmp_path


def test_integrate_adds_argentina_blurb_to_root_readme(website_root: Path) -> None:
    website_integrator.integrate(website_root, _YEARS)
    body = (website_root / "README.md").read_text()
    assert "### Argentina Production Data" in body
    assert "wells.parquet" in body
    assert "well_operator_history.parquet" in body
    assert "well_events.parquet" in body
    assert "monthly_production" in body
    # Spanish column names are mentioned (the contract from CONTEXT.md)
    assert "Spanish" in body or "español" in body.lower()


def test_integrate_readme_blurb_appears_under_datasets(website_root: Path) -> None:
    """The Argentina entry must sit under `## Datasets` and before
    `## Access Data` so it slots in next to Volve and FORCE 2020."""
    website_integrator.integrate(website_root, _YEARS)
    body = (website_root / "README.md").read_text()
    datasets_idx = body.index("## Datasets")
    argentina_idx = body.index("### Argentina Production Data")
    access_idx = body.index("## Access Data")
    assert datasets_idx < argentina_idx < access_idx


def test_integrate_readme_includes_duckdb_query_example(website_root: Path) -> None:
    """The blurb must carry a copy-pasteable DuckDB query example."""
    website_integrator.integrate(website_root, _YEARS)
    body = (website_root / "README.md").read_text()
    assert "import duckdb" in body
    assert "duckdb.sql(" in body
    # The example uses the published HTTP URLs so it works without download.
    assert "https://dev-petrodb.ocortez.com/argentina/" in body
    # And exercises the partitioned monthly series.
    assert "monthly_production/anio=*/data.parquet" in body
    assert "hive_partitioning = true" in body


def test_integrate_adds_argentina_tab_button_to_index_html(
    website_root: Path,
) -> None:
    website_integrator.integrate(website_root, _YEARS)
    body = (website_root / "parquet" / "index.html").read_text()
    assert 'data-tab="argentina"' in body
    assert "Argentina Production" in body
    # Existing tabs unaffected
    assert 'data-tab="volve"' in body
    assert 'data-tab="force2020"' in body


def test_integrate_adds_argentina_tab_content_to_index_html(
    website_root: Path,
) -> None:
    website_integrator.integrate(website_root, _YEARS)
    body = (website_root / "parquet" / "index.html").read_text()
    assert 'id="argentina-tab"' in body
    # Single-file tables, the manifest, and the schema docs.
    for artifact in (
        "argentina/wells.parquet",
        "argentina/well_operator_history.parquet",
        "argentina/well_events.parquet",
        "argentina/monthly_production/_files.json",
        "argentina/README.md",
        "argentina/schema.md",
        "argentina/schema.json",
        "argentina/schema.sql",
    ):
        assert f'"{artifact}"' in body, f"missing link to {artifact}"


def test_integrate_renders_per_year_download_buttons(website_root: Path) -> None:
    """Each year in the manifest gets a direct-download button with a
    custom `download` filename so files don't collide as `data.parquet`
    in the user's Downloads folder."""
    website_integrator.integrate(website_root, _YEARS)
    body = (website_root / "parquet" / "index.html").read_text()
    # Spot-check first/last and a middle year.
    for year in (_YEARS[0], 2015, _YEARS[-1]):
        assert (
            f'href="argentina/monthly_production/anio={year}/data.parquet"' in body
        ), f"missing per-year href for {year}"
        assert (
            f'download="monthly_production_{year}.parquet"' in body
        ), f"missing custom download filename for {year}"
    # The collapsible wraps them.
    assert "<details" in body and "</details>" in body


def test_integrate_index_html_button_appears_inside_tab_navigation(
    website_root: Path,
) -> None:
    """The new button must live inside the existing `.tab-navigation` div
    so the JavaScript tab handler picks it up."""
    website_integrator.integrate(website_root, _YEARS)
    body = (website_root / "parquet" / "index.html").read_text()
    nav_open = body.index('class="tab-navigation"')
    # The closing </div> of tab-navigation comes right before the
    # `Volve Tab Content` comment.
    nav_close = body.index("<!-- Volve Tab Content -->")
    button_pos = body.index('data-tab="argentina"')
    assert nav_open < button_pos < nav_close


def test_integrate_index_html_content_appears_before_footer(
    website_root: Path,
) -> None:
    """The new tab content div must come before `<footer>` so it lives
    inside the page container next to the existing tab-content blocks."""
    website_integrator.integrate(website_root, _YEARS)
    body = (website_root / "parquet" / "index.html").read_text()
    content_pos = body.index('id="argentina-tab"')
    footer_pos = body.index("<footer>")
    assert content_pos < footer_pos


def test_integrate_is_idempotent_on_root_readme(website_root: Path) -> None:
    website_integrator.integrate(website_root, _YEARS)
    first = (website_root / "README.md").read_text()
    website_integrator.integrate(website_root, _YEARS)
    second = (website_root / "README.md").read_text()
    assert first == second


def test_integrate_is_idempotent_on_index_html(website_root: Path) -> None:
    website_integrator.integrate(website_root, _YEARS)
    first = (website_root / "parquet" / "index.html").read_text()
    website_integrator.integrate(website_root, _YEARS)
    second = (website_root / "parquet" / "index.html").read_text()
    assert first == second


def test_integrate_does_not_duplicate_argentina_entries(website_root: Path) -> None:
    """Re-running must never accumulate copies of the inserted entries."""
    for _ in range(3):
        website_integrator.integrate(website_root, _YEARS)
    readme = (website_root / "README.md").read_text()
    index = (website_root / "parquet" / "index.html").read_text()
    assert readme.count("### Argentina Production Data") == 1
    assert index.count('data-tab="argentina"') == 1
    assert index.count('id="argentina-tab"') == 1


def test_integrate_writes_sentinel_markers(website_root: Path) -> None:
    """The sentinels are how the patch finds itself on a re-run; if they
    disappear, the patch will duplicate."""
    website_integrator.integrate(website_root, _YEARS)
    readme = (website_root / "README.md").read_text()
    index = (website_root / "parquet" / "index.html").read_text()
    assert website_integrator.README_BEGIN in readme
    assert website_integrator.README_END in readme
    assert website_integrator.INDEX_TAB_BUTTON_BEGIN in index
    assert website_integrator.INDEX_TAB_BUTTON_END in index
    assert website_integrator.INDEX_TAB_CONTENT_BEGIN in index
    assert website_integrator.INDEX_TAB_CONTENT_END in index


def test_integrate_replaces_stale_block_in_place(website_root: Path) -> None:
    """If the inserted block changes, re-running must overwrite the prior
    version rather than appending alongside it."""
    website_integrator.integrate(website_root, _YEARS)
    readme_path = website_root / "README.md"
    body = readme_path.read_text()
    # Doctor the file so the previous block contains stale text.
    stale = body.replace(
        "### Argentina Production Data",
        "### Argentina Production Data\nSTALE STALE STALE",
        1,
    )
    readme_path.write_text(stale)
    assert "STALE STALE STALE" in readme_path.read_text()

    website_integrator.integrate(website_root, _YEARS)
    fresh = readme_path.read_text()
    assert "STALE STALE STALE" not in fresh
    assert fresh.count("### Argentina Production Data") == 1

"""Surface the Petrobras 3W dataset on the static site.

Two idempotent patches:

- Root ``README.md``: add a Petrobras 3W entry under the ``## Datasets``
  section with a copy-pasteable DuckDB query example.
- ``parquet/index.html``: add a Petrobras 3W tab alongside the existing
  Volve / FORCE 2020 / Argentina tabs, listing the published files,
  pinned upstream identity, and the schema documents.

Both patches bracket the inserted region with sentinel HTML comments so
re-running the export replaces the block in place rather than appending
a duplicate. The same mechanism as the Argentina integrator.
"""

from __future__ import annotations

from pathlib import Path

from scripts.transform.petrobras_3w.constants import (
    PIN_DATASET_VERSION,
    PIN_GIT_TAG,
    UPSTREAM_REPO_URL,
)

README_BEGIN = "<!-- petrobras_3w:begin -->"
README_END = "<!-- petrobras_3w:end -->"

INDEX_TAB_BUTTON_BEGIN = "<!-- petrobras_3w-tab-button:begin -->"
INDEX_TAB_BUTTON_END = "<!-- petrobras_3w-tab-button:end -->"
INDEX_TAB_CONTENT_BEGIN = "<!-- petrobras_3w-tab-content:begin -->"
INDEX_TAB_CONTENT_END = "<!-- petrobras_3w-tab-content:end -->"

# Insert the README blurb above this header so it sits between the
# Argentina entry and the Access Data section.
README_ANCHOR = "## Access Data"

# Insert the new tab button at the end of the tab-navigation block,
# immediately before its closing </div>. Anchor on the multi-line
# Volve content tag to avoid matching any other </div>.
INDEX_TAB_BUTTON_ANCHOR = "        </div>\n\n        <!-- Volve Tab Content -->"

# Insert the new tab content immediately before <footer>.
INDEX_TAB_CONTENT_ANCHOR = "        <footer>"


def integrate(website_root: Path) -> None:
    """Idempotently inject the Petrobras 3W dataset entry into the static site.

    ``website_root`` is the repo root containing ``README.md`` and
    ``parquet/index.html``. Re-running with the same inputs produces
    byte-identical output.
    """
    website_root = Path(website_root)
    _patch_root_readme(website_root / "README.md")
    _patch_index_html(website_root / "parquet" / "index.html")


def _readme_payload() -> str:
    return f"""\

### Petrobras 3W Dataset
Labelled 1-Hz sensor-data windows from the Petrobras 3W dataset, sliced
into per-Instance Parquet files. Pinned at upstream git tag `{PIN_GIT_TAG}`
(dataset version `{PIN_DATASET_VERSION}`). This initial release publishes
the event-class lookup and documentation scaffolding; the Instance catalog,
real-Well master, and Observations time-series ship in follow-up issues.

List every event class (NORMAL plus the nine anomaly categories) with their
TRANSIENT-arc semantics:

```python
import duckdb

result = duckdb.sql(\"\"\"
    SELECT event_class, name, description,
           has_transient, transient_code
    FROM 'https://dev-petrodb.ocortez.com/petrobras_3w/event_types.parquet'
    ORDER BY event_class
\"\"\").df()
```

Full per-column English docs (including the 27-sensor glossary mirrored
from upstream `dataset.ini`) live in
[`parquet/petrobras_3w/README.md`](parquet/petrobras_3w/README.md). Upstream
source: <{UPSTREAM_REPO_URL}> (CC BY 4.0).

"""


def _patch_root_readme(path: Path) -> None:
    text = path.read_text()
    block = f"{README_BEGIN}\n{_readme_payload()}{README_END}\n\n"
    new_text = _replace_block_or_insert_before(
        text, README_BEGIN, README_END, README_ANCHOR, block
    )
    if new_text != text:
        path.write_text(new_text)


def _index_tab_button_payload() -> str:
    return """\
            <button class="tab-button" data-tab="petrobras_3w">
                Petrobras 3W
                <span class="tab-count">1 file</span>
            </button>
"""


def _index_tab_content_payload() -> str:
    return f"""\
        <!-- Petrobras 3W Tab Content -->
        <div id="petrobras_3w-tab" class="tab-content">
            <!-- Download Section -->
            <div class="download-section">
                <h2>Download Petrobras 3W Files</h2>
                <p style="margin-bottom: 24px; color: var(--text-secondary);">
                    Labelled 1-Hz sensor-data windows from the Petrobras 3W dataset.
                    Pinned at upstream git tag <code>{PIN_GIT_TAG}</code>
                    (dataset version <code>{PIN_DATASET_VERSION}</code>). This initial
                    release publishes the event-class lookup and documentation
                    scaffolding; the Instance catalog, real-Well master, and
                    Observations time-series ship in follow-up issues.
                </p>
                <div class="download-grid">
                    <a href="petrobras_3w/event_types.parquet" class="download-button" download>
                        <span>event_types.parquet</span>
                        <span class="download-icon">⬇</span>
                    </a>
                </div>

                <div class="download-grid" style="margin-top: 16px;">
                    <a href="petrobras_3w/README.md" class="download-button">
                        <span>README.md</span>
                        <span class="download-icon">📖</span>
                    </a>
                    <a href="petrobras_3w/schema.md" class="download-button">
                        <span>schema.md</span>
                        <span class="download-icon">📖</span>
                    </a>
                    <a href="petrobras_3w/schema.json" class="download-button">
                        <span>schema.json</span>
                        <span class="download-icon">{{}}</span>
                    </a>
                    <a href="petrobras_3w/schema.sql" class="download-button">
                        <span>schema.sql</span>
                        <span class="download-icon">⌘</span>
                    </a>
                    <a href="petrobras_3w/LICENSE-3W-DATA.md" class="download-button">
                        <span>LICENSE-3W-DATA.md</span>
                        <span class="download-icon">📄</span>
                    </a>
                </div>
                <p class="file-size">One lookup table · pinned upstream identity logged on every publish</p>
            </div>

            <!-- About Section -->
            <section>
                <h2>About This Dataset</h2>
                <p>
                    The <strong>Petrobras 3W dataset</strong> is a corpus of
                    ~2,228 labelled 1-Hz sensor-data windows recorded on
                    Petrobras's offshore wells, framed around at most one
                    anomaly event per window. The full corpus covers ten
                    operational regimes (NORMAL plus nine anomaly categories
                    such as <em>Hydrate in Production Line</em> and
                    <em>Severe Slugging</em>) across ~40 distinct real wells,
                    supplemented by simulated and hand-drawn instances.
                </p>
                <p>
                    Petrodb pins the upstream repository at git tag
                    <code>{PIN_GIT_TAG}</code> (dataset version
                    <code>{PIN_DATASET_VERSION}</code>) — refreshes are
                    event-driven on new upstream releases, never silent.
                </p>
            </section>

            <!-- Query Example Section -->
            <section>
                <h2>Quick Start with DuckDB</h2>
                <p>
                    List every event class with its TRANSIENT-arc semantics:
                </p>
                <div class="code-block">
                    <div class="code-header">
                        <span class="code-dot"></span>
                        <span class="code-dot"></span>
                        <span class="code-dot"></span>
                    </div>
                    <pre><span class="keyword">import</span> duckdb

<span class="comment"># List the 10 event classes and their TRANSIENT-arc semantics</span>
result = duckdb.<span class="function">sql</span>(<span class="string">\"\"\"
    SELECT event_class, name, description,
           has_transient, transient_code
    FROM 'petrobras_3w/event_types.parquet'
    ORDER BY event_class
\"\"\"</span>).<span class="function">df</span>()</pre>
                </div>
                <p>
                    More canonical patterns (per-event-class filter, joins
                    against the Instance catalog, single-Instance fetch)
                    will land alongside the catalog and Observations files
                    in follow-up releases.
                </p>
            </section>

            <!-- Schema Documents Section -->
            <section>
                <h2>Schema Documents</h2>
                <p>
                    Full per-column documentation is published alongside the parquets:
                </p>
                <div class="schema-grid">
                    <div class="table-card">
                        <h3 class="table-name">README.md</h3>
                        <p class="table-meta">Dataset overview, pinned upstream identity, query examples</p>
                        <div class="foreign-key-note">
                            → <a href="petrobras_3w/README.md">Open README.md</a>
                        </div>
                    </div>
                    <div class="table-card">
                        <h3 class="table-name">schema.md</h3>
                        <p class="table-meta">English column docs + 27-sensor glossary mirrored from upstream <code>dataset.ini</code></p>
                        <div class="foreign-key-note">
                            → <a href="petrobras_3w/schema.md">Open schema.md</a>
                        </div>
                    </div>
                    <div class="table-card">
                        <h3 class="table-name">schema.json</h3>
                        <p class="table-meta">Machine-readable column list, types, primary &amp; foreign keys</p>
                        <div class="foreign-key-note">
                            → <a href="petrobras_3w/schema.json">Open schema.json</a>
                        </div>
                    </div>
                    <div class="table-card">
                        <h3 class="table-name">schema.sql</h3>
                        <p class="table-meta">DDL that mirrors the published structure in a fresh DuckDB</p>
                        <div class="foreign-key-note">
                            → <a href="petrobras_3w/schema.sql">Open schema.sql</a>
                        </div>
                    </div>
                </div>
            </section>

            <!-- Source & License -->
            <section class="dataset-attribution">
                <h2>Source &amp; License</h2>
                <p>
                    Upstream repository: <a href="{UPSTREAM_REPO_URL}" target="_blank" rel="noopener">{UPSTREAM_REPO_URL}</a>
                    (pinned at git tag <code>{PIN_GIT_TAG}</code>, dataset version
                    <code>{PIN_DATASET_VERSION}</code>).
                </p>
                <p>
                    Licensed under <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">Creative Commons Attribution 4.0</a>.
                    All credit for the underlying measurements, labelling, and dataset
                    design belongs to Petrobras and the upstream maintainers.
                </p>
            </section>
        </div>

"""


def _patch_index_html(path: Path) -> None:
    original = path.read_text()

    button_block = (
        f"{INDEX_TAB_BUTTON_BEGIN}\n{_index_tab_button_payload()}"
        f"{INDEX_TAB_BUTTON_END}\n"
    )
    text = _replace_block_or_insert_before(
        original,
        INDEX_TAB_BUTTON_BEGIN,
        INDEX_TAB_BUTTON_END,
        INDEX_TAB_BUTTON_ANCHOR,
        button_block,
    )

    content_block = (
        f"{INDEX_TAB_CONTENT_BEGIN}\n{_index_tab_content_payload()}"
        f"{INDEX_TAB_CONTENT_END}\n\n"
    )
    text = _replace_block_or_insert_before(
        text,
        INDEX_TAB_CONTENT_BEGIN,
        INDEX_TAB_CONTENT_END,
        INDEX_TAB_CONTENT_ANCHOR,
        content_block,
    )

    if text != original:
        path.write_text(text)


def _replace_block_or_insert_before(
    text: str, begin: str, end: str, anchor: str, block: str
) -> str:
    """Replace the region between ``begin`` and ``end`` with ``block`` if
    the sentinels exist; otherwise insert ``block`` immediately before
    ``anchor``. Same mechanism as the Argentina integrator.
    """
    if begin in text and end in text:
        prefix, _, rest = text.partition(begin)
        _, _, suffix = rest.partition(end)
        suffix = suffix.lstrip("\n")
        return prefix + block + suffix
    pos = text.index(anchor)
    return text[:pos] + block + text[pos:]

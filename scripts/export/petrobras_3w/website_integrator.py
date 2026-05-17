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
(dataset version `{PIN_DATASET_VERSION}`). This release publishes the
event-class lookup, the real-Well master, the full Instance catalog, and
the per-Instance Observations time-series (hive-partitioned by event class).

Measure the labelled-data balance across the corpus from the catalog alone
(no Observations scan needed):

```python
import duckdb

base = 'https://dev-petrodb.ocortez.com/petrobras_3w'
result = duckdb.sql(f\"\"\"
    SELECT
        et.event_class,
        et.description,
        COUNT(*)             AS n_instances,
        SUM(i.n_rows)        AS n_observations
    FROM '{{base}}/instances.parquet' i
    JOIN '{{base}}/event_types.parquet' et
        ON et.event_class = i.event_class
    GROUP BY et.event_class, et.description
    ORDER BY et.event_class
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
                <span class="tab-count">3 files + ~2,228 instance time-series</span>
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
                    (dataset version <code>{PIN_DATASET_VERSION}</code>). This release
                    publishes the event-class lookup, the real-Well master, the full
                    Instance catalog, and the per-Instance Observations time-series
                    hive-partitioned by <code>event_class</code>.
                </p>
                <div class="download-grid">
                    <a href="petrobras_3w/event_types.parquet" class="download-button" download>
                        <span>event_types.parquet</span>
                        <span class="download-icon">⬇</span>
                    </a>
                    <a href="petrobras_3w/wells.parquet" class="download-button" download>
                        <span>wells.parquet</span>
                        <span class="download-icon">⬇</span>
                    </a>
                    <a href="petrobras_3w/instances.parquet" class="download-button" download>
                        <span>instances.parquet</span>
                        <span class="download-icon">⬇</span>
                    </a>
                    <a href="petrobras_3w/observations/_files.json" class="download-button">
                        <span>observations/_files.json</span>
                        <span class="download-icon">📜</span>
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
                <p class="file-size">Lookup + Wells master + Instance catalog + per-Instance Observations (hive-partitioned by event_class) · pinned upstream identity logged on every publish</p>
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
                    Measure the labelled-data balance across the corpus from the
                    Instance catalog alone (no Observations scan needed):
                </p>
                <div class="code-block">
                    <div class="code-header">
                        <span class="code-dot"></span>
                        <span class="code-dot"></span>
                        <span class="code-dot"></span>
                    </div>
                    <pre><span class="keyword">import</span> duckdb

base = <span class="string">'https://dev-petrodb.ocortez.com/petrobras_3w'</span>
result = duckdb.<span class="function">sql</span>(<span class="function">f</span><span class="string">\"\"\"
    SELECT
        et.event_class,
        et.description,
        COUNT(*)             AS n_instances,
        SUM(i.n_rows)        AS n_observations
    FROM '{{base}}/instances.parquet' i
    JOIN '{{base}}/event_types.parquet' et
        ON et.event_class = i.event_class
    GROUP BY et.event_class, et.description
    ORDER BY et.event_class
\"\"\"</span>).<span class="function">df</span>()</pre>
                </div>
                <p>
                    The per-Instance Observations files are accessible via the
                    hive-partitioned URL pattern
                    <code>observations/event_class=N/&lt;instance_id&gt;.parquet</code>.
                    Each file embeds <code>instance_id</code>, <code>well_id</code>,
                    and <code>well_kind</code> as constant columns, so corpus-wide
                    queries against a single event class do not need to join the
                    catalog:
                </p>
                <div class="code-block">
                    <div class="code-header">
                        <span class="code-dot"></span>
                        <span class="code-dot"></span>
                        <span class="code-dot"></span>
                    </div>
                    <pre><span class="comment">-- All real-Well Hydrate-in-Production-Line observations</span>
SELECT instance_id, well_id, <span class="string">"timestamp"</span>, <span class="string">"P-PDG"</span>, <span class="string">"T-PDG"</span>, class
FROM <span class="string">'https://dev-petrodb.ocortez.com/petrobras_3w/observations/event_class=8/*.parquet'</span>
WHERE well_kind = <span class="string">'real'</span>;</pre>
                </div>
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
